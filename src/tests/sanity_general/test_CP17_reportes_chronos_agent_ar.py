"""
CP17 — Reporte de Chronos: Agent A/R.
(Migración/mejora de `HERMES2-qa/src/sanity_general/test_CP17_reportes_chronos_agent_ar.py`.)

Usa el fixture `chronos_page` (SOLO Chronos — NO abre Hermes). Navega a
Reports > Agent A/R, imprime el reporte con rango Begin=ayer / End=hoy,
descarga el Excel (antes de View) y el PDF (después de View), abre el reporte en
una pestaña nueva y la captura.

Reutiliza:
  • chronos_page (fixture) → sesión de Chronos, sin login de Hermes
  • chronos_reportes        → navegar el reporte + imprimir_agent_ar (Excel/PDF/pestaña)

COMO CORRER:
    pytest src/tests/sanity_general -k CP17 -v -s
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

logger = get_logger("CP17")

EVIDENCE = "CP17_report_agent_ar"
DESCARGAS = str(settings.REPORTS_DIR / "downloads" / "CP17")


@pytest.mark.sanity_general
@pytest.mark.chronos
@pytest.mark.asyncio
@pytest.mark.parametrize("language,width,height", [("English", 1366, 768)])
async def test_CP17_report_agent_ar(chronos_page: Page, language, width, height):
    os.makedirs(DESCARGAS, exist_ok=True)
    evi = Evidencia(ScreenshotHelper(chronos_page), EVIDENCE)

    # ── Step 1: abrir Reports > Agent A/R ─────────────────────────────────────
    assert await RC.abrir_reporte(chronos_page, RC.AGENT_AR), \
        "No se pudo abrir el reporte Agent A/R en Chronos."

    # ── Step 2: imprimir (Begin=ayer, End=hoy) + Excel + PDF + pestaña nueva ──
    hoy = datetime.date.today()
    begin = (hoy - datetime.timedelta(days=1)).strftime("%m/%d/%Y")
    end = hoy.strftime("%m/%d/%Y")
    excel = os.path.join(DESCARGAS, "agent_ar_report_excel.xlsx")
    pdf = os.path.join(DESCARGAS, "agent_ar_report_pdf.pdf")
    logger.info("[CP17] Imprimiendo Agent A/R — %s a %s", begin, end)

    report_page = await RC.imprimir_agent_ar(
        chronos_page, begin, end, excel_path=excel, pdf_path=pdf)

    # ── Step 3: evidencia del reporte (pestaña nueva) y validación ────────────
    if report_page is not None:
        try:
            evi_rep = Evidencia(ScreenshotHelper(report_page), EVIDENCE)
            await evi_rep.shot("agent_ar_report_printed", paso=1)
        except Exception:
            pass
        try:
            await report_page.close()
        except Exception:
            pass
    else:
        await evi.shot("agent_ar_sin_pestana", paso=1)

    assert os.path.exists(excel) and os.path.getsize(excel) > 0, \
        "El Excel del reporte Agent A/R no se descargó."
    assert os.path.exists(pdf) and os.path.getsize(pdf) > 0, \
        "El PDF del reporte Agent A/R no se descargó."
    logger.info("[CP17] Agent A/R report OK — Excel y PDF descargados.")
