"""
CP03 — Money Transfer Depósito con pago Tarjeta de Débito (TDD).
(Rescate de `HERMES2-qa/src/sanity_general/test_CP03_Money_Transfer_Deposito_TDD.py`.)

Envío tipo DEPÓSITO a Colombia (BANCOLOMBIA.), con:
  • Cuestionario COMPLETO de compliance (país, ID, ocupación, tax ID, relación,
    propósito, origen de fondos, third-party) → src/sanity_general/cuestionario.py
  • Pago con TARJETA DE DÉBITO (transfer-totals-pin-0) + emulador POS
    (pos-accept-button) → manejado por flujo_mt.completar_envio(pos_pago=True).

El formulario principal reutiliza el motor del agente (flujo_mt), sólo cambian
los datos. El emulador de terminal bancaria ya está listo para recibir el cobro.

FASE ACTUAL: Steps 1–7 (Hermes: armar depósito → cuestionario → débito → POS → enviar).
FASE SIGUIENTE (Chronos): Steps 8–9 — Deposit Hold + rechazo.

COMO CORRER:
    pytest src/tests/sanity_general -k CP03 -v -s --headed
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
from src.sanity_general import cuestionario as Q
from src.sanity_general import cancelacion as C
from src.sanity_general import Evidencia

logger = get_logger("CP03")

# ── Datos del caso ──────────────────────────────────────────────────────────
PAYER_CODE = os.getenv("CP03_PAYER", "BANCOLOMBIA_DIRECTO")  # "Bancolombia." (Colombia)
TIPO_ENVIO = "deposit"
MONTO      = int(os.getenv("CP03_AMOUNT", "3000"))
CIUDAD     = "MEDELLIN"
ESTADO     = "ANTIOQUIA"
ACCOUNT_NUMBER = os.getenv("CP03_ACCOUNT", "88888888888")

# Cliente EXISTENTE fijo
CUST_NAME, CUST_LAST1, CUST_LAST2 = "SUSANA", "HERNANDEZ", "TEST"
CUST_PHONE = "5550100020"

# Cuestionario completo (terceros)
Q_COUNTRY      = "EL SALVADOR"
Q_ID_TYPE      = "MATRICULA CONSULAR"
Q_ID_NUMBER    = "S4152365269"
Q_EXP          = "04/15/2030"
Q_DOB          = "05/21/1983"
Q_OCCUPATION   = "CONSTRUCTION"
Q_SUB_OCC      = "ARCHITECT"
Q_TAX_TYPE     = "SOCIAL SECURITY NUMBER (SSN)"
Q_TAX_NUMBER   = "124-58-5698"
Q_RELATION     = "BROTHER"
Q_PURPOSE      = "HOME CONSTRUCTION"
Q_ORIGIN       = "SAVINGS"

COMPLETAR = os.getenv("COMPLETAR_ENVIO", "1").strip().lower() in ("1", "true", "si", "yes")
CANCELAR  = os.getenv("CP03_CANCELAR", "1").strip().lower() in ("1", "true", "si", "yes")
EVIDENCE  = "CP03_money_transfer_deposito_tdd"


def _cargar_payer(code: str):
    payers, ciudades = F.cargar_catalogo(modulo="colombia")
    for p in payers:
        if p["code"].upper() == code.upper():
            return dict(p), ciudades
    return dict(payers[0]), ciudades


@pytest.mark.sanity_general
@pytest.mark.asyncio
@pytest.mark.parametrize("language,width,height", [("English", 1366, 768)])
async def test_CP03_money_transfer_deposito_tdd(logged_page: Page, language, width, height):
    flow = HmTransferelektraPage(logged_page)
    datos = Datos()
    # Cliente EXISTENTE fijo + su teléfono; beneficiario random (phone prefijo 387).
    datos._cliente = [CUST_NAME, CUST_LAST1, CUST_LAST2]
    datos._cache["phone"] = CUST_PHONE
    screenshot = ScreenshotHelper(logged_page)
    evi = Evidencia(screenshot, EVIDENCE)

    cfg, _ = _cargar_payer(PAYER_CODE)
    cfg["payer_city"] = CIUDAD
    benef_phone = "387" + "".join(str(random.randint(0, 9)) for _ in range(7))
    cliente = datos.nombre_cliente()

    logger.info("[CP03] payer=%s | destino=COLOMBIA/%s | monto=%s | cuenta=%s | cliente=%s",
                cfg["code"], CIUDAD, MONTO, ACCOUNT_NUMBER, cliente)

    # ── Steps 1–2: Formulario principal (Depósito) ───────────────────────────
    await F.llenar_formulario_completo(
        flow, datos, cfg, "COLOMBIA", CIUDAD, ESTADO,
        monto=MONTO, tipo=TIPO_ENVIO, benef_phone=benef_phone)
    await evi.shot("cliente_beneficiario", locators=[
        logged_page.get_by_test_id("transfer-beneficiary-name-0-dropdown-input"),
        logged_page.get_by_test_id("transfer-beneficiary-first-lastname-0-input"),
    ])

    # Pagador (Depósito) + tipo de cuenta Checking + número de cuenta
    await F.seleccionar_pagador(flow, cfg, logger, tipo=TIPO_ENVIO)
    await flow.seleccionar_deposit_account_type(opcion=1)          # 1 = Cheques (Checking)
    await flow.fill_deposit_account_number(ACCOUNT_NUMBER)
    await evi.shot("deposito_cuenta", locators=[
        logged_page.get_by_test_id("transfer-payers-money-info-amount-0-deposit-amount-input"),
        logged_page.get_by_test_id("transfer-payers-money-info-account-number-0-deposit-input"),
    ])
    logger.info("[CP03] Steps 1–2 OK (depósito + pagador + cuenta).")

    # ── Step 3: Cuestionario COMPLETO de compliance ──────────────────────────
    await flow.wait_for_no_blocking_overlays()
    try:
        await flow.click_continue()
    except Exception:
        pass
    await logged_page.wait_for_timeout(1500)

    ok_q = await Q.llenar_cuestionario_completo(
        flow, country=Q_COUNTRY, id_type=Q_ID_TYPE, id_number=Q_ID_NUMBER,
        expiration_date=Q_EXP, date_of_birth=Q_DOB, occupation=Q_OCCUPATION,
        subcategory_occupation=Q_SUB_OCC, tax_id_type=Q_TAX_TYPE,
        tax_id_number=Q_TAX_NUMBER, beneficiary_relation=Q_RELATION,
        purpose=Q_PURPOSE, origin_founds=Q_ORIGIN, tipo=TIPO_ENVIO)
    await evi.shot("cuestionario")
    assert ok_q, "El cuestionario completo de compliance no se llenó correctamente."
    logger.info("[CP03] Step 3 OK (cuestionario completo).")

    # ── Step 4: Forma de pago Tarjeta de Débito ──────────────────────────────
    await F.seleccionar_pago_tarjeta_debito(flow, logger)
    await evi.shot("tarjeta_debito", locators=[logged_page.get_by_test_id(F.TESTID_PAGO_DEBITO)])
    logger.info("[CP03] Step 4 OK (Tarjeta de Débito seleccionada).")

    # ── Steps 5–7: Completar envío con POS (emulador de terminal) ────────────
    if COMPLETAR:
        # completar_envio captura por dentro (envio_continue, POS, éxito) vía evi.
        enviado = await F.completar_envio(
            flow, completar=True, logger=logger, evi=evi, pos_pago=True)
        assert enviado, "El envío con Tarjeta de Débito no se completó."
        logger.info("[CP03] Steps 5–7 OK — envío con TDD completado.")
    else:
        logger.info("[CP03] COMPLETAR_ENVIO=0 — envío NO completado (solo armado).")

    # ── Cancelación desde Reportes (por nombre del cliente) ──────────────────
    if COMPLETAR and CANCELAR:
        logger.info("[CP03] Cancelando la transacción de '%s'...", cliente)
        cancelada = await C.cancelar_por_cliente(
            flow, cliente, logger=logger, evi=evi,
            reason_index=0, notes="Automation CP03")
        assert cancelada, "La transacción no se pudo cancelar."
        logger.info("[CP03] Cancelación OK.")
    else:
        logger.info("[CP03] Cancelación OMITIDA (CP03_CANCELAR=0 o sin envío).")

    # ── Steps 8–9: PENDIENTE (Chronos > Deposit Hold + rechazo) ──────────────
    logger.info("[CP03] Steps 8–9 (Chronos Deposit Hold) pendientes de la fase Chronos.")
