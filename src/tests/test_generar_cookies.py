"""
Warm-up de sesiones para el PARALELO WEB (equivalente al `-m cookies` del repo viejo).

Problema que resuelve: en equipos CON el Hermes2Agent instalado, el login web
INTERACTIVO cae en el interstitial "Continúe en la aplicación de Maxi" (handoff al
escritorio). Pero ese handoff SOLO ocurre en el login con usuario/contraseña. Una
vez guardada la sesión SSO de Keycloak, `goto(/transfers)` entra en SILENCIO.

Este paso loguea UNA vez cada usuario de automatización y GUARDA su sesión por
worker (session_state/hermes2_storage_state_gwN.json), tolerando el interstitial.
Luego el sanity en paralelo carga esas sesiones y cada navegador entra directo.

USO (genera las sesiones de 4 usuarios en paralelo, una vez):
    python -m pytest -m cookies -n 4
    # o secuencial:
    python -m pytest -m cookies -v -s

Después:
    python -m pytest -m sanity_general -n 4 --html=report.html --self-contained-html

Cada sesión dura mientras el token siga vigente; si expira, se vuelve a correr
este warm-up (o el propio worker re-loguea al detectar sesión no activa).
"""
import pytest
from playwright.async_api import Page

from config import settings
from config.logger import get_logger
from src.helpers.session_helper import SessionHelper

logger = get_logger("cookies")

# Perfiles = workers de xdist. Cada uno usa su usuario (settings.usuario_por_worker)
# y su archivo de sesión (settings.storage_state_por_worker).
PERFILES = ["gw0", "gw1", "gw2", "gw3"]


@pytest.mark.cookies
@pytest.mark.asyncio
@pytest.mark.parametrize("perfil", PERFILES)
async def test_generar_sesion_por_usuario(perfil):
    """Loguea el usuario del perfil y guarda su sesión (para el paralelo web)."""
    from playwright.async_api import async_playwright

    user, pwd = settings.usuario_por_worker(perfil)
    storage = settings.storage_state_por_worker(perfil)
    if not user or not pwd:
        pytest.skip(f"[cookies] Sin credenciales para {perfil} — revisa el .env.")
    logger.info("[cookies] %s → usuario=%s → %s", perfil, user, storage.name)

    # Login en BACKGROUND (headless) por defecto: sin front-end, más rápido y sin
    # el diálogo nativo del protocolo (headless no lo dispara). Se puede forzar
    # headed con HERMES_COOKIES_HEADLESS=0.
    import os as _os
    headless = _os.getenv("HERMES_COOKIES_HEADLESS", "1").strip().lower() not in (
        "0", "false", "no")

    async with async_playwright() as pw:
        navegador = await pw.chromium.launch(
            headless=headless, slow_mo=settings.PW_SLOW_MO)
        contexto = await navegador.new_context(
            viewport={"width": 1366, "height": 768}, ignore_https_errors=True)
        page = await contexto.new_page()
        helper = SessionHelper(contexto, page, user=user, password=pwd,
                               storage_state=storage)
        try:
            ok = await helper.login_y_guardar_sesion()
            assert ok, f"No se pudo generar la sesión para {perfil} ({user})."
            assert storage.exists(), f"No se guardó el archivo de sesión {storage}."
            logger.info("[cookies] ✓ Sesión de %s (%s) lista.", perfil, user)
        finally:
            try:
                await contexto.close()
                await navegador.close()
            except Exception:
                pass
