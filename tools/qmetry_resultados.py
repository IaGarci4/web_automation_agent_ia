"""
Lista los RESULTADOS de ejecución del proyecto (Pass, Fail, Not Executed…) con
sus ids, tal como los define QMetry para el proyecto.

Los ids cambian por proyecto, así que el cliente los resuelve por NOMBRE. Este
script sirve para ver el catálogo real y confirmar cómo se llaman exactamente.

Uso:
    python tools/qmetry_resultados.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings                                      # noqa: E402
from src.helpers.qmetry_client import QMetryClient, QMetryError   # noqa: E402


def main() -> int:
    q = QMetryClient()
    print(f"Proyecto {settings.QMETRY_PROJECT_KEY} (id {settings.QMETRY_PROJECT_ID})")
    print("─" * 60)
    try:
        for r in q.resultados_disponibles():
            print(f"  id={r.get('id'):<10} {str(r.get('name')):<18} "
                  f"color={r.get('color')}  default={r.get('isDefault')}")
    except QMetryError as e:
        print(f"✖ {e}")
        return 1
    print("─" * 60)
    for nombre in ("Pass", "Fail", "Not Executed"):
        print(f"  '{nombre}' → id {q.id_resultado(nombre)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
