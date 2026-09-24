"""
Smoke test del modo AGENTE (CDP / WebView2).

Verifica que la automatización puede engancharse por CDP al WebView2 del
Hermes2Agent (ya autenticado por Kerberos) y operar la web app REUTILIZANDO el
Page Object existente, SIN cambiar selectores.

Requisitos antes de correr:
  1. Lanzar el agente con el puerto CDP abierto:  Ejecutar_Hermes2Agent.bat
  2. Iniciar sesión y entrar a la app (Envío de Dinero) en el agente.
  3. Confirmar el puerto:  python tools/agent_cdp_check.py

Ejecutar:
    $env:HERMES_AGENT_CDP="1"
    pytest src/tests/test_agent_cdp_smoke.py -v -s

La fixture `logged_page` detecta HERMES_AGENT_CDP y se engancha por CDP (omite el
login, reutiliza la página del WebView2). OJO: la captura de pantalla del agente
está bloqueada (sale negra) → este smoke valida por DOM, no por imagen.
"""

import pytest

from config import settings
from config.logger import get_logger
from src.pages.hm_transferelektra_page import HmTransferelektraPage

logger = get_logger("agent-cdp-smoke")

CELL_TESTID = "transfer-customer-cellphone-0-cellphone-input"


@pytest.mark.agent_cdp
@pytest.mark.asyncio
async def test_agent_cdp_smoke(logged_page):
    if not settings.AGENT_CDP:
        pytest.skip("Modo agente CDP desactivado. Actívalo con HERMES_AGENT_CDP=1 "
                    "(y lanza el agente con Ejecutar_Hermes2Agent.bat).")

    page = logged_page
    flow = HmTransferelektraPage(page)

    # Confirmar que estamos en la web app real dentro del WebView2.
    logger.info("[Smoke-CDP] URL enganchada: %s", page.url)
    assert ("test-hermes" in (page.url or "")) or ("/transfers" in (page.url or "")), \
        f"La página enganchada no es la web app: {page.url}"

    # POM SIN CAMBIOS: asegurar el formulario y operar un campo conocido.
    try:
        await flow.navigate()
    except Exception:
        pass
    inp = page.get_by_test_id(CELL_TESTID).first
    await inp.wait_for(state="visible", timeout=15_000)

    await flow.fill_transfer_customer_cellphone_0_cellphone_input("2105551234")
    valor = (await inp.input_value()).strip()
    logger.info("[Smoke-CDP] Campo teléfono leído de vuelta: '%s'", valor)

    assert valor.endswith("1234"), (
        f"El POM no pudo escribir/leer dentro del WebView2 (got '{valor}'). "
        f"Revisa el enganche CDP.")
    logger.info("[Smoke-CDP] ✓ El POM interactuó correctamente dentro del "
                "WebView2 del agente, sin cambiar selectores.")
