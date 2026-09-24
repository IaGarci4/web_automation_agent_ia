"""
conftest.py — fixtures GENÉRICAS para automatizar cualquier portal.

  • browser_page: navegador limpio (para flujos de LOGIN explícito).
  • logged_page : sesión persistente — hace login solo si hace falta (vía
                  SessionHelper) y reutiliza session_state/. Al terminar guarda
                  la auditoría de estructura y, si hubo errores, el diagnóstico.

Config del portal en config/settings.py (.env). No requiere API key.
"""

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

from config import settings
from config.logger import get_logger

logger = get_logger("conftest")


# ── Evidencias → QMetry (al terminar cada caso del sanity) ──────────────────

@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Guarda el reporte de cada fase en el item para saber si el test PASÓ.

    Lo usa la fixture de QMetry: el resultado que se escribe en el ciclo debe
    ser el veredicto REAL de la prueba, no el hecho de tener capturas."""
    outcome = yield
    setattr(item, "rep_" + outcome.get_result().when, outcome.get_result())


@pytest.fixture(autouse=True)
def qmetry_evidencias(request):
    """Sube las evidencias del caso a su Test Cycle en QMetry al terminar y
    marca el resultado (Pass/Fail) según el veredicto real de la prueba.

    Se activa solo con QMETRY_UPLOAD=1 y para tests marcados `sanity_general`.
    El CP se deduce del nombre del test (test_CP02_... → CP02) y el destino de
    cada imagen sale de config/qmetry_mapeo.json. Nunca interrumpe la prueba:
    si la subida falla, queda registrado en el log."""
    yield
    if not settings.QMETRY_UPLOAD:
        return
    if request.node.get_closest_marker("sanity_general") is None:
        return
    try:
        from src.helpers import qmetry_sync as _S
        cp = _S.cp_desde_nombre_test(request.node.name)
        if not cp:
            return
        # Veredicto REAL: passed sólo si la fase de ejecución pasó.
        rep = getattr(request.node, "rep_call", None)
        fallo = rep is not None and not rep.passed
        # Si el caso FALLÓ no se sube nada: el ciclo de QMetry es el registro
        # oficial de la prueba, y llenarlo con evidencias de una corrida
        # incompleta ensucia el reporte. Las capturas quedan en reports/ para
        # depurar, y se suben cuando el caso pase.
        if fallo:
            logger.info("[QMetry] %s FALLÓ — no se sube nada. Las evidencias "
                        "quedan en reports/evidence/. Cuando el caso pase se "
                        "subirán solas (o fuérzalo con "
                        "`python tools/qmetry_subir.py %s`).", cp, cp)
            return
        veredicto = "Pass" if settings.QMETRY_RESULTADO and rep is not None else None
        logger.info("[QMetry] Subiendo evidencias de %s%s…", cp,
                    f" (resultado: {veredicto})" if veredicto else "")
        _S.subir_evidencias(cp, veredicto=veredicto)
    except Exception as e:      # nunca tumbar un test por la subida
        logger.warning("[QMetry] No se pudieron subir las evidencias: %s", str(e)[:120])


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
        # Cámara falsa: la Ficha de Depósitos (CP10) toma una foto real desde
        # la webcam. Con estos flags Chromium expone un dispositivo simulado y
        # concede el permiso sin preguntar.
        "--use-fake-device-for-media-stream",
        "--use-fake-ui-for-media-stream",
        "--autoplay-policy=no-user-gesture-required",
        "--enable-media-stream",
    ]


# Cámara simulada a nivel de página: además de los flags, la app enumera los
# dispositivos con `navigator.mediaDevices`. En una máquina sin webcam la lista
# sale vacía y el desplegable de cámara del CP10 queda sin opciones, así que se
# inyecta un dispositivo falso que entrega video.
#
# ## Por qué el lienzo se REPINTA en bucle
#
# La primera versión pintaba el lienzo de negro UNA vez y devolvía
# `canvas.captureStream(30)`. Parece razonable y funciona… a veces. El detalle
# es que un `captureStream` de canvas no emite 30 fps porque se lo pidas: emite
# un fotograma **cuando el lienzo cambia**. Un lienzo pintado una sola vez
# produce un fotograma inicial y después nada.
#
# Resultado: el `<video>` de la app se quedaba a veces sin datos, 'Take
# Picture' no capturaba nada, 'Save Picture' no llegaba a aparecer y el caso
# moría 60 s más tarde diciendo «No se pudo pulsar 'Save Picture'» — señalando
# al botón equivocado. Que fallara un día sí y otro no era la pista: es una
# carrera, no un selector.
#
# Repintando en cada frame el stream siempre tiene datos. El reloj dibujado no
# es decoración: garantiza que cada fotograma DIFIERE del anterior, que es la
# condición que hace emitir al `captureStream`.
_SCRIPT_CAMARA = """
(() => {
  if (!navigator.mediaDevices) return;
  const fakeDevices = [{
    deviceId: 'fake-camera-1', kind: 'videoinput',
    label: 'Integrated Webcam (Default)', groupId: 'fake-group-1',
  }];
  navigator.mediaDevices.enumerateDevices = async () => fakeDevices;
  navigator.mediaDevices.getUserMedia = async () => {
    const canvas = document.createElement('canvas');
    canvas.width = 640; canvas.height = 480;
    const ctx = canvas.getContext('2d');
    const pintar = () => {
      ctx.fillStyle = 'black';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      // Marca que cambia cada frame: obliga al captureStream a emitir.
      ctx.fillStyle = '#111';
      ctx.font = '16px monospace';
      ctx.fillText(new Date().toISOString(), 12, canvas.height - 14);
      requestAnimationFrame(pintar);
    };
    pintar();
    return canvas.captureStream(30);
  };
})();
"""


async def _nuevo_contexto(pw, usar_sesion: bool, storage_path=None,
                          expected_user: str = None):
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
        # Solo reutilizar la sesión si pertenece al usuario configurado. Si las
        # credenciales cambiaron (p. ej. otra agencia), se descarta para forzar
        # un login limpio y NO operar con el usuario equivocado.
        from src.helpers.session_helper import (sesion_es_del_usuario,
                                                descartar_sesion)
        user = expected_user if expected_user is not None else settings.PORTAL_USER
        if sesion_es_del_usuario(ruta, user):
            kwargs["storage_state"] = str(ruta)
        else:
            logger.warning("[Sesión] La sesión guardada NO es del usuario '%s' "
                           "(o no está marcada) — se descarta y se hará login "
                           "limpio.", user)
            descartar_sesion(ruta)
    contexto = await navegador.new_context(**kwargs)
    try:
        await contexto.grant_permissions(["camera", "microphone"])
        await contexto.add_init_script(_SCRIPT_CAMARA)
    except Exception:
        pass                    # sin cámara simulada solo se afecta el CP10
    return navegador, contexto


async def _conectar_agente_cdp(pw):
    """Engancha por CDP al WebView2 del Hermes2Agent (modo AGENT_CDP).

    NO lanza navegador: se conecta al Chromium embebido ya autenticado (Kerberos),
    reutiliza su contexto y localiza la página de la web app real. Devuelve
    (navegador, contexto, page). La página YA está logueada — no hay que loguear.
    """
    import re as _re
    navegador = await pw.chromium.connect_over_cdp(settings.AGENT_CDP_URL)
    contexto = navegador.contexts[0] if navegador.contexts else await navegador.new_context()
    patron = _re.compile(settings.AGENT_PAGE_URL_RE, _re.I)

    def _match(p):
        try:
            return bool(patron.search(p.url or ""))
        except Exception:
            return False

    page = next((p for p in contexto.pages if _match(p)), None)
    if page is None:
        # La app puede tardar en montar el WebView; esperar a que aparezca.
        for _ in range(20):
            page = next((p for p in contexto.pages if _match(p)), None)
            if page:
                break
            try:
                await contexto.wait_for_event("page", timeout=1_500)
            except Exception:
                pass
        if page is None:
            page = contexto.pages[0] if contexto.pages else await contexto.new_page()
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=settings.TIMEOUT_NAVIGATION)
    except Exception:
        pass
    logger.info("[Agente-CDP] Enganchado a %s · página: %s",
                settings.AGENT_CDP_URL, (page.url or "")[:90])
    return navegador, contexto, page


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
    """Sesión persistente: login solo si expiró; reutiliza session_state/.

    En modo AGENT_CDP se ENGANCHA por CDP al WebView2 del Hermes2Agent (ya
    autenticado por Kerberos): reutiliza la página existente, OMITE el login, y en
    el teardown solo DESCONECTA (no cierra la app)."""
    from src.helpers.session_helper import SessionHelper
    async with async_playwright() as pw:
        # ── Modo AGENTE (CDP): enganche al WebView2, sin lanzar navegador ──────
        if settings.AGENT_CDP:
            try:
                navegador, contexto, page = await _conectar_agente_cdp(pw)
            except Exception as e:
                pytest.skip(
                    f"[Agente-CDP] No se pudo conectar a {settings.AGENT_CDP_URL} "
                    f"({str(e).splitlines()[0][:120]}). El puerto CDP no está abierto: "
                    f"1) cierra el agente por completo; 2) láncalo con "
                    f"Ejecutar_Hermes2Agent.bat (setea el puerto ANTES del exe); "
                    f"3) inicia sesión y entra a la app; 4) verifica con "
                    f"'python tools/agent_cdp_check.py'. Si aun así no abre, el agente "
                    f"fija los args por código → aplicar el Fallback (KRA-860, ver "
                    f"docs/AGENTE_CDP_WEBVIEW2.md).")
                return
            from src.helpers.diagnostics import Diagnostics
            diag = Diagnostics(page)
            diag.attach()
            # El WebView2 puede venir en el login del SSO (no siempre hay sesión
            # Kerberos activa). Autenticar si hace falta: reutiliza el login
            # estándar (mismos testids); si ya hay sesión, lo detecta y lo omite.
            try:
                helper = SessionHelper(contexto, page)
                await helper.ensure_logged_in()
                logger.info("[Agente-CDP] Sesión lista tras ensure_logged_in.")
            except Exception as e:
                logger.warning("[Agente-CDP] Login: %s", str(e)[:140])
            # Best-effort: cerrar notificaciones y fijar idioma (ya en la app).
            try:
                if "hermes" in settings.PORTAL_NAME.lower():
                    import os as _os
                    from src.pages.hm_transferelektra_page import HmTransferelektraPage
                    _flow = HmTransferelektraPage(page)
                    try:
                        res = await _flow.handle_notifications_modal()
                        if res.get("found"):
                            logger.info("[Agente-CDP] Notificaciones cerradas (%s).",
                                        res.get("count", 0))
                    except Exception:
                        pass
                    lang = "en" if _os.getenv("FLOW_LANG", "").strip().lower().startswith("en") else "es"
                    try:
                        if request.node.get_closest_marker("sanity_general"):
                            lang = "en"
                    except Exception:
                        pass
                    try:
                        await _flow.cambiar_idioma(lang)
                    except Exception:
                        pass
            except Exception as e:
                logger.warning("[Agente-CDP] Notificaciones/idioma: %s", str(e)[:100])
            logger.info("[Agente-CDP] Listo — URL: %s", page.url)
            try:
                yield page
            finally:
                # Auditoría de DOM/diagnóstico best-effort (la captura de pantalla
                # del agente está bloqueada → sale negra, así que NO screenshots).
                try:
                    if request.node.get_closest_marker("sanity_general") is None:
                        await _teardown_reportes(page, diag)
                except Exception:
                    pass
                # SOLO desconectar la conexión CDP: NO cerrar contexto/página/app.
                try:
                    await navegador.close()   # cierra la conexión, no el agente
                except Exception:
                    pass
            return

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
            pw, usar_sesion=True, storage_path=settings.STORAGE_STATE_MULTI,
            expected_user=settings.PORTAL_USER_MULTI)
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
