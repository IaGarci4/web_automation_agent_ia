"""
HmAgentbalancePage — Page Object para el flujo: hm_agentbalance
Generado automáticamente por json_to_pom.py — 2026-08-14

PATRON: Los métodos aceptan los valores como parámetros.
        Las constantes se definen en el test, no aquí.
"""

from playwright.async_api import expect
from config.logger import get_logger
from config.settings import TIMEOUT_ELEMENT
from src.locators.hm_agentbalance_locators import HmAgentbalanceLocators
from src.pages.base_page import BasePage

logger = get_logger("hm_agentbalance_page")


class HmAgentbalancePage(BasePage):
    """Page Object para el flujo hm_agentbalance."""

    # ── NAVEGACIÓN (sesión ya iniciada por logged_page) ─────────────────

    async def navigate(self) -> None:
        """Va a la URL inicial del flujo — sin recargar si ya está ahí."""
        target = "https://test-hermes.maxilabs.net/transfers"
        if self.page.url.split("?")[0].rstrip("/") == target.rstrip("/"):
            logger.info("navigate: ya en la URL inicial — sin recargar")
            await self.wait_for_no_blocking_overlays()
            return
        logger.info(f"navigate: {target}")
        await self.goto(target)
        # Una recarga completa puede reabrir el modal de notificaciones
        await self.handle_notifications_modal()
        await self.wait_for_no_blocking_overlays()

    # ── TRANSFERS ───────────────────────────────────────────

    async def click_reports(self) -> None:
        """Click en: Reports"""
        logger.info("click_reports...")
        await self.smart_click(testid=HmAgentbalanceLocators.REPORTS_NAVBAR_ITEM, texto="Reports", fallbacks=['[aria-label="dropdown"]'])

    async def click_agent_balance(self) -> None:
        """Click en: Agent Balance"""
        logger.info("click_agent_balance...")
        item = self.page.get_by_test_id(HmAgentbalanceLocators.REPORTS_0_NAVBAR_DROPDOWN_ITEM)
        if not await item.is_visible():
            # Abrir el dropdown del navbar solo si el item no está visible
            await self.smart_click(testid="reports-navbar-item")
        await self.smart_click(testid=HmAgentbalanceLocators.REPORTS_0_NAVBAR_DROPDOWN_ITEM, texto="Agent Balance", fallbacks=['[aria-label="dropdown item"]'])

    async def click_yes_leave(self) -> None:
        """Click en: YES, Leave"""
        logger.info("click_yes_leave...")
        await self.smart_click(testid=HmAgentbalanceLocators.MODAL_CONFIRMATION_DENY_BUTTON, texto="YES, Leave")

    # ── APP ─────────────────────────────────────────────────

    async def click_continuous_balance(self) -> None:
        """Selecciona la opción 'CONTINUOUS BALANCE' del dropdown."""
        logger.info("click_continuous_balance...")
        await self.select_option_by_text(
            self.format_testid_selector(HmAgentbalanceLocators.REPORT_TYPE_DROPDOWN_INPUT_click),
            "li[role='option'], .p-dropdown-item",
            "CONTINUOUS BALANCE",
        )

    async def click_search(self) -> None:
        """Click en: Search"""
        logger.info("click_search...")
        await self.smart_click(testid=HmAgentbalanceLocators.TEST_ID_BUTTON, texto="Search")

    async def click_agent_s_balance(self) -> None:
        """Click en: Agent’s Balance"""
        logger.info("click_agent_s_balance...")
        await self.smart_click(testid=HmAgentbalanceLocators.TEST_ID_H3_HEADING, texto="Agent’s Balance")

    async def click_options(self) -> None:
        """Click en: Options"""
        logger.info("click_options...")
        await self.smart_click(testid=HmAgentbalanceLocators.REPORT_OPTIONS_BUTTON, texto="Options")

    async def click_view(self) -> None:
        """Click en: View"""
        logger.info("click_view...")
        await self.smart_click(testid=HmAgentbalanceLocators.REPORT_OPTIONS_0_ICON_SVG, texto="View")

    async def scroll_628px(self) -> None:
        """Scroll para visualizar contenido (rueda o barra)."""
        await self.scroll_to(628, 0, selector="div")

    async def click_small_button_icon_component_ic(self) -> None:
        """Click en: small-button-icon-component-icon-svg"""
        logger.info("click_small_button_icon_component_ic...")
        await self.smart_click(testid=HmAgentbalanceLocators.SMALL_BUTTON_ICON_COMPONENT_ICON_SVG)

    async def scroll_200px(self) -> None:
        """Scroll para visualizar contenido (rueda o barra)."""
        await self.scroll_to(200, 0, selector="div")

    async def click_go_back(self) -> None:
        """Click en: Go Back"""
        logger.info("click_go_back...")
        await self.smart_click(testid=HmAgentbalanceLocators.TEST_ID_PARAGRAPH_MEDIUM_BOLD, texto="Go Back")

    async def click_transfers(self) -> None:
        """Click en: Transfers"""
        logger.info("click_transfers...")
        await self.smart_click(css=HmAgentbalanceLocators.DROPDOWN, texto="Transfers")
