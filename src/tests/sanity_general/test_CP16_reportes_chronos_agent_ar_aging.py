"""
CP16 — Reporte de Chronos: Agent A/R Aging.
(Migración/mejora de `HERMES2-qa/src/sanity_general/test_CP16_reportes_chronos_agent_ar_aging.py`.)

Usa el fixture `chronos_page` (SOLO Chronos — NO abre Hermes), navega a
Reports > A/R Aging, imprime el reporte con la fecha de HOY como Begin Date y
descarga el Excel.

Reutiliza:
  • chronos_page (fixture) → sesión de Chronos, sin login de Hermes
  • chronos_reportes        → navegar el reporte, imprimir por fecha y descargar Excel

COMO CORRER:
    pytest src/tests/sanity_general -k CP16 -v -s
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

logger = get_logger("CP16")

EVIDENCE = "CP16_report_agent_ar_aging"
DESCARGAS = str(settings.REPORTS_DIR / "downloads" / "CP16")


@pytest.mark.sanity_general
@pytest.mark.chronos
@pytest.mark.asyncio
@pytest.mark.parametrize("language,width,height", [("English", 1366, 768)])
async def test_CP16_report_agent_ar_aging(chronos_page: Page, language, width, height):
    os.makedirs(DESCARGAS, exist_ok=True)
    evi = Evidencia(ScreenshotHelper(chronos_page), EVIDENCE)

    # ── Step 1: abrir Reports > A/R Aging ─────────────────────────────────────
    assert await RC.abrir_reporte(chronos_page, RC.AR_AGING), \
        "No se pudo abrir el reporte Agent A/R Aging en Chronos."

    # ── Step 2: imprimir el reporte con Begin Date = hoy ──────────────────────
    begin = datetime.date.today().strftime("%m/%d/%Y")
    logger.info("[CP16] Imprimiendo A/R Aging — Begin Date=%s", begin)
    filas = await RC.imprimir_por_fecha(chronos_page, begin)
    await evi.shot("agent_ar_aging_report_printed", paso=1)
    logger.info("[CP16] Reporte cargado (%d fila(s)).", filas)

    # ── Step 3: descargar el Excel ────────────────────────────────────────────
    destino = os.path.join(DESCARGAS, "agent_ar_aging_report_excel.xlsx")
    ok = await RC.descargar_excel(chronos_page, destino)
    await evi.shot("agent_ar_aging_excel_downloaded", paso=2)
    assert ok and os.path.exists(destino) and os.path.getsize(destino) > 0, \
        "El Excel del reporte Agent A/R Aging no se descargó."
    logger.info("[CP16] Excel descargado: %s — Agent A/R Aging OK.", destino)
