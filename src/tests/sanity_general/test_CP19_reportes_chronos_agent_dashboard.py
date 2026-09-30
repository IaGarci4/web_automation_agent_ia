"""
CP19 — Reporte de Chronos: Agent Dashboard.
(Migración/mejora de `HERMES2-qa/src/sanity_general/test_CP19_reportes_chronos_agent_dashboard.py`.)

Usa el fixture `chronos_page` (SOLO Chronos — NO abre Hermes). Navega a
Reports > Dashboard, imprime con Begin Date = hoy-30 días (campo propio del
dashboard) y descarga el Excel.

COMO CORRER:
    pytest src/tests/sanity_general -k CP19 -v -s
"""
import datetime
import os

import pytest
from playwright.async_api import Page

from config import settings
from config.logger import get_logger
from src.helpers.screenshot_helper import ScreenshotHelper
from src.sanity_general import Evidencia
from src.sanity_general import chronos_reportes as RC

logger = get_logger("CP19")

EVIDENCE = "CP19_report_dashboard"
DESCARGAS = str(settings.REPORTS_DIR / "downloads" / "CP19")


@pytest.mark.sanity_general
@pytest.mark.chronos
@pytest.mark.asyncio
@pytest.mark.parametrize("language,width,height", [("English", 1366, 768)])
async def test_CP19_report_dashboard(chronos_page: Page, language, width, height):
    os.makedirs(DESCARGAS, exist_ok=True)
    evi = Evidencia(ScreenshotHelper(chronos_page), EVIDENCE)

    # ── Step 1: abrir Reports > Dashboard ─────────────────────────────────────
    assert await RC.abrir_reporte(chronos_page, RC.DASHBOARD), \
        "No se pudo abrir el reporte Agent Dashboard en Chronos."

    # ── Step 2: imprimir con Begin Date = hoy - 30 días ───────────────────────
    begin = (datetime.date.today() - datetime.timedelta(days=30)).strftime("%m/%d/%Y")
    logger.info("[CP19] Imprimiendo Dashboard — Begin Date=%s", begin)
    filas = await RC.imprimir_por_fecha(
        chronos_page, begin,
        input_begin=RC.DASHBOARD_INPUT_BEGIN, tabla=RC.DASHBOARD_TABLA)
    await evi.shot("agent_dashboard_report_printed", paso=1)
    logger.info("[CP19] Reporte cargado (%d fila(s)).", filas)

    # ── Step 3: descargar el Excel ────────────────────────────────────────────
    destino = os.path.join(DESCARGAS, "agent_dashboard_report_excel.xlsx")
    ok = await RC.descargar_excel(chronos_page, destino)
    await evi.shot("agent_dashboard_excel_downloaded", paso=2)
    assert ok and os.path.exists(destino) and os.path.getsize(destino) > 0, \
        "El Excel del reporte Agent Dashboard no se descargó."
    logger.info("[CP19] Excel descargado: %s — Agent Dashboard OK.", destino)
