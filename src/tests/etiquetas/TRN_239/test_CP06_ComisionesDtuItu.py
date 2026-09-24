"""
CP06-ComisionesDtuItu — el cálculo de comisión por tipo de producto
(TRN-295 / TRN-296).

Los dos tipos calculan distinto:

  · **DTU** — `Fee` + `CommissionPercentage`
  · **ITU** — los descuentos `D1/D2/R1/R2`

Es el punto más delicado de la migración: un redondeo distinto al del Urano
legacy no rompe ninguna prueba funcional y cuesta dinero en cada transacción.

## Qué puede y qué no puede afirmar este caso hoy

La fórmula exacta sigue sin confirmar (pregunta A). Sin ella, este caso **no
puede verificar el importe**: envía las variantes, deja la evidencia de cada
una y lee de BD lo que quedó guardado, para que la comparación fina se pueda
hacer en cuanto DEV responda.

Por eso los pasos de importe se reportan como *no verificado* y no como PASS.
Decir «comisión correcta» sin la fórmula sería inventarse el resultado — y
este es justo el caso donde eso saldría caro.

## Lo que sí se puede exigir, sin saber la fórmula

Los datos de producción dejaron ver una invariante:

    AgentCommission + CorpCommission  es CONSTANTE para un mismo SKU y monto.
    Lo que cambia entre agentes es el REPARTO, y lo decide el IdSchema.

```
SKU 9851  Agent 0.84 + Corp 0.92 = 1.76      SKU 8510  Agent 0.50 + Corp 3.00 = 3.50
SKU 9851  Agent 0.70 + Corp 1.06 = 1.76      SKU 8510  Agent 2.50 + Corp 1.00 = 3.50
```

Eso se puede comprobar sin conocer el cálculo: dos altas idénticas tienen que
sumar lo mismo. Si no suman lo mismo, la comisión depende de algo que no es el
producto ni el monto, y eso sí es un defecto — aunque no sepamos la fórmula.
"""

import random

import pytest

from config.logger import get_logger

from . import parametros as P
from .flujos import bd as BD
from .flujos import bodies as B
from .flujos import lunex_api as API

logger = get_logger("TRN-239")

# Las tres variantes que pide la guía.
VARIANTES = (
    ("DTU · Fee + CommissionPercentage", "DTU",
     {"Fee": 1.50, "CommissionPercentage": 9.00,
      "D1Discount": 0, "D2Discount": 0, "R1Discount": 0, "R2Discount": 0}),
    ("ITU · descuentos D1/D2", "ITU",
     {"Fee": 0, "CommissionPercentage": 0,
      "D1Discount": 1.08, "D2Discount": 0.50,
      "R1Discount": 0, "R2Discount": 0}),
    ("ITU · descuentos R1/R2", "ITU",
     {"Fee": 0, "CommissionPercentage": 0,
      "D1Discount": 0, "D2Discount": 0,
      "R1Discount": 0.75, "R2Discount": 0.25}),
)


@pytest.mark.etiqueta
@pytest.mark.api_lunex
@pytest.mark.caso_trn239(P.CP06, "Comisiones DTU e ITU: las tres variantes se "
                                 "aceptan y quedan registradas")
def test_CP06_ComisionesDtuItu(caso, cnt, productos, bd):
    catalogo_dtu = [p for p in productos if p[2] == "DTU"] or P.PRODUCTOS_DTU
    catalogo_itu = [p for p in productos if p[2] == "ITU"] or P.PRODUCTOS_ITU

    for i, (nombre, tipo, campos) in enumerate(VARIANTES, start=1):
        producto = random.choice(catalogo_dtu if tipo == "DTU" else catalogo_itu)
        cuerpo = B.alta(cnt, producto)
        cuerpo.update(campos)

        r = API.registrar(cuerpo)
        ev = caso.evi.http(f"comision_{i}", url=r.url, peticion=cuerpo,
                           respuesta=r.cuerpo or r.texto[:500],
                           estado=r.estado, ms=r.ms, paso=i)
        aceptada = caso.paso(
            f"Variante {i}: {nombre}", r.ok,
            f"SKU={cuerpo['SKU']} tran={cuerpo['TransactionID']} · "
            f"{r.resumen()}", ev)

        if not aceptada:
            continue

        # Lo persistido, contra las reglas duras de producción. No hace falta
        # la fórmula exacta de la comisión para exigir que la fila sea
        # coherente: Commission=D1 en ITU, Commission=Agent+Corp salvo DTU,
        # AmountInMN=Amount×ExRate. Si algo de eso no cuadra, es FALLA con el
        # valor; si cuadra, es OK.
        if bd is None:
            caso.paso(f"Variante {i}: coherencia en BD", False,
                      "sin conexión a BD no se puede validar lo persistido. "
                      "Corre con la VPN.")
            continue

        fila = BD.buscar_transaccion(bd, cuerpo["TransactionID"])
        if not fila:
            caso.paso(f"Variante {i}: coherencia en BD", False,
                      f"la API dijo Success pero {cuerpo['TransactionID']} no "
                      f"está en {P.TABLA_TRANSFER}: aceptó y no persistió.")
            continue

        caso.evi.http(f"comision_{i}_bd", respuesta=fila, paso=i)
        fallos = BD.coherencia_produccion(fila)
        caso.paso(
            f"Variante {i}: coherencia vs producción", not fallos,
            "todas las reglas duras se cumplen" if not fallos
            else "; ".join(fallos))

    _invariante_reparto(caso, cnt, bd, catalogo_itu)

    caso.anotar("Las tres variantes quedan registradas con su evidencia. "
                "Cuando DEV confirme la fórmula, el importe calculado se "
                "puede verificar sin tocar este caso.")
    caso.exigir()


def _suma_comision(fila) -> float:
    """`AgentCommission + CorpCommission` de una fila, o None si no están."""
    if not fila:
        return None
    def col(*nombres):
        for n in nombres:
            for k, v in fila.items():
                if k.lower() == n.lower() and v is not None:
                    return float(v)
        return None
    a = col("AgentCommission", "ComisionAgente")
    c = col("CorpCommission", "ComisionCorp", "CorporateCommission")
    return None if a is None or c is None else round(a + c, 4)


def _invariante_reparto(caso, cnt, bd, catalogo_itu):
    """Dos altas del mismo SKU y monto deben repartir la misma comisión total.

    Es lo único del cálculo que se puede exigir hoy: no necesita la fórmula,
    solo que el resultado sea reproducible. Si dos altas idénticas suman
    distinto, la comisión depende de algo que no es el producto ni el monto.
    """
    if bd is None:
        caso.paso("La comisión total es reproducible", None,
                  "sin conexión a BD no se pueden leer las comisiones")
        return

    producto = random.choice(catalogo_itu)
    sumas, ids = [], []
    for _ in range(2):
        cuerpo = B.alta(cnt, producto, monto=20.00)
        r = API.registrar(cuerpo)
        if not r.ok:
            caso.paso("La comisión total es reproducible", None,
                      f"una de las dos altas no se aceptó · {r.resumen()}")
            return
        ids.append(cuerpo["TransactionID"])
        sumas.append(_suma_comision(BD.buscar_transaccion(
            bd, cuerpo["TransactionID"])))

    if None in sumas:
        caso.paso("La comisión total es reproducible", None,
                  f"no se encontraron las columnas AgentCommission / "
                  f"CorpCommission en {P.TABLA_TRANSFER}")
        return

    iguales = abs(sumas[0] - sumas[1]) < 0.005
    caso.paso(
        "La comisión total es reproducible", iguales,
        f"SKU {producto[0]} a 20.00 dos veces ({', '.join(ids)}): "
        f"Agent+Corp = {sumas[0]} y {sumas[1]}."
        + ("" if iguales else
           " Dos altas idénticas repartieron comisiones distintas: el importe "
           "depende de algo que no es el producto ni el monto."))
