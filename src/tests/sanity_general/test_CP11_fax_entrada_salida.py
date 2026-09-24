"""
CP11 — Fax de entrada y salida.
(Rescate de `HERMES2-qa/src/sanity_general/test_CP11_Fax_de_entrada_y_salida.py`.)

Flujo (Chronos → Hermes → Chronos → Hermes):
  1. Chronos: Agents > Agent → abrir la ficha de la agencia y VALIDAR que tiene
     el FAX configurado. Si no lo tiene, el caso falla aquí: sin fax en la
     agencia, todo lo que sigue no prueba nada.
  2. Hermes (multi-agencia): Money Transfer tipo HOME DELIVERY con destino
     PILI / UNIPHIL DELIVERY (Filipinas) por $1.
  3. Reportes > Transacciones: buscar la transacción recién creada.
  4. Menú de la transacción → 'Send Fax'.
  5. Chronos: Processing > Fax Assignment → confirmar el registro del fax.
  6. Hermes: cancelar la transacción (el caso no deja basura).

MULTIAGENCIA: usa la fixture `logged_page_multi` (login multi + selección de
agencia), igual que el CP04. La agencia sale de AGENCY_CODE y el fax esperado
de AGENCY_FAX; ambos cambian por ambiente.

COMO CORRER:
    pytest src/tests/sanity_general -k CP11 -v -s --headed
"""
import os
import random
import pytest
from playwright.async_api import Page

from config import settings
from config.logger import get_logger
from src.pages.hm_transferelektra_page import HmTransferelektraPage
from src.helpers.screenshot_helper import ScreenshotHelper
from src.helpers.datos import Datos
from src.pagadores import flujo_mt as F
from src.sanity_general import cancelacion as C
from src.sanity_general import chronos as CR
from src.sanity_general import chronos_agentes as AG
from src.sanity_general import Evidencia

logger = get_logger("CP11")

# ── Datos del caso ──────────────────────────────────────────────────────────
TIPO_ENVIO = "home"
MONTO = int(os.getenv("CP11_AMOUNT", "1"))
PAYER = os.getenv("CP11_PAYER", "UNIPHIL DELIVERY")
CIUDAD = os.getenv("CP11_CITY", "PILI")
# PILI pertenece a CAMARINES SUR. El State del beneficiario es OBLIGATORIO: sin
# él la pantalla lo marca en rojo y 'Continue' no procede.
ESTADO = os.getenv("CP11_STATE", "CAMARINES SUR")
PAIS = os.getenv("CP11_COUNTRY", "PHILIPPINES")
BRANCH = os.getenv("CP11_BRANCH") or settings.por_ambiente("143", "143456789")

AGENCY_CODE = os.getenv("CP11_AGENCY", settings.AGENCY_CODE)
FAX = os.getenv("CP11_FAX", settings.AGENCY_FAX)

COMPLETAR = os.getenv("COMPLETAR_ENVIO", "1").strip().lower() in ("1", "true", "si", "yes")
CANCELAR = os.getenv("CP11_CANCELAR", "1").strip().lower() in ("1", "true", "si", "yes")
EVIDENCE = "CP11_fax_entrada_salida"

CFG_HOME = {
    "code": "UNIPHIL_DELIVERY",
    "search": PAYER,
    "row": "",
    "needs_branch": True,
    "country": PAIS,
    "payer_city": CIUDAD,
}


@pytest.mark.sanity_general
@pytest.mark.chronos
@pytest.mark.asyncio
@pytest.mark.parametrize("language,width,height", [("English", 1366, 768)])
async def test_CP11_fax_entrada_salida(logged_page_multi: Page, language,
                                       width, height):
    flow = HmTransferelektraPage(logged_page_multi)
    datos = Datos()
    evi = Evidencia(ScreenshotHelper(logged_page_multi), EVIDENCE)
    await logged_page_multi.evaluate("window.print = () => {};")

    logger.info("[CP11] MULTI agencia=%s | fax esperado=%s | HOME %s, %s / %s | "
                "monto=%s", AGENCY_CODE, FAX, CIUDAD, ESTADO, PAYER, MONTO)

    # ── Step 1: Chronos — validar el FAX de la agencia ───────────────────────
    chronos_page = await logged_page_multi.context.new_page()
    try:
        dentro = await CR.abrir_chronos(chronos_page)
        assert dentro, ("No se pudo entrar a Chronos. Revisa CHRONOS_USER / "
                        "CHRONOS_PASS y la aprobación del 2FA.")
        evi_ch = Evidencia(ScreenshotHelper(chronos_page), EVIDENCE, start=evi.n)

        assert await AG.ir_a_agente(chronos_page, AGENCY_CODE), \
            f"No se pudo abrir la ficha de la agencia {AGENCY_CODE} en Chronos."
        ok_fax, leido, campo = await AG.validar_fax(chronos_page, FAX)
        await evi_ch.shot("fax_agencia_validado", paso=1,
                          locators=[campo] if campo else None)
        assert ok_fax, (f"La agencia {AGENCY_CODE} no tiene el FAX esperado "
                        f"({FAX}); su ficha dice '{leido or 'vacío'}'.")
        evi.n = evi_ch.n
        logger.info("[CP11] Step 1 OK — FAX de la agencia confirmado.")
    finally:
        try:
            await logged_page_multi.bring_to_front()
        except Exception as e:
            logger.warning("[CP11] No se pudo volver a Hermes: %s", str(e)[:80])

    # ── Step 2: Hermes — Money Transfer HOME DELIVERY ────────────────────────
    benef_phone = "".join(str(random.randint(0, 9)) for _ in range(10))
    await F.llenar_formulario_completo(
        flow, datos, dict(CFG_HOME), PAIS, CIUDAD, ESTADO, monto=MONTO,
        tipo=TIPO_ENVIO, benef_phone=benef_phone)

    cliente = datos.nombre_cliente()
    logger.info("[CP11] Cliente del envío: %s", cliente)

    await F.seleccionar_pagador_home(flow, PAYER, logger, branch_code=BRANCH)
    await evi.shot("home_monto_pagador", paso=2, locators=[
        logged_page_multi.get_by_test_id(
            "transfer-payers-money-info-amount-0-home-amount-input"),
        logged_page_multi.get_by_test_id(
            "transfer-payers-money-info-payer-0-home-input"),
    ])

    if not COMPLETAR:
        logger.info("[CP11] COMPLETAR_ENVIO=0 — envío NO completado (solo armado).")
        return

    enviado = await F.completar_envio(flow, completar=True, logger=logger, evi=evi)
    assert enviado, "El envío HOME no se completó."
    logger.info("[CP11] Step 2 OK — transacción creada.")

    # ── Steps 3–4: Reportes → Send Fax ───────────────────────────────────────
    await C.ir_a_reportes_transacciones(flow, multi=True, agency=AGENCY_CODE)
    try:
        await flow.buscar_transaccion_por_nombre(cliente)
    except Exception as e:
        logger.warning("[CP11] Búsqueda por nombre falló (%s) — sigo con la "
                       "primera fila del reporte.", str(e)[:80])
    await evi.shot("transaccion_en_reportes", paso=3,
                   search_text=cliente.split()[0] if cliente else None,
                   selector="tbody tr, tr.report-transactions-result-row")

    # La evidencia se toma DENTRO, con el aviso 'Insertion into fax queue was
    # successful' todavía en pantalla; después el método lo cierra (si queda
    # abierto, sus overlays impiden cancelar en el paso 6).
    assert await flow.enviar_fax_transaccion(evi=evi, paso=4), \
        "No se pudo disparar 'Send Fax' desde el menú de la transacción."
    logger.info("[CP11] Steps 3–4 OK — fax enviado desde Reportes.")

    # ── Step 5: Chronos — Fax Assignment ─────────────────────────────────────
    try:
        await chronos_page.bring_to_front()
        assert await AG.ir_a_fax_assignment(chronos_page), \
            "No se pudo abrir Chronos > Processing > Fax Assignment."
        evi_fax = Evidencia(ScreenshotHelper(chronos_page), EVIDENCE, start=evi.n)
        hay, celda = await AG.hay_registro_de_fax(chronos_page)
        await evi_fax.shot("fax_assignment_registro", paso=5,
                           locators=[celda] if celda else None)
        assert hay, "No apareció ningún registro en Fax Assignment."
        evi.n = evi_fax.n
        logger.info("[CP11] Step 5 OK — fax registrado en Chronos.")
    finally:
        try:
            await chronos_page.close()
        except Exception:
            pass
        try:
            await logged_page_multi.bring_to_front()
        except Exception as e:
            logger.warning("[CP11] No se pudo volver a Hermes: %s", str(e)[:80])

    # ── Step 6: Cancelación (el caso no deja basura) ─────────────────────────
    if not CANCELAR:
        logger.info("[CP11] Cancelación OMITIDA (CP11_CANCELAR=0).")
        return
    cancelada = await C.cancelar_por_cliente(
        flow, cliente, logger=logger, evi=evi, reason_index=0,
        notes="Automation CP11", multi=True, agency=AGENCY_CODE)
    assert cancelada, "La transacción no se pudo cancelar."
    logger.info("[CP11] Step 6 OK — transacción cancelada.")
