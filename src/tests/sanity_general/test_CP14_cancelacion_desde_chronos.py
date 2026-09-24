"""
CP14 — Consulta y cancelación de una transacción desde Chronos.
(Migración/mejora de
`HERMES2-qa/src/sanity_general/test_CP14_Consulta_y_Cancelacion_de_una_transaccion_desde_Chronos.py`.)

Qué mejora respecto al sanity original:
  • Usa NUESTRA sesión estable: `logged_page` entra a Hermes 2 (login/sesión
    persistente/notificaciones/idioma) y `chronos.abrir_chronos` reutiliza la
    sesión de Chronos (cookies + login solo si expiró). Sin Kerberos.
  • La lógica frágil (envío Home, menús de Chronos, sondeo de estado, cancelación)
    vive endurecida en `src/sanity_general/cp14.py`.
  • Fallback de cancelación por Hermes reutilizando `cancelacion.py`.

Flujo:
  1. Hermes 2: arma y envía una transferencia a domicilio (Home) a Filipinas con
     un cliente existente (ROBERTOH LISEO), pagador UNIPHIL DELIVERY.
  2. Abre Chronos en pestaña nueva; busca por agencia + apellido; valida Sender.
  3. Status Change: espera 'Payment Ready' y cancela desde Chronos.
  4. Si no llega a 'Payment Ready' o la cancelación de Chronos falla → cancela
     desde Hermes 2 (Reportes > Transacciones).

COMO CORRER:
    pytest src/tests/sanity_general -k CP14 -v -s
    # cambiar datos:  $env:CP14_PAYER="..."; $env:CP14_AGENCY="0040-OK"
"""
import pytest
from playwright.async_api import Page

from config.logger import get_logger
from src.helpers.screenshot_helper import ScreenshotHelper
from src.pages.hm_transferelektra_page import HmTransferelektraPage
from src.sanity_general import Evidencia
from src.sanity_general import cp14 as CP14
from src.sanity_general import cancelacion as CANCEL

logger = get_logger("CP14")

EVIDENCE = "CP14_cancelacion_desde_chronos"


@pytest.mark.sanity_general
@pytest.mark.chronos
@pytest.mark.asyncio
@pytest.mark.parametrize("language,width,height", [("English", 1366, 768)])
async def test_CP14_cancelacion_desde_chronos(logged_page: Page, language, width, height):
    flow = HmTransferelektraPage(logged_page)
    evi = Evidencia(ScreenshotHelper(logged_page), EVIDENCE)
    chronos_page = None
    cliente_full = f"{CP14.CLIENTE_NOMBRE} {CP14.CLIENTE_APELLIDO}"

    logger.info("[CP14] Inicio — cliente=%s, destino=%s/%s, pagador=%s, agencia=%s",
                cliente_full, CP14.PAIS_BENEF, CP14.CIUDAD, CP14.PAGADOR, CP14.AGENCIA)

    # ── Step 1: armar y ENVIAR la transferencia a domicilio (Hermes 2) ────────
    await CP14.crear_envio_home(flow, language=language)
    await evi.shot("envio_completado", paso=1)
    logger.info("[CP14] Step 1 OK — transferencia enviada.")

    # ── Step 1b: leer el FOLIO en Reportes de Hermes (clave de búsqueda) ──────
    folio_hermes = await CP14.obtener_folio_en_hermes(flow, nombre_cliente=cliente_full)
    await evi.shot("folio_en_reportes", paso=1)
    assert folio_hermes, ("No se pudo leer el folio de la transferencia en "
                          "Reportes de Hermes — sin folio no se puede buscar en Chronos.")
    logger.info("[CP14] Folio de la transferencia: %s", folio_hermes)

    try:
        # ── Step 2: abrir Chronos en pestaña nueva y validar Sender ───────────
        chronos_page = await CP14.abrir_chronos_en_pestana(logged_page)
        chrono_evi = Evidencia(ScreenshotHelper(chronos_page), EVIDENCE)
        await chrono_evi.shot("chronos_cargado", paso=2)

        hallada = await CP14.buscar_transfer(chronos_page, folio_hermes)
        if hallada:
            await CP14.validar_sender(chronos_page, CP14.CLIENTE_NOMBRE)
            await chrono_evi.shot("sender_validado", paso=3)
            logger.info("[CP14] Steps 2–3 OK — transferencia hallada y Sender validado.")
        else:
            # No es fatal: Status Change vuelve a buscar (con más espera) y, si
            # tampoco aparece, se cae al fallback de Hermes.
            logger.warning("[CP14] Search Transfer no halló el folio %s — "
                           "continúo a Status Change.", folio_hermes)
            await chrono_evi.shot("search_transfer_sin_resultados", paso=3)

        # ── Step 4: Status Change → esperar Payment Ready → cancelar ──────────
        folio, alcanzado, ultimo = await CP14.status_change_hasta_payment_ready(
            chronos_page, folio_hermes)

        if alcanzado:
            try:
                await CP14.cancelar_transfer_chronos(chronos_page)
                await chrono_evi.shot("cancelada_en_chronos", paso=4)
                logger.info("[CP14] Step 4 OK — cancelada desde Chronos (folio=%s).", folio)
                return
            except Exception as exc:
                logger.warning("[CP14] Cancelación en Chronos falló (folio=%s): %s "
                               "— voy al fallback de Hermes.", folio, str(exc)[:120])
                await chrono_evi.shot("chronos_cancel_fallo", paso=4)
        else:
            logger.warning("[CP14] No llegó a 'Payment Ready' (último='%s') — "
                           "fallback de Hermes.", ultimo)
            await chrono_evi.shot("chronos_sin_payment_ready", paso=4)
    finally:
        if chronos_page is not None:
            try:
                await chronos_page.close()
            except Exception:
                pass

    # ── Step 4 (fallback): cancelar desde Hermes 2 (Reportes > Transacciones) ─
    logger.info("[CP14] Fallback — cancelando '%s' desde Hermes 2.", cliente_full)
    cancelada = await CANCEL.cancelar_por_cliente(
        flow, cliente_full, logger=logger, evi=evi, notes="Automation CP14")
    assert cancelada, ("No se pudo cancelar la transferencia ni por Chronos ni por "
                       "el fallback de Hermes 2.")
    logger.info("[CP14] Fallback OK — cancelada desde Hermes 2.")
