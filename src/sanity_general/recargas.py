"""
Recargas (Top Ups) — CP07 · Lunex / DTOne.

Dominio PROPIO (Servicios > Top Ups), sin relación con Money Transfer. Port del
POM del repo viejo (src/models/recharges.py) a funciones sobre `flow`
(HmTransferelektraPage), al estilo de bill_payment.py.

Dos sub-flujos:
  • MEGA TOP UPS  — formulario DENTRO del iframe de Lunex (país/operador/monto/
    nombre → Continuar). Widgets Chosen.js.
  • TOP UPS REGULAR — formulario nativo (beneficiario/relación/producto/monto/
    cliente → Continuar).

SEGURIDAD: NINGUNO de los dos ENVÍA la recarga. Ambos se detienen al validar que
el botón final ('Send'/'Enviar'/'Recargar') es visible — igual que el caso
original (usa un número real; completar dispararía un top-up de verdad).

Textos bilingües (EN/ES) donde el locator depende de texto visible; los
data-testid únicos no dependen del idioma. El iframe de Lunex suele estar en
español independientemente del idioma de Hermes.
"""

import os
import re
import random

from config.logger import get_logger

logger = get_logger("sanity.recargas")

# ── Navegación (Servicios > Top Ups) ────────────────────────────────────────
SERVICES_NAVBAR   = "services-navbar-item"
TOPUPS_DROPDOWN   = "services-1-navbar-dropdown-item"
MODAL_DENY_BTN    = "modal-confirmation-deny-button"
H4_HEADING        = "test-id-h4-heading"
RE_MEGA           = re.compile(r"mega\s*top\s*ups|mega\s*recargas", re.I)
RE_REGULAR        = re.compile(r"^\s*(top\s*ups|recargas)\s*$", re.I)

# ── Iframe de Lunex (Mega Top Ups) ──────────────────────────────────────────
LUNEX_IFRAME       = "iframe.iframe-content"
LUNEX_CONTAINER    = "topupslunex .topups-lunex-container"
LX_WORLD_LINK      = "#menu_topUpWorldDesc"
LX_US_PHONE        = "#phone_number_us"
LX_COUNTRY_CHOSEN  = "#Country_Top_Up_chosen"
LX_MOBILE_PHONE    = "#topupMobileNo"
LX_AMOUNT_CHOSEN   = "#Amount_Top_Up_chosen"
LX_TOPUP_NAME      = "#topupname"
LX_SUBMIT          = "#btnSubmit"
RE_SELECT_COUNTRY  = re.compile(r"seleccione el pa[ií]s|select country", re.I)
RE_SELECT_AMOUNT   = re.compile(r"seleccione el monto|select amount", re.I)
RE_CONTINUAR       = re.compile(r"continuar|continue", re.I)

# ── Top Ups regular (formulario nativo) ─────────────────────────────────────
BENEF_PHONE_TAB    = "dropdown-cellphone-tab-1"
BENEF_NAME_TAB     = "input-name-tab-1"
PRODUCT_TAB        = "dropdown-product-tab-1"
RELATIONSHIP_TAB   = "dropdown-relationship-tab-1"
CUST_PHONE_TAB     = "dropdown-cellphone-customer-tab-1"
CUST_NAME_TAB      = "input-name-customer-tab-1"
CUST_LASTNAME_TAB  = "input-first-last-name-customer-tab-1"
CONTINUE_REG_TAB   = "button-continue-tab-1"
INPUT_FIELD_BTN    = "input-field-button"
INPUT_FIELD_INPUT  = "input-field-input"
INPUT_FIELD_CELL   = "input-field-cellphone-input"
SELECT_FIELD_INPUT = "select-field-dropdown-input"
FILTER_DROPDOWN    = "input-filter-dropdown-dropdown-input"
TEST_ID_BUTTON     = "test-id-button"
RE_MEX_PREFIX      = re.compile(r"MEX\s*\(\+52\)", re.I)
RE_FRIEND          = re.compile(r"friend|amigo", re.I)
RE_PRODUCT_TOPUP   = re.compile(r"top\s*up|recarga", re.I)
RE_SEND            = re.compile(r"^\s*(send|enviar|recargar)\s*$", re.I)

TIMEOUT = 60_000


# ── Navegación ──────────────────────────────────────────────────────────────

async def _dismiss_modal(flow):
    """Cierra el modal 'YES, Leave'/'SÍ, Salir' si aparece (hasta 3 intentos)."""
    page = flow.page
    try:
        deny = page.get_by_test_id(MODAL_DENY_BTN).first
        # `is_visible()` NO acepta timeout: lo pasábamos y el TypeError hacía
        # que el modal nunca se cerrara. Se espera con wait_for.
        await deny.wait_for(state="visible", timeout=4_000)
        for intento in range(1, 4):
            await deny.click(force=True)
            try:
                await deny.wait_for(state="hidden", timeout=2_000)
                break
            except Exception:
                if intento == 3:
                    logger.warning("[Recargas] El modal no cerró tras 3 intentos.")
        await page.wait_for_timeout(1_000)
    except Exception:
        pass


async def _ir_a_topups(flow):
    """Servicios > Top Ups (+ cerrar modal de confirmación si aparece)."""
    page = flow.page
    logger.info("[Recargas] Navegando a Servicios > Top Ups…")
    await page.get_by_test_id(SERVICES_NAVBAR).first.click(force=True)
    await page.wait_for_timeout(800)
    await page.get_by_test_id(TOPUPS_DROPDOWN).first.click(force=True)
    await page.wait_for_timeout(1_500)
    await _dismiss_modal(flow)


async def abrir_mega_top_ups(flow):
    """Servicios > Top Ups → tarjeta 'Mega Top Ups' / 'Mega Recargas'."""
    await _ir_a_topups(flow)
    page = flow.page
    card = page.get_by_test_id(H4_HEADING).filter(has_text=RE_MEGA).first
    await card.wait_for(state="visible", timeout=TIMEOUT)
    await card.click(force=True)
    await page.wait_for_timeout(2_000)
    logger.info("[Recargas] Mega Top Ups abierto.")


async def abrir_regular_top_ups(flow):
    """Servicios > Top Ups → tarjeta 'Top Ups' / 'Recargas' (regular)."""
    await _ir_a_topups(flow)
    page = flow.page
    await page.wait_for_timeout(1_500)
    card = page.get_by_test_id(H4_HEADING).filter(has_text=RE_REGULAR).first
    await card.wait_for(state="visible", timeout=TIMEOUT)
    await card.click(force=True)
    await page.wait_for_timeout(2_500)
    logger.info("[Recargas] Top Ups regular abierto.")


# ── Mega Top Ups (iframe Lunex) ─────────────────────────────────────────────

async def llenar_mega_top_ups(flow, *, country="Mexico", phone_number="3322313245",
                               amount="$2", topup_name="TEST", evi=None) -> bool:
    """Llena el formulario de Mega Top Ups dentro del iframe de Lunex y VALIDA que
    el botón de envío (#btnSubmit) quede visible. NO envía la recarga.

    Devuelve True si llegó al botón de envío visible."""
    page = flow.page
    fr = page.frame_locator(LUNEX_IFRAME)
    logger.info("[Recargas] Mega Top Ups · esperando el iframe de Lunex…")

    # 1) Carga estructural + iframe
    try:
        await page.locator(LUNEX_CONTAINER).wait_for(state="visible", timeout=TIMEOUT)
    except Exception:
        logger.warning("[Recargas] No apareció el contenedor <topupslunex> — sigo intentando el iframe.")
    world = fr.locator(LX_WORLD_LINK)
    await world.wait_for(state="visible", timeout=TIMEOUT)
    await page.wait_for_timeout(2_000)

    # 2) Pestaña 'Top-Up the World' + teléfono US
    await world.click(force=True)
    await page.wait_for_timeout(2_000)
    us_phone = fr.locator(LX_US_PHONE)
    await us_phone.wait_for(state="visible", timeout=TIMEOUT)
    await us_phone.click()
    await us_phone.press_sequentially(phone_number, delay=90)
    if evi:
        await evi.shot("mega_numero_us")
    await world.click(force=True)                 # click fuera → valida y avanza
    await page.wait_for_timeout(3_000)

    # 3) País (Chosen.js)
    country_btn = fr.locator("a").filter(has_text=RE_SELECT_COUNTRY).first
    await country_btn.wait_for(state="visible", timeout=TIMEOUT)
    await country_btn.click()
    await fr.locator(LX_COUNTRY_CHOSEN).get_by_role("textbox").press_sequentially(country, delay=90)
    await page.wait_for_timeout(600)
    await fr.locator(LX_COUNTRY_CHOSEN).get_by_text(country, exact=False).first.click()

    # 4) Teléfono internacional
    mobile = fr.locator(LX_MOBILE_PHONE)
    await mobile.wait_for(state="visible", timeout=TIMEOUT)
    await mobile.click()
    await mobile.press_sequentially(phone_number, delay=90)
    try:
        await us_phone.press("Enter")
    except Exception:
        pass

    # 5) Operador: primer botón de carrier disponible (evita depender de un nombre fijo)
    await page.wait_for_timeout(1_200)
    try:
        carrier = fr.get_by_role("button").filter(has_text=re.compile(r"telcel|movistar|at&t|unefon|amigo", re.I)).first
        await carrier.wait_for(state="visible", timeout=TIMEOUT)
        await carrier.click()
    except Exception:
        logger.warning("[Recargas] No se pudo elegir operador por nombre — intento el primer botón.")
        try:
            await fr.get_by_role("button").first.click()
        except Exception:
            pass
    await page.wait_for_timeout(1_000)

    # 6) Monto (Chosen.js) — intenta el pedido; si no, la primera opción
    amount_btn = fr.locator("a").filter(has_text=RE_SELECT_AMOUNT).first
    await amount_btn.wait_for(state="visible", timeout=TIMEOUT)
    await amount_btn.click()
    await page.wait_for_timeout(500)
    cont = fr.locator(LX_AMOUNT_CHOSEN)
    try:
        await cont.get_by_text(amount, exact=True).first.click(timeout=4_000)
    except Exception:
        logger.warning("[Recargas] Monto '%s' no exacto — elijo el primero disponible.", amount)
        await cont.locator("li, .active-result").first.click()

    # 7) Nombre + Continuar
    name_inp = fr.locator(LX_TOPUP_NAME)
    await name_inp.wait_for(state="visible", timeout=TIMEOUT)
    await name_inp.click()
    await name_inp.fill(topup_name)
    await fr.get_by_role("button", name=RE_CONTINUAR).first.click()
    await page.wait_for_timeout(2_000)

    # 8) Validar botón de envío visible — SIN enviar
    submit = fr.locator(LX_SUBMIT)
    visible = False
    try:
        await submit.wait_for(state="visible", timeout=10_000)
        visible = True
    except Exception:
        logger.warning("[Recargas] Mega: #btnSubmit no visible — revisar el flujo de Lunex.")
    if evi:
        await evi.shot("mega_listo_para_enviar")
    logger.info("[Recargas] Mega Top Ups listo (Send visible=%s). NO se envía (número real).", visible)
    return visible


# ── Top Ups regular ─────────────────────────────────────────────────────────

async def _elegir_prefijo_mex(flow, tab_testid):
    """Abre el selector de prefijo del tab dado y elige MEX (+52)."""
    page = flow.page
    await page.get_by_test_id(tab_testid).get_by_test_id(INPUT_FIELD_BTN).first.click()
    await page.wait_for_timeout(500)
    await page.get_by_role("link", name=RE_MEX_PREFIX).first.click()


async def llenar_regular_top_ups(flow, *, beneficiary_phone="3322313245",
                                 beneficiary_name="TEST RECARGA",
                                 customer_phone="7774533317", customer_name="TEST",
                                 customer_lastname="TEST", evi=None) -> bool:
    """Llena el formulario de Top Ups regular y VALIDA que el botón final
    ('Send'/'Enviar'/'Recargar') quede visible. NO envía la recarga."""
    page = flow.page
    logger.info("[Recargas] Top Ups regular · beneficiario %s", beneficiary_phone)

    # 1) Beneficiario: prefijo MEX + teléfono + nombre
    await _elegir_prefijo_mex(flow, BENEF_PHONE_TAB)
    await page.get_by_test_id(BENEF_PHONE_TAB).get_by_test_id(INPUT_FIELD_INPUT).first.click()
    await page.get_by_test_id(BENEF_PHONE_TAB).get_by_test_id(INPUT_FIELD_INPUT).first.press_sequentially(
        beneficiary_phone, delay=90)
    await page.get_by_test_id(BENEF_NAME_TAB).get_by_test_id(INPUT_FIELD_INPUT).first.click()
    await page.get_by_test_id(BENEF_NAME_TAB).get_by_test_id(INPUT_FIELD_INPUT).first.press_sequentially(
        beneficiary_name, delay=80)

    # 2) Relación: FRIEND / AMIGO
    rel = page.get_by_test_id(RELATIONSHIP_TAB).get_by_test_id(FILTER_DROPDOWN).first
    await rel.wait_for(state="visible", timeout=TIMEOUT)
    await rel.click()
    await page.get_by_test_id(RELATIONSHIP_TAB).get_by_text(RE_FRIEND).first.click()
    await page.keyboard.press("Tab")               # fuerza el cierre del menú
    if evi:
        await evi.shot("regular_beneficiario")

    # 3) Primer valor del select-field genérico (aparece tras elegir relación)
    try:
        sf = page.get_by_test_id(SELECT_FIELD_INPUT).first
        await sf.click(timeout=10_000)
        opt = page.locator(".p-dropdown-panel .p-dropdown-item").first
        await opt.wait_for(state="visible", timeout=10_000)
        await opt.click()
    except Exception:
        logger.info("[Recargas] select-field genérico no presente — se omite.")

    # 4) Producto: TOP UP / RECARGA
    await page.wait_for_timeout(3_000)
    try:
        await page.get_by_test_id(PRODUCT_TAB).get_by_test_id(SELECT_FIELD_INPUT).first.click()
        await page.wait_for_timeout(500)
        await page.get_by_test_id(PRODUCT_TAB).get_by_text(RE_PRODUCT_TOPUP).first.click()
    except Exception:
        logger.warning("[Recargas] No se pudo elegir producto — reviso en vivo.")

    # 5) Primer monto disponible
    try:
        first_amount = page.locator(".radio-buttons-container .custom-radio-button label").first
        await first_amount.wait_for(state="visible", timeout=TIMEOUT)
        await first_amount.click()
    except Exception:
        logger.warning("[Recargas] No apareció un monto disponible — reviso en vivo.")
    if evi:
        await evi.shot("regular_monto")

    # 6) Cliente: prefijo MEX + teléfono + nombre + apellido
    await _elegir_prefijo_mex(flow, CUST_PHONE_TAB)
    await page.get_by_test_id(CUST_PHONE_TAB).get_by_test_id(INPUT_FIELD_CELL).first.click()
    await page.get_by_test_id(CUST_PHONE_TAB).get_by_test_id(INPUT_FIELD_CELL).first.press_sequentially(
        customer_phone, delay=90)
    await page.get_by_test_id(CUST_NAME_TAB).get_by_test_id(INPUT_FIELD_INPUT).first.click()
    await page.get_by_test_id(CUST_NAME_TAB).get_by_test_id(INPUT_FIELD_INPUT).first.press_sequentially(
        customer_name, delay=80)
    await page.get_by_test_id(CUST_LASTNAME_TAB).get_by_test_id(INPUT_FIELD_INPUT).first.click()
    await page.get_by_test_id(CUST_LASTNAME_TAB).get_by_test_id(INPUT_FIELD_INPUT).first.press_sequentially(
        customer_lastname, delay=80)

    # 7) Continuar → validar botón final visible (SIN enviar)
    await page.get_by_test_id(CONTINUE_REG_TAB).get_by_test_id(TEST_ID_BUTTON).first.click()
    await page.wait_for_timeout(2_000)
    visible = False
    try:
        await page.get_by_role("button", name=RE_SEND).first.wait_for(state="visible", timeout=10_000)
        visible = True
    except Exception:
        logger.warning("[Recargas] Regular: botón 'Send/Enviar' no visible — revisar en vivo.")
    if evi:
        await evi.shot("regular_listo_para_enviar")
    logger.info("[Recargas] Top Ups regular listo (Send visible=%s). NO se envía (número real).", visible)
    return visible
