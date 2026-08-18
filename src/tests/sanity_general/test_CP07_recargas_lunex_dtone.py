"""
CP07 — Recargas (Top Ups) · Lunex y DTOne.
(Rescate de `HERMES2-qa/.../test_CP07_Recargas_Lunex_DTOne.py`.)

Dominio PROPIO (Servicios > Top Ups). Usa src/sanity_general/recargas.py.

Flujo:
  1. Servicios > Top Ups → MEGA TOP UPS (iframe Lunex): número, país, operador,
     monto, nombre → Continuar → validar botón de envío visible.
  2. Servicios > Top Ups → TOP UPS REGULAR: beneficiario, relación (FRIEND),
     producto, monto, cliente → Continuar → validar botón de envío visible.

SEGURIDAD: NO se completa la recarga (número real; se detiene en 'Send/Enviar'
visible), igual que el caso original.

COMO CORRER:
    pytest src/tests/sanity_general -k CP07 -v -s --headed
"""
import os
import pytest
from playwright.async_api import Page

from config.logger import get_logger
from config import settings
from src.pages.hm_transferelektra_page import HmTransferelektraPage
from src.helpers.screenshot_helper import ScreenshotHelper
from src.sanity_general import recargas as R
from src.sanity_general import Evidencia

logger = get_logger("CP07")

# ── Datos del caso (override por env; cambian por ambiente si aplica) ─────────
MEGA_PHONE   = os.getenv("CP07_MEGA_PHONE",   "3322313245")
MEGA_COUNTRY = os.getenv("CP07_MEGA_COUNTRY", "Mexico")
MEGA_AMOUNT  = os.getenv("CP07_MEGA_AMOUNT",  "$2")
MEGA_NAME    = os.getenv("CP07_MEGA_NAME",    "TEST")

REG_BENEF_PHONE = os.getenv("CP07_BENEF_PHONE", "3322313245")
REG_BENEF_NAME  = os.getenv("CP07_BENEF_NAME",  "TEST RECARGA")
REG_CUST_PHONE  = os.getenv("CP07_CUST_PHONE",  "7774533317")
REG_CUST_NAME   = os.getenv("CP07_CUST_NAME",   "TEST")
REG_CUST_LAST   = os.getenv("CP07_CUST_LAST",   "TEST")

# Sub-flujos activables por env (por si se quiere correr solo uno en la demo).
HACER_MEGA    = os.getenv("CP07_MEGA",    "1").strip().lower() in ("1", "true", "si", "yes")
HACER_REGULAR = os.getenv("CP07_REGULAR", "1").strip().lower() in ("1", "true", "si", "yes")

EVIDENCE = "CP07_recargas_lunex_dtone"


@pytest.mark.sanity_general
@pytest.mark.asyncio
@pytest.mark.parametrize("language,width,height", [("English", 1366, 768)])
async def test_CP07_recargas_lunex_dtone(logged_page: Page, language, width, height):
    flow = HmTransferelektraPage(logged_page)
    screenshot = ScreenshotHelper(logged_page)
    evi = Evidencia(screenshot, EVIDENCE)
    await logged_page.evaluate("window.print = () => {};")

    mega_ok = regular_ok = True

    # ── Steps 1–3: MEGA TOP UPS (iframe Lunex) ───────────────────────────────
    if HACER_MEGA:
        logger.info("[CP07] MEGA TOP UPS · abriendo…")
        await R.abrir_mega_top_ups(flow)
        await evi.shot("mega_abierto")
        mega_ok = await R.llenar_mega_top_ups(
            flow, country=MEGA_COUNTRY, phone_number=MEGA_PHONE,
            amount=MEGA_AMOUNT, topup_name=MEGA_NAME, evi=evi)
        logger.info("[CP07] MEGA TOP UPS listo (Send visible=%s).", mega_ok)

    # ── Steps 4–8: TOP UPS REGULAR ───────────────────────────────────────────
    if HACER_REGULAR:
        logger.info("[CP07] TOP UPS REGULAR · abriendo…")
        await R.abrir_regular_top_ups(flow)
        await evi.shot("regular_abierto")
        regular_ok = await R.llenar_regular_top_ups(
            flow, beneficiary_phone=REG_BENEF_PHONE, beneficiary_name=REG_BENEF_NAME,
            customer_phone=REG_CUST_PHONE, customer_name=REG_CUST_NAME,
            customer_lastname=REG_CUST_LAST, evi=evi)
        logger.info("[CP07] TOP UPS REGULAR listo (Send visible=%s).", regular_ok)

    # Step 9 (búsqueda de transacciones por tipo 'Recarga') queda pendiente —
    # no se completa la recarga, así que no hay transacción que buscar.
    assert mega_ok and regular_ok, (
        "CP07: alguno de los formularios de recarga no llegó al botón de envío "
        "visible (revisar selectores del iframe Lunex / campos en test-hermes).")
    logger.info("[CP07] Recargas Lunex y DTOne — formularios validados (sin enviar) ✓")
