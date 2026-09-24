"""
CP03-EscaneoCheque — Escaneo y procesamiento de un cheque.

El escaneo es el momento en que el Front End habla con un PERIFÉRICO a través
del agente (no una impresora), así que es una ruta distinta a las demás y hay
que probarla aparte. La vigilancia envuelve el escaneo y el procesamiento.

Guía completa: README.md de esta carpeta.
"""

import pytest
from playwright.async_api import Page

from config.logger import get_logger
from src.helpers.screenshot_helper import ScreenshotHelper
from src.sanity_general import chronos_otros_productos as OP

from . import parametros as P
from .flujos import Evidencia
from .flujos import cheques as CH
from .flujos.transferencia_page import HmTransferelektraPage

logger = get_logger("KRA-1527")


@pytest.mark.etiqueta
@pytest.mark.hardware_agent
@pytest.mark.asyncio
@pytest.mark.parametrize("language,width,height", P.PANTALLA)
async def test_CP03_EscaneoCheque(logged_page: Page, vigilancia,
                                  language, width, height):
    flow = HmTransferelektraPage(logged_page)
    evi = Evidencia(ScreenshotHelper(logged_page), P.CP03)
    datos_cheque = {}

    await CH.configurar_escaner(flow)
    await CH.ir_a_cheques_individuales(flow)
    await evi.shot("pantalla_cheques", paso=1)

    async with vigilancia(P.CP03, "Escaneo y procesamiento de un cheque") as v:
        escaneado = await CH.escanear(flow)
        await logged_page.wait_for_timeout(3_000)
        if escaneado:
            datos_cheque = await CH.llenar_datos(
                flow, CH.generar_numero_cheque(), P.CHEQUE_MONTO)
            logger.info("[%s] Cheque %s por %s", P.CP03,
                        datos_cheque.get("check_number"), P.CHEQUE_MONTO)
            await CH.procesar(flow)
            await logged_page.wait_for_timeout(4_000)
            await CH.finalizar(flow)
        await logged_page.wait_for_timeout(4_000)
    await evi.shot("cheque_procesado", paso=2)

    # ── Limpieza ANTES del veredicto ────────────────────────────────────────
    # El cheque NO se cancela desde Hermes: el menú kebab del reporte no ofrece
    # 'Cancel' para el tipo CHECKS (comprobado — el menú abre, la opción no
    # está, y el cheque queda vivo en TEST). La baja se hace en Chronos
    # rechazándolo por el emisor, que es como lo hace el back office.
    #
    # Chronos va en una PESTAÑA APARTE del mismo contexto: es otra app con su
    # propia sesión, y cerrar la de Hermes rompería el resto del caso.
    numero = (datos_cheque or {}).get("check_number")
    if escaneado and P.CANCELAR and numero:
        chronos_page = await logged_page.context.new_page()
        try:
            evi_ch = Evidencia(ScreenshotHelper(chronos_page), P.CP03,
                               start=evi.n)
            ok, detalle = await OP.rechazar_cheque(
                chronos_page, numero_cheque=numero,
                agencia=P.CHEQUE_AGENCIA, motivo=P.CHEQUE_MOTIVO_RECHAZO,
                evi=evi_ch, paso=3)
            v.anotar(f"Limpieza: {detalle}")
            if not ok:
                logger.warning("[%s] ⚠ Quedó un cheque VIVO en TEST (%s): %s",
                               P.CP03, numero, detalle)
                logger.warning("[%s]   Recházalo a mano en Chronos. La captura "
                               "del punto exacto donde falló está en "
                               "reports/evidence/KRA-1527/chronos_fallos/ y el "
                               "log de arriba nombra la constante a ajustar.",
                               P.CP03)
        finally:
            try:
                await chronos_page.close()
            except Exception:
                pass
    elif escaneado and P.CANCELAR:
        logger.warning("[%s] ⚠ Sin número de cheque no se puede rechazar en "
                       "Chronos — el cheque queda vivo.", P.CP03)

    assert escaneado, ("El escaneo no respondió. Revisa que el escáner esté "
                       "elegido en Configuración > Dispositivos y que el "
                       "Hardware Agent esté corriendo.")
    v.exigir_comunicacion()
    v.exigir_sin_token()
