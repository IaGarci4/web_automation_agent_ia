"""
Auditoría del tráfico con el Hardware Agent — KRA-1527.

Qué hace: se engancha a la página de Playwright y registra **todo** lo que el
Front End intercambia con el agente local (`Hermes2Agent.exe`), sea por HTTP o
por WebSocket, y revisa que el JWT **no viaje en texto plano**.

Por qué importa: el volcado de memoria (`memdump_helper`) prueba que el token no
queda *almacenado* en claro. Esta auditoría prueba lo complementario — que no se
*transmita* en claro — y además sirve de **prueba de que la comunicación
ocurrió**. Sin ella, un volcado limpio puede ser un falso negativo: si la
impresión nunca se disparó, no hubo token que exponer y el PASS no vale nada.

El detector de JWT es el MISMO que usa `tools/dump_token_inspector.py`, para que
volcado y tráfico se juzguen con el mismo criterio y no haya discrepancias.

Uso:
    aud = AuditoriaHA(page, caso="CP01")
    await aud.iniciar()
    ...  # el flujo que dispara la impresión
    aud.detener()
    print(aud.veredicto)     # PASS | WARN | FAIL | SIN_TRAFICO
"""

import json
import re
import time
from datetime import datetime

from config import settings
from config.logger import get_logger

# El mismo detector del inspector de volcados: un solo criterio para todo.
from tools.dump_token_inspector import (  # noqa: E402
    RE_JWT_FULL, RE_JWT_FRAG, KEYWORDS, decode_jwt, explicada)

logger = get_logger("kra1527.ha")

# Cabeceras cuyo valor NO se guarda íntegro en el reporte (podría ser el token).
CABECERAS_SENSIBLES = ("authorization", "cookie", "set-cookie", "x-auth-token",
                       "proxy-authorization")
MAX_CUERPO = 4_000          # recorte de cuerpos largos en el reporte


def _texto(dato) -> bytes:
    if dato is None:
        return b""
    if isinstance(dato, bytes):
        return dato
    return str(dato).encode("utf-8", errors="ignore")


def analizar(blob) -> dict:
    """Busca JWT en un bloque de texto/bytes.

    Devuelve {'veredicto', 'jwts', 'fragmentos', 'palabras'} con el MISMO
    criterio del inspector de volcados:
      FAIL → JWT completo que decodifica como token de autenticación.
      WARN → cadenas 'eyJ…' que no decodifican (posible cifrado/parcial).
      PASS → nada relevante.
    """
    datos = _texto(blob)
    resultado = {"veredicto": "PASS", "jwts": [], "fragmentos": 0, "palabras": []}
    if not datos:
        return resultado

    for m in RE_JWT_FULL.finditer(datos):
        info = decode_jwt(m.group(0))
        if info and info.get("is_auth"):
            resultado["jwts"].append({
                "claims": info.get("claim_hits", []),
                "alg": (info.get("header") or {}).get("alg", "?"),
                "usuario": (info.get("payload") or {}).get("preferred_username", ""),
                "largo": info.get("length", 0),
            })
    # Cadenas «eyJ…» que no forman un JWT de auth. Se CLASIFICAN con el mismo
    # criterio que los volcados (`explicada`), en vez de contarlas todas como
    # sospechosas: un cuerpo normal del agente trae respuestas y logs en base64,
    # y marcarlos «revisar» hacía que casi cada petición saliera en ámbar. Un
    # reporte donde todo pide revisión no consigue que se revise nada.
    completos = {m.group(0) for m in RE_JWT_FULL.finditer(datos)}
    sin_explicar = 0
    for m in RE_JWT_FRAG.finditer(datos):
        tok = m.group(0)
        if any(tok in entero for entero in completos):
            continue                      # ya contado como JWT completo
        if not explicada(tok):
            sin_explicar += 1
    resultado["fragmentos"] = sin_explicar
    resultado["palabras"] = sorted({k.decode(errors="ignore").strip()
                                    for k in KEYWORDS if k.lower() in datos.lower()})
    if resultado["jwts"]:
        resultado["veredicto"] = "FAIL"
    elif resultado["fragmentos"] > 0:
        resultado["veredicto"] = "WARN"
    return resultado


def redactar(texto) -> str:
    """Sustituye cualquier JWT por un marcador, conservando su longitud.

    Se aplica AL CAPTURAR, no al renderizar: así el token no llega nunca al
    `resultados.json` ni al HTML. La evidencia debe demostrar la fuga, no
    convertirse en una fuga nueva — y estos archivos se comparten."""
    if not texto:
        return ""
    crudo = _texto(texto)

    def _marca(m):
        tok = m.group(0)
        info = decode_jwt(tok)
        clase = "JWT-AUTH" if (info and info.get("is_auth")) else "JWT?"
        return f"«{clase} redactado · {len(tok)} caracteres»".encode()

    limpio = RE_JWT_FULL.sub(_marca, crudo)
    # Fragmentos largos 'eyJ…' sueltos: se acortan, pueden ser medio token.
    limpio = RE_JWT_FRAG.sub(
        lambda m: (m.group(0)[:12] + b"...(" +
                   str(len(m.group(0))).encode() + b" car. redactados)"),
        limpio)
    return limpio.decode("utf-8", errors="replace")


def _cabeceras_seguras(cabeceras: dict) -> dict:
    """Copia las cabeceras ocultando los valores sensibles.

    Se conserva la LONGITUD y el veredicto del valor: basta para demostrar si
    había o no un JWT, sin escribir el token en un archivo que se comparte."""
    salida = {}
    for k, v in (cabeceras or {}).items():
        if k.lower() in CABECERAS_SENSIBLES:
            an = analizar(v)
            salida[k] = (f"«oculto· {len(v or '')} caracteres · "
                         f"{an['veredicto']}»")
        else:
            salida[k] = v
    return salida


class AuditoriaHA:
    """Registra y juzga el tráfico entre el Front End y el Hardware Agent."""

    # Hosts que son la propia aplicación o infraestructura conocida: se
    # descartan del censo de candidatos para que la lista sea corta y útil.
    HOSTS_CONOCIDOS = re.compile(
        r"maxilabs\.net|google|gstatic|cloudflare|jsdelivr|unpkg|"
        r"fontawesome|sentry|datadog|newrelic|clarity\.ms|doubleclick", re.I)

    def __init__(self, page, caso: str, patron: str = None, pistas=None):
        self.page = page
        self.caso = caso
        # `pistas`: alternativas extra para el patrón, típicamente los puertos
        # en los que el preflight vio ESCUCHAR al agente. Descubrir el puerto
        # real y no usarlo sería absurdo.
        base = patron or settings.HW_AGENT_URL_PATTERN
        if pistas:
            extra = "|".join(re.escape(str(p)) for p in pistas if p)
            if extra:
                base = f"{base}|:{extra}\\b" if extra else base
        self.patron = re.compile(base, re.I)
        self.eventos = []          # llamadas al agente (lo que se reporta)
        self.otros = 0             # tráfico descartado (no es del agente)
        # Censo de TODO lo que se vio, para poder diagnosticar un SIN_TRAFICO.
        # Sin esto, un 0 llamadas obliga a adivinar dónde vive el agente; con
        # esto, el propio fallo dice a qué hosts habló la app.
        self.hosts = {}            # host → nº de peticiones
        self.consola = []          # mensajes de consola que citan al agente
        self.bloqueadas = []       # intentos que el navegador NO llegó a hacer
        self.inicio = None
        self.fin = None
        self._activa = False
        self._contexto = None

    # ── ciclo de vida ───────────────────────────────────────────────────────
    async def iniciar(self) -> None:
        if self._activa:
            return
        self.inicio = time.time()
        self._activa = True
        # Se escucha en el CONTEXTO, no solo en la página: `page.on("request")`
        # NO ve las peticiones que salen de un service worker ni de otra
        # pestaña del mismo contexto, y una llamada al agente local es
        # exactamente el tipo de cosa que un front hace desde un worker.
        try:
            self._contexto = self.page.context
            self._contexto.on("request", self._on_request)
            self._contexto.on("response", self._on_response)
            self._contexto.on("requestfailed", self._on_request_failed)
        except Exception:
            self._contexto = None
            self.page.on("request", self._on_request)
            self.page.on("response", self._on_response)
        self.page.on("websocket", self._on_websocket)
        # La consola delata los intentos que el navegador BLOQUEA antes de
        # emitirlos (contenido mixto, certificado, CSP): en esos casos no hay
        # evento `request` y sin esto el intento sería invisible.
        self.page.on("console", self._on_console)
        logger.info("[HA] Auditoría iniciada (%s) — patrón de agente: %s",
                    self.caso, self.patron.pattern)

    def detener(self) -> None:
        if not self._activa:
            return
        if self._contexto is not None:
            for evento, cb in (("request", self._on_request),
                               ("response", self._on_response),
                               ("requestfailed", self._on_request_failed)):
                try:
                    self._contexto.remove_listener(evento, cb)
                except Exception:
                    pass
        for evento, cb in (("request", self._on_request),
                           ("response", self._on_response),
                           ("websocket", self._on_websocket),
                           ("console", self._on_console)):
            try:
                self.page.remove_listener(evento, cb)
            except Exception:
                pass
        self._activa = False
        self.fin = time.time()
        logger.info("[HA] Auditoría detenida — %d llamada(s) al agente, "
                    "veredicto %s.", len(self.eventos), self.veredicto)
        if not self.eventos:
            # El censo se vuelca AQUÍ, no solo en el assert: si el caso falla
            # más adelante por otra causa, esta pista igual queda en el log.
            logger.warning("[HA] %s", self.diagnostico_sin_trafico())

    # ── captura ─────────────────────────────────────────────────────────────
    def _es_del_agente(self, url: str) -> bool:
        return bool(self.patron.search(url or ""))

    def _registrar(self, tipo: str, url: str, detalle: dict) -> None:
        # El ANÁLISIS ya se hizo sobre el contenido original; lo que se GUARDA
        # va redactado. Así el veredicto es real y la evidencia no filtra nada.
        detalle["cuerpo"] = redactar(detalle.get("cuerpo"))
        detalle.update({"tipo": tipo, "url": redactar(url),
                        "hora": datetime.now().strftime("%H:%M:%S.%f")[:-3]})
        self.eventos.append(detalle)

    def _censar(self, url: str) -> None:
        """Anota el host de cada petición (sin querystring: puede llevar datos)."""
        try:
            sin_esquema = (url or "").split("://", 1)[-1]
            host = sin_esquema.split("/", 1)[0].split("?", 1)[0]
            if host:
                self.hosts[host] = self.hosts.get(host, 0) + 1
        except Exception:
            pass

    def _on_request(self, request) -> None:
        try:
            self._censar(request.url)
            if not self._es_del_agente(request.url):
                self.otros += 1
                return
            cuerpo = request.post_data or ""
            an_cuerpo = analizar(cuerpo)
            an_cab = analizar(json.dumps(request.headers or {}))
            an_url = analizar(request.url)
            self._registrar("petición", request.url, {
                "metodo": request.method,
                "cabeceras": _cabeceras_seguras(request.headers),
                "cuerpo": cuerpo[:MAX_CUERPO],
                "analisis": _peor(an_url, an_cab, an_cuerpo),
                "detalle_analisis": {"url": an_url, "cabeceras": an_cab,
                                     "cuerpo": an_cuerpo},
            })
        except Exception as e:
            logger.debug("[HA] request no auditado: %s", str(e)[:80])

    def _on_request_failed(self, request) -> None:
        """Petición al agente que el navegador emitió pero no completó.

        Cuenta como comunicación: el Front End SÍ intentó hablar con el agente
        y sus cabeceras —donde viajaría el token— ya se pueden analizar. Un
        fallo de red es un problema de entorno, no una razón para decir que el
        flujo no ejercitó al agente."""
        try:
            self._censar(request.url)
            if not self._es_del_agente(request.url):
                self.otros += 1
                return
            fallo = ""
            try:
                fallo = (request.failure or "") if isinstance(
                    request.failure, str) else str(request.failure or "")
            except Exception:
                pass
            cuerpo = request.post_data or ""
            an_cuerpo = analizar(cuerpo)
            an_cab = analizar(json.dumps(request.headers or {}))
            an_url = analizar(request.url)
            logger.warning("[HA] Petición al agente FALLIDA (%s): %s",
                           fallo or "sin detalle", redactar(request.url)[:120])
            self._registrar("petición fallida", request.url, {
                "metodo": request.method,
                "estado": f"fallida: {fallo}"[:120],
                "cabeceras": _cabeceras_seguras(request.headers),
                "cuerpo": cuerpo[:MAX_CUERPO],
                "analisis": _peor(an_url, an_cab, an_cuerpo),
            })
        except Exception as e:
            logger.debug("[HA] requestfailed no auditado: %s", str(e)[:80])

    def _on_console(self, mensaje) -> None:
        """Guarda los mensajes de consola que citan al agente.

        Si el navegador bloquea la llamada (contenido mixto sobre https,
        certificado local no confiable, CSP), no hay evento `request` — pero sí
        un error en consola. Sin esto, el intento sería invisible y el
        diagnóstico diría 'nunca lo intentó', que es distinto de 'lo intentó y
        se lo bloquearon'."""
        try:
            texto = (mensaje.text or "")[:400]
        except Exception:
            return
        if not self.patron.search(texto):
            return
        tipo = ""
        try:
            tipo = mensaje.type
        except Exception:
            pass
        entrada = f"[{tipo or 'log'}] {redactar(texto)}"
        if entrada not in self.consola:
            self.consola.append(entrada)
            logger.warning("[HA] Consola cita al agente: %s", entrada[:200])

    def _on_response(self, response) -> None:
        try:
            if not self._es_del_agente(response.url):
                return
            self._registrar("respuesta", response.url, {
                "metodo": "",
                "estado": response.status,
                "cabeceras": _cabeceras_seguras(response.headers),
                "cuerpo": "",          # el cuerpo se lee aparte: puede bloquear
                "analisis": analizar(json.dumps(response.headers or {})),
            })
        except Exception as e:
            logger.debug("[HA] response no auditada: %s", str(e)[:80])

    def _on_websocket(self, ws) -> None:
        if not self._es_del_agente(ws.url):
            return
        logger.info("[HA] WebSocket con el agente: %s", ws.url)

        def _frame(direccion):
            def _cb(payload):
                try:
                    an = analizar(payload)
                    self._registrar(f"ws {direccion}", ws.url, {
                        "metodo": "", "cabeceras": {},
                        "cuerpo": str(payload)[:MAX_CUERPO],
                        "analisis": an,
                    })
                except Exception:
                    pass
            return _cb

        ws.on("framesent", _frame("enviado"))
        ws.on("framereceived", _frame("recibido"))

    # ── resultado ───────────────────────────────────────────────────────────
    @property
    def hubo_trafico(self) -> bool:
        return bool(self.eventos)

    @property
    def veredicto(self) -> str:
        """PASS · WARN · FAIL · SIN_TRAFICO.

        SIN_TRAFICO no es un aprobado: significa que la prueba NO ejercitó al
        agente y por tanto no demuestra nada (ver §7 del brief, falso negativo).
        """
        if not self.eventos:
            return "SIN_TRAFICO"
        veredictos = [e["analisis"]["veredicto"] for e in self.eventos]
        if "FAIL" in veredictos:
            return "FAIL"
        if "WARN" in veredictos:
            return "WARN"
        return "PASS"

    @property
    def tokens_expuestos(self) -> list:
        salida = []
        for e in self.eventos:
            salida.extend(e["analisis"].get("jwts", []))
        return salida

    # ── diagnóstico de un SIN_TRAFICO ───────────────────────────────────────
    def hosts_vistos(self, limite: int = 12) -> list:
        """Hosts con los que habló el navegador, del más al menos usado."""
        return sorted(self.hosts.items(), key=lambda kv: -kv[1])[:limite]

    def candidatos(self, limite: int = 8) -> list:
        """Hosts que NO son la app ni infraestructura conocida.

        Si el agente no se detectó, es aquí donde está: un dominio propio que
        resuelve a 127.0.0.1 (truco habitual para tener certificado válido en
        local) no casa con un patrón de 'localhost' y pasa desapercibido."""
        return [(h, n) for h, n in self.hosts_vistos(limite=40)
                if not self.HOSTS_CONOCIDOS.search(h)][:limite]

    def diagnostico_sin_trafico(self) -> str:
        """Texto para el mensaje de fallo: qué se vio y qué revisar."""
        cand = self.candidatos()
        vistos = self.hosts_vistos(limite=8)
        partes = [f"Patrón de agente usado: /{self.patron.pattern}/.",
                  f"Peticiones observadas: {self.otros} (ninguna casó)."]
        if self.consola:
            partes.append("PERO la consola sí cita al agente — el navegador "
                          "bloqueó el intento antes de emitirlo (contenido "
                          "mixto, certificado local o CSP): "
                          + " | ".join(self.consola[:3]))
        if cand:
            partes.append("Hosts CANDIDATOS (ni la app ni CDNs conocidos): "
                          + ", ".join(f"{h} ×{n}" for h, n in cand)
                          + ". Si el agente es uno de estos, ajusta "
                            "HW_AGENT_URL_PATTERN en el .env.")
        elif vistos:
            partes.append("Todos los hosts vistos son de la app: "
                          + ", ".join(f"{h} ×{n}" for h, n in vistos)
                          + ". El navegador NUNCA intentó hablar con un "
                            "servicio local → la impresión no llegó a "
                            "invocar al agente.")
        else:
            partes.append("No se registró NINGUNA petición en la ventana "
                          "auditada: revisa que la vigilancia envuelva la "
                          "acción que imprime.")
        return " ".join(partes)

    def resumen(self) -> dict:
        return {
            "caso": self.caso,
            "veredicto": self.veredicto,
            "llamadas": len(self.eventos),
            "descartadas": self.otros,
            "tokens_expuestos": len(self.tokens_expuestos),
            "duracion_s": round((self.fin or time.time()) - (self.inicio or 0), 1),
            "eventos": self.eventos,
            "hosts": dict(self.hosts_vistos(limite=20)),
            "candidatos": [h for h, _ in self.candidatos()],
            "consola": self.consola[:10],
        }


class RedLenta:
    """Ralentiza la red del navegador para ampliar la ventana del request.

    Es la idea de Roman Arce: `Maxi.RulesOffice.Security.HttpProxy.exe` solo
    vive mientras dura el request, así que con una conexión lenta el proceso
    permanece abierto más tiempo y `procdump -w` tiene margen para volcarlo.

    Se implementa con CDP (`Network.emulateNetworkConditions`), que es lo que
    usa el throttling de las DevTools. Afecta SOLO al navegador de la prueba.

        async with RedLenta(page, kbps=50, latencia_ms=500):
            ...  # la acción que dispara el request
    """

    def __init__(self, page, kbps: int = 50, latencia_ms: int = 500):
        self.page = page
        self.kbps = kbps
        self.latencia_ms = latencia_ms
        self._cdp = None

    async def __aenter__(self):
        try:
            self._cdp = await self.page.context.new_cdp_session(self.page)
            await self._cdp.send("Network.enable")
            bps = self.kbps * 1024 / 8
            await self._cdp.send("Network.emulateNetworkConditions", {
                "offline": False,
                "latency": self.latencia_ms,
                "downloadThroughput": bps,
                "uploadThroughput": bps,
            })
            logger.info("[HA] Red ralentizada a %d kbps / %d ms de latencia "
                        "— amplía la ventana del proceso efímero.",
                        self.kbps, self.latencia_ms)
        except Exception as e:
            self._cdp = None
            logger.warning("[HA] No se pudo ralentizar la red (%s). El proxy "
                           "efímero puede ser difícil de capturar.", str(e)[:90])
        return self

    async def __aexit__(self, *exc):
        if not self._cdp:
            return False
        try:
            await self._cdp.send("Network.emulateNetworkConditions", {
                "offline": False, "latency": 0,
                "downloadThroughput": -1, "uploadThroughput": -1,
            })
            await self._cdp.detach()
            logger.info("[HA] Red restaurada a velocidad normal.")
        except Exception:
            pass
        return False


def _peor(*analisis) -> dict:
    """Combina varios análisis quedándose con el veredicto más grave."""
    orden = {"PASS": 0, "WARN": 1, "FAIL": 2}
    peor = max(analisis, key=lambda a: orden.get(a["veredicto"], 0))
    return {
        "veredicto": peor["veredicto"],
        "jwts": [j for a in analisis for j in a["jwts"]],
        "fragmentos": sum(a["fragmentos"] for a in analisis),
        "palabras": sorted({p for a in analisis for p in a["palabras"]}),
    }
