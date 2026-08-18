"""
CP04 — Money Transfer DOMÉSTICO (ATM / Pin4Cash) multi-agente con doble OFAC.
(Rescate de `HERMES2-qa/src/sanity_general/test_CP04_money_transfer_doméstico_multi_OFAC.py`.)

Particularidades (vs CP01–CP03):
  • MULTIAGENTE: login con PORTAL_USER_MULTI + selección de agencia (fixture
    logged_page_multi). Agencia por AGENCY_CODE (default 0040-OK).
  • DOMÉSTICO: beneficiario UNITED STATES (estado GEORGIA), tab ATM.
  • Beneficiario OFAC (JOAQUIN GUZMAN LOERA) → mensaje informativo de compliance
    (Back to Transfer), manejado por completar_envio.
  • Pagador ATM: MASTERCARD CASH PICK-UP.

FASE ACTUAL: Steps 1–6 + 11 (Hermes: multi-login → armar ATM → enviar → cancelar).
FASE SIGUIENTE (Chronos): Steps 7–10 — Signature Hold + OFAC Hold + doble validación + liberar.

COMO CORRER:
    pytest src/tests/sanity_general -k CP04 -v -s --headed
"""
import os
import random
import pytest
from playwright.async_api import Page

from config.logger import get_logger
from config import settings
from src.pages.hm_transferelektra_page import HmTransferelektraPage
from src.helpers.screenshot_helper import ScreenshotHelper
from src.helpers.datos import Datos
from src.helpers.zips_us import ciudad_estado_aleatorio
from src.pagadores import flujo_mt as F
from src.sanity_general import cancelacion as C
from src.sanity_general import Evidencia

logger = get_logger("CP04")

# ── Datos del caso ──────────────────────────────────────────────────────────
TIPO_ENVIO = "atm"
MONTO      = int(os.getenv("CP04_AMOUNT", "20"))
PAYER_SEARCH = os.getenv("CP04_PAYER", "MASTERCARD CASH PICK-UP")

# Beneficiario doméstico OFAC
BENEF_NAME, BENEF_LAST1, BENEF_LAST2 = "JOAQUIN", "GUZMAN", "LOERA"
BENEF_COUNTRY = "UNITED STATES"
# Estado/ciudad ALEATORIOS (cobertura amplia). Override opcional con CP04_STATE.

CUST_PHONE = "5550100021"

COMPLETAR = os.getenv("COMPLETAR_ENVIO", "1").strip().lower() in ("1", "true", "si", "yes")
CANCELAR  = os.getenv("CP04_CANCELAR", "1").strip().lower() in ("1", "true", "si", "yes")
EVIDENCE  = "CP04_money_transfer_domestico_multi_OFAC"


# Pagador ATM doméstico (no está en catálogo de países; se arma inline)
CFG_ATM = {
    "code": "MASTERCARD_CASH_PICKUP",
    "search": PAYER_SEARCH,
    "row": "",
    "needs_branch": False,
    "country": BENEF_COUNTRY,
    "payer_city": "",
}


@pytest.mark.sanity_general
@pytest.mark.asyncio
@pytest.mark.parametrize("language,width,height", [("English", 1366, 768)])
async def test_CP04_money_transfer_domestico_multi_OFAC(logged_page_multi: Page,
                                                        language, width, height):
    flow = HmTransferelektraPage(logged_page_multi)
    datos = Datos()
    # Beneficiario OFAC fijo; cliente random pero con teléfono fijo (cliente existente).
    datos._benef = [BENEF_NAME, BENEF_LAST1, BENEF_LAST2]
    datos._cache["phone"] = CUST_PHONE
    screenshot = ScreenshotHelper(logged_page_multi)
    evi = Evidencia(screenshot, EVIDENCE)

    cfg = dict(CFG_ATM)
    benef_phone = "".join(str(random.randint(0, 9)) for _ in range(10))

    # Estado/ciudad DOMÉSTICOS aleatorios (cobertura amplia de estados de EU).
    # Override opcional: CP04_STATE (nombre completo) + CP04_CITY.
    if os.getenv("CP04_STATE"):
        benef_state = os.getenv("CP04_STATE").strip().upper()
        benef_city = os.getenv("CP04_CITY", "ATLANTA").strip().upper()
    else:
        benef_city, benef_state = ciudad_estado_aleatorio()

    logger.info("[CP04] MULTI agencia=%s | doméstico ATM | payer=%s | ciudad=%s estado=%s | monto=%s",
                settings.AGENCY_CODE, PAYER_SEARCH, benef_city, benef_state, MONTO)

    # ── Steps 1–3: Formulario principal doméstico (ATM) ──────────────────────
    await F.llenar_formulario_completo(
        flow, datos, cfg, BENEF_COUNTRY, benef_city, benef_state,
        monto=MONTO, tipo=TIPO_ENVIO, benef_phone=benef_phone)

    # Nombre del cliente USADO (cacheado por datos DESPUÉS de llenar) — para cancelar.
    cliente = datos.nombre_cliente()
    logger.info("[CP04] Cliente del envío: %s", cliente)
    await evi.shot("cliente_beneficiario_OFAC", locators=[
        logged_page_multi.get_by_test_id("transfer-beneficiary-name-0-dropdown-input"),
        logged_page_multi.get_by_test_id("transfer-beneficiary-first-lastname-0-input"),
    ])

    # Pagador ATM = typeahead directo (no modal)
    await F.seleccionar_pagador_atm(flow, PAYER_SEARCH, logger)
    await evi.shot("ATM_monto_pagador", locators=[
        logged_page_multi.get_by_test_id("transfer-payers-money-info-amount-0-atm-amount-input"),
        logged_page_multi.get_by_test_id("transfer-payers-money-info-payer-0-atm-input"),
    ])
    logger.info("[CP04] Steps 1–3 OK (doméstico ATM + pagador).")

    # ── Steps 4–5: Completar envío (mensaje OFAC → Back to Transfer → enviar) ─
    if COMPLETAR:
        # completar_envio captura por dentro (mensaje OFAC, envio_continue, éxito) vía evi.
        enviado = await F.completar_envio(
            flow, completar=True, logger=logger, evi=evi)
        assert enviado, "El envío doméstico OFAC no se completó."
        logger.info("[CP04] Steps 4–5 OK — envío realizado (OFAC Hold).")
    else:
        logger.info("[CP04] COMPLETAR_ENVIO=0 — envío NO completado (solo armado).")

    # ── Step 11: Cancelación desde Reportes (por nombre del cliente) ─────────
    if COMPLETAR and CANCELAR:
        logger.info("[CP04] Cancelando la transacción de '%s'...", cliente)
        cancelada = await C.cancelar_por_cliente(
            flow, cliente, logger=logger, evi=evi,
            reason_index=0, notes="Automation CP04",
            multi=True, agency=settings.AGENCY_CODE)
        assert cancelada, "La transacción no se pudo cancelar."
        logger.info("[CP04] Cancelación OK.")
    else:
        logger.info("[CP04] Cancelación OMITIDA (CP04_CANCELAR=0 o sin envío).")

    # ── Steps 7–10: PENDIENTE (Chronos: Signature/OFAC Hold + doble validación) ─
    logger.info("[CP04] Steps 7–10 (Chronos) pendientes de la fase Chronos.")
