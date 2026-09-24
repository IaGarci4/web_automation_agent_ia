"""
Borrón y cuenta nueva para TRN-239.

El reporte se ACUMULA a propósito entre corridas: así se puede estabilizar un
caso a la vez sin perder los resultados de los otros. Cuando llega la corrida
que se entrega como evidencia, hace falta una forma explícita de empezar de
cero.

    python tools/trn239_reset.py            # pregunta antes de borrar
    python tools/trn239_reset.py --si       # sin preguntar

Lo que borra:
  · reports/evidence/TRN-239/   → pares petición/respuesta, HTML, acumulado

Lo que NO borra:
  · reports/trn239_contadores.json

Los contadores se conservan a propósito. `Key` es único e **irreutilizable**
según el requerimiento: si se reiniciaran, la siguiente corrida chocaría contra las
transacciones que esta acaba de crear, y el fallo parecería de la API. Para
reiniciarlos —solo si sabes por qué— usa `--contadores`.
"""

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.tests.etiquetas.TRN_239 import parametros as P        # noqa: E402


def _tamano(carpeta: Path) -> str:
    try:
        total = sum(f.stat().st_size for f in carpeta.rglob("*") if f.is_file())
    except Exception:
        return "?"
    return f"{total / 1e6:.1f} MB"


def main() -> int:
    ap = argparse.ArgumentParser(description="Reset de la etiqueta TRN-239")
    ap.add_argument("--si", action="store_true", help="no preguntar")
    ap.add_argument("--contadores", action="store_true",
                    help="reiniciar también Key y TransactionID (raro: ver el "
                         "encabezado de este archivo)")
    args = ap.parse_args()

    print("Reset de TRN-239")
    print("─" * 62)
    hay = P.EVIDENCIA_BASE.exists()
    if hay:
        archivos = sum(1 for _ in P.EVIDENCIA_BASE.rglob("*") if _.is_file())
        print(f"  SE BORRA   : {P.EVIDENCIA_BASE}")
        print(f"               {archivos} archivo(s) · {_tamano(P.EVIDENCIA_BASE)}")
    else:
        print(f"  Evidencias : no hay nada en {P.EVIDENCIA_BASE}")

    if args.contadores:
        print(f"  SE BORRA   : {P.CONTADORES} (Key y TransactionID)")
        print("               ⚠ la próxima corrida puede chocar con las "
              "transacciones ya creadas")
    elif P.CONTADORES.exists():
        print(f"  SE CONSERVA: {P.CONTADORES} (Key es irreutilizable)")
    print("─" * 62)

    if not args.si:
        if input("¿Borrar? [s/N] ").strip().lower() not in (
                "s", "si", "sí", "y", "yes"):
            print("Cancelado — no se borró nada.")
            return 1

    if hay:
        try:
            shutil.rmtree(P.EVIDENCIA_BASE)
            print(f"✓ Evidencias y reporte borrados: {P.EVIDENCIA_BASE}")
        except Exception as e:
            print(f"✗ No se pudo borrar {P.EVIDENCIA_BASE}: {e}")
            return 2

    if args.contadores:
        try:
            P.CONTADORES.unlink(missing_ok=True)
            print("✓ Contadores reiniciados.")
        except Exception as e:
            print(f"✗ No se pudieron borrar los contadores: {e}")

    print("\nListo. La siguiente corrida empieza de cero.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
