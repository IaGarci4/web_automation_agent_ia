"""
CP09 — Pagos en Línea: depósito, cargo y pago online.
(Rescate de `HERMES2-qa/.../test_CP09_pagos_en_linea.py`.)

Flujo (Chronos primero, luego Hermes):
  1. Abrir Chronos en una pestaña nueva (sesión reutilizada, sin login).
  2. Collection > Agent Monitor → buscar la agencia.
  3. Agregar DEPÓSITO ($1, nota 'test').
  4. Agregar OTRO CARGO (Credit, memo '4406-02 Balance Transfer Credit', $1).
  5. Collection > Collection → buscar la agencia.
  6. Validar/ajustar el BALANCE del agente.
  7. Cerrar la pestaña de Chronos y volver a Hermes.
  8. Hermes: Pagos en Línea → cuenta por alias → monto → Pay Now → confirmar.

Agencia y alias salen del ambiente activo (HERMES_ENV).

REQUISITO: la sesión de Chronos debe estar guardada. Si no, córrelo una vez:
    python tools/login_chronos.py

COMO CORRER:
    pytest src/tests/sanity_general -k CP09 -v -s --headed
"""
import os
import pytest
from playwright.async_api import Page

from config.logger import get_logger
from config import settings
from src.pages.hm_transferelektra_page import HmTransferelektraPage
from src.helpers.screenshot_helper import ScreenshotHelper
from src.sanity_general import chronos as CR
from src.sanity_general import chronos_cobranza as CB
from src.sanity_general import pagos_linea as PL
from src.sanity_general import Evidencia

logger = get_logger("CP09")

# ── Datos del caso (cambian por ambiente; override por env) ─────────────────
AGENCY_CODE = os.getenv("CP09_AGENCY", settings.AGENCY_CODE)
ALIAS_CUENTA = os.getenv("CP09_ALIAS", settings.por_ambiente(
    "MI RANCHITO MARKET", "Maxi Prueba(Expense)"))
MONTO_PAGO = os.getenv("CP09_MONTO", "1")

# Sub-fases activables (para depurar solo una parte).
HACER_CHRONOS = os.getenv("CP09_CHRONOS", "1").strip().lower() in ("1", "true", "si", "yes")
HACER_PAGO    = os.getenv("CP09_PAGO",    "1").strip().lower() in ("1", "true", "si", "yes")

EVIDENCE = "CP09_pagos_en_linea"


@pytest.mark.sanity_general
@pytest.mark.chronos
@pytest.mark.asyncio
@pytest.mark.parametrize("language,width,height", [("English", 1366, 768)])
async def test_CP09_pagos_en_linea(logged_page: Page, language, width, height):
    flow = HmTransferelektraPage(logged_page)
    evi = Evidencia(ScreenshotHelper(logged_page), EVIDENCE)
    await logged_page.evaluate("window.print = () => {};")
    logger.info("[CP09] agencia=%s | alias='%s' | monto=%s",
                AGENCY_CODE, ALIAS_CUENTA, MONTO_PAGO)

    # ── Steps 1–7: Chronos (pestaña nueva) ───────────────────────────────────
    if HACER_CHRONOS:
        chronos_page = await logged_page.context.new_page()
        try:
            dentro = await CR.abrir_chronos(chronos_page)
            assert dentro, ("No se pudo entrar a Chronos. Corre una vez "
                            "`python tools/login_chronos.py` para guardar la sesión.")
            evi_ch = Evidencia(ScreenshotHelper(chronos_page), EVIDENCE, start=evi.n)

            # Step 2: Agent Monitor + buscar agencia
            await CB.ir_a_agent_monitor(chronos_page)
            encontrado = await CB.buscar_agente(chronos_page, AGENCY_CODE)
            await evi_ch.shot("agent_monitor_agencia")
            assert encontrado, f"La agencia {AGENCY_CODE} no apareció en Agent Monitor."

            # Step 3: depósito
            dep_ok = await CB.agregar_deposito(chronos_page)
            await evi_ch.shot("deposito_agregado")
            assert dep_ok, "No se pudo agregar el depósito en Agent Monitor."

            # Step 4: otro cargo
            cargo_ok = await CB.agregar_otro_cargo(chronos_page)
            await evi_ch.shot("otro_cargo_agregado")
            assert cargo_ok, "No se pudo agregar el otro cargo en Agent Monitor."

            # Steps 5–6: Collection + balance
            await CB.ir_a_collection(chronos_page)
            hallada = await CB.buscar_agente(chronos_page, AGENCY_CODE, en_collection=True)
            await evi_ch.shot("collection_agencia")
            assert hallada, f"La agencia {AGENCY_CODE} no apareció en Collection."

            resultado = await CB.validar_balance(chronos_page)
            await evi_ch.shot("balance_validado")
            assert resultado["balance"], "No se pudo leer el balance del agente."
            logger.info("[CP09] Balance='%s' · aplicado=%s · ajustado=%s",
                        resultado["balance"], resultado["aplicado"],
                        resultado["ajustado"])
            evi.n = evi_ch.n                    # continúa la numeración
        finally:
            # Step 7: cerrar Chronos y volver a Hermes
            try:
                await chronos_page.close()
            except Exception:
                pass
            await logged_page.bring_to_front()
        logger.info("[CP09] Steps 1–7 OK (Chronos).")

    # ── Step 8: Hermes — pago en línea ───────────────────────────────────────
    if not HACER_PAGO:
        logger.info("[CP09] CP09_PAGO=0 — pago en línea omitido.")
        return

    assert await PL.abrir_pagos_en_linea(flow), "No se pudo abrir Pagos en Línea."
    await evi.shot("pagos_en_linea")

    await PL.revisar_terminos_nueva_cuenta(flow, evi=evi)

    assert await PL.elegir_cuenta(flow, ALIAS_CUENTA), \
        f"No se encontró la cuenta con alias '{ALIAS_CUENTA}'."
    await evi.shot("cuenta_seleccionada")

    assert await PL.pagar(flow, monto=MONTO_PAGO, evi=evi), \
        "El pago en línea no se completó."
    await evi.shot("pago_final")
    logger.info("[CP09] Step 8 OK — pago en línea completado ✓")
