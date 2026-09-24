"""
CP07-StatusFailt — un Status inválido debe ser rechazado (requerimiento).

## Solo hay DOS estados reales

    SUCCESS  → la transacción se aceptó
    VOID     → la transacción falló / se canceló

`FAILT` **no es un estado real**: es un string inventado. La API acepta
cualquier string en `Status`, así que hay que comprobar que **rechace** los
que no son SUCCESS/VOID. La Integration Guide lo dice:

    RegisterTransaction · Status · "SUCCESS or VOID — Other values are rejected"

y producción lo confirma: `Fallidas = 0` en 7 M de filas (nunca llega un FAILT).

## Por qué NO se elimina este caso

Es una **validación negativa**: manda ese Status inválido (`FAILT`) a propósito
y espera el **rechazo** (Errorcode 9). No estamos «inventando» un estado ni
guardándolo como válido — al revés, probamos que la API lo tumbe. Y fue esta
validación la que destapó el defecto: en la 1ª corrida la API **aceptó** FAILT
(Errorcode 0) y lo persistió con `IdStatus = 30`, indistinguible de un SUCCESS.
Por eso, si la API lo acepta, el caso sale **FALLA** con el detalle para DEV
(defecto D1). El valor vive en `parametros.STATUS_INVALIDO_PRUEBA`, nombrado así
justamente para que quede claro que es entrada inválida, no un estado del
sistema. (El CP09 code 9 hace la misma prueba con basura pura, `'ZZZ'`.)
"""

import random

import pytest

from config.logger import get_logger

from . import parametros as P
from .flujos import bd as BD
from .flujos import bodies as B
from .flujos import lunex_api as API

logger = get_logger("TRN-239")


@pytest.mark.etiqueta
@pytest.mark.api_lunex
@pytest.mark.caso_trn239(P.CP07, "Un Status fuera de requerimiento (FAILT) debe ser "
                                 "rechazado; solo SUCCESS y VOID son válidos")
def test_CP07_StatusFailt(caso, cnt, productos, bd):
    producto = random.choice(productos)

    # ── Status inválido: debe rechazarse ────────────────────────────────────
    fallida = B.alta(cnt, producto, estado=P.STATUS_INVALIDO_PRUEBA)
    r = API.registrar(fallida)
    ev = caso.evi.http("alta_status_invalido", url=r.url, peticion=fallida,
                       respuesta=r.cuerpo or r.texto[:500],
                       estado=r.estado, ms=r.ms, paso=1,
                       modificado=f"Status = '{P.STATUS_INVALIDO_PRUEBA}' "
                                  f"(fuera de SUCCESS/VOID)")

    # El código C# del legado valida `Status in (SUCCESS, VOID)` (regla r9,
    # ANTES incluso del Md5). Así que FAILT DEBE rechazarse con Errorcode 9.
    # Si la API lo ACEPTA, es un DEFECTO que sale a producción → FALLA, reportar
    # a DEV (no es «investigar»: el legado ya lo rechaza, la referencia existe).
    acepto = r.endpoint_existe and r.ok
    if not r.endpoint_existe:
        caso.paso(f"La API rechaza Status={P.STATUS_INVALIDO_PRUEBA} (solo SUCCESS/VOID)",
                  False, f"no hay endpoint publicado (HTTP {r.estado})", ev)
    elif not r.ok:
        caso.paso(f"La API rechaza Status={P.STATUS_INVALIDO_PRUEBA} (solo SUCCESS/VOID)",
                  True, f"la API rechazó · {r.resumen()}", ev)
    else:
        caso.paso(f"La API rechaza Status={P.STATUS_INVALIDO_PRUEBA} (solo SUCCESS/VOID)",
                  False, f"DEFECTO: la API ACEPTÓ FAILT (Errorcode 0). El código "
                  f"C# lo valida en r9 (Status∈SUCCESS/VOID) y en producción "
                  f"FAILT no existe (Fallidas=0 en 7 M de filas). Sale a "
                  f"producción → reportar a DEV. REPRODUCIR → POST {r.url} · "
                  f"Status='{P.STATUS_INVALIDO_PRUEBA}' · el cuerpo está en la evidencia.",
                  ev)

    # Si la API lo aceptó, se deja constancia de cómo quedó en BD.
    if acepto and bd is not None:
        fila = BD.buscar_transaccion(bd, fallida["TransactionID"])
        if fila:
            _, id_status = BD._valor(fila, "IdStatus")
            _, ln_status = BD._valor(fila, "Status")
            caso.anotar(
                f"FAILT fue aceptado y persistido: LNStatus={ln_status}, "
                f"IdStatus={id_status}. Si IdStatus=30, queda indistinguible de "
                f"un SUCCESS. Confirmar con DEV si se refuerza la validación de "
                f"Status o si el requerimiento debe contemplar FAILT.")

    caso.exigir()
