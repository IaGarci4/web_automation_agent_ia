"""
CP03-CancelacionTransaccion — cancelar en JSON y en SOAP.

Consolida los CP06 y CP07 de la guía.

## La duda que este caso resuelve

El Confluence documenta `Status: "Cancelled"` para cancelar; el dev probó con
`"VOID"` y la API respondió `Success`. Dos valores distintos y las dos cosas
funcionando no puede ser: uno de los dos está dejando la transacción en un
estado que nadie espera.

Aceptar la respuesta de la API no basta para saberlo — lo que importa es **qué
Status queda persistido**. Por eso el caso, cuando hay base de datos, lee la
fila después de cancelar y lo reporta. Esa lectura es la respuesta a la
pregunta 3 del brief.

El caso crea su propia alta en vez de depender del CP02: un caso que solo
funciona si otro corrió antes es un caso que va a fallar cuando alguien
ejecute este solo, y eso pasa todo el tiempo mientras se estabiliza.
"""

import random

import pytest

from config.logger import get_logger

from . import parametros as P
from .flujos import bd as BD
from .flujos import bodies as B
from .flujos import lunex_api as API

logger = get_logger("TRN-239")


def _alta_para_cancelar(caso, cnt, productos, etiqueta, paso):
    """Crea un alta y devuelve su cuerpo, o None si no se pudo.

    Ojo con el veredicto: esta alta es la PREPARACIÓN, no lo que el CP03
    prueba (que es la cancelación). Si la alta falla, no hemos demostrado que
    la cancelación esté rota —no llegamos a probarla—, así que el paso queda en
    **NO VERIFICADO**, no en FALLA, y el error de la API se anota como hallazgo.
    Antes un Errorcode 15 intermitente en esta alta tumbaba todo el CP03.
    """
    cuerpo = B.alta(cnt, random.choice(productos))
    r = API.registrar(cuerpo)
    ev = caso.evi.http(f"alta_previa_{etiqueta}", url=r.url, peticion=cuerpo,
                       respuesta=r.cuerpo, estado=r.estado, ms=r.ms, paso=paso)
    caso.paso(f"Alta previa para {etiqueta}", True if r.ok else None,
              f"tran={cuerpo['TransactionID']} · {r.resumen()}"
              + ("" if r.ok else
                 " — no se pudo montar la prueba de cancelación (la alta de "
                 "preparación no fue aceptada)"), ev)
    if not r.ok:
        caso.anotar(
            f"Alta de preparación {etiqueta} rechazada: {r.resumen()}. Las "
            f"demás altas de la corrida pasaron, así que parece intermitente; "
            f"si el Errorcode se repite en el mismo SKU, es ticket para DEV.")
    return cuerpo if r.ok else None


@pytest.mark.etiqueta
@pytest.mark.api_lunex
@pytest.mark.caso_trn239(P.CP03, "Cancelación de transacción en JSON y SOAP, y "
                                 "estado persistido en la base de datos")
def test_CP03_CancelacionTransaccion(caso, cnt, productos, bd):
    # ── Cancelación JSON ────────────────────────────────────────────────────
    alta = _alta_para_cancelar(caso, cnt, productos, "JSON", 1)
    if alta:
        cuerpo = B.cancelacion(cnt, alta["TransactionID"], alta["SKU"],
                               alta["SKUType"])
        r = API.cancelar(cuerpo)
        ev = caso.evi.http("cancel_json", url=r.url, peticion=cuerpo,
                           respuesta=r.cuerpo, estado=r.estado, ms=r.ms, paso=2)
        caso.paso(f"Cancelación JSON (Status={P.ESTADO_CANCELACION})", r.ok,
                  f"tran={alta['TransactionID']} · {r.resumen()}", ev)

        # El estado REAL, el que importa. Se confirma con DateOfCancel +
        # IdStatus=22, no solo con el texto (como pediste).
        if bd is None:
            caso.paso("Estado persistido tras cancelar", False,
                      "sin conexión a BD: no se pudo confirmar la cancelación. "
                      "Corre con la VPN o revisa el .env.")
        else:
            fila = BD.buscar_transaccion(bd, alta["TransactionID"])
            if not fila:
                caso.paso("Estado persistido tras cancelar", False,
                          f"la API dijo Success pero {alta['TransactionID']} "
                          f"NO está en {P.TABLA_TRANSFER}: aceptó y no persistió.")
            else:
                cancelada, detalle = BD.cancelacion_confirmada(fila)
                caso.paso("La cancelación quedó registrada en BD", cancelada,
                          detalle)
                persistido = BD.estado_persistido(bd, alta["TransactionID"])
                coincide = persistido.strip().casefold() == \
                    P.ESTADO_CANCELACION.strip().casefold()
                if cancelada and not coincide:
                    caso.anotar(
                        f"Se envió Status='{P.ESTADO_CANCELACION}' y BD guardó "
                        f"LNStatus='{persistido}'. Confirmar con DEV si la API "
                        f"traduce el estado (pregunta abierta).")
    else:
        caso.paso("Cancelación JSON", None,
                  "no hubo alta previa que cancelar")

    # ── Cancelación SOAP ────────────────────────────────────────────────────
    alta_s = _alta_para_cancelar(caso, cnt, productos, "SOAP", 3)
    if alta_s:
        cuerpo_s = B.cancelacion(cnt, alta_s["TransactionID"], alta_s["SKU"],
                                 alta_s["SKUType"])
        sobre = B.sobre_soap(cuerpo_s, "CancelTransaction")
        caso.evi.texto("cancel_soap_peticion", sobre, paso=4)
        r_s = API.cancelar_soap(cuerpo_s, sobre)
        ev = caso.evi.http("cancel_soap", url=r_s.url, peticion=cuerpo_s,
                           respuesta=r_s.cuerpo or r_s.texto[:800],
                           estado=r_s.estado, ms=r_s.ms, paso=4)
        caso.paso("Cancelación SOAP aceptada", r_s.ok,
                  f"tran={alta_s['TransactionID']} · {r_s.resumen()}", ev)
        caso.paso("La respuesta SOAP no trae Fault", not r_s.hay_fault_soap,
                  "Se encontró un <Fault>" if r_s.hay_fault_soap else "sin Fault")
    else:
        caso.paso("Cancelación SOAP", None, "no hubo alta previa que cancelar")

    caso.exigir()
