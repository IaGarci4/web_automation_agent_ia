"""
CP08-IntegridadDatos — lo enviado es lo guardado, y un reenvío no duplica.

**Este es el caso que justifica el ticket.** Todo lo demás comprueba que la
API contesta lo que debe; este comprueba que la base de datos quedó bien, que
es lo único que importa cuando se migra un back end de pagos.

Dos mitades:

  1. **Integridad** — se envía un alta y se compara campo por campo contra
     `lunex.TransferLN`. Una diferencia aquí es la migración perdiendo datos.
  2. **Idempotencia** — se reenvía el MISMO `TransactionID` y se cuenta
     cuántas filas hay. Dos filas es una recarga cobrada dos veces.

## Sin base de datos no hay caso

Este caso ES la validación de integridad, así que sin conexión a BD sale
**FALLA** (no «a medias»): hay que correrlo con la VPN. Un entregable de
migración que no pudo validar contra la base no está aprobado, y ahora lo dice
en rojo en vez de esconderlo en un color tibio.
"""

import random

import pytest

from config.logger import get_logger
from src.helpers import sql_helper

from . import parametros as P
from .flujos import bd as BD
from .flujos import bodies as B
from .flujos import lunex_api as API

logger = get_logger("TRN-239")


@pytest.mark.etiqueta
@pytest.mark.api_lunex
@pytest.mark.caso_trn239(P.CP08, "Integridad enviado-vs-persistido en "
                                 "lunex.TransferLN e idempotencia")
def test_CP08_IntegridadDatos(caso, cnt, productos, bd):
    if bd is None:
        caso.paso("Conexión a la base de datos", False,
                  (sql_helper.motivo_sin_conexion()
                   or "validación desactivada (TRN239_VALIDAR_BD=0)")
                  + " — este caso ES la validación de integridad; sin BD no "
                  "hay nada que comprobar. Corre con la VPN.")
        caso.exigir()
        return

    caso.paso("Conexión a la base de datos", True, sql_helper.describir())

    # ── 1. Integridad ───────────────────────────────────────────────────────
    cuerpo = B.alta(cnt, random.choice(productos))
    r = API.registrar(cuerpo)
    ev = caso.evi.http("alta_integridad", url=r.url, peticion=cuerpo,
                       respuesta=r.cuerpo, estado=r.estado, ms=r.ms, paso=1)
    if not caso.paso("Alta aceptada por la API", r.ok,
                     f"tran={cuerpo['TransactionID']} · {r.resumen()}", ev):
        caso.exigir()
        return

    fila = BD.buscar_transaccion(bd, cuerpo["TransactionID"])
    caso.evi.http("fila_persistida", respuesta=fila or "(no encontrada)", paso=2)

    if not fila:
        caso.paso("La transacción quedó en la base de datos", False,
                  f"{cuerpo['TransactionID']} no está en {P.TABLA_TRANSFER}. "
                  f"La API dijo Success y no persistió: es la diferencia de "
                  f"datos que este ticket busca.")
        caso.exigir()
        return

    caso.paso("La transacción quedó en la base de datos", True,
              f"{len(fila)} columna(s) leídas de {P.TABLA_TRANSFER}")

    comp = BD.comparar(fila, cuerpo)
    if comp["difieren"]:
        caso.paso("Lo enviado coincide con lo persistido", False,
                  "; ".join(comp["difieren"]))
    elif comp["coinciden"]:
        caso.paso("Lo enviado coincide con lo persistido", True,
                  "coinciden: " + ", ".join(comp["coinciden"]))
    else:
        caso.paso("Lo enviado coincide con lo persistido", None,
                  "no se reconoció ninguna columna comparable")

    if comp["sin_columna"]:
        caso.paso("Campos sin columna identificada", None,
                  f"{', '.join(comp['sin_columna'])} — el mapeo campo→columna "
                  f"es la pregunta 1 del brief; hasta que DEV lo confirme, "
                  f"estos campos no se comparan. Ajusta "
                  f"`flujos/bd.py::CANDIDATOS` cuando llegue la respuesta.")

    # Coherencia contra las reglas de producción: aquí es donde se detecta un
    # campo inconsistente (Commission, reparto, AmountInMN). Es la comparación
    # vs producción que importa cuando TEST va directo a prod.
    fallos = BD.coherencia_produccion(fila)
    caso.paso("Coherencia vs producción", not fallos,
              "todas las reglas duras se cumplen (Commission=D1 en ITU, "
              "Commission=Agent+Corp salvo DTU, AmountInMN=Amount×ExRate)"
              if not fallos else "; ".join(fallos))

    # ── 2. Idempotencia ─────────────────────────────────────────────────────
    # Se reenvía el mismo TransactionID. Lo que se mide no es qué contesta la
    # API —rechazar o responder idempotente son ambos aceptables— sino que en
    # la tabla NO acabe habiendo dos filas.
    repetido = B.alta(cnt, random.choice(productos),
                      transaction_id=cuerpo["TransactionID"])
    r2 = API.registrar(repetido)
    ev2 = caso.evi.http("reenvio_mismo_transaction_id", url=r2.url,
                        peticion=repetido, respuesta=r2.cuerpo,
                        estado=r2.estado, ms=r2.ms, paso=3)
    caso.paso("Reenvío del mismo TransactionID", True,
              f"la API respondió: {r2.resumen()}"
              + (" (lo aceptó)" if r2.ok else " (lo rechazó)"), ev2)

    n = BD.contar_transacciones(bd, cuerpo["TransactionID"])
    if n < 0:
        caso.paso("El reenvío no duplicó la transacción", None,
                  "no se pudo contar las filas")
    elif n == 1:
        caso.paso("El reenvío no duplicó la transacción", True,
                  f"1 fila con TransactionID={cuerpo['TransactionID']}: la "
                  f"API no insertó la repetida")
    else:
        # NO VERIFICADO, no FAIL. Yo daba por hecho que «exactamente una fila»
        # era lo correcto, y la producción dice lo contrario: el TransactionID
        # **no es único** en `lunex.TransferLN` (el 41695812 aparece 14 veces,
        # varios con dos estados distintos). Si el legacy permite duplicados,
        # que la API migrada también los permita no es un defecto demostrado
        # — es una decisión de producto que nadie nos ha confirmado.
        #
        # Marcarlo FAIL sería inventar un requisito. Marcarlo PASS sería
        # esconder un cobro doble. Se reporta y se pregunta.
        caso.paso("El reenvío no duplicó la transacción", None,
                  f"{n} filas con TransactionID={cuerpo['TransactionID']}. En "
                  f"producción el TransactionID tampoco es único (un mismo id "
                  f"llega a repetirse 14 veces), así que esto reproduce el "
                  f"comportamiento del legacy y no se puede llamar defecto sin "
                  f"que DEV confirme si la API nueva debe rechazar el reenvío. "
                  f"Pregunta abierta C.")
        caso.anotar("Duplicado reproducido: la API aceptó dos veces el mismo "
                    "TransactionID y quedaron dos filas. Falta la regla: "
                    "¿rechazar, ignorar o insertar?")

    caso.exigir()
