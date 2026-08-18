"""
CP02 — Money Transfer con OFAC hit y cancelación.
(Rescate de `HERMES2-qa/src/sanity_general/test_CP02_money_transfer_ofac_cancelacion.py`.)

El beneficiario es un nombre SANCIONADO (JOAQUIN GUZMAN LOERA) que dispara el
OFAC Hold. El envío se completa (cae en OFAC Hold) y luego se CANCELA desde
Reportes buscando por el nombre del beneficiario.

Reutiliza el motor: flujo_mt (formulario principal) + info_adicional
(si el pagador la exige) + cancelacion.

FASE ACTUAL: Steps 1–4 + 7 (Hermes: armar → enviar → cancelar).
FASE SIGUIENTE (Chronos): Step 6 — verificar el envío en Chronos > OFAC Hold.

COMO CORRER:
    pytest src/tests/sanity_general -k CP02 -v -s --headed
"""
import os
import random
import pytest
from playwright.async_api import Page

from config.logger import get_logger
from src.pages.hm_transferelektra_page import HmTransferelektraPage
from src.helpers.screenshot_helper import ScreenshotHelper
from src.helpers.datos import Datos
from src.pagadores import flujo_mt as F
from src.sanity_general import cancelacion as C
from src.sanity_general import Evidencia

logger = get_logger("CP02")

# ── Datos del caso ──────────────────────────────────────────────────────────
PAYER_CODE = os.getenv("CP02_PAYER", "WALMART")   # cash, MEXICO
TIPO_ENVIO = "cash"
MONTO      = int(os.getenv("CP02_AMOUNT", "310"))

# Beneficiario OFAC (nombre sancionado → dispara OFAC Hold)
BENEF_NAME  = "JOAQUIN"
BENEF_LAST1 = "GUZMAN"
BENEF_LAST2 = "LOERA"

# Info Adicional (por si el pagador la exige; con WALMART normalmente NO)
IA_PAIS    = "EL SALVADOR"
IA_TIPO_ID = "MATRICULA CONSULAR"
IA_NUM_ID  = "S4152365269"
IA_EXP     = "04/15/2030"
IA_DOB     = "05/21/1983"

COMPLETAR = os.getenv("COMPLETAR_ENVIO", "1").strip().lower() in ("1", "true", "si", "yes")
CANCELAR  = os.getenv("CP02_CANCELAR", "1").strip().lower() in ("1", "true", "si", "yes")
EVIDENCE  = "CP02_money_transfer_ofac_cancelacion"


def _cargar_payer(code: str):
    payers, ciudades = F.cargar_catalogo(modulo="mexico")
    for p in payers:
        if p["code"].upper() == code.upper():
            return dict(p), ciudades
    return dict(payers[0]), ciudades


@pytest.mark.sanity_general
@pytest.mark.asyncio
@pytest.mark.parametrize("language,width,height", [("English", 1366, 768)])
async def test_CP02_money_transfer_ofac_cancelacion(logged_page: Page, language, width, height):
    flow = HmTransferelektraPage(logged_page)
    datos = Datos()
    # Beneficiario FIJO OFAC (no random): fuerza el nombre sancionado.
    datos._benef = [BENEF_NAME, BENEF_LAST1, BENEF_LAST2]
    screenshot = ScreenshotHelper(logged_page)
    evi = Evidencia(screenshot, EVIDENCE)
    rng = random.Random()

    cfg, ciudades = _cargar_payer(PAYER_CODE)
    pais, ciudad, estado = F.destino(cfg, ciudades, rng)
    cfg["payer_city"] = ciudad

    benef_full = f"{BENEF_NAME} {BENEF_LAST1}"
    logger.info("[CP02] payer=%s | destino=%s/%s | monto=%s | beneficiario OFAC=%s %s %s",
                cfg["code"], ciudad, estado, MONTO, BENEF_NAME, BENEF_LAST1, BENEF_LAST2)

    # ── Step 1–2: Formulario principal (beneficiario OFAC) + pagador ─────────
    await F.llenar_formulario_completo(
        flow, datos, cfg, pais, ciudad, estado, monto=MONTO, tipo=TIPO_ENVIO)
    await evi.shot("cliente_beneficiario", locators=[
        logged_page.get_by_test_id("transfer-beneficiary-name-0-dropdown-input"),
        logged_page.get_by_test_id("transfer-beneficiary-first-lastname-0-input"),
    ])

    await F.seleccionar_pagador(flow, cfg, logger, tipo=TIPO_ENVIO)
    await evi.shot("OFAC_monto", locators=[
        logged_page.get_by_test_id("transfer-payers-money-info-amount-0-cash-amount-input")])
    logger.info("[CP02] Steps 1–2 OK (formulario OFAC + pagador).")

    # ── Steps 3–4: Completar envío (cae en OFAC Hold) ────────────────────────
    # El beneficiario OFAC dispara el mensaje informativo "Additional beneficiary
    # information is required… contact Compliance". completar_envio lo maneja
    # solo: pulsa 'Back to Transfer' y reintenta Continue hasta llegar al resumen
    # (y guarda evidencia 'mensaje_info_adicional.png'). Idéntico al script base.
    if COMPLETAR:
        # completar_envio captura por dentro (mensaje OFAC, envio_continue, éxito) vía evi.
        enviado = await F.completar_envio(
            flow, completar=True, logger=logger, evi=evi)
        assert enviado, "El envío OFAC no se completó (no apareció el modal de éxito)."
        logger.info("[CP02] Step 4 OK — envío realizado (OFAC Hold).")
    else:
        logger.info("[CP02] COMPLETAR_ENVIO=0 — envío NO completado (solo armado).")

    # ── Step 7: Cancelación desde Reportes (por nombre del beneficiario OFAC) ─
    if COMPLETAR and CANCELAR:
        logger.info("[CP02] Step 7 — cancelando la transacción de '%s'...", benef_full)
        cancelada = await C.cancelar_por_cliente(
            flow, benef_full, logger=logger, evi=evi,
            reason_index=0, notes="Automation CP02")
        assert cancelada, "La transacción OFAC no se pudo cancelar."
        logger.info("[CP02] Step 7 OK — transacción cancelada.")
    else:
        logger.info("[CP02] Cancelación OMITIDA (CP02_CANCELAR=0 o sin envío).")

    # ── Step 6: PENDIENTE (Chronos > OFAC Hold — verificar envío en la lista) ─
    logger.info("[CP02] Step 6 (Chronos OFAC Hold) pendiente de la fase Chronos.")
