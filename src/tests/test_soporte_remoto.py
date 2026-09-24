"""
Soporte Remoto — consulta el token en BD y lo aplica en el Hermes2Agent.

Flujo (dado por el equipo):
  1. Con la app abierta (se ve oscura pero responde) se cierran notificaciones y
     se fija idioma → lo hace la fixture `logged_page`.
  2. Se consulta el token en BD: SELECT * FROM corp.TokenSupport (caduca a
     medianoche; se cachea temporalmente).
  3. Clic en el dropdown de Soporte Remoto → opción 'Soporte Remoto'.
  4. Se teclea el token en el input.
  5. Clic en 'Continuar' → regresa al dashboard de Money Transfer.

Pensado para correr DENTRO del agente (WebView2) enganchado por CDP:
    # 1) Lanza el agente (Ejecutar_Hermes2Agent.bat) e inicia sesión
    # 2) Configura BD en .env (SERVIDOR_SQL, NAME_BD, USER_SQL, PASSWORD_SQL)
    $env:HERMES_AGENT_CDP="1"
    pytest src/tests/test_soporte_remoto.py -v -s

Se OMITE si no hay token en BD (sin .env/VPN o corp.TokenSupport vacía).
"""

import pytest

from config.logger import get_logger
from src.helpers.token_support import obtener_token
from src.pages.hm_transferelektra_page import HmTransferelektraPage

logger = get_logger("soporte-remoto")

DASHBOARD_TESTID = "transfer-customer-cellphone-0-cellphone-input"


@pytest.mark.soporte_remoto
@pytest.mark.asyncio
async def test_soporte_remoto(logged_page):
    token = obtener_token()
    if not token:
        pytest.skip("No se obtuvo el token de soporte de BD (revisa .env / VPN / "
                    "corp.TokenSupport). Ver el log de [token-support].")

    page = logged_page
    flow = HmTransferelektraPage(page)
    logger.info("[Soporte-Remoto] Token de BD: %s · URL: %s", token, page.url)

    # Notificaciones + idioma ya los hizo logged_page (paso 1). Aplicar el token:
    ok = await flow.aplicar_soporte_remoto(token)
    assert ok, "No se pudo aplicar el flujo de Soporte Remoto (ver log)."

    # 6) Regresa al dashboard / menú de Money Transfer: confirmar un elemento base.
    inp = page.get_by_test_id(DASHBOARD_TESTID).first
    await inp.wait_for(state="visible", timeout=15_000)
    logger.info("[Soporte-Remoto] ✓ Token aplicado y de vuelta en el dashboard de "
                "Money Transfer.")
