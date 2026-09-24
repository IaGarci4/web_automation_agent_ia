"""
Muestra el contenido CRUDO de un paso de ejecución (incluido `actualResult`).

Sirve para copiar el formato EXACTO con el que QMetry incrusta una imagen en el
campo "Actual Result" cuando se pega a mano, y así replicarlo por API.

Uso:
    python tools/qmetry_ver_paso.py --paso 2
    python tools/qmetry_ver_paso.py --paso 2 --caso BM-TC-4644 --ciclo BM-TR-1370
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings                                      # noqa: E402
from src.helpers.qmetry_client import QMetryClient, QMetryError   # noqa: E402


def _arg(nombre, defecto=None):
    if nombre in sys.argv:
        try:
            return sys.argv[sys.argv.index(nombre) + 1]
        except IndexError:
            pass
    return defecto


def main() -> int:
    ciclo_key = _arg("--ciclo", settings.QMETRY_TEST_CYCLE)
    caso_key = _arg("--caso", "BM-TC-4644")
    seq = _arg("--paso", "2")

    q = QMetryClient()
    ciclo = q.obtener_ciclo(ciclo_key)
    caso = q.buscar_caso_en_ciclo(ciclo["id"], caso_key)
    pasos = q.obtener_pasos(ciclo["id"], caso["testCaseExecutionId"])

    objetivo = next((p for p in pasos
                     if str(p.get("testStepSeqNo")) == str(seq)), None)
    if objetivo is None:
        print(f"✖ No existe el paso {seq}.")
        return 1

    print("─" * 78)
    print(f"  Paso #{objetivo.get('testStepSeqNo')} · "
          f"testStepExecutionId={objetivo.get('testStepExecutionId')}")
    print("─" * 78)
    print("\n>>> JSON COMPLETO DEL PASO:")
    print(json.dumps(objetivo, indent=2, ensure_ascii=False))

    actual = objetivo.get("actualResult")
    print("\n" + "─" * 78)
    print(">>> CAMPO 'actualResult' (así incrusta QMetry las imágenes):")
    print("─" * 78)
    if actual:
        print(actual)
        if "<img" in str(actual).lower():
            print("\n✓ Contiene una etiqueta <img> → este es el formato a replicar.")
    else:
        print("(vacío — si pegaste la imagen a mano y aparece vacío, QMetry la "
              "guarda en otro campo)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except QMetryError as e:
        print(f"✖ {e}")
        sys.exit(1)
