"""
Cliente de la API Lunex — el «Page Object» de esta etiqueta.

En las demás etiquetas el POM envuelve una pantalla: un método por acción, y
los casos no saben de selectores. Aquí envuelve un **endpoint**: un método por
operación, y los casos no saben de URLs, cabeceras ni códigos HTTP. La
intención es la misma — que un caso se lea como lo que prueba, no como lo que
teclea.

## El veredicto de «respuesta correcta»

    HTTP 200  +  Errorcode == 0  +  Error_text contiene 'Success'

Los tres, no uno. Un 200 con `Errorcode: 15` es un rechazo con buena cara, y
darlo por bueno sería el peor falso negativo posible en una migración cuyo
objetivo es cazar diferencias.

`Reponse_timestamp` va con una sola «s» en el requerimiento legacy. No es una
errata de este código: se conserva tal cual porque así llega.
"""

from __future__ import annotations

import json
import re
import time

from config.logger import get_logger

from .. import parametros as P

logger = get_logger("TRN-239.api")

try:
    import requests
except ImportError:                                          # pragma: no cover
    requests = None


class Respuesta:
    """Lo que devolvió un endpoint, ya interpretado."""

    def __init__(self, url, estado, cuerpo, ms, texto="", error=""):
        self.url = url
        self.estado = estado            # código HTTP (0 si ni salió)
        self.cuerpo = cuerpo            # dict si era JSON; {} si no
        self.ms = ms
        self.texto = texto              # crudo, para SOAP y para diagnóstico
        self.error = error              # excepción de red, si la hubo

    # ── Lecturas del requerimiento ───────────────────────────────────────────────
    @property
    def errorcode(self):
        return self.cuerpo.get("Errorcode", self.cuerpo.get("ErrorCode"))

    @property
    def error_text(self) -> str:
        return str(self.cuerpo.get("Error_text",
                                   self.cuerpo.get("ErrorText", "")))

    @property
    def ok(self) -> bool:
        return (self.estado == 200
                and str(self.errorcode) == "0"
                and "success" in self.error_text.lower())

    # Códigos que significan «aquí no hay nada que probar»: la ruta no está
    # publicada o el servicio no está en pie. NO son respuestas de la API.
    SIN_ENDPOINT = (0, 404, 405, 501, 502, 503, 504)

    @property
    def endpoint_existe(self) -> bool:
        """¿Contestó la APLICACIÓN, o solo el servidor diciendo que no está?

        La distinción parece pedante y es la que separa una prueba de un
        placebo. Ver `rechazada`.
        """
        return self.estado not in self.SIN_ENDPOINT

    @property
    def rechazada(self) -> bool:
        """True si la API **existió y rechazó** la petición.

        ## Por qué no es simplemente `not ok`

        Así estaba, y producía falsos positivos vergonzosos: con la API sin
        publicar, todas las llamadas devolvían 404, `not ok` era True, y los
        casos negativos salían en verde. El reporte afirmaba «la API rechaza
        las firmas inválidas» sobre un endpoint que no existe.

        Un caso negativo solo prueba algo si el destinatario está ahí para
        decir que no. Un 404 no es un rechazo: es una ausencia.

        Se sigue sin fijar un código concreto —el catálogo de Errorcode es la
        pregunta 4 del brief— pero se exige que la respuesta venga de la
        aplicación: 400, 401, 403, 409, 422, o un 200 con Errorcode != 0.
        """
        return self.endpoint_existe and not self.ok

    @property
    def hay_fault_soap(self) -> bool:
        return "<s:fault" in self.texto.lower() or "<fault" in self.texto.lower()

    @property
    def filtra_stack_trace(self) -> bool:
        """¿La respuesta se le escapó una traza interna?

        TRN-293 pide que un error de autenticación no devuelva detalles del
        servidor. Una traza en la respuesta es una fuga de información, y este
        es el sitio donde se detecta.
        """
        pistas = ("traceback", "stack trace", "stacktrace", "at System.",
                  "File \"/", "line ", "Microsoft.Data", "pyodbc",
                  "sqlalchemy", "fastapi", "uvicorn")
        bajo = self.texto.lower()
        return any(p.lower() in bajo for p in pistas)

    def resumen(self) -> str:
        if self.error:
            return f"sin respuesta ({self.error[:90]})"
        return (f"HTTP {self.estado} · Errorcode={self.errorcode} · "
                f"{self.error_text or '(sin Error_text)'} · {self.ms} ms")


def _post(url: str, *, json_body=None, xml_body=None, raw_body=None,
          accion_soap: str = None) -> Respuesta:
    if requests is None:
        return Respuesta(url, 0, {}, 0, error="falta el paquete `requests`")
    t0 = time.time()
    try:
        if raw_body is not None:
            # Cuerpo CRUDO tal cual (vacío o JSON malformado) para provocar
            # «Request is null» (code 1), que se dispara en la deserialización.
            r = requests.post(url, data=raw_body.encode("utf-8"),
                              headers={"Content-Type": "application/json"},
                              timeout=P.TIMEOUT)
        elif xml_body is not None:
            tipo = "application/soap+xml; charset=utf-8"
            if accion_soap:
                tipo += f'; action="{accion_soap}"'
            r = requests.post(url, data=xml_body.encode("utf-8"),
                              headers={"Content-Type": tipo},
                              timeout=P.TIMEOUT)
        else:
            r = requests.post(url, json=json_body, timeout=P.TIMEOUT,
                              headers={"Content-Type": "application/json"})
    except Exception as e:
        return Respuesta(url, 0, {}, int((time.time() - t0) * 1000),
                         error=str(e))
    ms = int((time.time() - t0) * 1000)
    texto = r.text or ""
    try:
        cuerpo = r.json()
        if not isinstance(cuerpo, dict):
            cuerpo = {"_valor": cuerpo}
    except Exception:
        cuerpo = _errorcode_de_xml(texto)
    return Respuesta(url, r.status_code, cuerpo, ms, texto=texto)


def _errorcode_de_xml(texto: str) -> dict:
    """Saca Errorcode/Error_text de una respuesta SOAP.

    Sin esto, una respuesta SOAP correcta se leería como «sin Errorcode» y el
    caso la daría por fallida: el veredicto quedaría decidido por el formato
    de la respuesta y no por su contenido, que es precisamente lo que el caso
    de paridad no puede permitirse.
    """
    fuera = {}
    for etiqueta, clave in (("Errorcode", "Errorcode"),
                            ("ErrorCode", "Errorcode"),
                            ("Error_text", "Error_text"),
                            ("ErrorText", "Error_text"),
                            ("ResponseID", "ResponseID")):
        m = re.search(rf"<(?:\w+:)?{etiqueta}>(.*?)</(?:\w+:)?{etiqueta}>",
                      texto, re.I | re.S)
        if m and clave not in fuera:
            fuera[clave] = m.group(1).strip()
    return fuera


# ── Operaciones ─────────────────────────────────────────────────────────────

def get(url: str, timeout: int = None) -> Respuesta:
    """GET genérico. Lo usa el preflight para tantear rutas."""
    if requests is None:
        return Respuesta(url, 0, {}, 0, error="falta el paquete `requests`")
    t0 = time.time()
    try:
        r = requests.get(url, timeout=timeout or P.TIMEOUT)
    except Exception as e:
        return Respuesta(url, 0, {}, int((time.time() - t0) * 1000), error=str(e))
    ms = int((time.time() - t0) * 1000)
    try:
        cuerpo = r.json()
        if not isinstance(cuerpo, dict):
            cuerpo = {"_valor": cuerpo}
    except Exception:
        cuerpo = {}
    return Respuesta(url, r.status_code, cuerpo, ms, texto=r.text or "")


def healthcheck() -> Respuesta:
    """`GET {base}healthcheck` — estado del servicio y de su BD (TRN-569)."""
    return get(P.BASE_URL + P.RUTA_HEALTH)


def registrar(cuerpo: dict) -> Respuesta:
    """`POST Payments/RegisterTransaction` en JSON."""
    r = _post(P.BASE_URL + P.RUTA_REGISTER, json_body=cuerpo)
    logger.info("[API] Register JSON tran=%s SKU=%s → %s",
                cuerpo.get("TransactionID"), cuerpo.get("SKU"), r.resumen())
    return r


def registrar_crudo(texto: str) -> Respuesta:
    """`POST RegisterTransaction` con un cuerpo CRUDO (texto tal cual).

    Para provocar «Request is null» (Errorcode 1): un cuerpo vacío (`""`) o un
    JSON malformado (`"{"`). No se puede hacer con `registrar()` porque ese
    serializa un dict; aquí se manda el texto sin tocar.
    """
    r = _post(P.BASE_URL + P.RUTA_REGISTER, raw_body=texto)
    logger.info("[API] Register CRUDO (%d bytes) → %s", len(texto), r.resumen())
    return r


def registrar_soap(cuerpo: dict, sobre: str) -> Respuesta:
    """`POST Payments/RegisterTransaction` en SOAP."""
    from .bodies import ACCION_REGISTER
    r = _post(P.BASE_URL + P.RUTA_REGISTER, xml_body=sobre,
              accion_soap=ACCION_REGISTER)
    logger.info("[API] Register SOAP tran=%s SKU=%s → %s",
                cuerpo.get("TransactionID"), cuerpo.get("SKU"), r.resumen())
    return r


def cancelar(cuerpo: dict) -> Respuesta:
    """`POST Payments/CancelTransaction` en JSON."""
    r = _post(P.BASE_URL + P.RUTA_CANCEL, json_body=cuerpo)
    logger.info("[API] Cancel JSON tran=%s status=%s → %s",
                cuerpo.get("TransactionID"), cuerpo.get("Status"), r.resumen())
    return r


def cancelar_soap(cuerpo: dict, sobre: str) -> Respuesta:
    """`POST Payments/CancelTransaction` en SOAP."""
    from .bodies import ACCION_CANCEL
    r = _post(P.BASE_URL + P.RUTA_CANCEL, xml_body=sobre,
              accion_soap=ACCION_CANCEL)
    logger.info("[API] Cancel SOAP tran=%s → %s",
                cuerpo.get("TransactionID"), r.resumen())
    return r


def veredicto_negativo(r: Respuesta, que_se_esperaba: str) -> tuple:
    """Veredicto de un caso negativo. Devuelve `(resultado, detalle)`.

    Tres desenlaces, y el del medio es el que faltaba:

      · La API existió y rechazó   → True   (la prueba salió bien)
      · El endpoint no existe      → None   (NO VERIFICADO: no se probó nada)
      · La API existió y ACEPTÓ    → False  (defecto real)

    Sin el caso del medio, un servidor ausente hacía pasar todos los
    negativos. Es un ayudante de tres líneas que evita el peor tipo de
    mentira que puede contar una suite: la que suena a buena noticia.
    """
    if not r.endpoint_existe:
        return None, (f"el endpoint no está publicado (HTTP {r.estado}): no "
                      f"se puede comprobar que {que_se_esperaba} — no hay "
                      f"nadie al otro lado que rechace")
    if r.ok:
        return False, f"la API ACEPTÓ la petición · {r.resumen()}"
    return True, r.resumen()


def json_legible(obj) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    except Exception:
        return str(obj)
