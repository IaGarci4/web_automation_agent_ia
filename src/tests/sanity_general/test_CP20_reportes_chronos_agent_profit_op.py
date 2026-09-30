"""
CP20 — Reporte de Chronos: Agent Profit O.P.
(Migración/mejora de `HERMES2-qa/src/sanity_general/test_CP20_reportes_chronos_agent_profit_op.py`.)

Usa el fixture `chronos_page` (SOLO Chronos — NO abre Hermes). Navega a
Reports > Agent Profit O.P., imprime con rango Begin=hoy-30 / End=hoy (botón
View) y descarga el Excel. 0 filas es válido (fines de semana).

COMO CORRER:
    pytest src/tests/sanity_general -k CP20 -v -s
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

logger = get_logger("CP20")

EVIDENCE = "CP20_report_agent_profit_op"
DESCARGAS = str(settings.REPORTS_DIR / "downloads" / "CP20")


@pytest.mark.sanity_general
@pytest.mark.chronos
@pytest.mark.asyncio
@pytest.mark.parametrize("language,width,height", [("English", 1366, 768)])
async def test_CP20_report_agent_profit_op(chronos_page: Page, language, width, height):
    os.makedirs(DESCARGAS, exist_ok=True)
    evi = Evidencia(ScreenshotHelper(chronos_page), EVIDENCE)

    assert await RC.abrir_reporte(chronos_page, RC.AGENT_PROFIT_OP), \
        "No se pudo abrir el reporte Agent Profit O.P. en Chronos."

    hoy = datetime.date.today()
    begin = (hoy - datetime.timedelta(days=30)).strftime("%m/%d/%Y")
    end = hoy.strftime("%m/%d/%Y")
    destino = os.path.join(DESCARGAS, "agent_profit_op_report_excel.xlsx")
    logger.info("[CP20] Imprimiendo Agent Profit O.P. — %s a %s", begin, end)

    filas = await RC.imprimir_por_rango_view(chronos_page, begin, end, excel_path=destino)
    await evi.shot("agent_profit_op_report_printed", paso=1)

    assert os.path.exists(destino) and os.path.getsize(destino) > 0, \
        "El Excel del reporte Agent Profit O.P. no se descargó."
    logger.info("[CP20] Agent Profit O.P. OK — %d fila(s), Excel: %s", filas, destino)
