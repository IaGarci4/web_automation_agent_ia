"""
CP14 — Consulta y cancelación de una transacción desde Chronos.
(Migración/mejora de
`HERMES2-qa/src/sanity_general/test_CP14_Consulta_y_Cancelacion_de_una_transaccion_desde_Chronos.py`
+ `src/models/refactor_money_transfer_page_tab1.py` (envío a domicilio)
+ `src/models_chronos/chronos_main_page.py::cp14_*` (Chronos).)

El caso, de punta a punta:
  1. En Hermes 2 arma y ENVÍA una transferencia a domicilio (Home) a Filipinas
     con un cliente EXISTENTE (autofill por apellido), pagador UNIPHIL DELIVERY.
  2. Abre Chronos (back office) en una pestaña nueva, reutilizando NUESTRA sesión
     estable (`chronos.abrir_chronos`: cookies + login solo si expiró).
  3. Busca la transferencia por agencia + apellido, valida el Sender.
  4. En Status Change espera a 'Payment Ready' y la CANCELA desde Chronos.
  5. Fallback: si Chronos no llega a 'Payment Ready' o la cancelación falla, se
     cancela desde Hermes 2 (Reportes > Transacciones) reutilizando `cancelacion`.

Este módulo NO conoce el test: expone funciones sobre `page`/`flow`. La lógica
frágil (esperas, overlays, menús de Chronos) vive aquí, endurecida sobre lo que
ya sabemos estable.

Fuentes de locators:
  • Envío Home: `HERMES2-qa/src/models/locators/refactor_mt_tab1_locators.py`.
  • Chronos CP14: `HERMES2-qa/src/models_chronos/chronos_main_page.py` (__init__).
Como la web app es idéntica, los testids no cambian; Chronos no usa testid y va
por CSS/XPath (así es en el repo original — sensible a cambios de columnas).
"""
import os
import re

from playwright.async_api import expect

from config import settings
from config.logger import get_logger
from src.sanity_general import chronos as CH
from src.sanity_general import cancelacion as CANCEL

logger = get_logger("sanity.cp14")

TIMEOUT = 30_000

# ── Datos por defecto del caso (mismos del sanity original) ───────────────────
CLIENTE_NOMBRE   = os.getenv("CP14_CUSTOMER",  "ROBERTOH")
CLIENTE_APELLIDO = os.getenv("CP14_LASTNAME",  "LISEO")
PAIS_BENEF       = os.getenv("CP14_COUNTRY",   "PHILIPPINES")
CIUDAD           = os.getenv("CP14_CITY",      "PILI")
MONTO            = os.getenv("CP14_AMOUNT",    "1.00")
PAGADOR          = os.getenv("CP14_PAYER",     "UNIPHIL DELIVERY")
# Fecha de nacimiento del beneficiario (mm/dd/yyyy). El beneficiario cargado del
# historial puede venir SIN fecha y la app la exige para un envío válido.
BENEF_DOB        = os.getenv("CP14_BENEF_DOB", "01/15/1990")
# Branch code: en test '143'; en prod el número largo del original.
BRANCH_CODE      = os.getenv("CP14_BRANCH",
                             settings.por_ambiente("143", "143456789"))
# Agencia en Chronos: '0040-OK' en test, '0020-TX' en prod (como el original).
AGENCIA          = os.getenv("CP14_AGENCY",
                             settings.por_ambiente("0040-OK", "0020-TX"))

# ── Testids del envío a domicilio (Home) ─────────────────────────────────────
T_CUSTOMER_NAME      = "transfer-customer-name-0-input"
T_CUSTOMER_LASTNAME  = "transfer-customer-first-lastName-0-input"
T_CUSTOMER_TBL_CLOSE = "transfers-customer-close-table-0"
T_BENEF_COUNTRY      = "transfer-beneficiary-country-0-dropdown-input"
T_BENEF_COUNTRY_OPT0 = "transfer-beneficiary-country-0-dropdown-item-0"
T_TRANSFER_CLEAR     = "transfer-payers-0-clear-button-icon-svg"
T_TAB_HOME           = "transfer-payers-0-tab-title-2"
T_HOME_CITY          = "transfer-payers-money-info-city-0-home-dropdown-input"
T_HOME_AMOUNT        = "transfer-payers-money-info-amount-0-home-amount-input"
T_HOME_PAYER         = "transfer-payers-money-info-payer-0-home-input"
T_BENEF_DOB          = "transfer-beneficiary-date-of-birth-0-input"
T_BENEF_TOGGLE       = "transfer-beneficiary-toggle-fields-button-0"
T_PAYER_SEARCH_MODAL = "transfers-money-info-modal-search-payer-0-input-search-input"
T_BRANCH_CODE        = "transfer-payers-money-info-branch-code-0-deposit-input"
T_CONTINUE           = "transfer-continue-button-0-button"
T_CONFIRM_SEND       = "transfers-container-modal-summary-0-send-button"
T_DECLINE_ANOTHER    = "transfers-container-modal-success-transfer-0-decline-button"
T_COMPLIANCE_MSG     = "compliance-show-messages-tab-0-message"

# ── Chronos CP14 (CSS/XPath — no hay testid) ─────────────────────────────────
CH_MENU              = "//button[@title='Menu']"
CH_TRANSFER_PANEL    = "#mat-expansion-panel-header-11"
CH_SEARCH_TRANSFER   = '//div[normalize-space()="Search Transfer"]'
CH_STATUS_CHANGE     = '//div[normalize-space()="Status Change"]'
CH_AGENT_BTN_SEARCH  = 2   # índice en '.btn.input-group-text'
CH_AGENT_BTN_STATUS  = 3
CH_LAST_NAME_FILTER  = '//div[5]/div[2]/input'
CH_FIRST_FOLIO       = '//tbody/tr/td[2]'
CH_CUSTOMER_NAME     = '[name="CustomerName"]'
CH_NOTE              = "#Note"
CH_CANCEL_REASON     = 'div.row > div.spr > select.custom-select'
CH_SUCCESS_MSG       = 'p:has-text("Transfer has been successfully saved.")'
CH_SEARCH_MODAL      = "#searchModal"
CH_FOLIO_INPUT       = "input[formcontrolname='Folio']"
# Fila del reporte de Hermes + índice de la columna de folio (0-based).
HM_ROW               = "tr.report-transactions-result-row"
HM_FOLIO_COL_INDEX   = 1


# ═════════════════════════════════════════════════════════════════════════════
# PARTE 1 — HERMES 2: armar y enviar la transferencia a domicilio (Home)
# ═════════════════════════════════════════════════════════════════════════════

async def _clic_testid(page, testid: str, desc: str, timeout: int = TIMEOUT,
                       force: bool = False) -> None:
    b = page.get_by_test_id(testid).first
    await b.wait_for(state="visible", timeout=timeout)
    try:
        await b.scroll_into_view_if_needed(timeout=3_000)
    except Exception:
        pass
    try:
        await b.click(timeout=timeout, force=force)
    except Exception:
        await b.click(force=True, timeout=8_000)
    logger.info("[CP14] %s", desc)


async def autofill_cliente_por_apellido(page, nombre: str, apellido: str) -> None:
    """Selecciona un cliente EXISTENTE por nombre + apellido desde la tabla de
    autocompletado (port de `autofill_customer_info_by_Lastname`)."""
    logger.info("[CP14] Autocompletando cliente: %s %s", nombre, apellido)
    nom = page.get_by_test_id(T_CUSTOMER_NAME).first
    await nom.click()
    await nom.fill(nombre)
    await page.wait_for_timeout(1_000)
    ape = page.get_by_test_id(T_CUSTOMER_LASTNAME).first
    await ape.click()
    await ape.fill(apellido)

    fila = page.locator(f"//tr[td[contains(normalize-space(), '{nombre}')]]")
    await expect(fila).to_be_visible(timeout=30_000)
    await fila.first.click()
    logger.info("[CP14] Cliente existente seleccionado.")
    await page.wait_for_timeout(15_000)

    # Cerrar el modal 'Compliance information needed' si aparece.
    try:
        cerrar = page.get_by_role(
            "dialog", name="Compliance information needed").locator(
            "button.p-dialog-header-close")
        if await cerrar.is_visible():
            await cerrar.click(force=True)
            logger.info("[CP14] Modal 'Compliance information needed' cerrado.")
            await page.wait_for_timeout(500)
    except Exception:
        pass


async def limpiar_y_tab_home(page) -> None:
    """Limpia la sección de pagador y selecciona la pestaña Home (a domicilio)."""
    try:
        await _clic_testid(page, T_TRANSFER_CLEAR, "Sección de pagador limpiada")
        await page.wait_for_timeout(2_000)
    except Exception as e:
        logger.info("[CP14] No hubo sección que limpiar: %s", str(e)[:80])
    await _clic_testid(page, T_TAB_HOME, "Pestaña Home (a domicilio)")
    await page.wait_for_timeout(2_000)


async def esperar_loader_oculto(flow, timeout: int = 30_000) -> None:
    """Espera a que el loader (svg giratorio) desaparezca."""
    try:
        await expect(flow.loader).not_to_be_visible(timeout=timeout)
    except Exception:
        logger.info("[CP14] El loader seguía visible tras %d ms — continúo.", timeout)


async def llenar_detalles_home(page, pais: str, ciudad: str, monto: str,
                               pagador: str) -> None:
    """Llena país/ciudad/monto/pagador del envío Home (port de
    `fill_transfer_home_type_details`, endurecido)."""
    logger.info("[CP14] Detalles Home: país=%s, ciudad=%s, monto=%s, pagador=%s",
                pais, ciudad, monto, pagador)

    # Si la tabla de búsqueda de cliente sigue abierta: cerrarla, fijar el país
    # del beneficiario y re-seleccionar la pestaña Home (igual que el original).
    try:
        tbl_close = page.get_by_test_id(T_CUSTOMER_TBL_CLOSE).first
        if await tbl_close.is_visible():
            logger.info("[CP14] Cerrando tabla de búsqueda de cliente.")
            await tbl_close.click()
            await page.wait_for_timeout(500)
            pais_dd = page.get_by_test_id(T_BENEF_COUNTRY).first
            await pais_dd.click()
            await pais_dd.fill("")
            await pais_dd.type(pais, delay=100)
            await page.wait_for_timeout(500)
            opt = page.get_by_test_id(T_BENEF_COUNTRY_OPT0).first
            await expect(opt).to_be_visible(timeout=10_000)
            await opt.click()
            logger.info("[CP14] País del beneficiario: %s", pais)
            await page.wait_for_timeout(2_000)
            await page.get_by_test_id(T_TAB_HOME).first.click()
    except Exception as e:
        logger.info("[CP14] País/tabla de cliente: %s", str(e)[:90])

    # Ciudad
    ciudad_inp = page.get_by_test_id(T_HOME_CITY).first
    await ciudad_inp.wait_for(state="visible", timeout=TIMEOUT)
    await ciudad_inp.fill(ciudad)
    await page.wait_for_timeout(2_500)
    await ciudad_inp.press("Enter")
    await page.wait_for_timeout(1_500)

    # Monto
    monto_inp = page.get_by_test_id(T_HOME_AMOUNT).first
    await monto_inp.click()
    try:
        await monto_inp.fill("")
    except Exception:
        pass
    await monto_inp.type(str(monto))
    await monto_inp.press("Tab")
    await page.wait_for_timeout(5_000)

    # Pagador: puede autoseleccionarse; si no, buscarlo en el modal.
    try:
        valor = (await page.get_by_test_id(T_HOME_PAYER).first.input_value()) or ""
    except Exception:
        valor = ""
    if valor.strip():
        logger.info("[CP14] Pagador autoseleccionado: '%s'", valor.strip())
        await page.get_by_test_id(T_HOME_AMOUNT).first.press("Tab")
    else:
        logger.info("[CP14] Seleccionando pagador '%s' en el modal.", pagador)
        modal = page.get_by_test_id(T_PAYER_SEARCH_MODAL).first
        await modal.wait_for(state="visible", timeout=20_000)
        await modal.click()
        await modal.fill(pagador)
        fila = page.locator(f"//td[contains(text(),'{pagador}')]/ancestor::tr")
        await fila.first.wait_for(state="visible", timeout=10_000)
        await fila.first.click()
        await page.wait_for_timeout(3_000)
        logger.info("[CP14] Pagador seleccionado.")


async def asegurar_dob_beneficiario(page, fecha: str = BENEF_DOB) -> None:
    """Llena la fecha de nacimiento del beneficiario si está vacía.

    El beneficiario que se autocarga del historial puede venir SIN fecha de
    nacimiento; la app la exige para un envío válido (y sin ella el registro
    puede no propagarse correctamente a Chronos). Si el campo no está visible,
    intenta expandir la sección de beneficiario."""
    try:
        campo = page.get_by_test_id(T_BENEF_DOB).first
        try:
            await campo.wait_for(state="visible", timeout=4_000)
        except Exception:
            # Expandir la sección de beneficiario y reintentar.
            try:
                await page.get_by_test_id(T_BENEF_TOGGLE).first.click(timeout=3_000)
                await page.wait_for_timeout(600)
            except Exception:
                pass
            await campo.wait_for(state="visible", timeout=6_000)

        actual = ((await campo.input_value()) or "").strip()
        if actual:
            logger.info("[CP14] DOB del beneficiario ya presente: %s", actual)
            return
        await campo.click()
        try:
            await campo.fill("")
        except Exception:
            pass
        await campo.type(fecha, delay=80)
        await campo.press("Tab")
        await page.wait_for_timeout(600)
        logger.info("[CP14] DOB del beneficiario ingresada: %s", fecha)
    except Exception as e:
        logger.warning("[CP14] No se pudo llenar el DOB del beneficiario: %s",
                       str(e)[:110])


async def branch_code_si_requiere(page, branch_code: str) -> None:
    """Si la app pide 'Bank Branch Code', lo teclea (port de
    `select_branch_code_if_required`)."""
    await page.wait_for_timeout(1_000)
    try:
        aviso = page.locator(
            "div#tooltip:has-text('Bank Branch Code field is required')")
        if await aviso.is_visible():
            logger.info("[CP14] Branch Code requerido — ingresando '%s'.", branch_code)
            campo = page.get_by_test_id(T_BRANCH_CODE).first
            await campo.click()
            await campo.fill("")
            await campo.type(branch_code, delay=100)
        else:
            logger.info("[CP14] No se requiere Branch Code.")
    except Exception as e:
        logger.warning("[CP14] Branch Code: %s", str(e)[:100])


async def completar_envio_home(page, language: str = "English") -> None:
    """Continuar → (maneja compliance) → Sí, Enviar → No hacer otro envío
    (port de `complete_money_transfer`, endurecido)."""
    logger.info("[CP14] Completando el envío…")
    await page.add_init_script("window.print = () => {};")

    cont = page.get_by_test_id(T_CONTINUE).first
    await cont.wait_for(state="visible", timeout=15_000)

    confirm = page.get_by_test_id(T_CONFIRM_SEND).first
    visible = False
    for intento in range(1, 7):
        logger.info("[CP14] Clic en Continuar (intento %d/6)…", intento)
        await cont.click(force=True)
        await page.wait_for_timeout(5_000)

        # Mensaje de compliance → 'Back to Transfer' y reintentar.
        msg = page.get_by_test_id(T_COMPLIANCE_MSG).first
        try:
            if await msg.is_visible():
                logger.warning("[CP14] Mensaje de compliance — regresando y reintentando.")
                texto = ("Regresar A Envío" if language == "Spanish"
                         else "Back to Transfer")
                await page.get_by_text(texto, exact=True).first.click()
                await page.wait_for_timeout(2_000)
                continue
        except Exception:
            pass

        await page.wait_for_timeout(10_000)
        try:
            if await confirm.is_visible():
                logger.info("[CP14] Botón 'Sí, Enviar' visible (intento %d).", intento)
                visible = True
                break
        except Exception:
            pass

    if not visible:
        raise Exception("El botón 'Sí, Enviar' no apareció tras varios intentos.")

    await confirm.wait_for(state="visible", timeout=15_000)
    await confirm.click()
    logger.info("[CP14] 'Sí, Enviar' pulsado.")
    await page.wait_for_timeout(15_000)

    try:
        await page.get_by_test_id(T_DECLINE_ANOTHER).first.click(force=True)
        logger.info("[CP14] 'No hacer otro envío' pulsado.")
    except Exception as e:
        logger.info("[CP14] No apareció el modal 'otro envío': %s", str(e)[:80])
    await page.wait_for_timeout(10_000)
    logger.info("[CP14] Envío completado.")


async def obtener_folio_en_hermes(flow, nombre_cliente: str = None,
                                  intentos: int = 6) -> str:
    """Tras enviar, va a Reportes > Transacciones, BUSCA la transacción (igual que
    el módulo de cancelación) y lee el FOLIO de la primera fila del resultado.
    Devuelve el folio (solo dígitos) o '' si no lo encuentra.

    Importante: el reporte NO auto-carga la tabla; hay que disparar 'Buscar' para
    que aparezcan las filas (por eso se reutiliza `buscar_transaccion_por_nombre`,
    lo mismo que hace `cancelacion.cancelar_por_cliente`)."""
    logger.info("[CP14] Leyendo el folio en Reportes de Hermes…")
    await CANCEL.ir_a_reportes_transacciones(flow)

    # Poblar la tabla: buscar por nombre del cliente (dispara 'Buscar').
    if nombre_cliente:
        try:
            await flow.buscar_transaccion_por_nombre(nombre_cliente)
        except Exception as e:
            logger.info("[CP14] Búsqueda por nombre no disponible (%s) — "
                        "intento leer el resultado igual.", str(e)[:80])
    await flow.page.wait_for_timeout(1_500)

    for intento in range(1, intentos + 1):
        try:
            # La fila del resultado puede venir con la clase específica o como
            # una fila normal de tabla — se prueban ambas.
            fila = flow.page.locator(HM_ROW).first
            if not await fila.count():
                fila = flow.page.locator("tbody tr").first
            await fila.wait_for(state="visible", timeout=8_000)
            celdas = fila.locator("td")
            # Log de todas las celdas (diagnóstico).
            n = await celdas.count()
            textos = []
            for i in range(min(n, 12)):
                t = (await celdas.nth(i).inner_text()) or ""
                textos.append(t.strip())
            logger.info("[CP14] Celdas de la 1ª fila: %s", textos)

            # 1) La columna del folio es el índice conocido (2ª columna). El folio
            #    puede tener pocos dígitos (ej. '208'), así que NO se filtra por
            #    longitud; solo se toma su valor numérico.
            folio = ""
            if HM_FOLIO_COL_INDEX < len(textos):
                folio = re.sub(r"\D", "", textos[HM_FOLIO_COL_INDEX])

            # 2) Respaldo: si esa celda no trae número, se escanea evitando la
            #    fecha (col 0), el teléfono (10 díg.) y montos (contienen '$').
            if not folio:
                for i, t in enumerate(textos):
                    if i == 0 or "$" in t:
                        continue
                    d = re.sub(r"\D", "", t)
                    if d and len(d) <= 8:   # folio corto; excluye teléfonos (10)
                        folio = d
                        break

            if folio:
                logger.info("[CP14] Folio leído: %s", folio)
                return folio
        except Exception as e:
            logger.info("[CP14] Folio aún no visible (intento %d/%d): %s",
                        intento, intentos, str(e)[:80])
        await flow.page.wait_for_timeout(2_000)
    logger.warning("[CP14] No se pudo leer el folio en Reportes de Hermes.")
    return ""


async def crear_envio_home(flow, *, nombre=CLIENTE_NOMBRE, apellido=CLIENTE_APELLIDO,
                           pais=PAIS_BENEF, ciudad=CIUDAD, monto=MONTO,
                           pagador=PAGADOR, branch_code=BRANCH_CODE,
                           language="English") -> None:
    """Orquesta el envío a domicilio completo con un cliente existente."""
    page = flow.page
    await page.wait_for_timeout(2_000)
    await autofill_cliente_por_apellido(page, nombre, apellido)
    await page.wait_for_timeout(5_000)
    await limpiar_y_tab_home(page)
    await esperar_loader_oculto(flow)
    await llenar_detalles_home(page, pais, ciudad, monto, pagador)
    await page.wait_for_timeout(2_000)
    await asegurar_dob_beneficiario(page)
    await branch_code_si_requiere(page, branch_code)
    await completar_envio_home(page, language)


# ═════════════════════════════════════════════════════════════════════════════
# PARTE 2 — CHRONOS: buscar, validar sender, esperar Payment Ready y cancelar
# ═════════════════════════════════════════════════════════════════════════════

async def abrir_chronos_en_pestana(page_hermes):
    """Abre Chronos en una pestaña NUEVA del mismo contexto y deja la sesión
    lista (reutiliza `chronos.abrir_chronos`: cookies + login solo si expiró).
    La pestaña de Hermes 2 queda intacta. Devuelve la página de Chronos."""
    logger.info("[CP14] Abriendo Chronos en una pestaña nueva…")
    chronos_page = await page_hermes.context.new_page()
    ok = await CH.abrir_chronos(chronos_page)
    if not ok:
        logger.warning("[CP14] No se pudo dejar la sesión de Chronos lista.")
    await chronos_page.wait_for_timeout(2_000)
    return chronos_page


async def _seleccionar_agencia(page, agencia: str) -> None:
    """Teclea la agencia y Enter; el panel de filtro se colapsa al confirmar."""
    caja = page.get_by_role("textbox", name="Agent :")
    await caja.click()
    try:
        await caja.fill("")
    except Exception:
        pass
    await caja.type(agencia, delay=100)
    await page.wait_for_timeout(5_000)
    await caja.press("Enter")
    try:
        await page.locator(CH_SEARCH_MODAL).wait_for(state="hidden", timeout=15_000)
    except Exception:
        pass
    logger.info("[CP14] Agencia '%s' seleccionada en Chronos.", agencia)


async def _aplicar_agencia(page, agencia: str, btn_idx: int) -> None:
    """Abre el filtro de agente (botón nth) y selecciona la agencia. Best-effort:
    si el agente ya viene pre-cargado, no rompe el flujo."""
    if not agencia:
        return
    try:
        await page.locator(".btn.input-group-text").nth(btn_idx).click()
        await _seleccionar_agencia(page, agencia)
    except Exception as e:
        logger.warning("[CP14] No se pudo aplicar la agencia '%s': %s",
                       agencia, str(e)[:100])


async def _filtrar_por_folio(page, folio: str) -> None:
    """Escribe el folio en el input 'Folio' de Chronos y lanza Search."""
    caja = page.locator(CH_FOLIO_INPUT).first
    await caja.wait_for(state="visible", timeout=15_000)
    await caja.click()
    try:
        await caja.fill("")
    except Exception:
        pass
    await caja.fill(str(folio))
    logger.info("[CP14] Chronos: filtro por folio '%s'.", folio)
    await page.get_by_role("button", name="Search").click()
    await page.wait_for_timeout(3_000)


async def _esperar_filas(page, *, reintentos: int = 8, espera_ms: int = 4_000) -> int:
    """Espera a que aparezcan filas de resultado, re-lanzando Search. Una
    transferencia recién creada tarda en propagarse a Chronos. Si sale el modal
    'No Transfers Found', lo cierra antes de reintentar. Devuelve el número de
    filas (0 si ninguna)."""
    filas = page.locator("tbody tr")
    for intento in range(1, reintentos + 1):
        # Cerrar el modal de error 'No Transfers Found' si está en pantalla.
        try:
            await CH.cerrar_modal_error(page)
        except Exception:
            pass
        try:
            n = await filas.count()
        except Exception:
            n = 0
        if n:
            try:
                await page.locator(CH_FIRST_FOLIO).first.wait_for(
                    state="visible", timeout=3_000)
                logger.info("[CP14] Resultados en Chronos: %d fila(s) (intento %d).",
                            n, intento)
                return n
            except Exception:
                pass
        logger.info("[CP14] Sin resultados aún (intento %d/%d) — reintento Search.",
                    intento, reintentos)
        try:
            await page.get_by_role("button", name="Search").click()
        except Exception:
            pass
        await page.wait_for_timeout(espera_ms)
    logger.warning("[CP14] Chronos no mostró resultados tras %d intentos.", reintentos)
    return 0


async def _abrir_menu_y_panel_transfer(page) -> None:
    await CH._click_listo(page, page.locator(CH_MENU).first, "Menú Chronos")
    await page.wait_for_timeout(1_000)
    await CH._click_listo(page, page.locator(CH_TRANSFER_PANEL).first,
                          "Panel Transfer expandido")
    await page.wait_for_timeout(1_000)


async def buscar_transfer(page, folio: str, agencia: str = AGENCIA) -> bool:
    """Search Transfer → filtra por AGENCIA + FOLIO → abre el primer resultado.

    Se filtra por agencia además del folio para no caer en una transacción con el
    mismo folio en otra agencia. Devuelve True si encontró y abrió un resultado;
    False si no hubo resultados (no lanza, para continuar a Status Change / fallback)."""
    logger.info("[CP14] Chronos: Search Transfer (agencia=%s, folio=%s)",
                agencia, folio)
    await _abrir_menu_y_panel_transfer(page)
    await CH._click_listo(page, page.locator(CH_SEARCH_TRANSFER).first,
                          "Search Transfer")
    await page.wait_for_timeout(1_500)

    await _aplicar_agencia(page, agencia, CH_AGENT_BTN_SEARCH)
    await _filtrar_por_folio(page, folio)

    if not await _esperar_filas(page):
        logger.warning("[CP14] Search Transfer sin resultados para folio '%s'.", folio)
        return False

    await page.locator(CH_FIRST_FOLIO).first.click()
    await page.wait_for_timeout(5_000)
    return True


async def validar_sender(page, cliente_esperado: str) -> None:
    """Abre la pestaña Sender, valida CustomerName y regresa."""
    logger.info("[CP14] Chronos: validando Sender == '%s'", cliente_esperado)
    tab = page.get_by_role("tab", name="Sender").first
    await tab.wait_for(state="visible", timeout=30_000)
    await tab.click(force=True)
    await page.wait_for_timeout(1_000)
    await expect(page.locator(CH_CUSTOMER_NAME).nth(0)).to_have_value(
        cliente_esperado, timeout=10_000)
    logger.info("[CP14] Sender validado.")
    await page.get_by_role("button", name="Go Back").click()
    await page.wait_for_timeout(2_000)


async def status_change_hasta_payment_ready(page, folio: str, agencia: str = AGENCIA,
                                            intentos: int = 15) -> tuple:
    """Status Change → filtra por AGENCIA + FOLIO → sondea el estado hasta
    'Payment Ready'. Devuelve (folio, alcanzado, ultimo_estado)."""
    logger.info("[CP14] Chronos: Status Change (agencia=%s, folio=%s)",
                agencia, folio)
    await CH._click_listo(page, page.locator(CH_MENU).first, "Menú Chronos")
    await page.wait_for_timeout(1_000)
    await CH._click_listo(page, page.locator(CH_STATUS_CHANGE).first, "Status Change")
    await page.wait_for_timeout(1_500)

    await _aplicar_agencia(page, agencia, CH_AGENT_BTN_STATUS)
    await _filtrar_por_folio(page, folio)

    # Tolerar la propagación de la transferencia recién creada.
    if not await _esperar_filas(page):
        logger.warning("[CP14] Status Change sin resultados para folio '%s'.", folio)
        return folio, False, "SIN_RESULTADOS"

    status_cell = page.locator('//tr[1]/td[9]/div')
    ultimo, alcanzado = "", False
    for intento in range(1, intentos + 1):
        logger.info("[CP14] Sondeo de estado %d/%d…", intento, intentos)
        try:
            await CH.cerrar_modal_error(page)
        except Exception:
            pass
        await page.get_by_role("button", name="Search").click()
        await page.wait_for_timeout(10_000)
        try:
            await status_cell.wait_for(state="visible", timeout=10_000)
            ultimo = (await status_cell.text_content() or "").strip()
        except Exception:
            ultimo = ""
        logger.info("[CP14] Estado en intento %d: '%s'", intento, ultimo)
        if ultimo == "Payment Ready":
            alcanzado = True
            break

    if alcanzado:
        await page.locator(CH_FIRST_FOLIO).first.click()
        await page.wait_for_timeout(5_000)
    else:
        logger.warning("[CP14] Nunca llegó a 'Payment Ready' (último: '%s').", ultimo)
    return folio, alcanzado, ultimo


async def cancelar_transfer_chronos(page) -> None:
    """Selecciona Cancelled + motivo + nota, guarda y valida (port de
    `cp14_cancel_transfer_and_validate`)."""
    logger.info("[CP14] Chronos: cancelando la transferencia.")
    status_select = page.locator("select").filter(
        has=page.locator("option", has_text="Cancelled"))
    await status_select.select_option(label="Cancelled")
    await page.wait_for_timeout(500)

    await page.locator(CH_CANCEL_REASON).select_option(
        label="Client request (No reason)")
    await page.wait_for_timeout(500)

    nota = page.locator(CH_NOTE)
    await nota.click()
    await nota.fill("TEST")

    await page.get_by_text("Save", exact=True).nth(3).click()
    await page.wait_for_timeout(4_000)

    await expect(page.locator(CH_SUCCESS_MSG)).to_have_text(
        "Transfer has been successfully saved.", timeout=15_000)
    logger.info("[CP14] Mensaje de éxito confirmado.")

    await page.get_by_role("button", name="Close").first.click()
    await page.wait_for_timeout(4_000)

    await expect(page.get_by_text("Cancelled", exact=True).nth(1)).to_have_text(
        "Cancelled", timeout=10_000)
    logger.info("[CP14] Cancelación validada en Chronos.")
