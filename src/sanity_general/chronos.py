"""
Chronos (back office) — sesión + pantalla Processing > Edited Checks.

Port del POM del repo viejo (`src/models_chronos/chronos_main_page.py`) a
funciones sobre una `page` de Playwright, al estilo del resto de módulos.

Chronos NO usa data-testid: todo va por CSS/XPath y por ÍNDICE de columna, así
que cualquier cambio de columnas rompe el flujo (así es en el repo original).

Autenticación — CAMBIA POR AMBIENTE, y se detecta sola:
  • TEST → formulario propio de Keycloak: usuario + contraseña, sin 2FA.
  • PROD → SSO de Google: correo Maxi + contraseña de Gmail + 2FA en el celular.
Se puede forzar con `CHRONOS_LOGIN_MODE=password|google`.

La sesión (cookies + localStorage) se guarda en `session_state/` y se reutiliza;
si no existe o expiró, el login se hace SOLO — igual que en Hermes, un único
comando basta. La espera larga del 2FA solo se activa si el reto aparece de
verdad, así que en test no se pierde tiempo.

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
# Espera para APROBAR el 2FA en el celular. SOLO se usa si de verdad aparece el
# reto de 2FA (producción); en test el login es directo y no se espera nada.
TIMEOUT_2FA = int(os.getenv("CHRONOS_2FA_MS", "120000"))
# Espera del home tras enviar credenciales cuando NO hay 2FA (test).
TIMEOUT_HOME = int(os.getenv("CHRONOS_HOME_MS", "30000"))
# Gracia antes de dar la sesión por muerta: Keycloak rebota por el SSO para
# re-autenticar en silencio, y ese rebote no debe gastar un intento de login.
GRACIA_SSO = int(os.getenv("CHRONOS_GRACIA_SSO_MS", "3000"))

# ── Login: el SSO cambia por ambiente ───────────────────────────────────────
# TEST → formulario propio de Keycloak (usuario + contraseña, sin 2FA).
# PROD → botón de Google → correo + contraseña de Gmail + 2FA en el celular.
KC_USER   = "#username, input[name='username']"
KC_PASS   = "#password, input[name='password']"
KC_SUBMIT = "#kc-login, input[name='login'], button[type='submit']"
BTN_GOOGLE = "#zocial-google"
# Cualquiera de estos en pantalla ⇒ estamos en el SSO, no dentro de Chronos.
SSO_MARCADORES = f"{BTN_GOOGLE}, #identifierId, #username, #kc-form-login"
# Retos de 2FA de Google (si aparece uno, se espera con paciencia).
RETO_2FA = ("div#deviceAddressContainer, div[data-challengetype], "
            "input[name='totpPin'], #idvPreregisteredPhoneNumber, "
            "div:has-text('2-Step Verification'), "
            "div:has-text('Verificación en 2 pasos')")


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


def _leer_estado() -> dict:
    """Lee el archivo de sesión. Acepta el formato viejo (lista de cookies)."""
    ruta = settings.CHRONOS_COOKIES
    if not ruta.exists():
        return {}
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("[Chronos] Sesión guardada ilegible: %s", str(e)[:90])
        return {}
    if isinstance(datos, list):                     # formato anterior
        return {"cookies": datos, "origins": []}
    if isinstance(datos, dict):
        return {"cookies": datos.get("cookies") or [],
                "origins": datos.get("origins") or []}
    return {}


async def cargar_cookies(context) -> bool:
    """Restaura la sesión de Chronos en el contexto. True si había algo que usar.

    Se restauran DOS cosas, porque una sola no alcanza:
      • cookies de Chronos + SSO (permiten el re-login silencioso de Keycloak),
      • localStorage del origen de Chronos (ahí vive el token de la app Angular).
    """
    estado = _leer_estado()
    cookies, origins = estado.get("cookies") or [], estado.get("origins") or []
    if not cookies and not origins:
        logger.info("[Chronos] Sin sesión guardada — se hará login la 1ª vez.")
        return False
    try:
        if cookies:
            await context.add_cookies(cookies)
            logger.info("[Chronos] %d cookies de sesión reutilizadas.", len(cookies))
        if origins:
            # El localStorage solo se puede escribir estando EN el origen, así
            # que se inyecta con un init script que corre antes de la app.
            payload = json.dumps(origins)
            await context.add_init_script(
                "(() => { const data = " + payload + ";"
                " const o = data.find(d => location.origin.startsWith("
                "  (d.origin||'').replace(/\\/$/, '')));"
                " if (!o) return;"
                " for (const it of (o.localStorage || [])) {"
                "   try { localStorage.setItem(it.name, it.value); } catch (e) {} }"
                "})();")
            logger.info("[Chronos] localStorage de %d origen(es) restaurado.",
                        len(origins))
        return True
    except Exception as e:
        logger.warning("[Chronos] No se pudo restaurar la sesión: %s", str(e)[:90])
        return False


async def guardar_cookies(context) -> None:
    """Guarda cookies (Chronos + SSO) y localStorage de Chronos."""
    try:
        todas = await context.cookies()
        cookies = [c for c in todas if _es_cookie_relevante(c)]
        origins = []
        try:
            estado = await context.storage_state()
            host = _host_chronos()
            for o in (estado.get("origins") or []):
                dom = (urlparse(o.get("origin", "")).hostname or "").lower()
                if not dom or dom.startswith("test-hermes") or dom.startswith("hermes"):
                    continue
                if (host and (dom in host or host in dom)) or _es_dominio_sso(dom):
                    origins.append(o)
        except Exception:
            pass
        if not cookies and not origins:
            logger.warning("[Chronos] No hay sesión de Chronos que guardar.")
            return
        settings.SESSION_DIR.mkdir(parents=True, exist_ok=True)
        settings.CHRONOS_COOKIES.write_text(
            json.dumps({"cookies": cookies, "origins": origins}, indent=2),
            encoding="utf-8")
        logger.info("[Chronos] Sesión guardada (%d cookies · %d origen/es) en %s",
                    len(cookies), len(origins), settings.CHRONOS_COOKIES.name)
    except Exception as e:
        logger.warning("[Chronos] No se pudo guardar la sesión: %s", str(e)[:90])


def _es_dominio_sso(dom: str) -> bool:
    return any(dom.endswith(d) for d in _DOMINIOS_SSO)


async def en_pantalla_de_login(page) -> bool:
    """True si la página actual es el SSO (Keycloak o Google), no Chronos."""
    try:
        url = (page.url or "").lower()
        if "accounts.google.com" in url or "/auth/realms" in url:
            return True
        return bool(await page.locator(SSO_MARCADORES).first.count())
    except Exception:
        return False


async def sesion_activa(page, timeout_ms: int = None) -> bool:
    """True si Chronos ya está dentro (el botón Menu del home es visible).

    Se resuelve por SONDEO rápido (no por `networkidle`: el home de Chronos
    hace polling de notificaciones y nunca queda inactivo, así que esperar
    'red inactiva' regalaba segundos en cada llamada).

    En cuanto ve el Menu devuelve True; en cuanto ve el SSO devuelve False.
    Así el caso arranca de inmediato cuando la sesión ya estaba viva."""
    limite = timeout_ms if timeout_ms is not None else settings.TIMEOUT_READY
    menu = page.locator(TOOLBAR_MENU).first
    login = page.locator(SSO_MARCADORES).first
    espera = 0
    sso_seguido = 0        # ms que el SSO lleva visible SIN interrupción
    while espera <= limite:
        try:
            if await menu.is_visible():
                return True
        except Exception:
            pass
        # Ver el SSO un instante NO significa que la sesión murió: Keycloak
        # rebota por ahí para re-autenticar en silencio. Solo se da por muerta
        # si el SSO se queda en pantalla de forma sostenida (GRACIA_SSO).
        try:
            sso_seguido = (sso_seguido + 250) if await login.is_visible() else 0
        except Exception:
            sso_seguido = 0
        if sso_seguido >= GRACIA_SSO:
            logger.info("[Chronos] SSO estable %.1f s — la sesión no está activa.",
                        sso_seguido / 1000)
            return False
        await page.wait_for_timeout(250)
        espera += 250
    return False


async def abrir_chronos(page, *, login_si_necesario: bool = True) -> bool:
    """Navega a Chronos y deja la sesión lista, REUTILIZANDO cookies.

    Orden: (1) inyecta las cookies guardadas, (2) navega, (3) si la sesión está
    activa NO hace login (clave: el SSO de Google limita los intentos),
    (4) si no, hace login y GUARDA las cookies para las próximas corridas."""
    context = page.context
    tenia_sesion = await cargar_cookies(context)

    logger.info("[Chronos] Navegando a %s", settings.CHRONOS_URL)
    try:
        await page.goto(settings.CHRONOS_URL, wait_until="domcontentloaded",
                        timeout=settings.TIMEOUT_NAVIGATION)
    except Exception as e:
        logger.warning("[Chronos] La navegación tardó (%s) — continúo.", str(e)[:70])
    if await sesion_activa(page):
        logger.info("[Chronos] ✓ Sesión activa — login omitido.")
        await guardar_cookies(context)      # refresca la expiración
        return True

    if tenia_sesion:
        logger.info("[Chronos] La sesión guardada ya no sirve — se renueva el login.")
    if not login_si_necesario:
        return False

    # Sesión no activa → LOGIN AUTOMÁTICO y CONTINUAR, igual que Hermes: un solo
    # comando basta, no hace falta correr nada aparte.
    for intento in (1, 2):
        logger.info("[Chronos] Sesión no activa — ejecutando login (intento %d/2)…",
                    intento)
        await login(page)
        # Tras el SSO la app puede quedar en una pantalla intermedia: se
        # re-navega al home y se comprueba antes de reintentar.
        if await sesion_activa(page):
            logger.info("[Chronos] ✓ Sesión establecida — continúo con el flujo.")
            await guardar_cookies(context)
            return True
        try:
            await page.goto(settings.CHRONOS_URL, wait_until="domcontentloaded",
                            timeout=settings.TIMEOUT_NAVIGATION)
        except Exception:
            pass
        if await sesion_activa(page):
            logger.info("[Chronos] ✓ Sesión establecida tras revalidar.")
            await guardar_cookies(context)
            return True
        if not await en_pantalla_de_login(page):
            break        # no está en el SSO: reintentar el login no ayudaría

    logger.error("[Chronos] No se pudo establecer la sesión. Revisa CHRONOS_USER / "
                 "CHRONOS_PASS y que hayas aprobado el 2FA en el celular "
                 "(espera actual: %d min, ajustable con CHRONOS_2FA_MS).",
                 TIMEOUT_2FA // 60000)
    return False


async def _esperar_home(page, *, permitir_2fa: bool) -> bool:
    """Espera el home de Chronos SIN regalar tiempo.

    Sondea cada 250 ms y devuelve en cuanto el Menu es visible — antes se hacía
    `wait_for_url(..., timeout=TIMEOUT_2FA)`, que seguía esperando aunque el
    home ya estuviera cargado. La espera larga del 2FA solo se activa si el reto
    aparece de verdad en pantalla (producción)."""
    menu = page.locator(TOOLBAR_MENU).first
    reto = page.locator(RETO_2FA).first
    limite = TIMEOUT_HOME
    aviso_2fa = False
    espera = 0
    while espera <= limite:
        try:
            if await menu.is_visible():
                logger.info("[Chronos] Home visible (%.1f s).", espera / 1000)
                return True
        except Exception:
            pass
        if permitir_2fa and not aviso_2fa:
            try:
                if await reto.count() and await reto.is_visible():
                    aviso_2fa = True
                    limite = TIMEOUT_2FA
                    logger.info("[Chronos] 2FA solicitado — APRUÉBALO en el "
                                "celular (hasta %d min)…", TIMEOUT_2FA // 60000)
            except Exception:
                pass
        await page.wait_for_timeout(250)
        espera += 250
    logger.warning("[Chronos] El home no apareció en %.0f s.", limite / 1000)
    return False


async def login(page) -> bool:
    """Login de Chronos, con el método que corresponda al ambiente.

    TEST usa el formulario de Keycloak (usuario + contraseña); PRODUCCIÓN usa el
    SSO de Google con 2FA. Por defecto se DETECTA mirando la pantalla, así que
    no hay que configurar nada; `CHRONOS_LOGIN_MODE=password|google` lo fuerza."""
    modo = (settings.CHRONOS_LOGIN_MODE or "auto").lower()
    if modo == "auto":
        # OJO con el orden: Keycloak muestra el formulario de usuario Y el botón
        # de Google a la vez. Si hay campo de usuario se prefiere el formulario,
        # que es determinístico y no gasta intentos del SSO ni pide 2FA.
        # En producción manda el ambiente, porque ahí el acceso es por Google.
        prefiere_google = settings.por_ambiente(False, True)
        try:
            hay_form = bool(await page.locator(KC_USER).first.count())
            hay_google = bool(await page.locator(BTN_GOOGLE).first.count())
            if hay_form and not prefiere_google:
                modo = "password"
            elif hay_google:
                modo = "google"
            elif hay_form:
                modo = "password"
            else:
                modo = "google" if prefiere_google else "password"
        except Exception:
            modo = "google" if prefiere_google else "password"
    logger.info("[Chronos] Login por %s.",
                "usuario y contraseña (Keycloak)" if modo == "password"
                else "SSO de Google + 2FA")
    return (await login_password(page) if modo == "password"
            else await login_google(page))


async def login_password(page) -> bool:
    """Login de TEST: formulario propio de Keycloak (sin 2FA)."""
    usuario, clave = settings.CHRONOS_USER, settings.CHRONOS_PASS
    if not usuario or not clave:
        logger.error("[Chronos] Faltan CHRONOS_USER / CHRONOS_PASS en el .env.")
        return False
    try:
        campo = page.locator(KC_USER).first
        await campo.wait_for(state="visible", timeout=30_000)
        await campo.fill(usuario)
        await page.locator(KC_PASS).first.fill(clave)
        logger.info("[Chronos] Credenciales de %s enviadas.", usuario)
        try:
            await page.locator(KC_SUBMIT).first.click(timeout=10_000)
        except Exception:
            await page.locator(KC_PASS).first.press("Enter")
        ok = await _esperar_home(page, permitir_2fa=False)
        logger.info("[Chronos] Login %s.", "OK" if ok else "no confirmado")
        return ok
    except Exception as e:
        logger.warning("[Chronos] Login con usuario/contraseña falló: %s", str(e)[:120])
        return False


async def login_google(page) -> bool:
    """Login de PRODUCCIÓN por SSO de Google (correo Maxi + contraseña de Gmail).

    Si Google pide 2FA se espera hasta TIMEOUT_2FA para aprobarlo en el celular;
    si no lo pide, entra de inmediato (no se espera de más)."""
    usuario, clave = settings.CHRONOS_USER, settings.CHRONOS_PASS
    if not usuario or not clave:
        logger.error("[Chronos] Faltan CHRONOS_USER / CHRONOS_PASS en el .env.")
        return False
    try:
        # Botón "Google" del SSO
        btn = page.locator(BTN_GOOGLE).first
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
        # Home de Chronos: sondeo rápido. La espera larga solo se activa si el
        # reto de 2FA aparece de verdad.
        ok = await _esperar_home(page, permitir_2fa=True)
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
