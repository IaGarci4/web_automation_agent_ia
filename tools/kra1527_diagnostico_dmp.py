"""
Diagnóstico de un `.DMP` que no se puede leer — KRA-1527.

## Por qué existe

Llevamos dos corridas de nueve minutos perdidas contra el mismo síntoma:
el volcado se captura, pesa medio giga, y al leerlo salta
`[Errno 13] Permission denied`. Las dos explicaciones que probamos (antivirus
escaneando, escritura sin terminar) resultaron falsas: el tamaño se mantuvo
estable 300 segundos, así que el archivo estaba completo y quieto.

El problema es que **Python no distingue las dos causas posibles**. Windows
tiene dos errores muy distintos aquí:

    ERROR_ACCESS_DENIED (5)      → el permiso al archivo está denegado.
                                   Culpables: ACL, antivirus bloqueándolo,
                                   cuarentena en el sitio.
    ERROR_SHARING_VIOLATION (32) → hay otro proceso con el archivo abierto
                                   sin compartir lectura.

Y los dos llegan a Python como el mismo `errno 13`. Adivinar cuál es de los dos
cuesta una corrida entera; preguntárselo a Windows cuesta cinco segundos.

## Uso

    python tools/kra1527_diagnostico_dmp.py                  # el .DMP más reciente
    python tools/kra1527_diagnostico_dmp.py --archivo <ruta>

No modifica nada excepto una copia temporal de prueba, que borra al terminar.
"""

import argparse
import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings                                    # noqa: E402
from src.helpers.memdump_helper import RESPALDO_DIR            # noqa: E402

# ── API de Windows: abrir el archivo y quedarnos con el error DE VERDAD ──────
GENERIC_READ = 0x80000000
FILE_SHARE_READ, FILE_SHARE_WRITE, FILE_SHARE_DELETE = 0x1, 0x2, 0x4
OPEN_EXISTING = 3
INVALID_HANDLE = ctypes.c_void_p(-1).value

_ERRORES = {
    5:  ("ERROR_ACCESS_DENIED", "El permiso al archivo está DENEGADO. No es "
         "que otro lo tenga abierto: es que no nos deja. Sospechosos: el "
         "antivirus lo bloqueó (un volcado de memoria con credenciales dentro "
         "es exactamente lo que produce el malware de robo de credenciales), o "
         "la ACL del archivo salió mal al crearlo."),
    32: ("ERROR_SHARING_VIOLATION", "Otro proceso lo tiene ABIERTO sin "
         "compartir la lectura. Aquí sí hay un dueño identificable: encuéntralo "
         "con `handle64.exe -a <ruta>` (Sysinternals) o con el Monitor de "
         "recursos → CPU → Identificadores asociados."),
    33: ("ERROR_LOCK_VIOLATION", "Hay un bloqueo por rangos sobre el archivo."),
}


def _abrir(ruta: Path, share: int):
    """CreateFileW en crudo. Devuelve (ok, código, nombre, explicación)."""
    CreateFileW = ctypes.windll.kernel32.CreateFileW
    CreateFileW.restype = wintypes.HANDLE
    h = CreateFileW(str(ruta), GENERIC_READ, share, None, OPEN_EXISTING, 0, None)
    if h and h != INVALID_HANDLE:
        ctypes.windll.kernel32.CloseHandle(h)
        return True, 0, "OK", ""
    cod = ctypes.get_last_error() or ctypes.windll.kernel32.GetLastError()
    nombre, expl = _ERRORES.get(cod, (f"WinError {cod}", ""))
    return False, cod, nombre, expl


def _ps(comando: str, timeout=60) -> str:
    """Ejecuta PowerShell y devuelve la salida (o el motivo del fallo)."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", comando],
            capture_output=True, text=True, timeout=timeout)
        return ((r.stdout or "") + (r.stderr or "")).strip()
    except Exception as e:
        return f"(no se pudo consultar: {str(e)[:100]})"


def _mas_reciente() -> Path:
    dmps = []
    for carpeta in [RESPALDO_DIR, *settings.DUMP_DIRS_CANDIDATAS,
                    Path(tempfile.gettempdir())]:
        try:
            dmps += list(carpeta.glob("*.dmp")) + list(carpeta.glob("*.DMP"))
        except Exception:
            continue
    if not dmps:
        return None
    return max(set(dmps), key=lambda f: f.stat().st_mtime)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archivo", help="ruta del .DMP (por defecto, el más reciente)")
    args = ap.parse_args()

    if os.name != "nt":
        print("Este diagnóstico solo tiene sentido en Windows.")
        return 2

    ruta = Path(args.archivo) if args.archivo else _mas_reciente()
    if not ruta or not ruta.exists():
        print(f"\n  No encontré ningún .DMP que diagnosticar.\n"
              f"  Busqué en: {RESPALDO_DIR}\n")
        return 2

    print("=" * 72)
    print("  DIAGNÓSTICO DE VOLCADO ILEGIBLE — KRA-1527")
    print("=" * 72)
    print(f"  Archivo : {ruta}")

    # ── 1. ¿Está quieto? ────────────────────────────────────────────────────
    t1 = ruta.stat().st_size
    time.sleep(3)
    t2 = ruta.stat().st_size
    print(f"  Tamaño  : {t1/1e6:.1f} MB"
          + ("" if t1 == t2 else f"  → {t2/1e6:.1f} MB ¡SIGUE CRECIENDO!"))
    print(f"  Escrito : hace {(time.time() - ruta.stat().st_mtime)/60:.1f} min")

    # ── 2. La pregunta clave: ¿cuál de los dos errores es? ──────────────────
    print("\n── ¿Por qué no se puede abrir? ─────────────────────────────────")
    combos = [
        ("compartiendo lectura+escritura+borrado (lo más permisivo)",
         FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE),
        ("compartiendo solo lectura (lo que hace Python)", FILE_SHARE_READ),
        ("sin compartir nada (acceso exclusivo)", 0),
    ]
    culpa = None
    for etiqueta, share in combos:
        ok, cod, nombre, expl = _abrir(ruta, share)
        print(f"  {'✓' if ok else '✗'} {etiqueta}: {nombre}")
        if not ok and culpa is None:
            culpa = (cod, nombre, expl)

    if culpa is None:
        print("\n  ⚠ El archivo SE ABRE sin problema ahora mismo. El bloqueo era "
              "temporal.\n  Analízalo ya:\n"
              f"    python tools/kra1527_volcar.py --archivo \"{ruta}\"")
        return 0

    cod, nombre, expl = culpa
    print(f"\n  → CAUSA: {nombre} ({cod})\n    {expl}")

    # ── 3. ¿Lo tocó el antivirus? ───────────────────────────────────────────
    print("\n── ¿Hay una detección de Defender sobre este archivo? ──────────")
    det = _ps("Get-MpThreatDetection | Sort-Object InitialDetectionTime "
              "-Descending | Select-Object -First 5 "
              "InitialDetectionTime,ThreatID,Resources | Format-List")
    print("  " + (det.replace("\n", "\n  ") if det else "(sin detecciones)"))

    print("\n── ¿Está la carpeta excluida del antivirus? ────────────────────")
    exc = _ps("(Get-MpPreference).ExclusionPath")
    carpeta = str(ruta.parent)
    excluida = carpeta.lower() in (exc or "").lower()
    print(f"  Exclusiones actuales: {exc or '(ninguna)'}")
    print(f"  ¿{carpeta} excluida?: {'SÍ' if excluida else 'NO'}")

    # ── 4. ¿Es cosa de Python o del archivo? ────────────────────────────────
    print("\n── ¿Lo puede leer otra herramienta? ───────────────────────────")
    fs = _ps(f'cmd /c findstr /m /c:"eyJ" "{ruta}" 2>&1 | Select-Object -First 2')
    print(f"  findstr : {fs[:200] or '(sin salida)'}")

    # ── 5. La prueba que decide el arreglo: ¿se puede COPIAR? ────────────────
    print("\n── ¿Se puede copiar a %TEMP% y leer la copia? ─────────────────")
    print("  (si esto funciona, el arreglo es analizar una copia, no el original)")
    copia = Path(tempfile.gettempdir()) / f"diag_{ruta.name}"
    try:
        shutil.copy2(ruta, copia)
        ok, cod2, nombre2, _ = _abrir(copia, FILE_SHARE_READ)
        print(f"  Copia creada ({copia.stat().st_size/1e6:.1f} MB) → "
              f"abrir la copia: {nombre2}")
        if ok:
            print("\n  ✅ ESTE ES EL CAMINO: el original está bloqueado pero se "
                  "puede copiar,\n     y la copia se lee. Dímelo y cambio el "
                  "helper para que analice una\n     copia temporal y conserve "
                  "el original como evidencia.")
    except Exception as e:
        print(f"  ✗ Ni copiar se puede: {type(e).__name__}: {str(e)[:120]}")
        print("    Con esto, el bloqueo es sobre el archivo entero. El arreglo "
              "va por\n    otro lado: volcar con una herramienta que Defender no "
              "marque (procdump\n    firmado por Microsoft) o excluir la carpeta.")
    finally:
        try:
            copia.unlink(missing_ok=True)
        except Exception:
            pass

    # ── 6. Permisos del archivo ─────────────────────────────────────────────
    print("\n── Permisos (por si la ACL salió mal al crearlo) ───────────────")
    ic = _ps(f'cmd /c icacls "{ruta}"')
    print("  " + (ic.replace("\n", "\n  ")[:600] if ic else "(sin datos)"))

    print("\n" + "=" * 72)
    print("  Pégame esta salida y lo arreglo con datos, no con hipótesis.")
    print("=" * 72)
    return 1


if __name__ == "__main__":
    sys.exit(main())
