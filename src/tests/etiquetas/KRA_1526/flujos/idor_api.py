"""
Cliente de replay IDOR — el «Page Object» de esta etiqueta, pero sobre HTTP.

Toma el `Baseline` capturado (token + IdUser/IdAgent propios + url/body reales)
y reproduce variantes permutando los IDs, exactamente como se haría a mano
editando el curl — solo que el curl se capturó solo.

Veredictos honestos (mismo espíritu que TRN-239):
  · Bloqueo correcto  = HTTP 403 (o de CODIGOS_BLOQUEO) y SIN datos de clientes.
  · Baseline correcto = HTTP 200 y CON datos.
  · Fuga IDOR         = 200 con datos al enviar un ID ajeno  → FALLA.
  · Endpoint ausente  = 404/timeout: nadie que rechace → no comprobable
                        (el caso decide si es FALLA o se omite).
"""

from __future__ import annotations

import re
import time
import urllib.parse

from config.logger import get_logger

from .. import parametros as P

logger = get_logger("KRA-1526.api")

try:
    import requests
except ImportError:                                          # pragma: no cover
    requests = None


class Resp:
    """Lo que devolvió el endpoint, ya interpretado."""

    def __init__(self, url, metodo, status, body, texto, ms, error=""):
        self.url = url
        self.metodo = metodo
        self.status = status
        self.body = body if isinstance(body, dict) else {}
        self.texto = texto or ""
        self.ms = ms
        self.error = error

    @property
    def endpoint_existe(self) -> bool:
        return self.status not in P.SIN_ENDPOINT

    @property
    def es_bloqueo(self) -> bool:
        """La aplicación existió y RECHAZÓ (403 u otro código de bloqueo)."""
        return self.endpoint_existe and self.status in P.CODIGOS_BLOQUEO

    def total_records(self):
        data = self.body.get("data") or {}
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

    def tiene_datos(self) -> bool:
        """True si la respuesta trae clientes (indicador de acceso/fuga)."""
        data = self.body.get("data") or {}
        if isinstance(data, dict):
            cust = data.get("customers")
            if isinstance(cust, list):
                return len(cust) > 0
            tr = data.get("totalRecords", data.get("total"))
            try:
                return int(tr) > 0
            except Exception:
                return bool(data) and cust is not None
        if isinstance(data, list):
            return len(data) > 0
        # Fallback textual para endpoints que no sean el de búsqueda.
        return bool(re.search(r'"idCustomer"|"customers"\s*:\s*\[', self.texto))

    def id_agents(self) -> set:
        data = self.body.get("data") or {}
        out = set()
        clientes = data.get("customers") if isinstance(data, dict) else None
        if isinstance(clientes, list):
            for c in clientes:
                if isinstance(c, dict):
                    v = c.get("idAgent", c.get("IdAgent"))
                    if v is not None:
                        out.add(str(v))
        return out

    def resumen(self) -> str:
        if self.error:
            return f"sin respuesta ({self.error[:90]})"
        tr = self.total_records()
        return (f"HTTP {self.status} · datos={'sí' if self.tiene_datos() else 'no'}"
                f"{f' · totalRecords={tr}' if tr is not None else ''} · {self.ms} ms")


# ── Reemplazo de IdUser / IdAgent respetando dónde viven ─────────────────────

def _sub_query(url: str, nombre: str, valor: str) -> str:
    return re.sub(r'(?i)([?&]' + nombre + r'=)([^&#]+)',
                  lambda m: m.group(1) + urllib.parse.quote(str(valor)),
                  url, count=1)


def _sub_body(body: str, nombre: str, valor: str) -> str:
    return re.sub(r'(?i)("' + nombre + r'"\s*:\s*)"?\d+"?',
                  lambda m: m.group(1) + str(valor), body, count=1)


def _sub_valor(texto: str, viejo, nuevo) -> str:
    """Reemplaza el VALOR `viejo` por `nuevo` como número completo (sin partir
    otros números). Agnóstico al nombre del parámetro."""
    if not texto or not viejo:
        return texto
    return re.sub(r'(?<!\d)' + re.escape(str(viejo)) + r'(?!\d)', str(nuevo), texto)


# ── Envío HTTP ────────────────────────────────────────────────────────────────

# Cabeceras que NO se deben reenviar: las gestiona el cliente HTTP o son de
# transporte. El resto (token, accept, referer, origin, cabeceras propias del
# canal Hermes…) se reenvía TAL CUAL para reproducir fielmente el request que el
# navegador mandó y que respondió 200 — reenviar solo un subconjunto provocaba
# HTTP 400 en el replay aunque los IDs fueran los propios.
_DROP_HEADERS = {
    "host", "content-length", "connection", "accept-encoding",
    "content-encoding", "transfer-encoding",
    ":authority", ":method", ":path", ":scheme",
}


def _headers_desde(base, extra: dict = None) -> dict:
    """Reenvía TODAS las cabeceras capturadas menos las de transporte."""
    h = {k: v for k, v in (base.headers or {}).items()
         if k.lower() not in _DROP_HEADERS}
    if extra:
        h.update(extra)
    return h


def enviar(url: str, metodo: str, headers: dict, body=None) -> Resp:
    if requests is None:
        return Resp(url, metodo, 0, {}, "", 0, error="falta el paquete `requests`")
    t0 = time.time()
    try:
        r = requests.request(metodo, url, headers=headers,
                             data=body.encode("utf-8") if isinstance(body, str) else body,
                             timeout=P.TIMEOUT, verify=False)
    except Exception as e:
        return Resp(url, metodo, 0, {}, "", int((time.time() - t0) * 1000),
                    error=str(e))
    ms = int((time.time() - t0) * 1000)
    texto = r.text or ""
    try:
        cuerpo = r.json()
        if not isinstance(cuerpo, dict):
            cuerpo = {"_valor": cuerpo}
    except Exception:
        cuerpo = {}
    return Resp(url, metodo, r.status_code, cuerpo, texto, ms)


# ── Operaciones sobre la BÚSQUEDA GLOBAL (capturada) ─────────────────────────

def replay_capturado(cap: dict, cambios: dict = None) -> Resp:
    """Reproduce un endpoint CAPTURADO en vivo (dict de base.extra), permutando
    IdUser/IdAgent donde vivan (query o body). Usa el método, url, body y
    cabeceras reales capturados — ruta y params exactos, sin inferir."""
    url = cap.get("url", "")
    body = cap.get("post_data")
    for nombre, valor in (cambios or {}).items():
        loc = cap.get("loc_user") if nombre.lower() == "iduser" else cap.get("loc_agent")
        if loc == "query":
            url = _sub_query(url, nombre, valor)
        elif loc == "body" and body:
            body = _sub_body(body, nombre, valor)
    headers = {k: v for k, v in (cap.get("headers") or {}).items()
               if k.lower() not in _DROP_HEADERS}
    r = enviar(url, cap.get("metodo", "GET"), headers, body)
    logger.info("[API] replay capturado %s → %s", cambios or "(propios)", r.resumen())
    return r


def replay_valor(cap: dict, viejo, nuevo) -> Resp:
    """Reproduce un endpoint capturado reemplazando un VALOR (p. ej. el IdUser
    propio) por otro en url y body — agnóstico al nombre del parámetro."""
    url = _sub_valor(cap.get("url", ""), viejo, nuevo)
    body = cap.get("post_data")
    if body:
        body = _sub_valor(body, viejo, nuevo)
    headers = {k: v for k, v in (cap.get("headers") or {}).items()
               if k.lower() not in _DROP_HEADERS}
    r = enviar(url, cap.get("metodo", "GET"), headers, body)
    logger.info("[API] replay valor %s→%s → %s", viejo, nuevo, r.resumen())
    return r


def id_distinto_de(cap: dict, id_agent) -> str:
    """Extrae del request capturado el id numérico de query que NO es el IdAgent
    (candidato a IdUser), cuando el parámetro no se llama literalmente IdUser."""
    import urllib.parse as _up
    try:
        qs = _up.urlparse(cap.get("url", "")).query
        for _, vals in _up.parse_qs(qs).items():
            for v in vals:
                if v.isdigit() and str(v) != str(id_agent):
                    return v
    except Exception:
        pass
    return ""


def replay_busqueda(base, cambios: dict = None) -> Resp:
    """Reproduce la búsqueda global del baseline. `cambios` = {'IdUser': valor,
    'IdAgent': valor}; cada ID se reemplaza donde viva (query o body)."""
    url = base.url
    body = base.post_data
    for nombre, valor in (cambios or {}).items():
        loc = base.loc_user if nombre.lower() == "iduser" else base.loc_agent
        if loc == "query":
            url = _sub_query(url, nombre, valor)
        elif loc == "body" and body:
            body = _sub_body(body, nombre, valor)
    r = enviar(url, base.metodo, _headers_desde(base), body)
    logger.info("[API] búsqueda %s → %s",
                cambios or "(propios)", r.resumen())
    return r


# ── Cobertura: otros endpoints con IdUser / IdAgent ──────────────────────────

def _fechas_rango(dias: int = 7):
    import datetime as _dt
    fin = _dt.date.today()
    ini = fin - _dt.timedelta(days=dias)
    return ini.isoformat(), fin.isoformat()


def _fechas_balance():
    """dateFrom = primero del mes 00:00:00 · dateTo = hoy 00:00:00 (como el
    request real capturado)."""
    import datetime as _dt
    hoy = _dt.date.today()
    ini = hoy.replace(day=1)
    return f"{ini.isoformat()}T00:00:00", f"{hoy.isoformat()}T00:00:00"


def _authorizer_desde(base) -> str:
    """El JWT para el header `authorizer` del host de lambdas: se toma del
    `authorization: Bearer <jwt>` capturado en la sesión, quitando 'Bearer '."""
    tok = (base.headers.get("authorization") or "").strip()
    if tok.lower().startswith("bearer "):
        tok = tok[7:].strip()
    return tok


def balance_por_cajero(base, id_user, id_agent, url: str = None) -> Resp:
    """`GET {lambdas}/api/reports/balance_by_cashier?dateFrom&dateTo&idAgent&idUser`.

    Host de LAMBDAS y header `authorizer` (JWT sin 'Bearer'), tomado FRESCO de la
    sesión — así el token nunca se hardcodea. Si `url` viene (KRA1526_BALANCE_URL),
    se usa esa URL tal cual (útil para fijar ids/fechas exactos)."""
    if url:
        u = url
    else:
        ini, fin = _fechas_balance()
        u = (f"{P.BALANCE_HOST}{P.RUTA_BALANCE_CAJERO}"
             f"?dateFrom={ini}&dateTo={fin}"
             f"&idAgent={urllib.parse.quote(str(id_agent))}"
             f"&idUser={urllib.parse.quote(str(id_user))}")
    headers = _headers_desde(base)
    az = _authorizer_desde(base)
    if az:
        headers["authorizer"] = az           # el header que exige el host lambdas
    r = enviar(u, "GET", headers)
    logger.info("[API] balance_by_cashier idUser=%s idAgent=%s → %s",
                id_user, id_agent, r.resumen())
    return r


def reporte_transacciones(base, id_agent, is_mono: bool = True) -> Resp:
    """`POST {host}/api/transactions/reports/money_transfers` con body
    {idAgent, isMonoAgent, beginDate, endDate}. Ruta inferida del análisis."""
    import json as _json
    host = base.host or P.BASE_URL
    ini, fin = _fechas_rango()
    body = _json.dumps({"idAgent": int(id_agent) if str(id_agent).isdigit() else id_agent,
                        "isMonoAgent": bool(is_mono),
                        "beginDate": ini, "endDate": fin})
    headers = _headers_desde(base)
    headers["content-type"] = "application/json"
    r = enviar(f"{host}{P.RUTA_MONEY_TRANSFERS}", "POST", headers, body)
    logger.info("[API] money_transfers idAgent=%s isMonoAgent=%s → %s",
                id_agent, is_mono, r.resumen())
    return r


# ── Veredictos ────────────────────────────────────────────────────────────────

def veredicto_baseline(r: Resp) -> tuple:
    """(resultado, detalle) — se espera 200 CON datos."""
    if not r.endpoint_existe:
        return False, (f"el endpoint no respondió (HTTP {r.status}); no hay "
                       f"baseline que comparar · {r.resumen()}")
    if r.status == 200 and r.tiene_datos():
        return True, r.resumen()
    if r.status == 200:
        return False, f"200 pero SIN datos: el baseline debería traer clientes · {r.resumen()}"
    return False, f"se esperaba 200 con datos · {r.resumen()}"


def veredicto_bloqueo(r: Resp, que: str) -> tuple:
    """(resultado, detalle) — se espera bloqueo (403) y SIN datos.

      · bloqueo + sin datos  → True
      · 200 con datos        → False (fuga IDOR: {que} NO se validó)
      · endpoint ausente     → False (no hay quién rechace: una prueba de
                               seguridad que no pudo ejecutarse no aprueba;
                               CP05/CP06 se omiten antes si su ruta inferida no
                               responde, así que aquí un ausente es anómalo)
    """
    if not r.endpoint_existe:
        return False, (f"el endpoint no respondió (HTTP {r.status}): no hay "
                       f"nadie que rechace, no se pudo comprobar {que} · "
                       f"{r.resumen()}")
    if r.tiene_datos():
        return False, (f"FUGA IDOR: la API devolvió datos con {que} · "
                       f"{r.resumen()}")
    if r.status == 200:
        # 200 (aunque no reconozcamos el cuerpo como 'datos') = NO fue bloqueado.
        return False, (f"FUGA IDOR: HTTP 200 con {que} — la petición NO fue "
                       f"bloqueada · {r.resumen()}")
    if r.es_bloqueo:
        return True, r.resumen()
    # Sin datos pero con un código inesperado (p. ej. 400/422): es un rechazo,
    # se acepta como bloqueo pero se anota el código real.
    return True, f"rechazado sin datos (código {r.status}, se esperaba 403) · {r.resumen()}"


def _identidad(body) -> tuple:
    """Firma de la IDENTIDAD de los datos devueltos, para detectar fuga cruzada.
    Distingue el 'de quién son' los datos: clientes (búsqueda) o agencia (balance)."""
    import json as _json
    d = (body or {}).get("data") or {}
    if isinstance(d, dict):
        cust = d.get("customers")
        if isinstance(cust, list):
            ids = tuple(sorted(
                (str(c.get("idCustomer")) if isinstance(c, dict) and c.get("idCustomer") is not None
                 else _json.dumps(c, sort_keys=True, default=str)) for c in cust))
            return ("cust", ids)                     # () si viene vacío
        if "agentCode" in d or "agentName" in d:     # balance por cajero
            return ("agent", str(d.get("agentCode") or d.get("agentName") or ""))
    if isinstance(d, list):
        return ("list", len(d))
    return None


def _vacio(ident) -> bool:
    return (ident is None
            or (ident[0] == "cust" and len(ident[1]) == 0)
            or (ident[0] == "list" and ident[1] == 0))


def veredicto_idor(r: Resp, base_body, que: str) -> tuple:
    """(resultado, detalle) — veredicto IDOR por IDENTIDAD de los datos.

    La propiedad de seguridad real: manipular un id NO debe exponer datos de otra
    identidad. Desenlaces seguros: bloqueo (403), o 200 devolviendo SOLO los datos
    propios (el server ignoró el id ajeno), o 200 vacío. Fuga: 200 con datos de
    OTRA identidad.
    """
    if not r.endpoint_existe:
        return False, (f"el endpoint no respondió (HTTP {r.status}): no se pudo "
                       f"comprobar {que} · {r.resumen()}")
    if r.es_bloqueo:
        return True, f"bloqueado (HTTP {r.status}) sin datos · {r.resumen()}"
    if r.status != 200:
        # 400/422 u otro rechazo sin 200: cuenta como rechazo (no expuso nada).
        return True, f"rechazado (HTTP {r.status}) · {r.resumen()}"
    ir = _identidad(r.body)
    ib = _identidad(base_body)
    if _vacio(ir):
        return True, f"HTTP 200 sin datos (sin fuga) · {r.resumen()}"
    if ib is not None and ir == ib:
        return True, (f"HTTP 200: el servidor IGNORÓ el id ajeno y devolvió SOLO "
                      f"los datos propios (sin fuga cruzada) · {r.resumen()}")
    return False, (f"FUGA IDOR: HTTP 200 con datos de OTRA identidad al enviar "
                   f"{que} · {r.resumen()}")


def veredicto_disenio_idagent(r: Resp) -> tuple:
    """(resultado, detalle) — caso de DISEÑO multi-agente: cambiar el IdAgent NO
    debe bloquear; el middleware no lo valida y responde 200.

      · 200               → True  (IdAgent ignorado, por diseño)
      · 403               → False (SÍ se validó: contradice la regla multi)
      · endpoint ausente  → False (no se pudo confirmar)
    """
    if r.status == 403:
        return False, ("HTTP 403: el IdAgent SÍ se validó — contradice la regla "
                       f"multi-agente (debería responder 200) · {r.resumen()}")
    if not r.endpoint_existe:
        return False, (f"el endpoint no respondió (HTTP {r.status}); no se pudo "
                       f"confirmar el diseño · {r.resumen()}")
    if r.status == 200:
        return True, f"HTTP 200 — el IdAgent no se valida, por diseño · {r.resumen()}"
    return False, (f"se esperaba HTTP 200 (diseño multi-agente); código "
                   f"{r.status} · {r.resumen()}")
