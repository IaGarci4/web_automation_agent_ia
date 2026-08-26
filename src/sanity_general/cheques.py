"""
Cheques (Checks) — CP07 · Procesamiento de cheque individual.

Port del POM del repo viejo (`src/models/checks_page.py`) a funciones sobre
`flow` / `page`. Cubre: navegar a Cheques > Individuales, escanear (el escáner
es un EMULADOR ya disponible), editar los datos del cheque, procesar, finalizar,
y buscar el cheque en Reportes > Transacciones con status 'Verify Hold'.

Notas del original que aquí se respetan:
  • Hay data-testid DUPLICADOS → siempre `.locator("visible=true").first`.
  • Los inputs tienen MÁSCARA de Angular: un `fill()` directo no la dispara;
    hay que click + fill("") + type(delay) + blur.
  • El monto usa máscara de moneda que llena de DERECHA a IZQUIERDA:
    "5.00" se teclea como "500".
  • El escaneo puede tardar (hasta 3 min): la señal de que terminó es que el
    campo de fecha de emisión se vuelve visible.
"""

import os
import random
import re
from datetime import datetime, timedelta
from decimal import Decimal

from config.logger import get_logger

logger = get_logger("sanity.cheques")

# ── Navegación ──────────────────────────────────────────────────────────────
CHECKS_NAVBAR      = "checks-navbar-item"
INDIVIDUALS_OPTION = "checks-0-navbar-dropdown-item"
MODAL_DENY_BTN     = "modal-confirmation-deny-button"     # 'YES, Leave'

# ── Configuración > Dispositivos (PREREQUISITO del escaneo) ─────────────────
# Sin el escáner seleccionado, 'Scan Check' no hace nada (y Hermes puede
# redirigir aquí). Se valida ANTES de entrar a Cheques.
SETTINGS_NAVBAR   = "settings-navbar-item"
DEVICES_OPTION    = "settings-2-navbar-dropdown-item"
COMBO_SEL         = "span[role='combobox']"
DROPDOWN_ITEM_SEL = ("li[role='option'], .p-dropdown-item, "
                     "[data-testid$='-dropdown-item']")
RE_SCANNER = re.compile(r"scanner|esc[aá]ner", re.I)
RE_CANON   = re.compile(r"canon", re.I)
ESCANER_ESPERADO = os.getenv("CP07_SCANNER", "CANON")

# ── Escaneo ─────────────────────────────────────────────────────────────────
SCAN_BUTTON      = "pre-scan-check-process-button"
SCAN_MODAL_TITLE = "checks-page-scan-check-modal-title-h5-heading"
SCAN_TIMEOUT     = 180_000

# ── Datos del cheque ────────────────────────────────────────────────────────
CHECK_NUMBER_INPUT = "issuer-check-form-checkNumber-input"
ISSUED_DATE_INPUT  = "issuer-check-form-dateIssued-input"
CHECK_AMOUNT_INPUT = "check-amount-input"
DATE_FORMAT        = "%m/%d/%Y"

# ── Procesar / finalizar ────────────────────────────────────────────────────
VALIDATE_BUTTON = "transaction-check-process-button"
FINISH_BUTTON   = "checks-page-success-process-check-modal-finish-process-button"

# ── Reportes > Transacciones (búsqueda del cheque) ──────────────────────────
TX_TYPE_DROPDOWN_LABEL = "[data-testid='select-field-dropdown-input'] span[role='combobox']"
START_DATE_INPUT = "report-range-dates-start-date-input"
SEARCH_BUTTON    = "test-id-button"
TX_ROW           = "tr.report-transactions-result-row"
STATUS_CHIP      = "span.text-chip"
FOLIO_COL, CHECK_NUMBER_COL = 1, 4
RE_BUSCAR = re.compile(r"buscar|search", re.I)
RE_CHECKS = re.compile(r"check|cheque", re.I)   # 'CHECKS' / 'CHEQUES' (EN/ES)


def generar_numero_cheque() -> str:
    """Número de cheque aleatorio para la corrida (como el original)."""
    return str(random.randint(1000, 999999))


def _teclas_monto(amount: str) -> str:
    """'5.00' → '500' (la máscara de moneda llena de derecha a izquierda)."""
    limpio = str(amount).replace("$", "").replace(",", "").strip()
    return str(int(Decimal(limpio) * 100))


async def _visible(page, testid: str, timeout: int = 30_000):
    """Primer elemento VISIBLE de un testid (hay duplicados en el DOM)."""
    loc = page.get_by_test_id(testid).locator("visible=true").first
    await loc.wait_for(state="visible", timeout=timeout)
    return loc


async def _fill_mascara(page, loc, valor: str, label: str) -> None:
    """Llenado compatible con la máscara de Angular: click + limpiar + teclear."""
    await loc.click(force=True)
    try:
        await loc.fill("")
    except Exception:
        pass
    await loc.type(str(valor), delay=90)
    try:
        await loc.blur()
    except Exception:
        pass
    await page.wait_for_timeout(700)
    logger.info("[Cheques] %s = %s", label, valor)


async def _click_si_esta(page, testid: str, label: str, timeout: int = 5_000) -> bool:
    """Click opcional (p.ej. el modal 'YES, Leave'): si no aparece, no falla."""
    try:
        loc = page.get_by_test_id(testid).locator("visible=true").first
        await loc.wait_for(state="visible", timeout=timeout)
        await loc.click(force=True)
        await page.wait_for_timeout(900)
        logger.info("[Cheques] %s", label)
        return True
    except Exception:
        return False


# ── Flujo ───────────────────────────────────────────────────────────────────

async def _combo_del_escaner(page):
    """Dropdown del SCANNER en Configuración > Dispositivos.

    Hay tres dropdowns muy parecidos (Printer, Scanner, MO Printer) y comparten
    `id="dropdown"`, así que el del escáner se localiza por su ETIQUETA (bilingüe)
    y, si eso falla, por el que ofrezca una opción tipo CANON (2º combobox)."""
    # 1) Por la etiqueta 'Scanner'/'Escáner' → primer combobox que le sigue.
    for etiqueta in ("Scanner", "Escáner", "Escaner"):
        try:
            loc = page.locator(
                f"xpath=//*[normalize-space(text())='{etiqueta}']"
                f"/following::span[@role='combobox'][1]").first
            if await loc.count() and await loc.is_visible():
                return loc
        except Exception:
            continue
    # 2) Fallback: el 2º combobox visible (orden: Printer, Scanner, MO Printer).
    try:
        combos = page.locator(COMBO_SEL).locator("visible=true")
        if await combos.count() >= 2:
            return combos.nth(1)
    except Exception:
        pass
    return None


async def configurar_escaner(flow, esperado: str = ESCANER_ESPERADO,
                            evi=None) -> bool:
    """PREREQUISITO del CP07: Configuración > Dispositivos y validar que el
    SCANNER sea el esperado (CANON). Si no lo está, lo selecciona.

    Se hace ANTES de entrar a Cheques: sin escáner configurado, 'Scan Check' no
    abre el modal de escaneo (y Hermes puede mandar a esta misma pantalla).
    """
    page = flow.page
    logger.info("[Cheques] Prerequisito · Configuración > Dispositivos…")
    # 1) Navegar (el engrane del navbar → 'Dispositivos')
    try:
        nav = page.get_by_test_id(SETTINGS_NAVBAR).first
        await nav.wait_for(state="visible", timeout=20_000)
        try:
            await nav.hover()
            await page.wait_for_timeout(300)
        except Exception:
            pass
        await nav.click(force=True)
        opt = page.get_by_test_id(DEVICES_OPTION).first
        await opt.wait_for(state="visible", timeout=10_000)
        await opt.click(force=True)
    except Exception as e:
        logger.warning("[Cheques] No se pudo abrir Dispositivos: %s", str(e)[:100])
        return False
    # 2) Modal de salida ('YES, Leave') si veníamos de otra pantalla
    await page.wait_for_timeout(1_200)
    await _click_si_esta(page, MODAL_DENY_BTN, "Modal de salida cerrado (YES, Leave)")

    # 3) La pantalla tarda en cargar los dispositivos (5-10 s): sondeo del combo
    combo = None
    for _ in range(20):                      # hasta ~10 s
        combo = await _combo_del_escaner(page)
        if combo is not None:
            break
        await page.wait_for_timeout(500)
    if combo is None:
        logger.warning("[Cheques] No apareció el selector de escáner.")
        return False

    # 4) ¿Ya está el esperado? (el aria-label trae el valor, ej. 'CANON (DEFAULT)')
    #    Se sondea: recién montado el combo puede leerse VACÍO y eso hacía creer
    #    que no había escáner (y abría el dropdown de más).
    actual = ""
    for _ in range(8):                        # hasta ~4 s
        try:
            actual = ((await combo.get_attribute("aria-label")) or
                      (await combo.inner_text()) or "").strip()
        except Exception:
            actual = ""
        if actual:
            break
        await page.wait_for_timeout(500)
    if re.search(esperado, actual, re.I):
        logger.info("[Cheques] Escáner ya seleccionado: '%s' ✓", actual.strip())
        if evi:
            await evi.shot("dispositivos_escaner_ok")
        return True

    # 5) No está → abrir el dropdown y elegir la opción del escáner esperado
    logger.info("[Cheques] Escáner actual '%s' — seleccionando '%s'…",
                actual.strip(), esperado)
    try:
        await combo.click(force=True)
        await page.wait_for_timeout(800)
        opciones = page.locator(DROPDOWN_ITEM_SEL).locator("visible=true")
        n = await opciones.count()
        for i in range(min(n, 40)):
            op = opciones.nth(i)
            txt = (await op.inner_text() or "").strip()
            if re.search(esperado, txt, re.I):
                await op.click(force=True)
                await page.wait_for_timeout(1_000)
                logger.info("[Cheques] Escáner seleccionado: '%s' ✓", txt)
                if evi:
                    await evi.shot("dispositivos_escaner_seleccionado")
                return True
        logger.warning("[Cheques] '%s' no está entre las opciones de escáner.", esperado)
    except Exception as e:
        logger.warning("[Cheques] No se pudo seleccionar el escáner: %s", str(e)[:100])
    if evi:
        await evi.shot("dispositivos_escaner_sin_seleccionar")
    return False


async def ir_a_cheques_individuales(flow) -> None:
    """Cheques > Cheques individuales (cierra el modal de salida si aparece)."""
    page = flow.page
    logger.info("[Cheques] Navegando a Cheques > Individuales…")
    nav = page.get_by_test_id(CHECKS_NAVBAR).first
    await nav.wait_for(state="visible", timeout=15_000)
    try:
        await nav.hover()
        await page.wait_for_timeout(300)
    except Exception:
        pass
    await nav.click(force=True)
    opt = page.get_by_test_id(INDIVIDUALS_OPTION).first
    await opt.wait_for(state="visible", timeout=10_000)
    await opt.click(force=True)
    await page.wait_for_timeout(1_800)
    await _click_si_esta(page, MODAL_DENY_BTN, "Modal de salida cerrado (YES, Leave)")
    await page.get_by_test_id(SCAN_BUTTON).locator("visible=true").first.wait_for(
        state="visible", timeout=30_000)
    logger.info("[Cheques] Pantalla de cheques individuales lista.")


RE_SCAN = re.compile(r"scan\s*check|escanear\s*cheque|escanear", re.I)


async def _esperar_campos(page, timeout_ms: int) -> bool:
    """Espera SOLO a que aparezcan los campos del cheque (fin del escaneo).

    Es distinta de _reaccion_al_scan: aquí el modal de escaneo se IGNORA (sigue
    en pantalla mientras el escáner trabaja). Antes se reutilizaba la otra
    función y devolvía 'modal' en el primer sondeo → abortaba en milisegundos."""
    paso, t = 500, 0
    while t < timeout_ms:
        try:
            if await page.get_by_test_id(ISSUED_DATE_INPUT).locator(
                    "visible=true").first.is_visible():
                return True
        except Exception:
            pass
        await page.wait_for_timeout(paso)
        t += paso
    return False


async def _reaccion_al_scan(page, timeout_ms: int) -> str:
    """Espera (poll) una señal de que el escaneo ARRANCÓ o TERMINÓ:
      'modal'  → se abrió el modal de escaneo
      'campos' → ya están los campos del cheque (terminó)
      ''       → nada cambió (el clic no tomó efecto)"""
    paso, t = 500, 0
    while t < timeout_ms:
        try:
            if await page.get_by_test_id(ISSUED_DATE_INPUT).locator(
                    "visible=true").first.is_visible():
                return "campos"
        except Exception:
            pass
        try:
            if await page.get_by_test_id(SCAN_MODAL_TITLE).locator(
                    "visible=true").first.is_visible():
                return "modal"
        except Exception:
            pass
        await page.wait_for_timeout(paso)
        t += paso
    return ""


async def _click_scan(flow) -> bool:
    """Pulsa 'Scan Check'. En Hermes el data-testid suele estar en un WRAPPER, así
    que un click con force sobre él NO dispara el handler del <button> real: por eso
    se intenta (1) como el repo viejo —selector CSS crudo con wait_and_click—,
    (2) el <button> interno del wrapper, (3) por rol/texto (EN/ES)."""
    page = flow.page
    intentos = (
        ("wait_and_click(css)",
         lambda: flow.wait_and_click(f"[data-testid='{SCAN_BUTTON}']")),
        ("button interno",
         lambda: page.get_by_test_id(SCAN_BUTTON).locator(
             "button, [role='button']").first.click(timeout=6_000)),
        ("testid directo",
         lambda: page.get_by_test_id(SCAN_BUTTON).locator(
             "visible=true").first.click(timeout=6_000)),
        ("por texto/rol",
         lambda: page.get_by_role("button", name=RE_SCAN).first.click(timeout=6_000)),
    )
    for etiqueta, accion in intentos:
        try:
            await accion()
            logger.info("[Cheques] 'Scan Check' pulsado (%s).", etiqueta)
            return True
        except Exception as e:
            logger.info("[Cheques] 'Scan Check' vía %s no aplicó (%s).",
                        etiqueta, str(e)[:70])
    return False


async def escanear(flow, timeout: int = SCAN_TIMEOUT) -> bool:
    """Lanza el escaneo (emulador) y espera a que termine.

    La señal de fin es que el campo de FECHA DE EMISIÓN se vuelve visible (así
    lo detecta el original: el modal informativo puede quedarse en pantalla).

    Si tras pulsar el botón NADA cambia (la pantalla se queda en 'Scan Check'),
    se REINTENTA el clic — antes se esperaban 3 minutos en vano."""
    page = flow.page
    logger.info("[Cheques] Escaneando el cheque (emulador)…")
    for intento in range(1, 4):
        if not await _click_scan(flow):
            logger.warning("[Cheques] No se pudo pulsar 'Scan Check' (intento %d).", intento)
            await page.wait_for_timeout(1_500)
            continue
        # ¿Arrancó algo? (modal o campos). Ventana corta: si no reacciona, el
        # clic no tomó efecto y hay que reintentar.
        estado = await _reaccion_al_scan(page, 12_000)
        if estado == "campos":
            logger.info("[Cheques] Escaneo completado (intento %d).", intento)
            return True
        if estado == "modal":
            logger.info("[Cheques] Modal de escaneo abierto — esperando el "
                        "resultado del escáner (hasta %d s)…", timeout // 1000)
            if await _esperar_campos(page, timeout):
                try:
                    await page.wait_for_load_state("networkidle", timeout=30_000)
                except Exception:
                    pass
                logger.info("[Cheques] Escaneo completado.")
                return True
            logger.warning("[Cheques] El modal de escaneo no devolvió los campos "
                           "en %d s.", timeout // 1000)
            return False
        # Caso típico: Hermes manda a Configuración > Dispositivos cuando no
        # detecta el escáner (o no hay uno seleccionado para esta agencia).
        if "settings/devices" in (page.url or "").lower():
            logger.error("[Cheques] Hermes redirigió a Configuración > Dispositivos: "
                         "hay que SELECCIONAR el escáner (emulador) para esta "
                         "agencia antes de escanear.")
            return False
        logger.warning("[Cheques] El clic en 'Scan Check' no tuvo efecto "
                       "(intento %d) — reintento.", intento)
    logger.warning("[Cheques] El escaneo no expuso los campos del cheque.")
    return False


async def llenar_datos(flow, numero: str, amount: str = "5.00") -> dict:
    """Edita número de cheque, fecha de emisión (+1 día) y monto.

    Devuelve {'check_number', 'issued_date', 'amount'} para usarlo luego en la
    búsqueda en Reportes y en la verificación desde Chronos."""
    page = flow.page

    # 1) Número de cheque — VERIFICADO: la máscara de Angular puede comerse un
    #    dígito (escribir 129846 y dejar 12986). Se reintenta y, al final, se usa
    #    el valor REALMENTE aplicado (si no, se buscaría en el reporte un número
    #    que no existe y el caso fallaría con 'status None').
    inp_num = await _visible(page, CHECK_NUMBER_INPUT)
    numero_aplicado = str(numero)
    for intento in (1, 2, 3):
        await _fill_mascara(page, inp_num, numero, "Número de cheque")
        try:
            leido = "".join(c for c in (await inp_num.input_value() or "") if c.isdigit())
        except Exception:
            leido = ""
        if leido == str(numero):
            numero_aplicado = leido
            break
        logger.warning("[Cheques] El número quedó '%s' y se pidió '%s' "
                       "(intento %d) — reintento.", leido, numero, intento)
        if leido:
            numero_aplicado = leido      # respaldo: lo que de verdad quedó
    if numero_aplicado != str(numero):
        logger.warning("[Cheques] Se usará el número REAL del campo: %s", numero_aplicado)

    # 2) Fecha de emisión = la que trae el cheque + 1 día (o hoy + 1 si viene vacía)
    inp_fecha = await _visible(page, ISSUED_DATE_INPUT)
    actual = ""
    try:
        actual = (await inp_fecha.input_value() or "").strip()
    except Exception:
        pass
    try:
        base = datetime.strptime(actual, DATE_FORMAT) if actual else datetime.now()
    except Exception:
        base = datetime.now()
    nueva_fecha = (base + timedelta(days=1)).strftime(DATE_FORMAT)
    await _fill_mascara(page, inp_fecha, nueva_fecha, "Fecha de emisión (+1 día)")

    # 3) Monto (máscara de moneda: se teclea sin punto, de derecha a izquierda)
    inp_monto = await _visible(page, CHECK_AMOUNT_INPUT)
    await _fill_mascara(page, inp_monto, _teclas_monto(amount), f"Monto ({amount})")
    aplicado = amount
    try:
        crudo = (await inp_monto.input_value() or "").replace("$", "").replace(",", "").strip()
        if crudo:
            aplicado = f"{Decimal(crudo):.2f}"
    except Exception:
        pass

    # Se devuelve el número REALMENTE aplicado (no el solicitado): es el que
    # hay que buscar en Reportes y verificar luego en Chronos.
    datos = {"check_number": numero_aplicado, "issued_date": nueva_fecha,
             "amount": aplicado}
    logger.info("[Cheques] Datos del cheque: %s", datos)
    return datos


async def procesar(flow) -> None:
    """Click en 'Procesar' (Validate Check)."""
    page = flow.page
    btn = await _visible(page, VALIDATE_BUTTON)
    try:
        await btn.wait_for(state="visible", timeout=30_000)
    except Exception:
        pass
    await btn.click(force=True)
    await page.wait_for_timeout(4_000)
    logger.info("[Cheques] Cheque PROCESADO (Validate).")


async def finalizar(flow) -> None:
    """Click en 'Finalizar' del modal de éxito."""
    page = flow.page
    btn = await _visible(page, FINISH_BUTTON, timeout=60_000)
    await btn.click(force=True)
    await page.wait_for_timeout(2_000)
    logger.info("[Cheques] Proceso FINALIZADO.")


# ── Reportes > Transacciones ────────────────────────────────────────────────

def fecha_ayer() -> str:
    return (datetime.now() - timedelta(days=1)).strftime(DATE_FORMAT)


def fecha_hoy() -> str:
    return datetime.now().strftime(DATE_FORMAT)


async def seleccionar_tipo_checks(flow) -> bool:
    """Fija el 'Transaction Type' en CHECKS (viene en MONEY TRANSFER por default).

    Robusto: no depende de un aria-label exacto (fallaba con
    li[role=option][aria-label='CHECKS']); abre el dropdown y elige la opción
    cuyo texto contenga CHECK/CHEQUE, y VERIFICA que el label quedó cambiado."""
    page = flow.page
    for intento in (1, 2):
        try:
            combo = page.locator(TX_TYPE_DROPDOWN_LABEL).first
            await combo.wait_for(state="visible", timeout=15_000)
            # ¿Ya está en CHECKS?
            actual = ((await combo.get_attribute("aria-label")) or
                      (await combo.inner_text()) or "")
            if RE_CHECKS.search(actual):
                logger.info("[Cheques] Tipo de transacción ya es '%s' ✓", actual.strip())
                return True
            await combo.click(force=True)
            await page.wait_for_timeout(1_000)
            opciones = page.locator(DROPDOWN_ITEM_SEL).locator("visible=true")
            n = await opciones.count()
            for i in range(min(n, 40)):
                op = opciones.nth(i)
                txt = ((await op.get_attribute("aria-label")) or
                       (await op.inner_text()) or "").strip()
                if RE_CHECKS.search(txt):
                    await op.click(force=True)
                    await page.wait_for_timeout(1_200)
                    nuevo = ((await combo.get_attribute("aria-label")) or
                             (await combo.inner_text()) or "")
                    if RE_CHECKS.search(nuevo):
                        logger.info("[Cheques] Tipo de transacción: %s ✓", txt)
                        return True
            logger.warning("[Cheques] 'CHECKS' no apareció entre las %d opciones "
                           "(intento %d).", n, intento)
            try:                     # cerrar el panel antes de reintentar
                await page.keyboard.press("Escape")
            except Exception:
                pass
        except Exception as e:
            logger.warning("[Cheques] Tipo de transacción, intento %d: %s",
                           intento, str(e)[:90])
        await page.wait_for_timeout(800)
    return False


async def buscar_cheques_desde(flow, desde: str) -> None:
    """En Reportes > Transacciones: tipo 'CHECKS' + fecha inicial + Buscar."""
    page = flow.page
    if not await seleccionar_tipo_checks(flow):
        logger.error("[Cheques] El reporte sigue filtrado por otro tipo "
                     "(se esperaba CHECKS) — el cheque no aparecerá.")
    # Fecha inicial
    try:
        inp = await _visible(page, START_DATE_INPUT, timeout=15_000)
        await _fill_mascara(page, inp, desde, "Fecha inicial del reporte")
    except Exception as e:
        logger.warning("[Cheques] No se pudo fijar la fecha inicial: %s", str(e)[:90])
    # Buscar (testid genérico → desambiguar por texto EN/ES)
    try:
        btn = page.get_by_test_id(SEARCH_BUTTON).filter(has_text=RE_BUSCAR).first
        if await btn.count() == 0:
            btn = page.get_by_test_id(SEARCH_BUTTON).first
        await btn.click(force=True)
    except Exception as e:
        logger.warning("[Cheques] No se pudo pulsar Buscar: %s", str(e)[:90])
    await page.wait_for_timeout(6_000)
    try:
        await page.wait_for_load_state("networkidle", timeout=30_000)
    except Exception:
        pass


async def fila_del_cheque(flow, numero: str):
    """Fila de Reportes > Transacciones cuyo Check Number coincide (o None)."""
    page = flow.page
    filas = page.locator(TX_ROW)
    try:
        await filas.first.wait_for(state="visible", timeout=30_000)
    except Exception:
        logger.warning("[Cheques] El reporte no devolvió filas.")
        return None
    n = await filas.count()
    for i in range(min(n, 80)):
        fila = filas.nth(i)
        try:
            celda = (await fila.locator("td").nth(CHECK_NUMBER_COL).inner_text() or "").strip()
            if celda == str(numero):
                return fila
        except Exception:
            continue
    return None


async def status_y_folio(flow, numero: str):
    """(status, folio) del cheque en el reporte. (None, None) si no aparece."""
    fila = await fila_del_cheque(flow, numero)
    if fila is None:
        return None, None, None
    status = folio = None
    try:
        await fila.scroll_into_view_if_needed()
    except Exception:
        pass
    try:
        status = (await fila.locator(STATUS_CHIP).first.inner_text() or "").strip()
    except Exception:
        pass
    try:
        folio = (await fila.locator("td").nth(FOLIO_COL).inner_text() or "").strip()
    except Exception:
        pass
    logger.info("[Cheques] Cheque %s → status='%s' folio='%s'", numero, status, folio)
    return status, folio, fila
