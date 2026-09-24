"""
Borrón y cuenta nueva para la etiqueta KRA-1527.

Deja el ambiente como si la etiqueta nunca se hubiera corrido: sin evidencias
viejas, sin reporte acumulado y sin volcados de memoria olvidados.

Existe porque el reporte **se acumula a propósito** entre corridas (así se
puede estabilizar un caso a la vez sin perder los resultados de los otros), y
entonces hace falta una forma explícita de empezar de cero antes de la corrida
que se va a entregar como evidencia.

    python tools/kra1527_reset.py            # pregunta antes de borrar
    python tools/kra1527_reset.py --si       # sin preguntar
    python tools/kra1527_reset.py --solo-dmp # solo los .DMP
    python tools/kra1527_reset.py --con-dmp  # capturas Y volcados

Lo que borra por defecto:
  • reports/evidence/KRA-1527/   → capturas, reportes del inspector, HTML

Lo que NO borra por defecto:
  • reports/evidence/KRA-1527/VolcadoMemoriaDMP/  → los .DMP

## Por qué los .DMP se salvan del borrón

Los volcados vivían en `%TEMP%` y eran desechables; ahora se escriben dentro
de la carpeta de evidencia, y este script la borraba entera con `rmtree`. La
salvaguarda que impide barrer el respaldo está en `borrar_volcados()`, pero
`rmtree` no pasa por ahí: se lleva el árbol completo sin preguntar. Un volcado
cuesta una transacción real en producción y pesa medio giga; recuperarlo es
repetir el caso. Así que el reset limpia lo reproducible —capturas, HTML,
reporte acumulado— y deja los .DMP salvo que se pidan explícitamente.
"""

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings                              # noqa: E402
from src.helpers.memdump_helper import (RESPALDO_DIR,     # noqa: E402
                                        purgar_respaldo)

EVIDENCIA = settings.EVIDENCE_DIR / "KRA-1527"


def _volcados() -> list:
    """Los .DMP del respaldo. `set` porque en Windows el glob ignora
    mayúsculas y `*.dmp`/`*.DMP` devuelven el mismo archivo dos veces."""
    if not RESPALDO_DIR.exists():
        return []
    try:
        return sorted(set(RESPALDO_DIR.glob("*.dmp")) |
                      set(RESPALDO_DIR.glob("*.DMP")))
    except Exception:
        return []


def _borrar_evidencia_salvo_dmp() -> None:
    """Vacía la carpeta de evidencia dejando intacto `VolcadoMemoriaDMP`."""
    for hijo in EVIDENCIA.iterdir():
        try:
            if hijo.resolve() == RESPALDO_DIR.resolve():
                continue
        except Exception:
            pass
        try:
            shutil.rmtree(hijo) if hijo.is_dir() else hijo.unlink()
        except Exception as e:
            print(f"  ✗ No se pudo borrar {hijo.name}: {e}")


def _tamano(carpeta: Path) -> str:
    try:
        total = sum(f.stat().st_size for f in carpeta.rglob("*") if f.is_file())
    except Exception:
        return "?"
    return f"{total / 1e6:.1f} MB"


def main() -> int:
    ap = argparse.ArgumentParser(description="Reset de la etiqueta KRA-1527")
    ap.add_argument("--si", action="store_true", help="no preguntar")
    ap.add_argument("--solo-dmp", action="store_true",
                    help="borrar solo los volcados de memoria")
    ap.add_argument("--con-dmp", action="store_true",
                    help="borrar también los .DMP (por defecto se conservan)")
    args = ap.parse_args()

    toca_evidencia = not args.solo_dmp
    toca_dmp = args.solo_dmp or args.con_dmp

    volcados = _volcados()
    peso_dmp = sum(f.stat().st_size for f in volcados) / 1e9

    print("Reset de KRA-1527")
    print("─" * 60)
    if toca_evidencia:
        if EVIDENCIA.exists():
            archivos = sum(1 for f in EVIDENCIA.rglob("*")
                           if f.is_file() and f not in volcados)
            print(f"  SE BORRA  : {EVIDENCIA}")
            print(f"              {archivos} archivo(s) · {_tamano(EVIDENCIA)}"
                  " (capturas, reportes, HTML)")
        else:
            print(f"  Evidencias: no hay nada en {EVIDENCIA}")
    if toca_dmp:
        print(f"  SE BORRA  : {len(volcados)} volcado(s) .DMP · "
              f"{peso_dmp:.2f} GB")
        print(f"              {RESPALDO_DIR}")
    elif volcados:
        # Decirlo aquí y no en la ayuda: es el momento en que importa.
        print(f"  SE CONSERVA: {len(volcados)} volcado(s) .DMP · "
              f"{peso_dmp:.2f} GB")
        print(f"              {RESPALDO_DIR}")
        print("              (para borrarlos: --con-dmp)")
    print("─" * 60)

    if not args.si:
        resp = input("¿Borrar? [s/N] ").strip().lower()
        if resp not in ("s", "si", "sí", "y", "yes"):
            print("Cancelado — no se borró nada.")
            return 1

    if toca_evidencia and EVIDENCIA.exists():
        try:
            if toca_dmp:
                shutil.rmtree(EVIDENCIA)
                print(f"✓ Evidencias, reporte y volcados borrados: {EVIDENCIA}")
                print("\nListo. La siguiente corrida empieza de cero.")
                return 0
            _borrar_evidencia_salvo_dmp()
            print(f"✓ Evidencias y reporte borrados: {EVIDENCIA}")
        except Exception as e:
            print(f"✗ No se pudo borrar {EVIDENCIA}: {e}")
            return 2

    if toca_dmp:
        n, gb = purgar_respaldo()
        print(f"✓ {n} volcado(s) .DMP borrado(s) · {gb} GB liberados.")

    print("\nListo. La siguiente corrida empieza de cero.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
