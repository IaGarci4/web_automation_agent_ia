"""
SessionHelper GENÉRICO — login + sesión persistente para CUALQUIER portal.

Resuelve el punto clave: en un portal nuevo (Zeus, un CRM, etc.) hace el login
una sola vez, GUARDA la sesión (cookies + localStorage) y en las siguientes
corridas la reutiliza — si sigue válida, omite el login.

Todo se configura por .env / config.settings (URL, selectores de usuario,
contraseña y botón). Nada está atado a un portal específico.

Uso (lo invoca la fixture logged_page de conftest.py):
    helper = SessionHelper(context, page)
    await helper.ensure_logged_in()
"""

import json
import re
from pathlib import Path

from config import settings
from config.logger import get_logger

logger = get_logger("session")


class HandoffEscritorioError(RuntimeError):
    """El login web quedó atrapado en el 'handoff' al Hermes2Agent de escritorio
    (equipo con el HA instalado). El paralelo web debe correr en un servidor sin
    el HA, o usar el modo agente (HERMES_AGENT_CDP=1)."""


# ── Vinculación sesión ↔ usuario ─────────────────────────────────────────────
# La sesión persistente (cookies + localStorage) se guarda junto a un "sidecar"
# que anota QUÉ usuario la generó. Así, si cambian las credenciales en el .env
# (p. ej. de una agencia a otra), la sesión vieja se descarta y se hace login
# limpio en vez de operar con el usuario equivocado.

def _sidecar(storage_path) -> Path:
    return Path(str(storage_path) + ".user")


def marcar_sesion(storage_path, user: str) -> None:
    """Escribe el sidecar con el usuario dueño de la sesión."""
    try:
        _sidecar(storage_path).write_text(
            json.dumps({"user": (user or "").strip()}), encoding="utf-8")
    except Exception as e:
        logger.warning("[Sesión] No se pudo marcar el usuario de la sesión: %s",
                       str(e)[:90])


def sesion_es_del_usuario(storage_path, user: str) -> bool:
    """True solo si la sesión guardada pertenece a `user` (según el sidecar).

    Si NO hay sidecar (sesión antigua sin marca), devuelve False a propósito:
    así se fuerza un login limpio una vez y la sesión queda marcada. Esto evita
    el bug de operar con un usuario/agencia distinto al configurado."""
    try:
        sc = _sidecar(storage_path)
        if not sc.exists():
            return False
        data = json.loads(sc.read_text(encoding="utf-8"))
        return (data.get("user") or "").strip() == (user or "").strip()
    except Exception:
        return False


def descartar_sesion(storage_path) -> None:
    """Borra la sesión guardada y su sidecar (fuerza login limpio)."""
    for p in (Path(str(storage_path)), _sidecar(storage_path)):
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass

# Botón que descarta el modal «Instalación Requerida» del Hardware Agent.
_RE_CONTINUAR = re.compile(r"continuar|continue|aceptar|accept|omitir|skip", re.I)

# Confirmación del modal "Éxito — agencia de comunicación 'PC'. ¿Desea continuar?"
# El botón es data-testid='test-id-button' (GENÉRICO) con texto "SÍ, Continuar"/
# "YES, Continue"; por eso se localiza por TEXTO (EN/ES), no por testid.
_RE_SI_CONTINUAR = re.compile(r"s[ií],?\s*continuar|yes,?\s*continue", re.I)


class SessionHelper:
    def __init__(self, context, page, user: str = None, password: str = None,
                 storage_state=None):
        self.context = context
        self.page = page
        # Overrides opcionales (ej. perfil MULTIAGENTE). Si no se pasan, usa .env.
        self.user = user if user is not None else settings.PORTAL_USER
        self.password = password if password is not None else settings.PORTAL_PASS
        self.storage_state = storage_state if storage_state is not None else settings.STORAGE_STATE

    # ── API principal ───────────────────────────────────────────────────────

    async def ensure_logged_in(self) -> bool:
        """
        Garantiza una sesión activa en el portal:
          1. Navega a APP_URL.
          2. Si ya está dentro (URL/elemento 'ready') → sesión OK, no hace login.
          3. Si ve el formulario de login → hace login real y RE-GUARDA la sesión.
        Devuelve True si quedó logueado.
        """
        await self.page.goto(settings.APP_URL,
                             wait_until="domcontentloaded",
                             timeout=settings.TIMEOUT_NAVIGATION)
        await self.page.wait_for_timeout(1500)

        if await self._sesion_activa():
            logger.info("✓ Sesión activa — login omitido.")
            return True

        # No detectamos sesión en el chequeo rápido. Antes de asumir que hay que
        # loguear, esperamos LO PRIMERO que aparezca: el formulario de login O la
        # app ya cargada (READY_SELECTOR). Esto evita el cuelgue de 90s esperando
        # el campo de usuario cuando en realidad la app tardó en montar el DOM y
        # la sesión SÍ era válida (patrón robusto de ai_agent).
        login_loc = self._loc(settings.LOGIN_USER_TESTID, settings.LOGIN_USER_SELECTOR).first
        ready_loc = (self.page.locator(settings.READY_SELECTOR).first
                     if settings.READY_SELECTOR else None)
        marker = login_loc.or_(ready_loc) if ready_loc is not None else login_loc
        try:
            await marker.wait_for(state="visible", timeout=settings.TIMEOUT_ELEMENT)
        except Exception:
            logger.warning("Ni login ni app visibles tras la espera — intento login igual.")

        # Si la app cargó (ready visible) y NO hay campo de login → sesión válida.
        try:
            if (ready_loc is not None and await ready_loc.is_visible()
                    and not await login_loc.is_visible()):
                logger.info("✓ App cargada (sesión válida) — login omitido.")
                return True
        except Exception:
            pass

        # Quizá no era login sino el interstitial 'Abrir Maxisend' (sesión SSO
        # válida pero Keycloak mostró la pantalla intermedia): intentarlo primero.
        if await self.abrir_app_si_interstitial(timeout_ms=3_000):
            await self._esperar_listo()
            try:
                if settings.READY_SELECTOR and await self.page.locator(
                        settings.READY_SELECTOR).first.is_visible():
                    logger.info("✓ App cargada tras 'Abrir Maxisend' — login omitido.")
                    await self._guardar_sesion()
                    return True
            except Exception:
                pass

        logger.info("Sesión no activa — ejecutando login...")
        await self._login()
        # Tras enviar credenciales, Keycloak puede mostrar 'Abrir Maxisend'.
        await self.abrir_app_si_interstitial()
        await self._esperar_listo()
        await self._guardar_sesion()
        return True

    async def login_y_guardar_sesion(self, espera_post_ms: int = 8_000) -> bool:
        """WARM-UP para el paralelo web (equivalente al `-m cookies` del repo viejo).

        Navega, hace el login interactivo (usuario/contraseña) y GUARDA la sesión
        (cookies + localStorage), TOLERANDO el interstitial de handoff al escritorio
        — NO pulsa 'Abrir Maxisend'. Con la sesión SSO de Keycloak ya guardada, los
        workers del paralelo entran luego a /transfers en SILENCIO (sin volver a
        pasar por el login ni por el interstitial). Devuelve True si guardó sesión."""
        await self.page.goto(settings.APP_URL, wait_until="domcontentloaded",
                             timeout=settings.TIMEOUT_NAVIGATION)
        await self.page.wait_for_timeout(1_500)

        # Si ya hay sesión válida (app cargada), solo guardar.
        if await self._sesion_activa():
            await self._guardar_sesion()
            logger.info("[Warm-up] Sesión ya activa — guardada para %s.", self.user)
            return True

        # Esperar el formulario de login y autenticar.
        login_loc = self._loc(settings.LOGIN_USER_TESTID, settings.LOGIN_USER_SELECTOR).first
        try:
            await login_loc.wait_for(state="visible", timeout=settings.TIMEOUT_ELEMENT)
        except Exception:
            logger.info("[Warm-up] Formulario de login no visible — intento igual.")
        await self._login()   # descarta modal 'Instalación Requerida' + llena + envía

        # Dar tiempo a que Keycloak complete la autenticación (aunque quede en el
        # interstitial). NO se pulsa 'Abrir Maxisend'. Luego se guarda la sesión.
        await self.page.wait_for_timeout(espera_post_ms)
        await self._guardar_sesion()
        logger.info("[Warm-up] Sesión guardada para %s (tras login; se toleró el "
                    "interstitial si apareció).", self.user)
        return True

    # ── Detección de sesión ───────────────────────────────────────────────────

    async def _sesion_activa(self) -> bool:
        """¿Ya estamos dentro? Por patrón de URL y/o elemento 'ready'.

        NOTA (fix): antes, si no había READY_SELECTOR configurado o si no se
        encontraba, se caía en un heurístico de dominio ("la URL ya no es la
        de APP_URL" → "sesión activa"). Eso es correcto para portales con
        login en el MISMO dominio (login.example.com/app → app.example.com/home),
        pero es exactamente lo CONTRARIO para portales con SSO externo (Hermes2:
        test-hermes.maxilabs.net te redirige a sso.maxilabs.net cuando NO hay
        sesión válida). Con el heurístico viejo, ese redirect a un dominio
        externo se leía como "ya estamos dentro" y el login se saltaba,
        dejando la página parada en la pantalla de SSO — el flujo intentaba
        llenar campos del formulario de transferencia ahí y fallaba por
        timeout. Ahora, si hay READY_SELECTOR configurado (como en el preset
        de Hermes2), es la señal AUTORITATIVA: se espera un momento por si la
        SPA todavía está montando el DOM, pero si no aparece, se concluye que
        NO hay sesión activa (ya no se cae al heurístico de dominio).
        """
        # Si hay un campo de contraseña visible, NO estamos logueados.
        try:
            pass_field = self._loc(settings.LOGIN_PASS_TESTID, settings.LOGIN_PASS_SELECTOR)
            if await pass_field.count() > 0 and await pass_field.first.is_visible():
                return False
        except Exception:
            pass
        # Patrón de URL de "ya dentro"
        if settings.READY_URL_PATTERN:
            try:
                import re
                pat = settings.READY_URL_PATTERN.replace("**", ".*")
                if re.search(pat, self.page.url):
                    return True
            except Exception:
                pass
        # Elemento que confirma la app cargada: si está configurado, es la
        # señal definitiva (no cae al heurístico de dominio, ver nota arriba).
        if settings.READY_SELECTOR:
            try:
                el = self.page.locator(settings.READY_SELECTOR).first
                await el.wait_for(state="visible", timeout=5000)
                return True
            except Exception:
                return False
        # Sin READY_SELECTOR configurado: heurística de dominio (best-effort,
        # solo válida para portales de login same-domain).
        return settings.APP_URL.rstrip("/") not in self.page.url

    # ── Login ─────────────────────────────────────────────────────────────────

    def _loc(self, testid: str, css: str):
        """Prioriza data-testid si se definió; si no, usa el selector CSS."""
        if testid:
            return self.page.get_by_test_id(testid)
        return self.page.locator(css)

    async def _escribir(self, locator, valor: str) -> None:
        """
        Escribe `valor` como lo haría un humano y deja el control 'touched'.

        NOTA (fix): antes se usaba locator.fill(), que setea el value y dispara
        UN solo evento 'input'. Muchos formularios de login en Angular (como el
        de Hermes2/Keycloak) mantienen el botón de envío DISABLED hasta que el
        reactive form se marca válido, y eso requiere:
          1) eventos por carácter (input/keyup) → press_sequentially, y
          2) que el campo pierda el foco (blur) → marca el control 'touched'
             (necesario si el form usa updateOn:'blur').
        Con fill() + click inmediato, el form quedaba inválido, el botón seguía
        disabled y el click esperaba 30s hasta hacer timeout.
        """
        # El modal 'Instalación Requerida' aparece con RETRASO y su backdrop
        # intercepta el puntero. Se elimina por JS JUSTO antes de escribir y, si el
        # clic falla igual (apareció en medio), se elimina y se reintenta.
        ultimo = None
        for intento in range(3):
            await self._quitar_modal_js()
            try:
                await locator.scroll_into_view_if_needed(timeout=8_000)
                await locator.click(timeout=8_000)
                try:
                    await locator.fill("")  # limpia cualquier valor previo
                except Exception:
                    pass
                await locator.press_sequentially(valor, delay=30)
                try:
                    await locator.blur()
                except Exception:
                    await self.page.keyboard.press("Tab")
                return
            except Exception as e:
                ultimo = e
                await self._quitar_modal_js()
                await self.page.wait_for_timeout(700)
        if ultimo:
            raise ultimo

    async def _quitar_modal_js(self) -> int:
        """Elimina por JS el modal 'Instalación Requerida' y su backdrop (si están).
        Idempotente y sin ruido si no hay modal. Devuelve cuántos nodos quitó."""
        try:
            return await self.page.evaluate("""
                () => {
                  let n = 0;
                  for (const d of document.querySelectorAll(
                        "div[id*='modal-installation-required'], .modal-backdrop")) {
                    d.remove(); n++;
                  }
                  document.body.classList.remove('modal-open');
                  document.body.style.overflow = '';
                  return n;
                }""")
        except Exception:
            return 0

    async def cerrar_modal_instalacion(self, timeout_ms: int = 6_000) -> bool:
        """Descarta el modal «Instalación Requerida» del Hardware Agent.

        Hermes lo muestra en el login cuando no detecta el Maxitransfer Hardware
        Agent. Es un `role=dialog` que **intercepta los eventos de puntero**: el
        campo de usuario se ve visible y habilitado, pero el clic nunca le llega
        y el login muere con un timeout de 30 s que apunta al sitio equivocado.

        Se cierra con «Continuar/Continue» (o la X) y el flujo sigue: la mayoría
        de los casos no necesitan el agente. Los que sí (KRA-1527) fallarán más
        adelante en su propia comprobación, que es donde corresponde."""
        page = self.page
        # El modal se detecta por su TEXTO (independiente del idioma y del id
        # concreto): en la pantalla de LOGIN su id difiere del de dentro de la
        # app, por eso antes fallaba la detección por id y el login se atoraba.
        _RE_INSTALL = re.compile(
            r"instalaci[oó]n requerida|installation required|"
            r"componente de software|software component", re.I)
        candidatos = (
            page.get_by_role("button", name=_RE_CONTINUAR),
            page.locator("div[id*='modal-installation-required'] button"),
            page.locator("div.modal.show button").filter(has_text=_RE_CONTINUAR),
            page.locator("div[role='dialog'] button, .modal.show button, "
                         ".p-dialog button").filter(has_text=_RE_CONTINUAR),
            page.locator("div[id*='modal-installation-required'] .close, "
                         "div[id*='modal-installation-required'] button.close"),
        )
        espera = 0
        while espera <= timeout_ms:
            # ¿Está el modal en pantalla? Se busca por id O por texto.
            try:
                por_id = page.locator("div[id*='modal-installation-required']").first
                visible = await por_id.count() and await por_id.is_visible()
            except Exception:
                visible = False
            if not visible:
                try:
                    txt = page.get_by_text(_RE_INSTALL).first
                    visible = await txt.count() and await txt.is_visible()
                except Exception:
                    visible = False
            if not visible:
                # El modal aparece con RETRASO tras cargar el login: NO rendirse en
                # la 1ª vuelta; seguir sondeando hasta el timeout por si aparece.
                await page.wait_for_timeout(200)
                espera += 200
                continue
            for loc in candidatos:
                try:
                    btn = loc.first
                    if not await btn.is_visible():
                        continue
                    await btn.click(force=True, timeout=4_000)
                    await page.wait_for_timeout(600)
                    # ¿Se cerró de verdad? (el clic a veces no basta)
                    try:
                        aun = page.locator("div[id*='modal-installation-required']").first
                        if not (await aun.count() and await aun.is_visible()):
                            logger.info("[Login] Modal 'Instalación Requerida' "
                                        "descartado con 'Continuar'.")
                            return True
                    except Exception:
                        return True
                except Exception:
                    continue
            await page.wait_for_timeout(200)
            espera += 200

        # Último recurso: el modal (y su backdrop) siguen bloqueando el formulario
        # → se ELIMINAN por JS. El Hardware Agent no hace falta para el login web;
        # los casos que sí lo requieren (impresión) fallan luego en su validación.
        try:
            quitados = await page.evaluate("""
                () => {
                  let n = 0;
                  for (const d of document.querySelectorAll(
                        "div[id*='modal-installation-required'], .modal-backdrop")) {
                    d.remove(); n++;
                  }
                  document.body.classList.remove('modal-open');
                  document.body.style.overflow = '';
                  return n;
                }""")
            if quitados:
                logger.info("[Login] Modal 'Instalación Requerida' eliminado por JS "
                            "(%d nodo/s) — el HA no es necesario para el login web.",
                            quitados)
                return True
        except Exception as e:
            logger.warning("[Login] No se pudo eliminar el modal por JS: %s", str(e)[:80])
        logger.warning("[Login] El modal 'Instalación Requerida' sigue en "
                       "pantalla; sus overlays van a bloquear el formulario.")
        return False

    async def abrir_app_si_interstitial(self, timeout_ms: int = 8_000) -> bool:
        """Maneja la pantalla intermedia post-login 'Continúe en la aplicación de
        Maxi'. Está pensado para el SERVIDOR SIN Hardware Agent (paralelo web):
        ahí no está registrado el protocolo `hermes2agent://`, así que pulsar
        'Abrir Maxisend' continúa a /transfers en el navegador (no hay diálogo
        nativo). Con timeouts CORTOS para NO colgarse.

        Devuelve True si logró entrar a la app; False si no había interstitial.
        Si el interstitial existe pero no se puede continuar por web (equipo CON
        el Hermes2Agent → handoff al escritorio), lanza HandoffEscritorioError para
        que la fixture lo reporte con una guía clara en vez de colgarse."""
        page = self.page
        _RE_INTER = re.compile(
            r"contin[uú]e en la aplicaci|continue in the maxi|"
            r"ser redirigido a la aplicaci", re.I)

        async def _ya_en_app() -> bool:
            try:
                if settings.READY_SELECTOR:
                    r = page.locator(settings.READY_SELECTOR).first
                    return bool(await r.count()) and await r.is_visible()
            except Exception:
                pass
            return False

        async def _en_interstitial() -> bool:
            try:
                loc = page.get_by_text(_RE_INTER).first
                return bool(await loc.count()) and await loc.is_visible()
            except Exception:
                return False

        if await _ya_en_app():
            return False
        if not await _en_interstitial():
            return False

        logger.info("[Login] Interstitial 'Continúe en la aplicación de Maxi' "
                    "detectado — intento continuar a la app por web.")

        # SERVIDOR SIN HA: pulsar 'Abrir Maxisend' navega a /transfers en el
        # navegador (no hay protocolo registrado → sin diálogo nativo).
        try:
            btn = page.get_by_role("button", name=re.compile(r"abrir\s*maxi|open\s*maxi", re.I)).first
            if await btn.count() and await btn.is_visible():
                await btn.click(timeout=4_000)
                await page.wait_for_timeout(1_500)
                if await _ya_en_app():
                    logger.info("[Login] Entré a la app tras 'Abrir Maxisend'.")
                    return True
        except Exception:
            pass

        # Fallback: re-navegar a la app UNA vez (bounded).
        try:
            await page.goto(settings.APP_URL, wait_until="domcontentloaded",
                            timeout=settings.TIMEOUT_NAVIGATION)
            await page.wait_for_timeout(1_500)
            if await _ya_en_app():
                logger.info("[Login] Entré a la app por re-navegación.")
                return True
        except Exception:
            pass

        # No se pudo continuar por web: es el handoff al escritorio (equipo con HA).
        raise HandoffEscritorioError(
            "Login web bloqueado por el handoff al Hermes2Agent (la pantalla "
            "'Continúe en la aplicación de Maxi' solo ofrece abrir la app de "
            "escritorio). Corre el paralelo web en un servidor SIN el Hardware "
            "Agent instalado, o usa el modo agente con HERMES_AGENT_CDP=1.")

    async def _login(self) -> None:
        if not self.user or not self.password:
            logger.warning("Usuario/clave vacíos — define credenciales en .env")

        usuario = self._loc(settings.LOGIN_USER_TESTID, settings.LOGIN_USER_SELECTOR).first
        clave   = self._loc(settings.LOGIN_PASS_TESTID, settings.LOGIN_PASS_SELECTOR).first
        enviar  = self._loc(settings.LOGIN_SUBMIT_TESTID, settings.LOGIN_SUBMIT_SELECTOR).first

        await usuario.wait_for(state="visible", timeout=settings.TIMEOUT_ELEMENT)
        # ANTES de teclear: el modal 'Instalación Requerida' del Hardware Agent
        # tapa el formulario. NO se pulsa 'Continuar' (eso AVANZA la página y quita
        # el campo de usuario); solo se ELIMINA por JS el modal + backdrop, dejando
        # el formulario intacto. `_escribir` además lo re-quita en cada intento.
        await self._quitar_modal_js()
        await self._escribir(usuario, self.user)
        await self._escribir(clave, self.password)

        # El botón de envío arranca DISABLED hasta que el form Angular es válido.
        # Esperar a que se habilite en vez de clickear a ciegas (clickear un
        # botón disabled provocaba el timeout de 30s visto en producción).
        await self._enviar_login(enviar, clave)
        logger.info("Credenciales enviadas.")

        # Si el portal pide 2FA manual, damos tiempo generoso la primera vez.
        await self.page.wait_for_timeout(2000)

    async def _enviar_login(self, boton, campo_clave) -> None:
        """
        Envía el formulario esperando a que el botón se habilite. Si tras el
        timeout sigue deshabilitado, cae a un fallback: Enter en el campo de
        contraseña (muchos formularios envían con Enter aunque el botón siga
        pintado como disabled por un instante).
        """
        try:
            await boton.wait_for(state="visible", timeout=settings.TIMEOUT_ELEMENT)
        except Exception:
            pass

        intentos = max(1, int(settings.TIMEOUT_ELEMENT / 500))
        for _ in range(intentos):
            try:
                if await boton.is_enabled():
                    await boton.click()
                    return
            except Exception:
                pass
            await self.page.wait_for_timeout(500)

        logger.warning("El botón de login sigue deshabilitado — intento enviar con Enter.")
        try:
            await campo_clave.press("Enter")
        except Exception as e:
            logger.warning(f"No se pudo enviar el login (botón disabled y Enter falló): {e}")

    async def _esperar_listo(self) -> None:
        """Espera a que la app cargue tras el login (ready selector/URL o 2FA)."""
        try:
            if settings.READY_SELECTOR:
                await self.page.locator(settings.READY_SELECTOR).first.wait_for(
                    state="visible", timeout=settings.TIMEOUT_2FA)
            elif settings.READY_URL_PATTERN:
                await self.page.wait_for_url(settings.READY_URL_PATTERN,
                                             timeout=settings.TIMEOUT_2FA)
            else:
                await self.page.wait_for_load_state("networkidle",
                                                    timeout=settings.TIMEOUT_ELEMENT)
        except Exception:
            logger.warning("No se confirmó 'ready' tras login — continuando.")

    async def _guardar_sesion(self) -> None:
        settings.SESSION_DIR.mkdir(parents=True, exist_ok=True)
        await self.context.storage_state(path=str(self.storage_state))
        # Marca la sesión con el usuario que la generó (para invalidarla si
        # cambian las credenciales).
        marcar_sesion(self.storage_state, self.user)
        logger.info(f"Sesión guardada en {self.storage_state} (usuario: {self.user})")


# ── Selección de agencia (perfil MULTIAGENTE) ───────────────────────────────

# Selectores del BUSCADOR del modal de agencia (login o header 'Select an agency').
_AGENCY_SEARCH_SELS = [
    "[data-testid='multi-agency-search-input']",
    "input[placeholder*='code or telephone' i]",
    "input[placeholder*='name, code' i]",
    "input[placeholder*='código' i]",
    "input[placeholder*='nombre, código' i]",
]


async def modal_agencia_visible(page) -> bool:
    """True si el modal 'Select an agency' está en pantalla (su buscador visible)."""
    for sel in _AGENCY_SEARCH_SELS:
        try:
            if await page.locator(sel).first.is_visible():
                return True
        except Exception:
            continue
    return False


async def seleccionar_agencia(page, agency: str, timeout: int = 30_000) -> bool:
    """Tras el login multiagente aparece el modal de selección de agencia.
    Busca la agencia por código y selecciona la primera fila. Confirma el PC
    si aparece. Devuelve True si seleccionó; False si el modal no apareció
    (agencia ya seleccionada de una sesión previa).

    Detecta el modal por VARIOS selectores del buscador, porque el modal del
    LOGIN y el del HEADER ('Select an agency' en Reportes) pueden diferir:
      • login  : data-testid='multi-agency-search-input'
      • header : input con placeholder 'Search by name, code or telephone'
    Luego filtra por el código y clickea la fila. Confirma el PC si aparece.
    """
    import time as _t
    import os as _os

    # ── REGLA DE ORO (PRODUCCIÓN) ────────────────────────────────────────────
    # En PROD la agencia multiagente SIEMPRE debe ser 0020-TX (ninguna otra). Si
    # el caller pide otra —por una config vieja, un override, o un error— se
    # FUERZA a 0020-TX y se registra el intento. Blindaje central: cualquier
    # flujo multiagente que pase por aquí queda protegido, sin tocar cada test.
    if getattr(settings, "_ES_PROD", False):
        _prod_ag = _os.getenv("PROD_AGENCY_CODE", "0020-TX")
        if str(agency or "").strip().upper() != _prod_ag.strip().upper():
            logger.warning("[Multi] REGLA DE ORO (producción): agencia '%s' NO "
                           "permitida — se FUERZA '%s'.", agency, _prod_ag)
        agency = _prod_ag

    # Selectores ESPECÍFICOS del buscador de agencia (evitar fallback amplio que
    # podría matchear otro input y hacer que se teclee ahí el nombre del cliente).
    search_sels = [
        "[data-testid='multi-agency-search-input']",
        "input[placeholder*='code or telephone' i]",
        "input[placeholder*='name, code' i]",
        "input[placeholder*='código' i]",
        "input[placeholder*='nombre, código' i]",
    ]
    search = None
    deadline = _t.monotonic() + timeout / 1000
    while _t.monotonic() < deadline and search is None:
        for sel in search_sels:
            try:
                loc = page.locator(sel).first
                if await loc.is_visible():
                    search = loc
                    break
            except Exception:
                continue
        if search is None:
            await page.wait_for_timeout(1_000)

    if search is None:
        logger.info("[Multi] Modal de agencia no apareció — agencia ya seleccionada.")
        return False

    await search.click()
    await page.wait_for_timeout(300)
    await search.fill(agency)
    await page.wait_for_timeout(1_500)

    # Clic en la fila del código de agencia (o primera fila filtrada)
    fila_sels = [
        f"tbody tr:has-text('{agency}') td",
        f"tr:has-text('{agency}')",
        "tbody.p-datatable-tbody tr td.text-center",
        "td.text-center",
    ]
    clic = False
    for rs in fila_sels:
        try:
            row = page.locator(rs).first
            await row.wait_for(state="visible", timeout=5_000)
            await row.click(timeout=5_000)
            clic = True
            break
        except Exception:
            continue
    if not clic:
        logger.warning("[Multi] No se pudo clicar la fila de agencia '%s'.", agency)
        return False
    await page.wait_for_timeout(1_500)

    # Confirmación PC: modal "Éxito — agencia de comunicación 'PC'. ¿Desea
    # continuar?" con botón "SÍ, Continuar"/"YES, Continue". Solo aparece para
    # agencias tipo PC; se espera un momento por si tarda en montar.
    candidatos = [
        page.get_by_role("button", name=_RE_SI_CONTINUAR),
        page.get_by_test_id("test-id-button").filter(has_text=_RE_SI_CONTINUAR),
        page.get_by_test_id("agency-alert-btn-continue"),
    ]
    for cand in candidatos:
        try:
            btn = cand.first
            # Timeout CORTO: si NO hay confirmación PC (2ª selección de agencia),
            # no perder 8s por cada candidato — se salta rápido.
            await btn.wait_for(state="visible", timeout=3_000)
            await btn.click()
            await page.wait_for_timeout(1_500)
            logger.info("[Multi] Confirmación PC 'SÍ, Continuar' pulsada.")
            break
        except Exception:
            continue

    logger.info("[Multi] Agencia '%s' seleccionada.", agency)
    return True
