"""
Captura EN VIVO del request de la búsqueda global — el paso que reemplaza al
«copiar el curl del navegador» a mano.

Qué hace, sin que el usuario toque nada:
  1. Abre Hermes 2 con la sesión persistente (login solo si expiró).
  2. Cierra el modal de notificaciones si aparece.
  3. Teclea el teléfono de prueba en el buscador de cliente de Money Transfer.
     Eso dispara `GET /api/bff/customer/search?...IdUser=..&IdAgent=..` con el
     token en la cabecera Authorization.
  4. Intercepta ESE request y su respuesta 200.
  5. Devuelve un `Baseline` con: método, url, host, cabeceras (token incluido),
     body (si POST), IdUser/IdAgent propios y su ubicación (query/body), y la
     respuesta 200 (totalRecords + IdAgent de los clientes) para la regresión.

El navegador se cierra al terminar: el resto de la corrida reproduce las
variantes con `requests` usando el token capturado (dura ~20 min).
"""

from __future__ import annotations

import re
import urllib.parse

from playwright.async_api import async_playwright

from config import settings
from config.logger import get_logger

from .. import parametros as P

logger = get_logger("KRA-1526.captura")

# Campo de teléfono del cliente en Money Transfer (dispara /customer/search).
_TESTIDS_TELEFONO = (
    "transfer-customer-cellphone-0-cellphone-input",
    "customer-billpay-form-phone-input",
)
_RE_BUSQUEDA = re.compile(r"customer/search|customer%2Fsearch", re.I)


class Baseline:
    """El request real de la búsqueda global, ya interpretado."""

    def __init__(self):
        self.perfil = "mono"
        self.extra = {}             # endpoints extra capturados (balance, money_transfers)
        self.metodo = "GET"
        self.url = ""
        self.host = ""              # https://host  (para construir otros endpoints)
        self.headers = {}           # incluye 'authorization'
        self.post_data = None       # cuerpo crudo si fue POST
        self.id_user = None
        self.id_agent = None
        self.loc_user = None        # 'query' | 'body'
        self.loc_agent = None
        self.resp_status = None
        self.resp_body = None       # dict del JSON de respuesta (baseline 200)

    @property
    def token(self) -> str:
        return self.headers.get("authorization", "")

    @property
    def total_records(self):
        d = self.resp_body if isinstance(self.resp_body, dict) else {}
        data = d.get("data") or {}
        if isinstance(data, dict):
            tr = data.get("totalRecords", data.get("total", data.get("totalCount")))
            if tr is not None:
                return tr
            cust = data.get("customers")
            if isinstance(cust, list):
                return len(cust)
        if isinstance(data, list):
            return len(data)
        return None

    def id_agents_en_respuesta(self) -> set:
        """Conjunto de idAgent de los clientes devueltos (para la regresión)."""
        d = self.resp_body if isinstance(self.resp_body, dict) else {}
        data = d.get("data") or {}
        clientes = data.get("customers") if isinstance(data, dict) else None
        out = set()
        if isinstance(clientes, list):
            for c in clientes:
                if isinstance(c, dict):
                    v = c.get("idAgent", c.get("IdAgent"))
                    if v is not None:
                        out.add(str(v))
        return out

    def resumen(self) -> str:
        return (f"{self.metodo} {self.url[:90]} · IdUser={self.id_user}"
                f"({self.loc_user}) IdAgent={self.id_agent}({self.loc_agent}) · "
                f"HTTP {self.resp_status} · totalRecords={self.total_records}")

    def valido(self) -> bool:
        return bool(self.url and self.id_user and self.id_agent
                    and self.token and self.resp_status == 200)


def _buscar_param(texto: str, nombre: str):
    """Devuelve ('query'|'body', valor) buscando IdUser/IdAgent en query o body."""
    if not texto:
        return None, None
    m = re.search(r'(?i)[?&]' + nombre + r'=([^&#\s"\']+)', texto)
    if m:
        return "query", urllib.parse.unquote(m.group(1))
    m = re.search(r'(?i)"' + nombre + r'"\s*:\s*"?(\d+)"?', texto)
    if m:
        return "body", m.group(1)
    return None, None


async def _req_a_dict(req, resp=None) -> dict:
    """Serializa un request (y su respuesta) capturado a un dict reutilizable."""
    try:
        headers = {k.lower(): v for k, v in (await req.all_headers()).items()}
    except Exception:
        headers = {k.lower(): v for k, v in (req.headers or {}).items()}
    try:
        post = req.post_data
    except Exception:
        post = None
    host = "{u.scheme}://{u.netloc}".format(u=urllib.parse.urlparse(req.url))
    texto = req.url + " " + (post or "")
    lu, iu = _buscar_param(texto, "IdUser")
    la, ia = _buscar_param(texto, "IdAgent")
    d = {"metodo": req.method, "url": req.url, "host": host, "headers": headers,
         "post_data": post, "loc_user": lu, "id_user": iu,
         "loc_agent": la, "id_agent": ia, "resp_status": None, "resp_body": None}
    if resp is not None:
        d["resp_status"] = resp.status
        try:
            d["resp_body"] = await resp.json()
        except Exception:
            try:
                d["resp_body"] = {"_texto": (await resp.text())[:1200]}
            except Exception:
                pass
    return d


async def _seleccionar_primer_cajero(page) -> bool:
    """Abre el primer desplegable visible del reporte por cajero y elige la 1ª
    opción real. Genérico (PrimeNG/select), best-effort: sin esto el reporte no
    dispara su petición y el botón Buscar queda deshabilitado."""
    selectores = ["p-dropdown", "[role='combobox']", "select",
                  ".p-dropdown", "p-multiselect"]
    opciones_sel = ("li[role='option']", ".p-dropdown-item", "[role='option']",
                    ".p-multiselect-item", "option")
    for s in selectores:
        loc = page.locator(s)
        try:
            total = min(await loc.count(), 6)
        except Exception:
            total = 0
        for i in range(total):
            dd = loc.nth(i)
            try:
                if not await dd.is_visible():
                    continue
                await dd.click(force=True, timeout=3_000)
                await page.wait_for_timeout(700)
                for os_ in opciones_sel:
                    op = page.locator(os_)
                    try:
                        if await op.count() and await op.first.is_visible():
                            await op.first.click(force=True, timeout=3_000)
                            await page.wait_for_timeout(600)
                            logger.info("[Captura] Cajero/opción seleccionada "
                                        "(%s).", s)
                            return True
                    except Exception:
                        continue
            except Exception:
                continue
    logger.info("[Captura] No hallé un desplegable de cajero para seleccionar.")
    return False


async def _pulsar_buscar_cajero(page) -> bool:
    """Pulsa Buscar en Balance por Cajero: por testid y, si falla, por texto."""
    try:
        btn = page.get_by_test_id("reports-by-cashier-search-button").first
        await btn.click(timeout=5_000)
        logger.info("[Captura] Buscar (por cajero) pulsado por testid.")
        return True
    except Exception:
        pass
    try:
        btn = page.get_by_role("button", name=re.compile(r"buscar|search", re.I)).first
        await btn.click(timeout=5_000)
        logger.info("[Captura] Buscar (por cajero) pulsado por texto.")
        return True
    except Exception:
        logger.info("[Captura] No se pudo pulsar Buscar por cajero.")
        return False


async def _capturar_reportes(page, base) -> None:
    """Best-effort: abre Reportes → Balance por Cajero y CAPTURA su request real
    (el que lleva IdUser E IdAgent), para que CP05 reproduzca ruta/params/headers
    exactos en vez de inferirlos.

    La captura es AMPLIA a propósito: en la fase de balance, cualquier request al
    API de Hermes que lleve IdUser Y IdAgent (y que NO sea la búsqueda de cliente)
    es el endpoint de balance — así no dependemos de acertar su nombre exacto.

    NOTA: no navegamos a Reporte de transacciones aquí; CP06 usa su ruta (que ya
    responde 200 con el token capturado) y esa navegación colgaba la sesión."""
    _RE_HOST = re.compile(r"maxilabs\.net", re.I)
    idagent = str(base.id_agent or "")
    cap = {"balance": None}
    resps = {}
    users = {"ok": False}

    def _es_balance(req) -> bool:
        # El request de BALANCE por cajero lleva el IdAgent (6485) Y el IdUser del
        # cajero (otro id). Excluimos la búsqueda de cliente y el catálogo de
        # cajeros (users_by_agent), que solo trae el IdAgent. Detección agnóstica
        # al nombre del parámetro: 'balance' en la URL, o IdAgent + otro id.
        try:
            texto = req.url + " " + (req.post_data or "")
        except Exception:
            texto = req.url
        low = texto.lower()
        if "customer/search" in low or "users_by_agent" in low:
            return False
        if "balance" in low:
            return True
        if idagent and re.search(r"(?<!\d)" + re.escape(idagent) + r"(?!\d)", texto):
            otros = [n for n in re.findall(r"\d{4,}", texto) if n != idagent]
            return bool(otros)
        return False

    def _on_req(req):
        try:
            if cap["balance"] is None and _RE_HOST.search(req.url) and _es_balance(req):
                cap["balance"] = req
        except Exception:
            pass

    def _on_resp(resp):
        try:
            if _RE_HOST.search(resp.url):
                resps[resp.url] = resp
                if "users_by_agent" in resp.url.lower():
                    users["ok"] = True
        except Exception:
            pass

    page.on("request", _on_req)
    page.on("response", _on_resp)
    try:
        from src.sanity_general import balance as BAL
        if await BAL.abrir_balance_por_cajero(page):
            # 1) Esperar a que cargue el catálogo de cajeros (users_by_agent):
            #    hasta que llega, el desplegable de cajero está vacío.
            for _ in range(20):
                if users["ok"]:
                    break
                await page.wait_for_timeout(300)
            await BAL._cerrar_warning(page)     # cierra 'Yes, Leave' si tapa la UI
            # 2) Seleccionar un cajero (con reintentos; el control aparece tras
            #    cargar el catálogo). Cerramos el modal entre intentos.
            for _ in range(3):
                if await _seleccionar_primer_cajero(page):
                    break
                await BAL._cerrar_warning(page)
                await page.wait_for_timeout(900)
            await BAL._cerrar_warning(page)
            # 3) Buscar → dispara balance_by_cashier.
            await _pulsar_buscar_cajero(page)
            await BAL._cerrar_warning(page)
            await page.wait_for_timeout(4_000)
    except Exception as e:
        logger.warning("[Captura] Balance por Cajero no capturado: %s", str(e)[:120])
    finally:
        try:
            page.remove_listener("request", _on_req)
            page.remove_listener("response", _on_resp)
        except Exception:
            pass

    req = cap["balance"]
    if req is not None:
        try:
            base.extra["balance"] = await _req_a_dict(req, resps.get(req.url))
            e = base.extra["balance"]
            logger.info("[Captura] Reporte 'balance' capturado: %s %s · HTTP %s",
                        e["metodo"], e["url"][:90], e["resp_status"])
        except Exception:
            pass
    else:
        logger.info("[Captura] No se capturó un request de balance con "
                    "IdUser/IdAgent (CP05 caerá a la ruta inferida).")


async def _cerrar_notificaciones(page) -> None:
    try:
        from src.pages.hm_transferelektra_page import HmTransferelektraPage
        flow = HmTransferelektraPage(page)
        await flow.handle_notifications_modal()
    except Exception:
        pass


async def _teclear_telefono(page, telefono: str) -> bool:
    for testid in _TESTIDS_TELEFONO:
        try:
            inp = page.get_by_test_id(testid).first
            if await inp.count() == 0:
                continue
            await inp.click(force=True, timeout=4_000)
            try:
                await inp.fill("")
            except Exception:
                pass
            await inp.press_sequentially(telefono, delay=60)
            logger.info("[Captura] Teléfono tecleado en '%s'.", testid)
            return True
        except Exception:
            continue
    return False


async def capturar_baseline(perfil: str = "mono", agency: str = None) -> Baseline:
    """Ejecuta el login + búsqueda y devuelve el Baseline capturado.

    `perfil`: 'mono' (default) o 'multi'. En multi usa las credenciales
    multiagente, su propio storage_state, y SELECCIONA la agencia `agency`
    (p. ej. '0040') antes de buscar."""
    es_multi = str(perfil).lower() == "multi"
    if es_multi:
        storage = settings.STORAGE_STATE_MULTI
        user = settings.PORTAL_USER_MULTI
        password = settings.PORTAL_PASS_MULTI
    else:
        storage = settings.STORAGE_STATE
        user = password = None

    base = Baseline()
    base.perfil = perfil
    async with async_playwright() as pw:
        navegador = await pw.chromium.launch(
            headless=settings.PW_HEADLESS, slow_mo=settings.PW_SLOW_MO,
            args=["--ignore-certificate-errors", "--allow-insecure-localhost"])
        kwargs = {"viewport": {"width": 1366, "height": 768},
                  "ignore_https_errors": True}
        if storage.exists():
            kwargs["storage_state"] = str(storage)
        contexto = await navegador.new_context(**kwargs)
        page = await contexto.new_page()

        capturas = {"req": None}
        respuestas = []

        def _on_request(req):
            try:
                if capturas["req"] is None and _RE_BUSQUEDA.search(req.url):
                    capturas["req"] = req
            except Exception:
                pass

        def _on_response(resp):
            try:
                if _RE_BUSQUEDA.search(resp.url) and resp.status == 200:
                    respuestas.append(resp)
            except Exception:
                pass

        page.on("request", _on_request)
        page.on("response", _on_response)

        try:
            from src.helpers.session_helper import SessionHelper
            helper = SessionHelper(contexto, page, user=user, password=password,
                                   storage_state=storage)
            await helper.ensure_logged_in()

            if es_multi:
                # El perfil multiagente pasa por el modal de selección de agencia
                # (no por el de notificaciones). Selecciona la agencia pedida y
                # re-guarda la sesión ya con la agencia fijada.
                from src.helpers.session_helper import seleccionar_agencia
                try:
                    selecciono = await seleccionar_agencia(page, agency)
                    if selecciono:
                        await page.wait_for_timeout(1_500)
                        settings.SESSION_DIR.mkdir(parents=True, exist_ok=True)
                        await contexto.storage_state(path=str(storage))
                    logger.info("[Captura·multi] Agencia '%s' %s.", agency,
                                "seleccionada" if selecciono else
                                "ya activa (modal no apareció)")
                except Exception as e:
                    logger.warning("[Captura·multi] Selección de agencia '%s': %s",
                                   agency, str(e)[:120])
            else:
                await _cerrar_notificaciones(page)

            # Asegurar que estamos en el formulario de transferencias.
            try:
                if "/transfers" not in page.url:
                    await page.goto(settings.APP_URL, wait_until="domcontentloaded",
                                    timeout=settings.TIMEOUT_NAVIGATION)
                    await page.wait_for_timeout(1_500)
            except Exception:
                pass

            if not await _teclear_telefono(page, P.TELEFONO_PRUEBA):
                logger.warning("[Captura] No encontré el campo de teléfono para "
                               "disparar la búsqueda global.")
                return base

            # Esperar a que aparezca el request de búsqueda.
            for _ in range(40):
                if capturas["req"] is not None:
                    break
                await page.wait_for_timeout(300)

            req = capturas["req"]
            if req is None:
                logger.warning("[Captura] No se interceptó el request de "
                               "/customer/search tras teclear el teléfono.")
                return base

            base.metodo = req.method
            base.url = req.url
            try:
                base.headers = {k.lower(): v for k, v in (await req.all_headers()).items()}
            except Exception:
                base.headers = {k.lower(): v for k, v in (req.headers or {}).items()}
            try:
                base.post_data = req.post_data
            except Exception:
                base.post_data = None
            base.host = "{u.scheme}://{u.netloc}".format(
                u=urllib.parse.urlparse(req.url))

            texto = base.url + " " + (base.post_data or "")
            base.loc_user, base.id_user = _buscar_param(texto, "IdUser")
            base.loc_agent, base.id_agent = _buscar_param(texto, "IdAgent")

            # Respuesta 200 (esperar a que llegue y leer el body).
            for _ in range(30):
                if respuestas:
                    break
                await page.wait_for_timeout(300)
            if respuestas:
                resp = respuestas[0]
                base.resp_status = resp.status
                try:
                    base.resp_body = await resp.json()
                except Exception:
                    try:
                        base.resp_body = {"_texto": (await resp.text())[:1500]}
                    except Exception:
                        base.resp_body = None
            logger.info("[Captura] Baseline: %s", base.resumen())
            # CP05 (balance) y CP06 (money_transfers) se resuelven por API con el
            # token de la sesión (contrato real conocido), así que NO navegamos a
            # esos reportes en el navegador — más rápido y sin modales.
            return base
        finally:
            try:
                await contexto.close()
            except Exception:
                pass
            try:
                await navegador.close()
            except Exception:
                pass
