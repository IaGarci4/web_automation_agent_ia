"""
CP01 — Money Transfer Cash con KYC Hold y modificación de transacción.
(Rescate del sanity manual `HERMES2-qa/src/sanity_general/test_CP01_...py`.)

Piloto del rescate: ataca la capa MÁS inestable del sanity manual — la
Información Adicional — con selección por data-testid determinístico
(src/sanity_general/info_adicional.py), en vez del frágil "seleccionar por texto".

FASE ACTUAL (este archivo): Steps 1–5 (Hermes)
  1. Sesión monoagente (fixture logged_page).
  2–3. Formulario principal (cliente + beneficiario + Cash/ciudad/tarifa/monto/pagador)
       → REUTILIZA src/pagadores/flujo_mt.py (lógica que ya llena bien un envío).
  4. Información Adicional (país, tipo ID, número, expiración, nacimiento) → capa ESTABLE.
  5. Completar envío (Continue → resumen → YES, Send → éxito).

FASE SIGUIENTE (pendiente, requiere sesión Chronos + captura del diálogo Release):
  6. Reportes > Transacciones — buscar la transacción.
  7. Chronos > Compliance > KYC Hold — liberar (ver docs/sanity_general/CP01_info_adicional_DOM.md).
  8. Hermes > Modificar transacción.
  9. Cancelar transacción desde Reportes.

COMO CORRER:
    pytest src/tests/sanity_general -k CP01 -v -s --headed
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
from src.sanity_general import info_adicional as IA
from src.sanity_general import cancelacion as C
from src.sanity_general import Evidencia

logger = get_logger("CP01")

# ── Datos del caso (equivalentes al sanity manual) ──────────────────────────
PAYER_CODE   = os.getenv("CP01_PAYER", "SORIANA")   # cash, MEXICO
TIPO_ENVIO   = "cash"
MONTO        = int(os.getenv("CP01_AMOUNT", "20"))   # > $10 dispara la KYC Rule (Request ID)

# Identificación del cliente (ficha de Info Adicional)
IA_PAIS      = "EL SALVADOR"
IA_TIPO_ID   = "MATRICULA CONSULAR"
IA_NUM_ID    = "S4152365269"
IA_EXP       = "04/15/2030"
IA_DOB       = "05/21/1983"

COMPLETAR = os.getenv("COMPLETAR_ENVIO", "1").strip().lower() in ("1", "true", "si", "yes")
# CP01 incluye CANCELACIÓN por defecto (envío + cancelación). Apagar con CP01_CANCELAR=0.
CANCELAR  = os.getenv("CP01_CANCELAR", "1").strip().lower() in ("1", "true", "si", "yes")
EVIDENCE  = "CP01_money_transfer_cash_kyc"


def _cargar_payer(code: str) -> dict:
    payers, ciudades = F.cargar_catalogo(modulo="mexico")
    for p in payers:
        if p["code"].upper() == code.upper():
            return dict(p), ciudades
    # Fallback: primer payer cash activo
    return dict(payers[0]), ciudades


@pytest.mark.sanity_general
@pytest.mark.asyncio
@pytest.mark.parametrize("language,width,height", [("English", 1366, 768)])
async def test_CP01_money_transfer_cash_kyc(logged_page: Page, language, width, height):
    flow = HmTransferelektraPage(logged_page)
    datos = Datos()
    screenshot = ScreenshotHelper(logged_page)
    evi = Evidencia(screenshot, EVIDENCE)
    rng = random.Random()

    cfg, ciudades = _cargar_payer(PAYER_CODE)
    pais, ciudad, estado = F.destino(cfg, ciudades, rng)
    cfg["payer_city"] = ciudad

    logger.info("[CP01] payer=%s | destino=%s/%s | monto=%s | tipo=%s",
                cfg["code"], ciudad, estado, MONTO, TIPO_ENVIO)

    # ── Steps 2–3: Formulario principal (REUTILIZADO) ────────────────────────
    await F.llenar_formulario_completo(
        flow, datos, cfg, pais, ciudad, estado, monto=MONTO, tipo=TIPO_ENVIO)

    # Nombre del cliente USADO (cacheado por datos) — para buscar y cancelar luego.
    cliente = datos.nombre_cliente()
    logger.info("[CP01] Cliente del envío: %s", cliente)

    # Evidencia con marcado: nombres del beneficiario
    await evi.shot("cliente_beneficiario", paso=1, locators=[
        logged_page.get_by_test_id("transfer-beneficiary-name-0-dropdown-input"),
        logged_page.get_by_test_id("transfer-beneficiary-first-lastname-0-input"),
        logged_page.get_by_test_id("transfer-beneficiary-second-lastname-0-input"),
    ])

    await F.seleccionar_pagador(flow, cfg, logger, tipo=TIPO_ENVIO)

    # Evidencia con marcado: monto del envío
    await evi.shot("cash_monto_pagador", paso=2, locators=[
        logged_page.get_by_test_id("transfer-payers-money-info-amount-0-cash-amount-input")])
    logger.info("[CP01] Steps 2–3 OK (formulario principal + pagador).")

    # ── Step 4: Información Adicional (CAPA ESTABLE) ──────────────────────────
    # El primer Continue dispara la ficha de Info Adicional (KYC Rule: Request ID
    # cuando Sender Sends > $10). abrir_info_adicional es idempotente.
    await flow.wait_for_no_blocking_overlays()
    try:
        await flow.click_continue()
    except Exception:
        pass
    await logged_page.wait_for_timeout(1500)

    llenado = await IA.llenar_info_adicional_simple(
        flow, pais=IA_PAIS, tipo_id=IA_TIPO_ID, num_id=IA_NUM_ID,
        exp=IA_EXP, dob=IA_DOB, tipo=TIPO_ENVIO)

    # Evidencia con marcado: campos de identificación (país + número de ID)
    await evi.shot("info_adicional", paso=3, locators=[
        logged_page.get_by_test_id(IA.INPUT_PAIS),
        logged_page.get_by_test_id(IA.INPUT_NUM_ID),
    ])
    assert llenado, "La ficha de Información Adicional no se llenó correctamente."
    await IA.aceptar(flow)
    logger.info("[CP01] Step 4 OK (Información Adicional llenada y aceptada).")

    # ── Step 5: Completar envío ──────────────────────────────────────────────
    if COMPLETAR:
        # completar_envio captura por dentro (envio_continue, envio_exitoso) vía evi.
        enviado = await F.completar_envio(
            flow, completar=True, logger=logger, evi=evi)
        assert enviado, "El envío no se completó (no apareció el modal de éxito)."
        logger.info("[CP01] Step 5 OK — transacción enviada.")
    else:
        logger.info("[CP01] COMPLETAR_ENVIO=0 — envío NO completado (solo armado).")

    # ── Step 9: Cancelación de la transacción (Reportes → Transacciones) ──────
    if COMPLETAR and CANCELAR:
        logger.info("[CP01] Step 9 — cancelando la transacción de '%s'...", cliente)
        cancelada = await C.cancelar_por_cliente(
            flow, cliente, logger=logger, evi=evi,
            reason_index=0, notes="Automation CP01")
        assert cancelada, "La transacción no se pudo cancelar."
        logger.info("[CP01] Step 9 OK — transacción cancelada.")
    else:
        logger.info("[CP01] Cancelación OMITIDA (CP01_CANCELAR=0 o sin envío).")

    # ── Steps 6–8: PENDIENTES (Chronos KYC Hold + modificar) ─────────────────
    # Ver docs/sanity_general/CP01_info_adicional_DOM.md (sección KYC Hold).
    logger.info("[CP01] Steps 6–8 (KYC Hold + modificar) pendientes de la fase Chronos.")
