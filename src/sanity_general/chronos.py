"""
Chronos (back office) — sesión + pantalla Processing > Edited Checks.

Port del POM del repo viejo (`src/models_chronos/chronos_main_page.py`) a
funciones sobre una `page` de Playwright, al estilo del resto de módulos.

Chronos NO usa data-testid: todo va por CSS/XPath y por ÍNDICE de columna, así
que cualquier cambio de columnas rompe el flujo (así es en el repo original).

Autenticación: Chronos entra por **SSO de Google**. La sesión se guarda en
`session_state/chronos_storage_state.json` y se reutiliza; si no existe o
expiró, se hace el login (correo Maxi + contraseña de Gmail) con `CHRONOS_USER`
y `CHRONOS_PASS`. La primera vez puede pedir 2FA → hay `TIMEOUT_2FA` para
aprobarlo a mano.

URLs y agencia por ambiente salen de config/settings (HERMES_ENV).
"""

import json
import os
import re
from urllib.parse import urlparse

from config import settings
from config.logger import get_logger

logger = get_logger("sanity.chronos")

# ── Navegación / menú ───────────────────────────────────────────────────────
TOOLBAR_MENU        = "//button[@title='Menu']"
PROCESSING_OPTION   = "//mat-panel-title[contains(text(),'Processing')]"
EDITED_CHECKS_LINK  = "a[href*='processing/edited-checks']"
RE_EDITED_TITLE     = re.compile(r"edited\s*checks", re.I)
TITLE_SEL           = "h1.custom-app-name"

# ── Tabla Edited Checks ─────────────────────────────────────────────────────
SEARCH_INPUT = ('input#AgentSearchBar, input[placeholder*="Agent" i], '
                'input[formcontrolname*="search" i], input[type="text"].form-control')
ROWS_SEL = ("p-table table.ui-table-scrollable-body-table "
            "tbody.ui-table-tbody tr:not(.handle)")
COL_DATE, COL_AGENT, COL_FOLIO, COL_AMOUNT = 0, 1, 3, 4

# ── Detalle: pestaña Issuer + rechazo ───────────────────────────────────────
ISSUER_TAB          = 'a#Issuer[role="tab"]'
ISSUER_CHECK_NUMBER = 'input[name="CheckNumberIssuerEdited"]'
REJECT_REASON_SEL   = 'select[formcontrolname="IdRejectReason"]'
RE_REJECT           = re.compile(r"^\s*Reject\s*$", re.I)
REJECT_BTN          = "button.btn-red"
MODAL_CONTENT       = "div.modal-content"
RE_SUCCESS          = re.compile(r"success|éxito|exito", re.I)
RE_CLOSE            = re.compile(r"close|cerrar", re.I)

TIMEOUT = 120_000
# Espera para APROBAR el 2FA en el celular (2 min por defecto; antes 3).
TIMEOUT_2FA = int(os.getenv("CHRONOS_2FA_MS", "120000"))


def _norm_amount(txt: str) -> str:
    return (txt or "").replace("$", "").replace(",", "").strip()


async def _click_listo(page, locator, desc: str, timeout: int = TIMEOUT):
    """Espera visible + habilitado y hace click (sin force, como el original)."""
    await locator.wait_for(state="visible", timeout=timeout)
    try:
        await locator.click(timeout=timeout)
    except Exception:
        await locator.click(force=True, timeout=15_000)
    logger.info("[Chronos] %s", desc)


# ── Sesión (cookies persistentes: el SSO limita los intentos de login) ──────

# Dominios cuyas cookies se conservan: Chronos + el SSO de Google. Las de Google
# son las que evitan RE-AUTENTICAR (y por tanto gastar intentos de login).
_DOMINIOS_SSO = ("google.com", "accounts.google.com", "googleapis.com",
                 "maxilabs.net", "maxiagentes.net", "sso.maxilabs.net")


def _host_chronos() -> str:
    try:
        return urlparse(settings.CHRONOS_URL).hostname or ""
    except Exception:
        return ""


def _es_cookie_relevante(c: dict) -> bool:
    """¿La cookie pertenece a Chronos o al SSO? (las de Hermes NO se guardan
    aquí para no pisar su propia sesión al reinyectarlas)."""
    dom = (c.get("domain") or "").lstrip(".").lower()
    if not dom:
        return False
    if dom.startswith("test-hermes") or dom.startswith("hermes"):
        return False
    host = _host_chronos()
    if host and (dom in host or host in dom):
        return True
    return any(dom.endswith(d) for d in _DOMINIOS_SSO)


async def cargar_cookies(context) -> bool:
    """Inyecta en el contexto las cookies de Chronos guardadas. True si había."""
    ruta = settings.CHRONOS_COOKIES
    if not ruta.exists():
        logger.info("[Chronos] Sin cookies guardadas — se hará login la 1ª vez.")
        return False
    try:
        cookies = json.loads(ruta.read_text(encoding="utf-8"))
        if not cookies:
            return False
        await context.add_cookies(cookies)
        logger.info("[Chronos] %d cookies de sesión reutilizadas (sin login).",
                    len(cookies))
        return True
    except Exception as e:
        logger.warning("[Chronos] No se pudieron cargar las cookies: %s", str(e)[:90])
        return False


async def guardar_cookies(context) -> None:
    """Guarda las cookies de Chronos + SSO para la próxima corrida."""
    try:
        todas = await context.cookies()
        cookies = [c for c in todas if _es_cookie_relevante(c)]
        if not cookies:
            logger.warning("[Chronos] No hay cookies de Chronos que guardar.")
            return
        settings.SESSION_DIR.mkdir(parents=True, exist_ok=True)
        settings.CHRONOS_COOKIES.write_text(
            json.dumps(cookies, indent=2), encoding="utf-8")
        logger.info("[Chronos] %d cookies de sesión guardadas en %s",
                    len(cookies), settings.CHRONOS_COOKIES.name)
    except Exception as e:
        logger.warning("[Chronos] No se pudieron guardar las cookies: %s", str(e)[:90])


async def sesion_activa(page) -> bool:
    """True si Chronos ya está dentro (el botón Menu del home es visible)."""
    try:
        await page.locator(TOOLBAR_MENU).first.wait_for(
            state="visible", timeout=settings.TIMEOUT_READY)
        return True
    except Exception:
        return False


async def abrir_chronos(page, *, login_si_necesario: bool = True) -> bool:
    """Navega a Chronos y deja la sesión lista, REUTILIZANDO cookies.

    Orden: (1) inyecta las cookies guardadas, (2) navega, (3) si la sesión está
    activa NO hace login (clave: el SSO de Google limita los intentos),
    (4) si no, hace login y GUARDA las cookies para las próximas corridas."""
    context = page.context
    tenia_cookies = await cargar_cookies(context)

    logger.info("[Chronos] Navegando a %s", settings.CHRONOS_URL)
    await page.goto(settings.CHRONOS_URL, wait_until="domcontentloaded",
                   timeout=settings.TIMEOUT_NAVIGATION)
    if await sesion_activa(page):
        logger.info("[Chronos] ✓ Sesión activa — login omitido.")
        await guardar_cookies(context)      # refresca la expiración
        return True

    if tenia_cookies:
        logger.info("[Chronos] Las cookies guardadas ya no sirven — se renueva el login.")
    if not login_si_necesario:
        return False

    # Sesión no activa → LOGIN y CONTINUAR (igual que la fixture de Hermes).
    logger.info("[Chronos] Sesión no activa — ejecutando login…")
    await login_google(page)

    # Revalidar: tras el SSO la app puede quedar en una pantalla intermedia, así
    # que se re-navega al home y se comprueba (hasta 2 vueltas) antes de rendirse.
    for intento in (1, 2):
        if await sesion_activa(page):
            logger.info("[Chronos] ✓ Sesión establecida — continúo con el flujo.")
            await guardar_cookies(context)
            return True
        logger.info("[Chronos] Revalidando sesión (intento %d)…", intento)
        try:
            await page.goto(settings.CHRONOS_URL, wait_until="domcontentloaded",
                            timeout=settings.TIMEOUT_NAVIGATION)
        except Exception:
            pass
    logger.error("[Chronos] No se pudo establecer la sesión. Corre una vez "
                 "`python tools/login_chronos.py` y reintenta.")
    return False


async def login_google(page) -> bool:
    """Login de Chronos por SSO de Google (correo Maxi + contraseña de Gmail).

    La primera vez puede pedir 2FA: se espera hasta TIMEOUT_2FA para aprobarlo
    manualmente (igual que el flujo de Hermes)."""
    usuario, clave = settings.CHRONOS_USER, settings.CHRONOS_PASS
    if not usuario or not clave:
        logger.error("[Chronos] Faltan CHRONOS_USER / CHRONOS_PASS en el .env.")
        return False
    try:
        # Botón "Google" del SSO
        btn = page.locator("#zocial-google").first
        await btn.wait_for(state="visible", timeout=60_000)
        await btn.click()
        # Selector de cuentas: SOLO si Google lo muestra explícitamente
        # (data-identifier). Sin fallback por texto: antes clickeaba cualquier
        # coincidencia y dejaba el formulario a medias.
        elegida = False
        try:
            cuenta = page.locator(f"div[data-identifier='{usuario}']").first
            if await cuenta.count() and await cuenta.is_visible():
                await cuenta.click()
                logger.info("[Chronos] Cuenta '%s' elegida del selector.", usuario)
                await page.wait_for_timeout(1_500)
                elegida = True
        except Exception:
            pass

        # Correo — secuencia del repo viejo: ESPERAR visible → fill → Enter →
        # y solo entonces 'Siguiente' (antes se pulsaba con el campo vacío y
        # Google respondía 'Introduce una dirección de correo electrónico').
        if not elegida:
            email = page.locator("#identifierId").first
            await email.wait_for(state="visible", timeout=60_000)
            await email.click()
            await email.fill(usuario)
            await page.wait_for_timeout(1_000)
            valor = (await email.input_value() or "").strip()
            if not valor:
                logger.warning("[Chronos] El campo de correo quedó vacío — reintento.")
                await email.type(usuario, delay=60)
                await page.wait_for_timeout(600)
            logger.info("[Chronos] Correo ingresado: %s", usuario)
            await email.press("Enter")
            try:                     # 'Siguiente' solo si sigue en pantalla
                sig = page.get_by_role(
                    "button", name=re.compile(r"siguiente|next", re.I)).first
                await sig.wait_for(state="visible", timeout=5_000)
                await sig.click()
            except Exception:
                pass
        # Contraseña (puede no pedirse si la cuenta ya estaba autenticada)
        pwd = page.locator('input[name="Passwd"]').first
        try:
            await pwd.wait_for(state="visible", timeout=20_000)
            await pwd.fill(clave)
            await pwd.press("Enter")
            logger.info("[Chronos] Credenciales enviadas — esperando tu "
                        "APROBACIÓN del 2FA (hasta %d min)…",
                        TIMEOUT_2FA // 60000)
        except Exception:
            logger.info("[Chronos] No se pidió contraseña (sesión de Google ya "
                        "autenticada) — esperando el home.")
        # Home de Chronos (media el 2FA que apruebas en el celular → espera larga)
        await page.wait_for_url(settings.CHRONOS_READY_URL,
                                timeout=TIMEOUT_2FA)
        ok = await sesion_activa(page)
        logger.info("[Chronos] Login %s.", "OK" if ok else "no confirmado")
        return ok
    except Exception as e:
        logger.warning("[Chronos] Login falló: %s", str(e)[:120])
        logger.warning("[Chronos] OJO: el SSO de Google limita los intentos. Si "
                       "esto se repite, entra a Chronos MANUALMENTE en un "
                       "navegador y vuelve a correr: la sesión se guardará.")
        return False


async def guardar_sesion(context) -> None:
    """Guarda el storage_state de Chronos para reutilizarlo después."""
    try:
        settings.SESSION_DIR.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=str(settings.STORAGE_STATE_CHRONOS))
        logger.info("[Chronos] Sesión guardada.")
    except Exception as e:
        logger.warning("[Chronos] No se pudo guardar la sesión: %s", str(e)[:90])


# ── Processing > Edited Checks ───────────────────────────────────────────────

async def ir_a_edited_checks(page) -> bool:
    """Menu → Processing → Edited Checks. True si el título quedó visible."""
    try:
        await _click_listo(page, page.locator(TOOLBAR_MENU).first, "Menu abierto")
        await _click_listo(page, page.locator(PROCESSING_OPTION).first, "Processing")
        await _click_listo(page, page.locator(EDITED_CHECKS_LINK).first, "Edited Checks")
        titulo = page.locator(TITLE_SEL).filter(has_text=RE_EDITED_TITLE).first
        await titulo.wait_for(state="visible", timeout=180_000)
        logger.info("[Chronos] Pantalla Edited Checks lista.")
        return True
    except Exception as e:
        logger.warning("[Chronos] No se pudo abrir Edited Checks: %s", str(e)[:110])
        return False


async def buscar_agencia(page, agency_code: str) -> None:
    """Filtra la tabla por el código de agencia."""
    inp = page.locator(SEARCH_INPUT).locator("visible=true").first
    await inp.wait_for(state="visible", timeout=TIMEOUT)
    await inp.click()
    await inp.fill("")
    await inp.type(agency_code, delay=90)
    await page.wait_for_timeout(2_000)
    try:
        await page.wait_for_load_state("networkidle", timeout=30_000)
    except Exception:
        pass
    logger.info("[Chronos] Edited Checks filtrado por agencia %s", agency_code)


async def buscar_fila(page, *, amount: str, agency_code: str = None,
                      folio: str = None, movement_date: str = None):
    """Localiza la fila de la transacción. El FOLIO es el criterio fuerte; si no
    se pasa, filtra por monto (+ agencia) y prefiere la fecha del movimiento."""
    filas = page.locator(ROWS_SEL)
    try:
        await filas.first.wait_for(state="visible", timeout=TIMEOUT)
    except Exception:
        logger.warning("[Chronos] Edited Checks: la tabla no mostró filas.")
        return None
    esperado = _norm_amount(str(amount))
    candidatos = []
    n = await filas.count()
    for i in range(min(n, 80)):
        fila = filas.nth(i)
        celdas = fila.locator("td")
        try:
            if folio:
                f = (await celdas.nth(COL_FOLIO).inner_text() or "").strip()
                if f == str(folio):
                    logger.info("[Chronos] Fila encontrada por folio %s.", folio)
                    return fila
            if _norm_amount(await celdas.nth(COL_AMOUNT).inner_text()) != esperado:
                continue
            if agency_code:
                ag = (await celdas.nth(COL_AGENT).inner_text() or "").strip()
                if ag != agency_code:
                    continue
            fecha = (await celdas.nth(COL_DATE).inner_text() or "").strip()
            candidatos.append((fecha, fila))
        except Exception:
            continue
    if not candidatos:
        return None
    if movement_date:
        for fecha, fila in candidatos:
            if fecha.startswith(movement_date):
                return fila
        logger.warning("[Chronos] Ninguna fila con fecha %s — uso la más reciente.",
                       movement_date)
    return candidatos[0][1]


async def abrir_fila(page, fila) -> None:
    """Abre el detalle (el accionable es la fecha subrayada de la 1ª columna)."""
    await fila.scroll_into_view_if_needed()
    link = fila.locator("td").first.locator("u")
    objetivo = link.first if await link.count() else fila
    await _click_listo(page, objetivo, "Detalle de la transacción abierto")
    await page.wait_for_timeout(2_000)


async def leer_check_number_issuer(page) -> str:
    """Lee el Check Number de la pestaña Issuer (sin recargar si ya está activa)."""
    tab = page.locator(ISSUER_TAB).first
    await tab.wait_for(state="visible", timeout=TIMEOUT)
    try:
        clases = await tab.get_attribute("class") or ""
        if "active" not in clases:      # el anchor tiene href="" → recargaría
            await _click_listo(page, tab, "Pestaña Issuer")
            await page.wait_for_timeout(1_000)
    except Exception:
        pass
    inp = page.locator(ISSUER_CHECK_NUMBER).locator("visible=true").first
    await inp.wait_for(state="visible", timeout=TIMEOUT)
    valor = (await inp.input_value() or "").strip()
    logger.info("[Chronos] Check Number (Issuer): %s", valor)
    return valor


RE_ERROR_TITLE = re.compile(r"error", re.I)
RE_OFAC_HOLD   = re.compile(r"ofac\s*hold", re.I)


async def _leer_modal_error(page, timeout_ms: int = 6_000) -> str:
    """Si Chronos muestra un modal de ERROR, devuelve su mensaje (o '')."""
    try:
        modal = page.locator(MODAL_CONTENT).filter(
            has=page.locator("h4.modal-title", has_text=RE_ERROR_TITLE)).first
        await modal.wait_for(state="visible", timeout=timeout_ms)
        cuerpo = modal.locator("div.modal-body, .modal-body").first
        txt = (await cuerpo.inner_text() if await cuerpo.count()
               else await modal.inner_text()) or ""
        return " ".join(txt.split())
    except Exception:
        return ""


async def cerrar_modal_error(page) -> None:
    """Cierra el modal de error (botón Close/Cerrar)."""
    try:
        modal = page.locator(MODAL_CONTENT).filter(
            has=page.locator("h4.modal-title", has_text=RE_ERROR_TITLE)).first
        btn = modal.locator("button").filter(has_text=RE_CLOSE).first
        if await btn.count():
            await btn.click(timeout=8_000)
            await modal.wait_for(state="hidden", timeout=15_000)
    except Exception:
        pass


async def rechazar(page, reason: str = "Other"):
    """Selecciona el motivo y pulsa Reject.

    Devuelve (ok, motivo):
      • (True,  '')                    → rechazada, modal de éxito visible.
      • (False, 'OFAC_HOLD: <msg>')    → Chronos NO permite rechazar porque la
        transacción está en OFAC Hold (regla de negocio: hay que resolver el
        OFAC Hold antes; no es un fallo de automatización).
      • (False, '<msg u error>')       → cualquier otro motivo.
    """
    try:
        sel = page.locator(REJECT_REASON_SEL).locator("visible=true").first
        await sel.wait_for(state="visible", timeout=TIMEOUT)
        await sel.select_option(label=reason)          # por LABEL, no por value
        btn = page.locator(REJECT_BTN).filter(has_text=RE_REJECT).first
        await _click_listo(page, btn, f"Reject ({reason})")

        # Chronos responde con modal de ÉXITO o de ERROR (p.ej. OFAC Hold).
        error = await _leer_modal_error(page, timeout_ms=6_000)
        if error:
            if RE_OFAC_HOLD.search(error):
                logger.error("[Chronos] NO se puede rechazar: la transacción está "
                             "en OFAC HOLD. Mensaje: %s", error)
                logger.error("[Chronos] Regla de negocio: primero hay que resolver "
                             "el OFAC Hold (Compliance) y luego rechazar.")
                await cerrar_modal_error(page)
                return False, f"OFAC_HOLD: {error}"
            logger.error("[Chronos] Rechazo rechazado por la app: %s", error)
            await cerrar_modal_error(page)
            return False, error

        modal = page.locator(MODAL_CONTENT).filter(
            has=page.locator("h4.modal-title", has_text=RE_SUCCESS)).first
        await modal.wait_for(state="visible", timeout=TIMEOUT)
        logger.info("[Chronos] Transacción RECHAZADA (motivo '%s').", reason)
        return True, ""
    except Exception as e:
        logger.warning("[Chronos] No se pudo rechazar: %s", str(e)[:110])
        return False, str(e)[:150]


async def cerrar_modal_exito(page) -> None:
    """Cierra el modal de éxito del rechazo."""
    try:
        modal = page.locator(MODAL_CONTENT).filter(
            has=page.locator("h4.modal-title", has_text=RE_SUCCESS)).first
        btn = modal.locator("button.btn-blue").filter(has_text=RE_CLOSE).first
        await _click_listo(page, btn, "Modal de éxito cerrado")
        await modal.wait_for(state="hidden", timeout=30_000)
    except Exception:
        pass
