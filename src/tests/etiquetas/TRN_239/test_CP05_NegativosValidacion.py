"""
CP05-NegativosValidacion — lo que la API debe rechazar (TRN-294, TRN-300).

Tres entradas inválidas, cada una rompiendo UNA cosa sobre un cuerpo por lo
demás válido:

  · campos obligatorios ausentes        → TRN-294
  · `Amount` negativo                   → un pago por importe negativo
  · cancelar un `TransactionID` que no existe → TRN-300

Los tres comparten caso porque comparten evidencia y porque el criterio es el
mismo: **rechazo controlado**. No basta con que falle; tiene que fallar
diciendo qué está mal y sin escupir una excepción cruda. Un 500 con un
traceback es tan defecto como un 200 que acepta basura.
"""

import random

import pytest

from config.logger import get_logger

from . import parametros as P
from .flujos import bodies as B
from .flujos import lunex_api as API

logger = get_logger("TRN-239")


def _controlado(r):
    """Rechazo limpio: rechaza, no revienta y no filtra la tripa.

    Devuelve `None` —no verificado— si el endpoint no existe: un 404 no
    revienta ni filtra nada, y llamarlo «rechazo controlado» sería aprobar
    sobre una ausencia.
    """
    if not r.endpoint_existe:
        return None
    return r.rechazada and r.estado != 500 and not r.filtra_stack_trace


@pytest.mark.etiqueta
@pytest.mark.api_lunex
@pytest.mark.caso_trn239(P.CP05, "La API rechaza de forma controlada los datos "
                                 "inválidos y la cancelación inexistente")
def test_CP05_NegativosValidacion(caso, cnt, productos):
    # ── 1. Campos obligatorios faltantes (TRN-294) ──────────────────────────
    key = cnt.siguiente("key")
    incompleto = {"Login": P.LOGIN, "Md5": B.md5_firma(key), "Key": key,
                  "Action": "lunex", "Status": P.ESTADO_ALTA,
                  "Amount": P.MONTO}
    r1 = API.registrar(incompleto)
    ev1 = caso.evi.http("campos_faltantes", url=r1.url, peticion=incompleto,
                        respuesta=r1.cuerpo or r1.texto[:800],
                        estado=r1.estado, ms=r1.ms, paso=1,
                        modificado="se OMITEN TransactionID, SKU, Entity, "
                                   "ExternalID y SKUType")
    res1, det1 = API.veredicto_negativo(
        r1, "rechaza un cuerpo sin TransactionID, SKU ni Entity")
    caso.paso("Rechaza el alta con campos obligatorios ausentes", res1,
              det1 + " · MODIFICADO en el request: se OMITEN TransactionID, "
              "SKU, Entity, ExternalID y SKUType.", ev1)
    caso.paso("El rechazo es controlado (sin 500 ni traza)", _controlado(r1),
              f"HTTP {r1.estado}"
              + (" con traza en la respuesta" if r1.filtra_stack_trace else ""))
    # OJO con el veredicto: el REQUERIMIENTO define el code 5 como un
    # «Validation error» genérico. Que la API responda así CUMPLE el requerimiento
    # — no es defecto de la migración. Que además nombre el campo es una
    # MEJORA (TRN-294), no un requisito. Por eso este paso es OK en los dos
    # casos; solo cambia la nota. (Antes lo marcaba FALLA, y era injusto:
    # castigaba a la API por algo que el requerimiento no le pide.)
    identifica = any(c in (r1.error_text + r1.texto[:400]).lower()
                     for c in ("transactionid", "sku", "entity", "required",
                               "requerid", "falta", "missing", "field"))
    caso.paso(
        "El rechazo trae Errorcode 5 (Validation error)", r1.errorcode == 5,
        (f"identifica el campo: '{r1.error_text}' (supera el requerimiento)"
         if identifica else
         f"mensaje genérico '{r1.error_text}': cumple el requerimiento (code 5 = "
         f"«Validation error»). El detalle por campo es TRN-294, una mejora "
         f"pendiente — NO un defecto de esta migración."))

    # ── 2. Amount negativo ──────────────────────────────────────────────────
    negativo = B.alta(cnt, random.choice(productos), monto=-25.0)
    r2 = API.registrar(negativo)
    ev2 = caso.evi.http("amount_negativo", url=r2.url, peticion=negativo,
                        respuesta=r2.cuerpo or r2.texto[:800],
                        estado=r2.estado, ms=r2.ms, paso=2,
                        modificado="Amount = -25.0 (negativo)")
    res2, det2 = API.veredicto_negativo(r2, "rechaza un importe negativo")
    caso.paso("Rechaza un Amount negativo", res2,
              f"{det2} · MODIFICADO en el request: Amount = -25.0.", ev2)
    caso.paso("El rechazo del importe es controlado", _controlado(r2),
              f"HTTP {r2.estado}")

    # ── 3. Cancelar algo que no existe (TRN-300) ────────────────────────────
    inexistente = B.cancelacion(cnt, "9999999999", "8510", "ITU")
    r3 = API.cancelar(inexistente)
    ev3 = caso.evi.http("cancel_inexistente", url=r3.url, peticion=inexistente,
                        respuesta=r3.cuerpo or r3.texto[:800],
                        estado=r3.estado, ms=r3.ms, paso=3,
                        modificado="TransactionID = 9999999999 (no existe)")
    res3, det3 = API.veredicto_negativo(
        r3, "rechaza cancelar una transacción que no existe")
    caso.paso("Rechaza cancelar un TransactionID inexistente", res3,
              det3 + " · MODIFICADO en el request (CancelTransaction): "
              "TransactionID = 9999999999 (no existe).", ev3)
    caso.paso("El error es del catálogo, no una excepción cruda (TRN-300)",
              _controlado(r3),
              f"HTTP {r3.estado} · Errorcode={r3.errorcode} · "
              f"{r3.error_text or '(sin Error_text)'}")

    caso.exigir()
