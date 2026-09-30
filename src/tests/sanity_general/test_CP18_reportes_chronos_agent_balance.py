"""
CP18 — Reporte de Chronos: Agent Balance.
(Migración/mejora de `HERMES2-qa/src/sanity_general/test_CP18_reportes_chronos_agent_balance.py`.)

Usa el fixture `chronos_page` (SOLO Chronos — NO abre Hermes). Navega a
Reports > Agent Balance, elige el agente, descarga Excel y PDF (fechas por
defecto) y abre el reporte en una pestaña nueva.

COMO CORRER:
    pytest src/tests/sanity_general -k CP18 -v -s
"""
import os

import pytest
from playwright.async_api import Page

from config import settings
from config.logger import get_logger
from src.helpers.screenshot_helper import ScreenshotHelper
from src.sanity_general import Evidencia
from src.sanity_general import chronos_reportes as RC

logger = get_logger("CP18")

AGENT_CODE = os.getenv("CP18_AGENCY", settings.AGENCY_CODE)   # 0040-OK / 0020-TX
EVIDENCE = "CP18_report_agent_balance"
DESCARGAS = str(settings.REPORTS_DIR / "downloads" / "CP18")


@pytest.mark.sanity_general
@pytest.mark.chronos
@pytest.mark.asyncio
@pytest.mark.parametrize("language,width,height", [("English", 1366, 768)])
async def test_CP18_report_agent_balance(chronos_page: Page, language, width, height):
    os.makedirs(DESCARGAS, exist_ok=True)
    evi = Evidencia(ScreenshotHelper(chronos_page), EVIDENCE)

    # ── Step 1: abrir Reports > Agent Balance ─────────────────────────────────
    assert await RC.abrir_reporte(chronos_page, RC.AGENT_BALANCE), \
        "No se pudo abrir el reporte Agent Balance en Chronos."

    # ── Step 2: elegir agente + Excel + PDF + pestaña nueva ───────────────────
    excel = os.path.join(DESCARGAS, "agent_balance_report_excel.xlsx")
    pdf = os.path.join(DESCARGAS, "agent_balance_report_pdf.pdf")
    logger.info("[CP18] Imprimiendo Agent Balance — agente=%s", AGENT_CODE)
    report_page = await RC.imprimir_agent_balance(
        chronos_page, AGENT_CODE, excel_path=excel, pdf_path=pdf)

    # ── Step 3: evidencia del reporte (pestaña nueva) y validación ────────────
    if report_page is not None:
        try:
            await Evidencia(ScreenshotHelper(report_page), EVIDENCE).shot(
                "agent_balance_report_printed", paso=1)
        except Exception:
            pass
        try:
            await report_page.close()
        except Exception:
            pass
    else:
        await evi.shot("agent_balance_sin_pestana", paso=1)

    assert os.path.exists(excel) and os.path.getsize(excel) > 0, \
        "El Excel del reporte Agent Balance no se descargó."
    assert os.path.exists(pdf) and os.path.getsize(pdf) > 0, \
        "El PDF del reporte Agent Balance no se descargó."
    logger.info("[CP18] Agent Balance report OK — Excel y PDF descargados.")
