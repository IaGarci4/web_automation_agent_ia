"""
conftest.py — fixtures GENÉRICAS para automatizar cualquier portal.

  • browser_page: navegador limpio (para flujos de LOGIN explícito).
  • logged_page : sesión persistente — hace login solo si hace falta (vía
                  SessionHelper) y reutiliza session_state/. Al terminar guarda
                  la auditoría de estructura y, si hubo errores, el diagnóstico.

Config del portal en config/settings.py (.env). No requiere API key.
"""

import pytest_asyncio
from playwright.async_api import async_playwright

from config import settings
from config.logger import get_logger

logger = get_logger("conftest")


def _launch_args() -> list:
    """
    Flags de compatibilidad de Chromium (port de ai_agent → _launch_args).

    Evitan el popup del navegador "Acceder a otras aplicaciones y servicios de
    este dispositivo" (permiso que dispara HERMES al hablar con el Hardware
    Agent local), los prompts de certificado/contenido inseguro y el cierre
    inesperado del target durante esos handshakes. Es lo que hace que el otro
    agente corra sin que aparezca ese diálogo.
    """
    return [
        "--ignore-certificate-errors",
        "--allow-insecure-localhost",
        "--disable-web-security",
        "--allow-running-insecure-content",
        "--use-fake-device-for-media-stream",
        "--use-fake-ui-for-media-stream",
    ]


async def _nuevo_contexto(pw, usar_sesion: bool, storage_path=None):
    navegador = await pw.chromium.launch(
        headless=settings.PW_HEADLESS,
        slow_mo=settings.PW_SLOW_MO,
        args=_launch_args(),
    )
    kwargs = {
        "viewport": {"width": 1366, "height": 768},
        "permissions": ["camera", "microphone"],
        "ignore_https_errors": True,
    }
    ruta = storage_path if storage_path is not None else settings.STORAGE_STATE
    if usar_sesion and ruta.exists():
        kwargs["storage_state"] = str(ruta)
    contexto = await navegador.new_context(**kwargs)
    return navegador, contexto


@pytest_asyncio.fixture
async def browser_page():
    """Navegador limpio (sin sesión) — para flujos de login explícito."""
    async with async_playwright() as pw:
        navegador, contexto = await _nuevo_contexto(pw, usar_sesion=False)
        page = await contexto.new_page()
        await page.goto(settings.APP_URL, wait_until="domcontentloaded",
                        timeout=settings.TIMEOUT_NAVIGATION)
        try:
            yield page
        finally:
            await contexto.close()
            await navegador.close()


@pytest_asyncio.fixture
async def logged_page(request):
    """Sesión persistente: login solo si expiró; reutiliza session_state/."""
    from src.helpers.session_helper import SessionHelper
    async with async_playwright() as pw:
        navegador, contexto = await _nuevo_contexto(pw, usar_sesion=True)
        page = await contexto.new_page()

        # Diagnóstico: captura pasiva de consola + HTTP (4xx/5xx con payload,
        # respuesta y cURL) + excepciones JS durante TODA la prueba. Se engancha
        # ANTES del login para no perder errores tempranos.
        from src.helpers.diagnostics import Diagnostics
        diag = Diagnostics(page)
        diag.attach()

        helper = SessionHelper(contexto, page)
        await helper.ensure_logged_in()

        # Notificaciones: leer y cerrar el modal intrusivo "Notificaciones
        # Importantes" si aparece (port fiel de ai_agent → conftest L200).
        # OJO: tras el login la URL ya es /transfers, por lo que el navigate()
        # del flujo entra por su atajo y NO maneja el modal; hay que cerrarlo
        # AQUÍ, una vez, justo después del login. Gateado a portales Hermes
        # para no penalizar 30s a otros portales que no tienen este modal.
        try:
            if "hermes" in settings.PORTAL_NAME.lower():
                import os as _os
                from src.pages.hm_transferelektra_page import HmTransferelektraPage
                _flow = HmTransferelektraPage(page)
                res = await _flow.handle_notifications_modal()
                if res.get("found"):
                    logger.info(f"[logged_page] Notificaciones cerradas ({res.get('count', 0)} leídas).")
                # Idioma: si FLOW_LANG está definido explícitamente (lo fija la GUI
                # para correr en el idioma ELEGIDO en la interfaz), ESE manda. Si no,
                # se respeta el parámetro 'language' del test (flujos grabados en
                # inglés, ej. 'CONTINUOUS BALANCE' vs 'BALANCE CONTINUO').
                if "FLOW_LANG" in _os.environ:
                    lang = "en" if _os.environ["FLOW_LANG"].strip().lower().startswith("en") else "es"
                else:
                    lang = "es"
                    try:
                        if getattr(request.node, "callspec", None):
                            _p = request.node.callspec.params.get("language")
                            if _p:
                                lang = "en" if str(_p).strip().lower()[:3] in ("en_", "eng", "in", "ing", "en") else "es"
                    except Exception:
                        pass
                # PRECAUCIÓN (demo): el Sanity General se ejecuta SIEMPRE en inglés
                # por ahora, sin importar el idioma de la GUI/FLOW_LANG. Es el más
                # probado. Para volver a bilingüe, quitar este override.
                try:
                    if request.node.get_closest_marker("sanity_general"):
                        lang = "en"
                except Exception:
                    pass
                await _flow.cambiar_idioma(lang)
        except Exception as e:
            logger.warning(f"[logged_page] Notificaciones/idioma: {e}")

        logger.info(f"[logged_page] Listo — URL: {page.url}")
        try:
            yield page
        finally:
            # Auditoría de estructura + diagnóstico de errores (best-effort).
            # El SANITY solo produce EVIDENCIAS + reporte HTML (no auditoría/diag):
            # si el test trae el marker `sanity_general`, se OMITE el teardown de
            # reportes. El resto de módulos (pagadores/etiquetas) lo conserva.
            es_sanity = False
            try:
                es_sanity = request.node.get_closest_marker("sanity_general") is not None
            except Exception:
                es_sanity = False
            if not es_sanity:
                await _teardown_reportes(page, diag)
            await contexto.close()
            await navegador.close()


@pytest_asyncio.fixture
async def logged_page_multi(request):
    """Sesión persistente MULTIAGENTE: login con PORTAL_USER_MULTI + selección de
    agencia (AGENCY_CODE). Archivo de sesión aparte del mono. Para CPs como CP04."""
    from src.helpers.session_helper import SessionHelper, seleccionar_agencia
    async with async_playwright() as pw:
        navegador, contexto = await _nuevo_contexto(
            pw, usar_sesion=True, storage_path=settings.STORAGE_STATE_MULTI)
        page = await contexto.new_page()

        from src.helpers.diagnostics import Diagnostics
        diag = Diagnostics(page)
        diag.attach()

        helper = SessionHelper(
            contexto, page,
            user=settings.PORTAL_USER_MULTI,
            password=settings.PORTAL_PASS_MULTI,
            storage_state=settings.STORAGE_STATE_MULTI,
        )
        await helper.ensure_logged_in()

        # Selección de agencia (si el modal aparece). Tras seleccionar, re-guardar
        # la sesión para reutilizarla ya con la agencia fijada.
        try:
            selecciono = await seleccionar_agencia(page, settings.AGENCY_CODE)
            if selecciono:
                await page.wait_for_timeout(1500)
                settings.SESSION_DIR.mkdir(parents=True, exist_ok=True)
                await contexto.storage_state(path=str(settings.STORAGE_STATE_MULTI))
        except Exception as e:
            logger.warning(f"[logged_page_multi] Selección de agencia: {e}")

        # Idioma (SIN cierre de notificaciones: el perfil MULTIAGENTE no muestra
        # el modal de notificaciones intrusivo — pasa por la selección de agencia).
        try:
            if "hermes" in settings.PORTAL_NAME.lower():
                import os as _os
                from src.pages.hm_transferelektra_page import HmTransferelektraPage
                _flow = HmTransferelektraPage(page)
                if "FLOW_LANG" in _os.environ:
                    lang = "en" if _os.environ["FLOW_LANG"].strip().lower().startswith("en") else "es"
                else:
                    lang = "es"
                    try:
                        if getattr(request.node, "callspec", None):
                            _p = request.node.callspec.params.get("language")
                            if _p:
                                lang = "en" if str(_p).strip().lower()[:3] in ("en_", "eng", "in", "ing", "en") else "es"
                    except Exception:
                        pass
                # PRECAUCIÓN (demo): el Sanity General se ejecuta SIEMPRE en inglés
                # por ahora, sin importar el idioma de la GUI/FLOW_LANG. Es el más
                # probado. Para volver a bilingüe, quitar este override.
                try:
                    if request.node.get_closest_marker("sanity_general"):
                        lang = "en"
                except Exception:
                    pass
                await _flow.cambiar_idioma(lang)
        except Exception as e:
            logger.warning(f"[logged_page_multi] Idioma: {e}")

        logger.info(f"[logged_page_multi] Listo — URL: {page.url}")
        try:
            yield page
        finally:
            es_sanity = False
            try:
                es_sanity = request.node.get_closest_marker("sanity_general") is not None
            except Exception:
                es_sanity = False
            if not es_sanity:
                await _teardown_reportes(page, diag)
            await contexto.close()
            await navegador.close()


async def _teardown_reportes(page, diag=None):
    """Guarda auditoría de DOM y, si los hubo, el reporte de diagnóstico
    (consola + HTTP 4xx/5xx con payload/respuesta/cURL + excepciones JS)."""
    try:
        from src.helpers.dom_audit import DomAudit
        audit = DomAudit(page, flujo=settings.PORTAL_NAME)
        await audit.scan(etiqueta=settings.PORTAL_NAME)
        settings.AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        audit.save_html(str(settings.AUDIT_DIR / f"{settings.PORTAL_NAME}.html"))
        logger.info("[logged_page] Auditoría de estructura guardada.")
    except Exception as e:
        logger.warning(f"[logged_page] Auditoría no generada: {e}")

    # Volcar diagnóstico SOLO si hubo errores (consola/HTTP/JS)
    if diag is not None and diag.tiene_errores():
        try:
            rutas = await diag.dump(str(settings.DIAG_DIR / settings.PORTAL_NAME))
            logger.warning(f"[logged_page] ⚠ Errores capturados ({diag.resumen()}) "
                           f"→ {rutas['html']}")
        except Exception as e:
            logger.warning(f"[logged_page] Dump de diagnóstico falló: {e}")
