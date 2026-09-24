"""
¿Por qué toda alta legítima devuelve `Errorcode 15`?

La corrida del 10-sep dejó un cuadro muy concreto:

    MD5 falso          →  4   Session is invalid
    campos faltantes   →  5   Validation error
    Amount negativo    →  5   Validation error
    cancelar inexistente → 12 Transaction does not exists…
    ALTA LEGÍTIMA      →  15  Internal error, please notify to technical support

De ahí se deducen dos cosas sin tocar nada más:

  · Las **credenciales son correctas**. Un MD5 malo da 4; el nuestro no da 4.
  · El **cuerpo pasa la validación**. Faltar campos da 5; el nuestro no da 5.

Así que la petición entra, se autentica, se valida… y explota al procesarse.
Lo que queda por separar es si explota por un defecto de la API o porque
algún dato del cuerpo no existe en SU entorno — `Entity`, `SKU`, `IdAgent` e
`IdUser` vienen de los valores por defecto heredados del runner viejo y nunca
los confirmó desarrollo.

## Cómo lo separa esta herramienta

Cambiando **un eje cada vez** sobre el mismo cuerpo base. Si un eje cambia el
Errorcode, ese eje es la causa; si ninguno lo cambia, el 15 es del servidor y
se reporta tal cual.

Es la misma escalera que sirvió con el volcado de memoria: no adivinar, medir.

    python tools/trn239_diagnostico_alta.py

Nada de esto escribe datos mientras siga saliendo 15. Si alguna variante
llega a `Errorcode 0`, **eso sí da de alta una transacción real en TEST** —
y también es la respuesta que buscamos.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.tests.etiquetas.TRN_239 import parametros as P       # noqa: E402
from src.tests.etiquetas.TRN_239.flujos import bodies as B     # noqa: E402
from src.tests.etiquetas.TRN_239.flujos import lunex_api as API  # noqa: E402

# SKU citados en el requerimiento del Confluence. Si el catálogo de la API no es el
# mismo `lunex.Product` que lee la etiqueta, estos deberían existir igual.
SKU_CONTRATO = [
    ("8485", "Honduras - PaqueTigo", "ITU"),
    ("8510", "Mexico - Telcel Amigo Sin Limite", "ITU"),
]

# Campos que el requerimiento marca como obligatorios. Todo lo demás es relleno
# que podría estar molestando.
MINIMOS = ("Login", "Md5", "Key", "Action", "Status", "TransactionID",
           "TransactionDate", "Entity", "ExternalID", "SKU", "SKUName",
           "SKUType", "Amount", "Phone")


def _linea(nombre, r, extra=""):
    marca = "✓" if r.ok else " "
    print(f"  {marca} {nombre:<44} → {r.estado} · Errorcode="
          f"{r.errorcode} · {r.error_text or '(sin texto)'}")
    if extra:
        print(f"      {extra}")
    return r


def main() -> int:
    cnt = B.Contadores()
    print()
    print("═" * 78)
    print("  TRN-239 · ¿de dónde sale el Errorcode 15?")
    print("═" * 78)
    print(f"  {P.BASE_URL}{P.RUTA_REGISTER}")
    print(f"  Login={P.LOGIN} · Entity={P.ENTITY} · "
          f"IdAgent={P.ID_AGENT} · IdUser={P.ID_USER}")
    print("─" * 78)

    resultados = {}

    # 0. Línea base — tal cual lo manda la etiqueta.
    base = B.alta(cnt, P.PRODUCTOS[0])
    resultados["base"] = _linea("Base (como la etiqueta)", API.registrar(base))

    # 1. SKU del requerimiento, por si el catálogo de la API es otro.
    for sku, nombre, tipo in SKU_CONTRATO:
        cuerpo = B.alta(cnt, (sku, nombre, tipo))
        resultados[f"sku_{sku}"] = _linea(
            f"SKU {sku} ({nombre[:22]})", API.registrar(cuerpo))

    # 2. Solo los campos obligatorios: descarta que estorbe algún opcional
    #    (PIN, DestinationAmount, AccessNumber… todos van en null).
    completo = B.alta(cnt, P.PRODUCTOS[0])
    minimo = {k: v for k, v in completo.items() if k in MINIMOS}
    resultados["minimo"] = _linea(
        f"Solo los {len(MINIMOS)} campos obligatorios", API.registrar(minimo))

    # 3. Importe entero, por si el decimal o la coherencia con la comisión
    #    rompe algo aguas abajo.
    entero = B.alta(cnt, P.PRODUCTOS[0], monto=10)
    entero["AmountInMN"] = 0
    entero["ExRate"] = 0
    entero["CommissionPercentage"] = 0
    entero["D1Discount"] = 0
    resultados["monto_simple"] = _linea(
        "Amount=10 sin comisión ni tipo de cambio", API.registrar(entero))

    # 4. Sin los campos de dinero derivados, que son los que más dependen del
    #    catálogo del servidor.
    sin_derivados = B.alta(cnt, P.PRODUCTOS[0])
    for k in ("AmountInMN", "ExRate", "CountryCurrency", "D1Discount",
              "D2Discount", "R1Discount", "R2Discount", "Fee",
              "CommissionPercentage"):
        sin_derivados.pop(k, None)
    resultados["sin_derivados"] = _linea(
        "Sin campos de comisión ni cambio", API.registrar(sin_derivados))

    # 5. Entity alternativa, si se pasó una por entorno.
    import os
    otra = os.getenv("TRN239_ENTITY_ALT", "").strip()
    if otra:
        cuerpo = B.alta(cnt, P.PRODUCTOS[0])
        cuerpo["Entity"] = otra
        resultados["entity_alt"] = _linea(
            f"Entity alternativa ({otra})", API.registrar(cuerpo))

    # ── Lectura ─────────────────────────────────────────────────────────────
    print("─" * 78)
    codigos = {k: str(r.errorcode) for k, r in resultados.items()}
    distintos = set(codigos.values())
    exitosas = [k for k, r in resultados.items() if r.ok]

    if exitosas:
        print("  RESPUESTA: alguna variante SÍ funcionó →",
              ", ".join(exitosas))
        print("  El 15 no es del servidor: es un dato del cuerpo que su")
        print("  entorno no acepta. Compara esa variante con la base.")
    elif len(distintos) == 1:
        print(f"  RESPUESTA: TODAS las variantes dan el mismo Errorcode "
              f"({distintos.pop()}).")
        print("  Ni el SKU, ni los opcionales, ni los importes derivados lo")
        print("  cambian. Con la autenticación correcta y la validación")
        print("  superada, el fallo está DENTRO de la API: es un defecto que")
        print("  reportar a desarrollo, no un problema de las pruebas.")
        print()
        print("  Qué adjuntar al ticket:")
        print("   · el cuadro de arriba (misma respuesta ante cinco cuerpos"
              " distintos)")
        print("   · un TransactionID de los intentos, para que busquen el")
        print("     stack en sus logs por correlación de hora")
        print("   · que los negativos SÍ responden bien (4, 5, 12): el")
        print("     catálogo de errores funciona, lo que falla es el alta")
    else:
        print("  RESPUESTA: las variantes dan códigos DISTINTOS:")
        for k, c in codigos.items():
            print(f"      {k:<20} → Errorcode {c}")
        print("  El eje que cambia el código es la causa.")
    print("═" * 78)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
