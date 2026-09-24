"""
CP02-FichaDeposito — Impresión de la ficha de depósito.

Ficha de Depósitos: foto (cámara simulada del conftest) + monto + envío. El
envío de la ficha es lo que dispara al agente, así que la vigilancia envuelve
solo ese paso.

Guía completa: README.md de esta carpeta.
"""

import pytest
from playwright.async_api import Page

from config.logger import get_logger
from src.helpers.screenshot_helper import ScreenshotHelper

from . import parametros as P
from .flujos import Evidencia
from .flujos import deposito as DS
from .flujos.transferencia_page import HmTransferelektraPage

logger = get_logger("KRA-1527")


@pytest.mark.etiqueta
@pytest.mark.hardware_agent
@pytest.mark.asyncio
@pytest.mark.parametrize("language,width,height", P.PANTALLA)
async def test_CP02_FichaDeposito(logged_page: Page, vigilancia,
                                  language, width, height):
    flow = HmTransferelektraPage(logged_page)
    evi = Evidencia(ScreenshotHelper(logged_page), P.CP02)

    assert await DS.abrir(flow), "No se pudo abrir la Ficha de Depósitos."
    assert await DS.tomar_foto(flow), "No se pudo tomar la foto."
    assert await DS.escribir_monto(flow, P.DS_MONTO), \
        "No se pudo escribir el monto."
    await evi.shot("ficha_lista", paso=1)

    async with vigilancia(P.CP02, "Impresión de la ficha de depósito") as v:
        enviada = await DS.enviar(flow)
        await logged_page.wait_for_timeout(6_000)
    await evi.shot("ficha_enviada", paso=2)

    # Sin limpieza, y es intencional: la ficha de depósito NO es una
    # transacción del reporte de Transacciones y la aplicación no ofrece
    # cancelarla — se resuelve en Chronos (Cobranza > Recibo Digital). Queda
    # anotado para que nadie lo lea como un olvido.
    v.anotar("La ficha de depósito no es cancelable desde Hermes: se concilia "
             "en Chronos. No queda transacción viva en el reporte.")

    assert enviada, "La ficha no se envió."
    v.exigir_comunicacion()
    v.exigir_sin_token()
