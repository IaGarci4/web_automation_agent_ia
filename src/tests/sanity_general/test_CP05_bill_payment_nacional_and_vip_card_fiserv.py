"""
CP05 — Bill Payment Nacional con servicio Fiserv.
(Rescate de `HERMES2-qa/.../test_CP05_bill_payment_nacional_and_vip_card_fiserv.py`.)

IDÉNTICO a CP05 salvo el servicio (Fiserv) y sus datos. Reutiliza por completo
el módulo src/sanity_general/bill_payment.py (el llenado nacional es agnóstico al
servicio: biller, cuenta, ZIP, monto).

Flujo:
  1. Servicios > Pago de Bill → buscar cliente por teléfono.
  2. Tab Nacional + Fiserv (Biller 'Comcast XFINITY SameDay', Cuenta, ZIP, Monto).
  3. Continuar habilitado → pagar → cancelar desde Reportes (resaltando el registro).

COMO CORRER:
    pytest src/tests/sanity_general -k CP05 -v -s --headed
"""
import os
import pytest
from playwright.async_api import Page

from config.logger import get_logger
from config import settings
from src.pages.hm_transferelektra_page import HmTransferelektraPage
from src.helpers.screenshot_helper import ScreenshotHelper
from src.sanity_general import bill_payment as BP
from src.sanity_general import Evidencia

logger = get_logger("CP05")

# ── Datos del caso (cambian según ambiente test/prod; override por env) ──────
CUSTOMER_PHONE = os.getenv("CP05_PHONE",   settings.por_ambiente("5435345345", "4353454354"))
FISERV_BILLER  = os.getenv("CP05_BILLER",  settings.por_ambiente(
    "Comcast XFINITY SameDay", "Comcast XFINITY Cable Todas las Cuentas"))
FISERV_ACCOUNT = os.getenv("CP05_ACCOUNT", settings.por_ambiente(
    "8495443022532599", "8495443022532599"))
FISERV_ZIP     = os.getenv("CP05_ZIP",     settings.por_ambiente("75001-4444", "45002-4444"))

COMPLETAR = os.getenv("COMPLETAR_ENVIO", "1").strip().lower() in ("1", "true", "si", "yes")
CANCELAR  = os.getenv("CP05_CANCELAR", "1").strip().lower() in ("1", "true", "si", "yes")
EVIDENCE  = "CP05_bill_payment_nacional_fiserv"


@pytest.mark.sanity_general
@pytest.mark.asyncio
@pytest.mark.parametrize("language,width,height", [("English", 1366, 768)])
async def test_CP05_bill_payment_nacional_fiserv(logged_page: Page, language, width, height):
    flow = HmTransferelektraPage(logged_page)
    screenshot = ScreenshotHelper(logged_page)
    evi = Evidencia(screenshot, EVIDENCE)
    await logged_page.evaluate("window.print = () => {};")

    # ── Step 1: Navegar a Bill Payment + buscar cliente ──────────────────────
    await BP.navigate_to_bill_payment(flow)
    await evi.shot("bill_payment_loaded")

    await BP.search_customer_by_phone(flow, CUSTOMER_PHONE)
    await BP.close_customer_search_table(flow)
    customer_name = await BP.get_customer_name(flow)
    assert customer_name, "El nombre del cliente debe poblarse tras la selección."
    logger.info("[CP05] Cliente: %s", customer_name)
    await evi.shot("customer_loaded")

    # ── Step 2: Nacional + Fiserv ────────────────────────────────────────────
    await BP.select_national_tab(flow)
    amount = BP.generate_random_amount()
    await BP.fill_national_payment(
        flow, biller_company=FISERV_BILLER, account_number=FISERV_ACCOUNT,
        amount=amount, biller_zip_code=FISERV_ZIP)

    assert await BP.is_continue_enabled(flow), \
        "El botón Continuar debe habilitarse tras llenar los campos."
    logger.info("[CP05] Continuar habilitado ✓ (monto %s).", amount)
    await evi.shot("fiserv_form_filled", locators=[logged_page.get_by_test_id(BP.CONTINUE_BTN)])

    # ── Step 3: Pagar ────────────────────────────────────────────────────────
    if COMPLETAR:
        await BP.click_continue(flow)
        await BP.summary_pagar(flow)
        await evi.shot("payment_confirmed")
        logger.info("[CP05] Pago Fiserv confirmado ✓.")
    else:
        logger.info("[CP05] COMPLETAR_ENVIO=0 — pago NO realizado (solo armado).")

    # ── Cancelación desde Reportes (por teléfono, tipo BILL PAYMENT) ─────────
    if COMPLETAR and CANCELAR:
        cancelado = await BP.cancelar_bill_payment(
            flow, CUSTOMER_PHONE, logger=logger, evi=evi, notes="Automation CP05")
        assert cancelado, "El pago de bill no se pudo cancelar."
        logger.info("[CP05] Cancelación OK.")
    else:
        logger.info("[CP05] Cancelación OMITIDA (CP05_CANCELAR=0 o sin pago).")
