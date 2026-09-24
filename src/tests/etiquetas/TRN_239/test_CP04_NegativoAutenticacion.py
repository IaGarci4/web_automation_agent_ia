"""
CP04-NegativoAutenticacion — firma MD5 inválida (TRN-293).

Dos exigencias, y la segunda es la que de verdad pide el subticket:

  1. La API **rechaza** la petición. Un alta que entra con firma falsa es un
     agujero de autenticación.
  2. La respuesta **no filtra una traza interna**. TRN-293 se abrió porque un
     error de autenticación devolvía detalle del servidor: rutas, nombres de
     framework, el stack. Eso le regala a un atacante el mapa de la casa.

El rechazo se comprueba por la NEGACIÓN de «respuesta correcta», no contra un
código concreto: el catálogo de Errorcode sigue sin documentar (pregunta 4 del
brief) y fijar un número ahora sería adivinar. Cualquier forma de rechazo
—401, 403, un Errorcode distinto de 0— cuenta.
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
@pytest.mark.caso_trn239(P.CP04, "La API rechaza una firma MD5 inválida y no "
                                 "filtra detalles internos")
def test_CP04_NegativoAutenticacion(caso, cnt, productos):
    # Cuerpo VÁLIDO al que se le rompe una sola cosa: la firma. Así, si la
    # API lo acepta, no queda duda de por qué — no hay otro campo malo que
    # pudiera explicarlo.
    cuerpo = B.alta(cnt, random.choice(productos))
    cuerpo["Md5"] = "0" * 32

    r = API.registrar(cuerpo)
    ev = caso.evi.http("md5_invalido", url=r.url, peticion=cuerpo,
                       respuesta=r.cuerpo or r.texto[:800],
                       estado=r.estado, ms=r.ms, paso=1,
                       modificado="Md5 = 32 ceros ('0'*32): firma inválida")

    resultado, detalle = API.veredicto_negativo(
        r, "rechaza un MD5 falso")
    caso.paso("La API rechaza la firma inválida", resultado,
              detalle + (" — ACEPTÓ un alta con MD5 falso" if r.ok else "")
              + " · MODIFICADO en el request: Md5 = 32 ceros ('0'*32).", ev)

    # La comprobación de la traza solo dice algo si hubo respuesta de la
    # aplicación: una página 404 del servidor tampoco trae stack, y darla por
    # buena sería aprobar TRN-293 sin haberlo probado.
    caso.paso("La respuesta no filtra traza interna",
              (not r.filtra_stack_trace) if r.endpoint_existe else None,
              ("Se detectó una traza o detalle de framework en la respuesta "
               "(TRN-293): " + r.texto[:180]) if r.filtra_stack_trace
              else ("sin trazas ni detalle de framework" if r.endpoint_existe
                    else "sin endpoint que responda: no se puede afirmar que "
                         "no filtra nada"))

    # Segundo vector: firma bien formada pero calculada con otra contraseña.
    # Un 'Md5' de 32 ceros puede rechazarse por formato sin llegar a validar
    # la firma; este sí obliga a comprobarla.
    cuerpo2 = B.alta(cnt, random.choice(productos))
    cuerpo2["Md5"] = B.md5_firma(cuerpo2["Key"], password="contrasena-erronea")
    r2 = API.registrar(cuerpo2)
    ev2 = caso.evi.http("md5_otra_password", url=r2.url, peticion=cuerpo2,
                        respuesta=r2.cuerpo or r2.texto[:800],
                        estado=r2.estado, ms=r2.ms, paso=2,
                        modificado="Md5 recalculado con password erróneo "
                                   "('contrasena-erronea'); Login/Key correctos")
    resultado2, detalle2 = API.veredicto_negativo(
        r2, "rechaza una firma calculada con otra contraseña")
    caso.paso("Rechaza una firma bien formada pero incorrecta",
              resultado2, detalle2 + " · MODIFICADO en el request: Md5 "
              "recalculado con password erróneo ('contrasena-erronea'); "
              "Login/Key correctos.", ev2)

    caso.exigir()
