"""
Sube a QMetry las evidencias YA generadas por el sanity.

Útil cuando corriste las pruebas sin `QMETRY_UPLOAD=1`, o para reintentar.
Es idempotente: no duplica lo que ya está adjunto.

Uso:
    python tools/qmetry_subir.py CP02                 # un caso
    python tools/qmetry_subir.py CP02 CP03            # varios
    python tools/qmetry_subir.py --todos              # todos los que tengan mapeo
    python tools/qmetry_subir.py CP02 --ciclo BM-TR-1370
    python tools/qmetry_subir.py --prod CP02          # ciclo de producción
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

if "--prod" in sys.argv:
    os.environ["HERMES_ENV"] = "prod"

from config import settings                              # noqa: E402
from src.helpers import qmetry_sync as S                 # noqa: E402


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    ciclo = None
    if "--ciclo" in sys.argv:
        try:
            ciclo = sys.argv[sys.argv.index("--ciclo") + 1]
            if ciclo in args:
                args.remove(ciclo)
        except IndexError:
            pass

    mapeo = S.cargar_mapeo()
    if "--todos" in sys.argv:
        cps = [cp for cp, m in mapeo.items() if (m.get("test_case") or "").strip()]
    else:
        cps = [a.upper() for a in args]
    if not cps:
        print("Indica al menos un CP (ej. CP02) o usa --todos.")
        print("\nCasos con mapeo configurado:")
        for cp, m in mapeo.items():
            tc = (m.get("test_case") or "").strip() or "(sin test_case)"
            print(f"   · {cp:6} → {tc}")
        return 1

    print(f"Ciclo: {ciclo or settings.QMETRY_TEST_CYCLE} "
          f"(ambiente {settings.ENV.upper()})")
    total = {"subidas": 0, "omitidas": 0, "errores": 0}
    for cp in cps:
        print(f"\n▶ {cp}")
        carpeta = S.carpeta_de_evidencias(cp)
        print(f"   evidencias: {carpeta if carpeta else '(no hay carpeta)'}")
        r = S.subir_evidencias(cp, ciclo_key=ciclo)
        print(f"   → {r['subidas']} subida(s) · {r['omitidas']} omitida(s) · "
              f"{r['errores']} error(es)")
        for k in total:
            total[k] += r[k]

    print("\n" + "─" * 60)
    print(f"TOTAL: {total['subidas']} subida(s) · {total['omitidas']} omitida(s) "
          f"· {total['errores']} error(es)")
    return 0 if total["errores"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
