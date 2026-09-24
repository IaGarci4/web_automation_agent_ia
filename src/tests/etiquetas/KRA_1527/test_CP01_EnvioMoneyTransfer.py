"""
CP01-EnvioMoneyTransfer — Impresión del recibo de un Money Transfer.

Envío completo y **ACEPTANDO** la impresión del recibo. Es el caso base de la
etiqueta: la ruta más común por la que el Front End invoca al Hardware Agent.

⚠️ Aquí NO se neutraliza `window.print` y la impresión se acepta, al contrario
que en el sanity. Si eso se cambia, el caso aprueba sin haber probado nada.

**La cancelación va ANTES del veredicto**, a propósito: el envío es real y si
el caso falla —como pasó la primera vez, por no encontrar al agente— la
transacción se quedaría viva en TEST. Limpiar primero y juzgar después.

Guía completa: README.md de esta carpeta.
"""

import pytest
from playwright.async_api import Page

from config.logger import get_logger
from src.helpers.datos import Datos
from src.helpers.screenshot_helper import ScreenshotHelper

from . import parametros as P
from .flujos import Evidencia
from .flujos import cancelaciones as C
from .flujos import mt as F
from .flujos import transacciones as T
from .flujos.transferencia_page import HmTransferelektraPage

logger = get_logger("KRA-1527")


@pytest.mark.etiqueta
@pytest.mark.hardware_agent
@pytest.mark.asyncio
@pytest.mark.parametrize("language,width,height", P.PANTALLA)
async def test_CP01_EnvioMoneyTransfer(logged_page: Page, vigilancia,
                                       language, width, height):
    flow = HmTransferelektraPage(logged_page)
    datos = Datos()
    evi = Evidencia(ScreenshotHelper(logged_page), P.CP01)

    # Sin paso previo por Configuración > Dispositivos: la impresora ya venía
    # elegida en el ambiente («TICKET (DEFAULT)») y comprobarlo no cambió el
    # resultado — seguía sin verse tráfico HTTP. Cada visita a Dispositivos
    # costaba medio minuto y arriesgaba el aviso de «salir de esta página».
    # El módulo `flujos/impresora.py` sigue disponible si algún ambiente
    # aparece sin impresora configurada.
    cfg, ciudades = P.cargar_payer()
    # Destino del CATÁLOGO, no al azar. Aleatorizar la ciudad rompía el envío:
    # ELEKTRA no opera en todas, así que cuando tocaba una sin sucursales el
    # modal salía vacío y Continue no avanzaba. Lo aleatorio se queda donde no
    # afecta al negocio —nombres, direcciones, teléfonos—; la geografía sale de
    # la pareja pagador/ciudad que el módulo declara como buena.
    pais, ciudad, estado = F.destino_del_pagador(cfg, ciudades, logger)
    logger.info("[%s] Envío %s → %s/%s por $%s (con impresión de recibo).",
                P.CP01, cfg["code"], ciudad, estado, P.MT_MONTO)

    await F.llenar_formulario_completo(flow, datos, cfg, pais, ciudad, estado,
                                       monto=P.MT_MONTO, tipo="cash")
    await F.seleccionar_pagador(flow, cfg, logger, tipo="cash")
    await evi.shot("envio_armado", paso=1)

    async with vigilancia(P.CP01, "Impresión del recibo de un Money Transfer") as v:
        # La impresión del recibo es AUTOMÁTICA al completarse el envío. El
        # modal que sale después pregunta «¿otra transacción?» y se cierra con
        # NO — pulsar su botón afirmativo (lo que hacía `imprimir_recibo=True`)
        # no imprimía nada y dejaba la app arrancando un envío nuevo.
        enviado = await F.completar_envio(flow, completar=True, logger=logger,
                                          evi=evi)
        await logged_page.wait_for_timeout(6_000)      # que el agente responda
    await evi.shot("recibo_impreso", paso=2)

    # ── Limpieza ANTES del veredicto ────────────────────────────────────────
    if enviado and P.CANCELAR:
        await T.ir_a_reportes_transacciones(flow)
        ok, detalle = await C.cancelar_money_transfer(flow, evi=evi, paso=3)
        v.anotar(f"Limpieza: {detalle}")
        if not ok:
            logger.warning("[%s] ⚠ Quedó una transacción VIVA en TEST: %s",
                           P.CP01, detalle)

    assert enviado, "El envío no se completó; sin recibo no hay nada que auditar."
    v.exigir_comunicacion()
    v.exigir_sin_token()
