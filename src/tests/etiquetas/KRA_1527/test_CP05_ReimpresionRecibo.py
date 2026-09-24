"""
CP06-ReimpresionRecibo — Reimpresión de recibo desde el historial.

Es una ruta al Hardware Agent **distinta** a la del CP01: allí se imprime el
recibo recién generado dentro del flujo de envío; aquí se le pide a la app que
vuelva a imprimir una transacción del historial, y el diálogo es otro (hay que
elegir tipo de impresión e impresora antes de mandar el trabajo).

    Reportes > Transacciones → Buscar → menú «···» de una fila
      → «Imprimir Recibo» → tipo WINDOWS PRINTER → «Imprimir»

**El error posterior es esperado y NO invalida el caso**: aparece después de
que la petición salió hacia el agente, que es lo único que esta etiqueta
audita. Se guarda como evidencia y se anota en el reporte.

El flujo vive en `flujos/reimpresion.py`, propio de la etiqueta.
"""

import pytest
from playwright.async_api import Page

from config.logger import get_logger
from src.helpers import dialogo_impresion as DIALOGO
from src.helpers.screenshot_helper import ScreenshotHelper

from . import parametros as P
from .flujos import Evidencia
from .flujos import reimpresion as RE
from .flujos import transacciones as T
from .flujos.transferencia_page import HmTransferelektraPage

logger = get_logger("KRA-1527")


@pytest.mark.etiqueta
@pytest.mark.hardware_agent
@pytest.mark.asyncio
@pytest.mark.parametrize("language,width,height", P.PANTALLA)
async def test_CP05_ReimpresionRecibo(logged_page: Page, vigilancia,
                                      language, width, height):
    flow = HmTransferelektraPage(logged_page)
    evi = Evidencia(ScreenshotHelper(logged_page), P.CP05)

    # Navegación reusada de la cancelación: mismo menú, misma tabla, y ya
    # sortea el aviso «¿salir de esta página?».
    await T.ir_a_reportes_transacciones(flow)
    await evi.shot("reporte_transacciones", paso=1)

    async with vigilancia(P.CP05, "Reimpresión de recibo desde el historial") as v:
        reimpreso, detalle = await RE.reimprimir(flow, evi=evi, paso=2)

        # ── Completar la impresión de verdad ────────────────────────────────
        # Pulsar «Print» NO es imprimir. La impresora del entorno es
        # MICROSOFT PRINT TO PDF, así que Windows abre «Guardar impresión
        # como» y el trabajo se queda ahí, esperando un nombre de archivo,
        # fuera del alcance de Playwright. El caso decía PASSED con el
        # diálogo colgado en el escritorio.
        #
        # El PDF en disco es la prueba: si existe, el trabajo salió del
        # agente, pasó por el driver y Windows lo escribió. Se guarda dentro
        # del árbol de evidencia del caso, no en el Escritorio.
        impresa, pdf, motivo = True, None, "no se llegó a imprimir"
        if reimpreso:
            impresa, pdf, motivo = await DIALOGO.completar_impresion(
                P.pdf_impresion(P.CP05))
            detalle = f"{detalle} · Impresión: {motivo}"

        await logged_page.wait_for_timeout(6_000)      # que el agente responda
        v.notas = detalle
    await evi.shot("reimpresion_finalizada", paso=3)

    assert reimpreso, f"No se llegó a disparar la reimpresión. {detalle}"

    # El criterio, literal: si el script no completa el flujo y se queda
    # atorado, es FAIL. Un diálogo modal esperando ES quedarse atorado.
    assert impresa, (
        f"[{P.CP05}] La reimpresión NO se completó: {motivo}.\n"
        f"  Se pulsó 'Print' y el Hardware Agent hizo su parte, pero el "
        f"diálogo «Guardar impresión como» de Windows quedó esperando, así "
        f"que el trabajo no llegó a imprimirse.\n"
        f"  Esto NO es el hallazgo del ticket: es el flujo sin terminar.\n"
        f"  Si el diálogo salió y no se reconoció, añade su título a TITULOS "
        f"en `src/helpers/dialogo_impresion.py`.\n"
        f"  Detalle: {detalle}")
    assert not DIALOGO.hay_dialogo_abierto(), (
        f"[{P.CP05}] Quedó un diálogo de impresión abierto al terminar. El "
        f"caso no puede darse por bueno con una ventana modal esperando: la "
        f"siguiente corrida la heredaría.")

    if pdf:
        logger.info("[%s] Evidencia de la impresión: %s", P.CP05, pdf)
    logger.info("[%s] %s", P.CP05, detalle)
    v.exigir_comunicacion()
    v.exigir_sin_token()
