"""
Driver de repetición de pytest para el runner de la GUI.

Ejecuta pytest en bucle: por CANTIDAD (--count N) o por TIEMPO (--seconds S).
Si no se pasa ninguno, corre una sola vez. La salida de cada iteración va a
stdout (el runner la captura en el log). Pensado para pruebas repetidas, p.ej.
"corre la etiqueta KRA-1125 negativas 5 veces" o "... por 2 minutos".

Uso:
    python tools/run_repeat.py --count 5 -- <args de pytest>
    python tools/run_repeat.py --seconds 120 -- <args de pytest>
"""

import subprocess
import sys
import time


def _parse(argv):
    count, seconds, rest = 0, 0, list(argv)
    out = []
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == "--count" and i + 1 < len(rest):
            count = int(rest[i + 1]); i += 2; continue
        if a == "--seconds" and i + 1 < len(rest):
            seconds = int(rest[i + 1]); i += 2; continue
        if a == "--":
            out = rest[i + 1:]; break
        out.append(a); i += 1
    return count, seconds, out


def main():
    count, seconds, pytest_args = _parse(sys.argv[1:])
    inicio = time.time()
    i = 0
    fallos = 0
    while True:
        i += 1
        etiqueta = f"Iteración {i}"
        if count:
            etiqueta += f"/{count}"
        elif seconds:
            transcurrido = int(time.time() - inicio)
            etiqueta += f" · {transcurrido}s/{seconds}s"
        print(f"\n===================== {etiqueta} =====================",
              flush=True)
        rc = subprocess.run([sys.executable, "-m", "pytest", *pytest_args]).returncode
        if rc != 0:
            fallos += 1
        if count and i >= count:
            break
        if seconds and (time.time() - inicio) >= seconds:
            break
        if not count and not seconds:
            break

    print(f"\n[run_repeat] Terminadas {i} iteración(es) · {fallos} con fallos.",
          flush=True)
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()
