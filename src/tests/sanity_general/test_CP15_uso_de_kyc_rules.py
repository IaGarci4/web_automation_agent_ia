"""
CP15 — Uso de KYC Rules.
(Migración/mejora de `HERMES2-qa/src/sanity_general/test_CP15_Uso_de_KYC_Rules.py`.)

Con una KYC Rule ACTIVA (activada manualmente en Chronos para el pagador SORIANA
en la agencia de prueba), un envío normal dispara compliance: al Continuar, Hermes
exige Información Adicional. El caso valida que el motivo mencione la regla, llena
la identificación, completa el envío y lo cancela.

Reutiliza el motor estable:
  • flujo_mt        → formulario principal (cliente + beneficiario + pagador + monto)
  • kyc_rules       → Continue + validar la regla + llenar/aceptar Info Adicional
  • flujo_mt        → completar el envío (Continue → resumen → Sí, Enviar)
  • cancelacion     → cancelar desde Reportes

COMO CORRER:
    pytest src/tests/sanity_general -k CP15 -v -s
    # cambiar datos:  $env:CP15_PAYER="SORIANA"; $env:CP15_AMOUNT="20"
"""
import os
import random

import pytest
from playwright.async_api import Page

from config import settings
from config.logger import get_logger
from src.helpers.datos import Datos
from src.helpers.screenshot_helper import ScreenshotHelper
from src.pages.hm_transferelektra_page import HmTransferelektraPage
from src.pagadores import flujo_mt as F
from src.sanity_general import Evidencia
from src.sanity_general import kyc_rules as KYC
from src.sanity_general import cancelacion as CANCEL

logger = get_logger("CP15")

# ── Datos del caso ────────────────────────────────────────────────────────────
PAYER_CODE = os.getenv("CP15_PAYER", "SORIANA")     # cash, MEXICO, con KYC Rule
TIPO_ENVIO = "cash"
MONTO      = int(os.getenv("CP15_AMOUNT", "20"))
CIUDAD     = os.getenv("CP15_CITY", "OCOTLAN")
ESTADO     = os.getenv("CP15_STATE", "JALISCO")
# Teléfono del CLIENTE en PRODUCCIÓN: número FIJO ASIGNADO (bloque ficticio NANP
# 555-01NN) para que el SMS del recibo llegue a un buzón controlado. En TEST se
# ignora y se usa el aleatorio de siempre. Override puntual: CP15_PROD_PHONE.
PROD_PHONE = os.getenv("CP15_PROD_PHONE", "5550100025")

# Nombre de la KYC Rule activa (cambia por ambiente, igual que el sanity original).
RULE_NAME = os.getenv("CP15_RULE") or settings.por_ambiente(
    "Agencia 0040 Sanity KYC Rule Payer - Soriana",
    "Agencia 0020 Sanity KYC Rule")

# Identificación a capturar en la Info Adicional (datos del caso).
IA_PAIS    = os.getenv("CP15_ID_COUNTRY", "UNITED STATES")
IA_TIPO_ID = os.getenv("CP15_ID_TYPE") or settings.por_ambiente(
    "MILITARY IDENTIFICATION", "MILITARY ID")
IA_NUM_ID  = os.getenv("CP15_ID_NUMBER", "DL123456789")
IA_EXP     = os.getenv("CP15_ID_EXP", "12/31/2028")
IA_DOB     = os.getenv("CP15_ID_DOB", "01/01/1990")

CANCELAR = os.getenv("CP15_CANCELAR", "1").strip().lower() in ("1", "true", "si", "sí", "yes")
EVIDENCE = "CP15_uso_de_kyc_rules"


def _cargar_payer(code: str):
    payers, ciudades = F.cargar_catalogo(modulo="mexico")
    for p in payers:
        if p["code"].upper() == code.upper():
            return dict(p), ciudades
    return dict(payers[0]), ciudades


@pytest.mark.sanity_general
@pytest.mark.asyncio
@pytest.mark.parametrize("language,width,height", [("English", 1366, 768)])
async def test_CP15_uso_de_kyc_rules(logged_page: Page, language, width, height):
    flow = HmTransferelektraPage(logged_page)
    datos = Datos()
    screenshot = ScreenshotHelper(logged_page)
    evi = Evidencia(screenshot, EVIDENCE)
    rng = random.Random()

    cfg, ciudades = _cargar_payer(PAYER_CODE)
    pais = cfg.get("country", "MEXICo")
    # OJO: la ciudad del PAGADOR es HOMÓNIMA (OCOTLAN existe en JALISCO y en
    # OAXACA). Se teclea solo 'OCOTLAN' (stem) y se selecciona por TEXTO la opción
    # que contenga 'JALISCO' — donde SÍ existe SORIANA. (Aislado a este caso vía
    # ciudad_cash_contiene; no afecta a otros CP.)
    cfg["payer_city"] = CIUDAD                       # stem, sin estado
    logger.info("[CP15] payer=%s | destino=%s/%s | monto=%s | KYC Rule='%s'",
                cfg["code"], CIUDAD, ESTADO, MONTO, RULE_NAME)

    # ── Step 1: formulario principal + pagador (envío normal) ─────────────────
    await F.llenar_formulario_completo(
        flow, datos, cfg, pais, CIUDAD, ESTADO, monto=MONTO, tipo=TIPO_ENVIO,
        ciudad_cash_contiene=ESTADO, customer_phone=PROD_PHONE)
    await F.seleccionar_pagador(flow, cfg, logger, tipo=TIPO_ENVIO)
    await evi.shot("transfer_form_filled", paso=1)
    cliente = datos.nombre_cliente()
    logger.info("[CP15] Step 1 OK — formulario listo (cliente=%s).", cliente)

    # ── Steps 2–6: compliance por la KYC Rule (Continue → validar → llenar) ───
    aparecio, regla_ok = await KYC.resolver_compliance_kyc(
        flow, rule_name=RULE_NAME, pais=IA_PAIS, tipo_id=IA_TIPO_ID,
        num_id=IA_NUM_ID, exp=IA_EXP, dob=IA_DOB, tipo=TIPO_ENVIO,
        logger=logger, evi=evi)
    assert aparecio, ("El compliance por la KYC Rule NO apareció — verifica que la "
                      "regla esté ACTIVA en Chronos para el pagador/agencia.")
    assert regla_ok, (f"El motivo de compliance no menciona la KYC Rule esperada "
                      f"('{RULE_NAME}').")
    logger.info("[CP15] Steps 2–6 OK — compliance por KYC Rule validado y llenado.")

    # ── Step 7: completar el envío (Continue → resumen → Sí, Enviar) ──────────
    enviado = await F.completar_envio(
        flow, completar=True, logger=logger, evi=evi, tipo_envio=TIPO_ENVIO)
    assert enviado, "El envío no se completó tras resolver el compliance de la KYC Rule."
    await evi.shot("transfer_completed", paso=7)
    logger.info("[CP15] Step 7 OK — envío completado.")

    # ── Step 8: cancelar desde Reportes ───────────────────────────────────────
    if CANCELAR:
        cancelada = await CANCEL.cancelar_por_cliente(
            flow, cliente, logger=logger, evi=evi, notes="Automation CP15")
        assert cancelada, "No se pudo cancelar la transacción del CP15."
        await evi.shot("transaction_cancelled", paso=8)
        logger.info("[CP15] Step 8 OK — transacción cancelada.")
    else:
        logger.info("[CP15] Cancelación OMITIDA (CP15_CANCELAR=0).")

    logger.info("[CP15] Uso de KYC Rules OK.")
