"""
Muestra las evidencias que generó un caso y A QUÉ PASO de QMetry irían.

No toca QMetry: solo lee los PNG locales y aplica las reglas de mapeo. Sirve
para revisar el reparto antes de subir nada.

Uso:
    python tools/ver_evidencias.py CP01
    python tools/ver_evidencias.py CP01 --abrir      # abre la carpeta
    python tools/ver_evidencias.py --todos
"""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.helpers import qmetry_sync as S           # noqa: E402


def _mostrar(cp: str) -> None:
    cp = cp.upper()
    carpeta = S.carpeta_de_evidencias(cp)
    mapeo = S.cargar_mapeo().get(cp, {}) or {}
    caso = (mapeo.get("test_case") or "").strip() or "(sin test_case configurado)"
    print(f"\n▶ {cp} → {caso}")
    if not carpeta:
        print("   (sin carpeta de evidencias — corre el caso primero)")
        return
    print(f"   carpeta: {carpeta}")
    imagenes = sorted(carpeta.glob("*.png"))
    if not imagenes:
        print("   (sin imágenes)")
        return

    pasos_map = mapeo.get("pasos") or {}
    patrones = S.mapeo_ultimo_paso(cp)
    print(f"   {len(imagenes)} imagen(es):\n")
    print(f"   {'archivo':44} {'KB':>6}  destino")
    print("   " + "─" * 70)
    for img in imagenes:
        kb = img.stat().st_size // 1024
        directo = S.paso_en_nombre(img.name)
        if directo is not None:
            destino = f"paso {directo}  (por el nombre)"
        elif S._va_al_ultimo_paso(img.name, patrones):
            destino = "ÚLTIMO paso  (regla de cancelación)"
        else:
            seq = S._paso_para(img.name, pasos_map)
            destino = (f"paso {seq}  (mapeo del JSON)" if seq
                       else "ejecución del caso  (sin mapeo)")
        print(f"   {img.name:44} {kb:>6}  {destino}")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--todos" in sys.argv:
        cps = [cp for cp in S.cargar_mapeo()]
    else:
        cps = args or ["CP01"]

    for cp in cps:
        _mostrar(cp)

    if "--abrir" in sys.argv and cps:
        carpeta = S.carpeta_de_evidencias(cps[0].upper())
        if carpeta:
            try:
                if os.name == "nt":
                    os.startfile(str(carpeta))            # noqa: S606
                else:
                    subprocess.run(["xdg-open", str(carpeta)])
            except Exception:
                pass
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
