"""
TEST — Hm Agentbalance
Generado automáticamente por json_to_pom.py — 2026-08-14

Flujo grabado:
  Step 1 — transfers
  Step 2 — app

PREREQUISITOS:
  - Variables: HERMES2_USER, HERMES2_PSWD (o defaults en config/settings.py)
  - Sesion: fixture logged_page — login automatico solo si expiro (session_state/)

EJECUTAR:
    pytest src/tests/test_hm_agentbalance.py -v -s
"""

import os
import pytest
from playwright.async_api import Page

from config.logger import get_logger
from config.settings import PORTAL_USER, PORTAL_PASS
from src.pages.hm_agentbalance_page import HmAgentbalancePage
from src.helpers.screenshot_helper import ScreenshotHelper
from src.helpers.datos import Datos

logger = get_logger("test_hm_agentbalance")


# ── Constantes del caso de prueba ────────────────────────────────────────────

EVIDENCE_FOLDER = "HM-AgentBalance"


@pytest.mark.sanity_general
@pytest.mark.parametrize("language,width,height", [
    ("English", 1366, 768)
])
@pytest.mark.asyncio
async def test_hm_agentbalance(
    logged_page: Page,
    language: str,
    width: int,
    height: int,
):
    """
    Hm Agentbalance

    Step 1 — transfers
    Step 2 — app
    """
    # ── Setup ────────────────────────────────────────────────────────────
    flow       = HmAgentbalancePage(logged_page)
    screenshot = ScreenshotHelper(logged_page)
    # Datos: overrides del lenguaje natural (FLOW_OVERRIDES) + Faker
    datos      = Datos()

    # ── Carpeta de evidencias ────────────────────────────────────────────
    # Todos los reportes bajo reports/ (evidencia por flujo)
    evidence_dir = os.path.join(
        os.path.dirname(__file__), "..", "..", "reports", "evidence", EVIDENCE_FOLDER
    )
    os.makedirs(evidence_dir, exist_ok=True)

    def evidence(filename: str) -> str:
        return os.path.join(evidence_dir, filename)

    # ── Step 1: TRANSFERS ─────────────────────────────────────────
    logger.info("Step 1 — TRANSFERS")

    await flow.navigate()               # Sesión ya iniciada (logged_page) — va directo al flujo
    await screenshot.screenshot_only(screenshot_path=evidence("step00_inicio.png"))
    await flow.click_reports()  # Reports
    await flow.wait_for_no_blocking_overlays()  # BasePage: espera loaders/overlays
    await screenshot.screenshot_only(screenshot_path=evidence("t01_click_reports.png"))
    await flow.click_agent_balance()  # Agent Balance
    await flow.wait_for_no_blocking_overlays()  # BasePage: espera loaders/overlays
    await screenshot.screenshot_only(screenshot_path=evidence("t02_click_agent_balance.png"))
    await flow.click_yes_leave()  # YES, Leave
    await flow.wait_for_no_blocking_overlays()  # BasePage: espera cierre de modal
    await screenshot.screenshot_only(screenshot_path=evidence("t03_click_yes_leave.png"))

    await screenshot.screenshot_only(screenshot_path=evidence("step01_transfers.png"))
    logger.info("Step 1 completado.")

    # ── Step 2: APP ───────────────────────────────────────────────
    logger.info("Step 2 — APP")

    await flow.click_continuous_balance()  # CONTINUOUS BALANCE
    await flow.wait_for_no_blocking_overlays()  # BasePage: espera loaders/overlays
    await screenshot.screenshot_only(screenshot_path=evidence("t04_click_continuous_balance.png"))
    await flow.click_search()  # Search
    await screenshot.screenshot_only(screenshot_path=evidence("t05_click_search.png"))
    await flow.click_agent_s_balance()  # Agent’s Balance
    await screenshot.screenshot_only(screenshot_path=evidence("t06_click_agent_s_balance.png"))
    await flow.click_options()  # Options
    await screenshot.screenshot_only(screenshot_path=evidence("t07_click_options.png"))
    await flow.click_view()  # View
    await screenshot.screenshot_only(screenshot_path=evidence("t08_click_view.png"))
    await flow.scroll_628px()  # scroll
    await flow.click_small_button_icon_component_ic()  # small-button-icon-component-icon-svg
    await screenshot.screenshot_only(screenshot_path=evidence("t09_click_small_button_icon_compon.png"))
    await flow.scroll_200px()  # scroll
    await flow.click_go_back()  # Go Back
    await screenshot.screenshot_only(screenshot_path=evidence("t10_click_go_back.png"))
    await flow.click_transfers()  # Transfers
    await flow.wait_for_no_blocking_overlays()  # BasePage: espera loaders/overlays
    await screenshot.screenshot_only(screenshot_path=evidence("t11_click_transfers.png"))

    await screenshot.screenshot_with_highlight(
        screenshot_path=evidence("step02_app.png"),
        search_text="Search",
    )
    logger.info("Step 2 completado.")

    # -- Fin ---------------------------------------------------------------
    logger.info("test_hm_agentbalance finalizado exitosamente.")