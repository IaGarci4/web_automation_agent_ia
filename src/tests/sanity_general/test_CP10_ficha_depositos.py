"""
CP10 — Ficha de Depósitos (Deposit Slip).
(Rescate de `HERMES2-qa/src/sanity_general/test_CP10_Ficha_de_Depositos.py`.)

Son DOS pruebas, como en el sanity original:

  1. HAPPY PATH
     Ficha de Depósitos → foto → monto → Send → éxito → en Chronos, borrar el
     recibo digital que se acaba de generar.

  2. CASO ALTERNATIVO (validaciones de la pantalla)
     foto → monto → zoom in ×4 (300%) → zoom out ×4 (100%) → limpiar (el botón
     de envío debe quedar DESHABILITADO) → borrar la foto → retomarla → monto →
     Send → éxito → borrar el recibo en Chronos.

Cada prueba LIMPIA lo que crea: el recibo se elimina en Chronos para no dejar
basura en el ambiente. Si el borrado falla, la prueba falla — un sanity que
ensucia el ambiente no sirve.

CÁMARA: la pantalla toma una foto real. El conftest levanta Chromium con una
webcam simulada (flags de media stream + `navigator.mediaDevices` falseado), así
que funciona en máquinas sin cámara y en headless.

COMO CORRER:
    pytest src/tests/sanity_general -k CP10 -v -s
    pytest src/tests/sanity_general -k "CP10 and happy" -v -s
    pytest src/tests/sanity_general -k "CP10 and alternativo" -v -s
"""
import os
import pytest
from playwright.async_api import Page

from config import settings
from config.logger import get_logger
from src.pages.hm_transferelektra_page import HmTransferelektraPage
from src.helpers.screenshot_helper import ScreenshotHelper
from src.sanity_general import chronos as CR
from src.sanity_general import chronos_recibo_digital as RD
from src.sanity_general import deposit_slip as DS
from src.sanity_general import Evidencia

logger = get_logger("CP10")

MONTO = os.getenv("CP10_MONTO", "333")
AGENCY_CODE = os.getenv("CP10_AGENCY", settings.AGENCY_CODE)
# El borrado del recibo en Chronos puede apagarse para depurar solo Hermes.
LIMPIAR_CHRONOS = os.getenv("CP10_CHRONOS", "1").strip().lower() in (
    "1", "true", "si", "yes")

EVIDENCE_HAPPY = "CP10_ficha_depositos_happy_path"
EVIDENCE_ALT = "CP10_ficha_depositos_caso_alternativo"


async def _borrar_recibo_en_chronos(logged_page, evi, etiqueta: str) -> bool:
    """Abre Chronos en otra pestaña y elimina el recibo digital recién creado."""
    if not LIMPIAR_CHRONOS:
        logger.info("[CP10] CP10_CHRONOS=0 — no se limpia el recibo.")
        return True
    chronos_page = await logged_page.context.new_page()
    try:
        dentro = await CR.abrir_chronos(chronos_page)
        if not dentro:
            logger.warning("[CP10] No se pudo entrar a Chronos.")
            return False
        evi_ch = Evidencia(ScreenshotHelper(chronos_page), etiqueta, start=evi.n)
        if not await RD.ir_a_recibo_digital(chronos_page):
            return False
        await evi_ch.shot("chronos_recibo_digital")
        if not await RD.seleccionar_registro(chronos_page, AGENCY_CODE):
            return False
        borrado = await RD.eliminar(chronos_page)
        await evi_ch.shot("recibo_eliminado")
        evi.n = evi_ch.n
        return borrado
    finally:
        try:
            await chronos_page.close()
        except Exception:
            pass
        try:
            await logged_page.bring_to_front()
        except Exception as e:
            logger.warning("[CP10] No se pudo volver a Hermes: %s", str(e)[:80])


@pytest.mark.sanity_general
@pytest.mark.chronos
@pytest.mark.asyncio
@pytest.mark.parametrize("language,width,height", [("English", 1366, 768)])
async def test_CP10_ficha_depositos_happy_path(logged_page: Page, language,
                                               width, height):
    flow = HmTransferelektraPage(logged_page)
    evi = Evidencia(ScreenshotHelper(logged_page), EVIDENCE_HAPPY)
    logger.info("[CP10] Happy path — monto=%s | agencia=%s", MONTO, AGENCY_CODE)

    assert await DS.abrir(flow), "No se pudo abrir la Ficha de Depósitos."
    await evi.shot("ficha_abierta", paso=1)

    assert await DS.tomar_foto(flow), "No se pudo tomar/guardar la foto."
    assert await DS.escribir_monto(flow, MONTO), "No se pudo escribir el monto."
    await evi.shot("foto_y_monto", paso=2)

    assert await DS.enviar(flow), "La ficha no se envió (sin aviso de éxito)."
    await evi.shot("ficha_enviada", paso=3)

    assert await _borrar_recibo_en_chronos(logged_page, evi, EVIDENCE_HAPPY), \
        "No se pudo eliminar el recibo digital en Chronos."
    logger.info("[CP10] Happy path OK.")


@pytest.mark.sanity_general
@pytest.mark.chronos
@pytest.mark.asyncio
@pytest.mark.parametrize("language,width,height", [("English", 1366, 768)])
async def test_CP10_ficha_depositos_caso_alternativo(logged_page: Page, language,
                                                     width, height):
    flow = HmTransferelektraPage(logged_page)
    evi = Evidencia(ScreenshotHelper(logged_page), EVIDENCE_ALT)
    logger.info("[CP10] Caso alternativo — validaciones de la pantalla.")

    assert await DS.abrir(flow), "No se pudo abrir la Ficha de Depósitos."
    assert await DS.tomar_foto(flow), "No se pudo tomar/guardar la foto."
    await evi.shot("foto_guardada", paso=1)
    assert await DS.escribir_monto(flow, MONTO), "No se pudo escribir el monto."

    # Zoom: 4 clics acercan al 300%, 4 clics alejan de vuelta al 100%.
    acercado = await DS.zoom(flow, veces=4, acercar=True)
    await evi.shot("zoom_300", paso=2)
    assert "300" in acercado, f"El zoom no llegó a 300% (quedó en '{acercado}')."

    alejado = await DS.zoom(flow, veces=4, acercar=False)
    await evi.shot("zoom_100", paso=3)
    assert "100" in alejado, f"El zoom no volvió a 100% (quedó en '{alejado}')."

    # Limpiar → el envío debe DESHABILITARSE (es la validación del caso).
    assert await DS.limpiar_formulario(flow), "No se pudo limpiar el formulario."
    assert await DS.envio_deshabilitado(flow), \
        "Tras limpiar, el botón de envío seguía habilitado."
    await evi.shot("envio_deshabilitado", paso=4)

    assert await DS.borrar_foto(flow), "No se pudo borrar la foto."
    await evi.shot("camara_sin_foto", paso=5)

    assert await DS.retomar_foto(flow), "No se pudo retomar la foto."
    assert await DS.escribir_monto(flow, MONTO), "No se pudo reescribir el monto."
    assert await DS.enviar(flow), "La ficha no se envió (sin aviso de éxito)."
    await evi.shot("ficha_enviada", paso=6)

    assert await _borrar_recibo_en_chronos(logged_page, evi, EVIDENCE_ALT), \
        "No se pudo eliminar el recibo digital en Chronos."
    logger.info("[CP10] Caso alternativo OK.")
