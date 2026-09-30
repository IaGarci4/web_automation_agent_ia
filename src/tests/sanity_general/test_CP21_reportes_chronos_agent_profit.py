"""
CP21 — Reporte de Chronos: Agent Profit.
(Migración/mejora de `HERMES2-qa/src/sanity_general/test_CP21_reportes_chronos_agent_profit.py`.)

Usa el fixture `chronos_page` (SOLO Chronos — NO abre Hermes). Navega a
Reports > Agent Profit, imprime con rango Begin=hoy-3 / End=hoy (botón View) y
descarga el Excel. 0 filas es válido (fines de semana sin transacciones).

COMO CORRER:
    pytest src/tests/sanity_general -k CP21 -v -s
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

logger = get_logger("CP21")

EVIDENCE = "CP21_report_agent_profit"
DESCARGAS = str(settings.REPORTS_DIR / "downloads" / "CP21")


@pytest.mark.sanity_general
@pytest.mark.chronos
@pytest.mark.asyncio
@pytest.mark.parametrize("language,width,height", [("English", 1366, 768)])
async def test_CP21_report_agent_profit(chronos_page: Page, language, width, height):
    os.makedirs(DESCARGAS, exist_ok=True)
    evi = Evidencia(ScreenshotHelper(chronos_page), EVIDENCE)

    assert await RC.abrir_reporte(chronos_page, RC.AGENT_PROFIT), \
        "No se pudo abrir el reporte Agent Profit en Chronos."

    hoy = datetime.date.today()
    begin = (hoy - datetime.timedelta(days=3)).strftime("%m/%d/%Y")
    end = hoy.strftime("%m/%d/%Y")
    destino = os.path.join(DESCARGAS, "agent_profit_report_excel.xlsx")
    logger.info("[CP21] Imprimiendo Agent Profit — %s a %s", begin, end)

    filas = await RC.imprimir_por_rango_view(chronos_page, begin, end, excel_path=destino)
    await evi.shot("agent_profit_report_printed", paso=1)

    assert os.path.exists(destino) and os.path.getsize(destino) > 0, \
        "El Excel del reporte Agent Profit no se descargó."
    logger.info("[CP21] Agent Profit OK — %d fila(s), Excel: %s", filas, destino)
