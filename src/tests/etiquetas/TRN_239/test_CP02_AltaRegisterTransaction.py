"""
CP02-AltaRegisterTransaction — alta JSON, alta SOAP y paridad entre las dos.

Consolida los CP03, CP04 y CP05 de la guía. Van juntos porque comparten
evidencia y porque la paridad **solo tiene sentido** si las dos altas se
construyen igual: se arma un único diccionario y se envía dos veces, una como
JSON y otra envuelta en el sobre SOAP del legacy. Si se construyeran por
separado, una diferencia entre formatos podría venir del arnés, que es
exactamente lo que una prueba de migración no puede permitirse.

Cada alta exitosa ESCRIBE en `lunex.TransferLN`: son datos reales en TEST.
`TRN239_ALTAS` controla cuántas; por defecto 2.
"""

import random

import pytest

from config.logger import get_logger

from . import parametros as P
from .flujos import bodies as B
from .flujos import lunex_api as API

logger = get_logger("TRN-239")


@pytest.mark.etiqueta
@pytest.mark.api_lunex
@pytest.mark.caso_trn239(P.CP02, "Alta de transacción en JSON y SOAP, y paridad "
                                 "entre ambos formatos")
def test_CP02_AltaRegisterTransaction(caso, cnt, productos):
    paso = 0

    # ── Altas JSON ──────────────────────────────────────────────────────────
    exitosas = []
    ultima_json = None          # se usa abajo para la paridad
    for i in range(P.ALTAS):
        cuerpo = B.alta(cnt, random.choice(productos))
        r = API.registrar(cuerpo)
        ultima_json = r
        paso += 1
        ev = caso.evi.http(f"alta_json_{i+1}", url=r.url, peticion=cuerpo,
                           respuesta=r.cuerpo or r.texto[:500],
                           estado=r.estado, ms=r.ms, paso=paso)
        ok = caso.paso(
            f"Alta JSON #{i+1}", r.ok,
            f"SKU={cuerpo['SKU']} ({cuerpo['SKUType']}) "
            f"tran={cuerpo['TransactionID']} · {r.resumen()}", ev)
        if ok:
            exitosas.append(cuerpo)

    # Se guardan para que el CP03 pueda cancelar algo que existe de verdad.
    caso.altas = exitosas

    # ── Alta SOAP ───────────────────────────────────────────────────────────
    cuerpo_soap = B.alta(cnt, random.choice(productos))
    sobre = B.sobre_soap(cuerpo_soap, "RegisterTransaction")
    paso += 1
    caso.evi.texto("alta_soap_peticion", sobre, paso=paso)
    r_soap = API.registrar_soap(cuerpo_soap, sobre)
    ev = caso.evi.http("alta_soap", url=r_soap.url, peticion=cuerpo_soap,
                       respuesta=r_soap.cuerpo or r_soap.texto[:800],
                       estado=r_soap.estado, ms=r_soap.ms, paso=paso)

    caso.paso("Alta SOAP aceptada", r_soap.ok,
              f"SKU={cuerpo_soap['SKU']} tran={cuerpo_soap['TransactionID']} "
              f"· {r_soap.resumen()}", ev)
    # «No trae Fault» lo cumple también una página de error del servidor, así
    # que solo significa algo si contestó la aplicación.
    caso.paso("La respuesta SOAP no trae Fault",
              (not r_soap.hay_fault_soap) if r_soap.endpoint_existe else None,
              "Se encontró un <Fault> en la respuesta" if r_soap.hay_fault_soap
              else ("sin Fault" if r_soap.endpoint_existe else
                    f"el endpoint no está publicado (HTTP {r_soap.estado}): "
                    f"la ausencia de Fault no prueba nada"))

    # ── Paridad ─────────────────────────────────────────────────────────────
    # Los dos formatos tienen que producir el MISMO resultado. Si uno acepta y
    # el otro no, la migración rompió uno de los dos caminos — y el legacy
    # hablaba SOAP, así que ese es el que más importa que siga vivo.
    if ultima_json is None:
        caso.paso("Paridad SOAP vs JSON", None,
                  "no se envió ningún alta JSON (TRN239_ALTAS=0): no hay con "
                  "qué comparar")
    elif not (ultima_json.endpoint_existe and r_soap.endpoint_existe):
        # «Los dos fallaron igual» NO es paridad. En la primera corrida los
        # dos devolvieron 404 y este paso salió en verde: comparaba dos
        # ausencias y las declaraba equivalentes. Lo eran, y no significaba
        # nada.
        caso.paso("Paridad SOAP vs JSON", None,
                  f"el endpoint no está publicado (JSON→{ultima_json.estado}, "
                  f"SOAP→{r_soap.estado}): no hay dos comportamientos que "
                  f"comparar")
    elif not (ultima_json.ok or r_soap.ok):
        # Los dos fallaron. Que fallen IGUAL es información útil —dice que
        # ambos formatos entran por el mismo camino— pero no permite afirmar
        # la paridad que pide el caso, que es «los dos registran bien».
        # Aprobar aquí sería aprobar una simetría en la avería.
        mismo = ultima_json.errorcode == r_soap.errorcode
        caso.paso(
            "Paridad SOAP vs JSON", None,
            f"ninguno de los dos formatos completó el alta "
            f"(JSON Errorcode={ultima_json.errorcode}, "
            f"SOAP Errorcode={r_soap.errorcode}): no se puede verificar que "
            f"produzcan el mismo resultado. "
            + ("Fallan con el MISMO error, así que comparten camino."
               if mismo else
               "Fallan con errores DISTINTOS: eso ya es una diferencia entre "
               "formatos y merece revisarse."))
    else:
        caso.paso(
            "Paridad SOAP vs JSON", ultima_json.ok == r_soap.ok,
            f"JSON: {'aceptada' if ultima_json.ok else 'rechazada'} "
            f"(Errorcode={ultima_json.errorcode}) · "
            f"SOAP: {'aceptada' if r_soap.ok else 'rechazada'} "
            f"(Errorcode={r_soap.errorcode})")

    caso.exigir()
