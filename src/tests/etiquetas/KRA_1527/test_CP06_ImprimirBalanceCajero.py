"""
CP06-ImprimirBalanceCajero — COBERTURA ADICIONAL (fuera de la tabla de QMetry).

Reportes > Balance por Cajero → Buscar → Imprimir. Es otra ruta de impresión al
agente, distinta a la del recibo: se imprime un reporte, no un comprobante de
transacción. Se incluye porque cubrir solo una ruta dejaría el fix a medio
validar.

Reutiliza el módulo del CP12 del sanity, copiado en `flujos/balance.py`.
"""

import pytest
from playwright.async_api import Page

from config.logger import get_logger
from src.helpers import dialogo_impresion as DIALOGO
from src.helpers.screenshot_helper import ScreenshotHelper

from . import parametros as P
from .flujos import Evidencia
from .flujos import balance as B
from .flujos import modales as MOD
from .flujos import reimpresion as RE

logger = get_logger("KRA-1527")


@pytest.mark.etiqueta
@pytest.mark.hardware_agent
@pytest.mark.asyncio
@pytest.mark.parametrize("language,width,height", P.PANTALLA)
async def test_CP06_ImprimirBalanceCajero(logged_page: Page, vigilancia,
                                          language, width, height):
    evi = Evidencia(ScreenshotHelper(logged_page), P.CP06)

    # Los tres pasos previos se comprueban de uno en uno. Antes solo se
    # exigía el primero y el resultado de la búsqueda se tiraba: con el aviso
    # «¿salir de esta página?» de por medio la app se quedaba en /transfers,
    # el caso seguía adelante a ciegas, y el fallo salía 78 s después
    # culpando al botón de imprimir — tres pasos más allá del problema real.
    assert await B.abrir_balance_por_cajero(logged_page), (
        "No se llegó a Balance por Cajero. Si la app se quedó en /transfers, "
        "el culpable es el aviso «¿salir de esta página?»: su overlay se come "
        "los clics. Revisa Step01.")
    assert await B.buscar_por_cajero(logged_page), (
        "La pantalla abrió pero el botón Buscar no respondió: sin resultados "
        "no hay nada que imprimir.")
    await evi.shot("balance_buscado", paso=1)

    async with vigilancia(P.CP06, "Imprimir el reporte de balance por cajero") as v:
        # ── 1. El botón Print de la barra abre un MODAL, no imprime ─────────
        # «Print Report By Cashier», con Print Type = TICKET, impresora
        # MAXI TICKET PRINTER y el botón Print DESHABILITADO. El caso pulsaba
        # el de la barra y se quedaba esperando el diálogo de Windows, que no
        # podía llegar: el trabajo ni siquiera había salido de Hermes.
        boton = logged_page.get_by_test_id(B.CAJERO_BTN_IMPRIMIR).first
        try:
            await boton.click(force=True, timeout=15_000)
            logger.info("[%s] Botón Print de la barra pulsado.", P.CP06)
            pulsado = True
        except Exception as e:
            logger.warning("[%s] No se pudo pulsar Print: %s", P.CP06,
                           str(e)[:100])
            pulsado = False

        # ── 2. El modal: TICKET → WINDOWS PRINTER, que es el tipo que enruta
        #       el trabajo por el agente local. Es el MISMO modal del CP05, así
        #       que se reutiliza su módulo en vez de duplicar la lógica.
        modal, configurado, enviado = None, False, False
        if pulsado:
            modal = await RE.esperar_modal_impresion(logged_page)
            if modal is None:
                logger.warning("[%s] El modal de impresión no apareció.", P.CP06)
            else:
                await evi.shot("modal_impresion", paso=2)
                configurado = await RE.configurar_impresion(logged_page, modal)
                # `pulsar_imprimir` espera a que el botón esté HABILITADO: con
                # TICKET sigue gris, y un clic sobre un botón deshabilitado no
                # hace nada — el fallo aparecería mucho después.
                enviado = await RE.pulsar_imprimir(logged_page, modal)

        await MOD.atender_bloqueantes(logged_page, logger)

        # ── 3. Y después viene el diálogo de WINDOWS ────────────────────────
        # La impresora es MICROSOFT PRINT TO PDF y se queda esperando un
        # nombre de archivo, fuera del alcance de Playwright. El PDF que sale
        # va al árbol de evidencia del caso y es la prueba de que la impresión
        # terminó — pulsar un botón no lo es.
        impresa, pdf, motivo = True, None, "no se llegó a imprimir"
        if enviado:
            impresa, pdf, motivo = await DIALOGO.completar_impresion(
                P.pdf_impresion(P.CP06))
            v.notas = f"Impresión: {motivo}"

        await logged_page.wait_for_timeout(6_000)      # que el agente responda
    await evi.shot("impresion_disparada", paso=3)

    assert pulsado, "No se pudo pulsar el botón Print de la barra."
    assert modal is not None, (
        f"[{P.CP06}] El botón Print no abrió el modal «Print Report By "
        f"Cashier». Sin ese modal no hay forma de elegir WINDOWS PRINTER, y "
        f"sin WINDOWS PRINTER el trabajo no pasa por el Hardware Agent.")
    assert configurado, (
        f"[{P.CP06}] No se pudo poner el tipo de impresión en "
        f"'{RE.TIPO_IMPRESION}'. Con TICKET la impresora es MAXI TICKET "
        f"PRINTER y el botón Print del modal se queda deshabilitado.")
    assert enviado, (
        f"[{P.CP06}] El botón Print del modal nunca se habilitó o no respondió.")
    assert impresa, (
        f"[{P.CP06}] La impresión NO se completó: {motivo}. El diálogo de "
        f"Windows quedó esperando, así que el trabajo no llegó a imprimirse.")
    assert not DIALOGO.hay_dialogo_abierto(), (
        f"[{P.CP06}] Quedó un diálogo de impresión abierto al terminar: la "
        f"siguiente corrida lo heredaría.")
    if pdf:
        logger.info("[%s] Evidencia de la impresión: %s", P.CP06, pdf)

    v.exigir_comunicacion()
    v.exigir_sin_token()
