"""
Diagnóstico: ¿dónde quedaron los adjuntos que subimos a QMetry?

La API confirma los adjuntos pero la interfaz no los muestra. Este script
responde las tres preguntas que importan:

  1. ¿Cuántas EJECUCIONES tiene el caso en el ciclo? (si hay varias, la UI
     muestra la última; si subimos a otra, no se ve nada).
  2. ¿Qué adjuntos ve la API por paso y por ejecución, con qué `size`, `level`
     y `url`? (size = 0 → el archivo llegó vacío a S3).
  3. ¿La URL del adjunto descarga realmente la imagen?

Uso:
    python tools/qmetry_diag.py
    python tools/qmetry_diag.py --caso BM-TC-4644 --ciclo BM-TR-1370
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests                                                # noqa: E402
from config import settings                                    # noqa: E402
from src.helpers.qmetry_client import QMetryClient, QMetryError  # noqa: E402


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
    q = QMetryClient()

    print("─" * 78)
    print(f"  Ciclo {ciclo_key} · Caso {caso_key} · proyecto {settings.QMETRY_PROJECT_KEY}")
    print("─" * 78)

    ciclo = q.obtener_ciclo(ciclo_key)
    cid = ciclo["id"]
    caso = q.buscar_caso_en_ciclo(cid, caso_key)
    exec_id = caso.get("testCaseExecutionId")
    map_id = caso.get("testCycleTestCaseMapId")
    print(f"\nCaso: testCaseExecutionId={exec_id} · testCycleTestCaseMapId={map_id}")
    print(f"      versionNo={caso.get('versionNo')} · "
          f"executionResult={(caso.get('executionResult') or {}).get('name')}")

    # ── 1. ¿Cuántas ejecuciones hay? ────────────────────────────────────────
    print("\n[1] EJECUCIONES del caso en este ciclo")
    try:
        data = q._pedir("GET", f"/testcycles/{cid}/testcases/{map_id}/executions",
                        params={"startAt": 0, "maxResults": 50})
        filas = data.get("data") or []
        if not filas:
            print("    (la API no devolvió historial de ejecuciones)")
        for f in filas:
            eid = (f.get("testCaseExecutionId") or f.get("id") or
                   f.get("executionId"))
            marca = "  ← la que usamos" if str(eid) == str(exec_id) else ""
            print(f"    · id={eid} · {f.get('executedOn') or f.get('created') or ''} "
                  f"· {(f.get('executionResult') or {}).get('name','')}{marca}")
        if len(filas) > 1:
            print("    ⚠ Hay VARIAS ejecuciones: la interfaz muestra la más")
            print("      reciente. Si subimos a otra, no se ve.")
    except QMetryError as e:
        print(f"    ⚠ No se pudo consultar: {str(e)[:120]}")

    # ── 2. Adjuntos por paso ────────────────────────────────────────────────
    print("\n[2] ADJUNTOS por paso (lo que ve la API)")
    pasos = q.obtener_pasos(cid, exec_id)
    total = 0
    for p in pasos:
        sid = p.get("testStepExecutionId")
        seq = p.get("testStepSeqNo")
        encontrados = []
        for inline in (False, True):
            try:
                for a in q.listar_adjuntos_paso(cid, sid, inline=inline):
                    encontrados.append((inline, a))
            except QMetryError:
                pass
        if not encontrados:
            continue
        print(f"\n    Paso #{seq} (stepExecutionId={sid})")
        for inline, a in encontrados:
            total += 1
            print(f"      · {a.get('name') or a.get('fileName')}")
            print(f"        id={a.get('id')} · size={a.get('size')} bytes · "
                  f"level={a.get('level')} · inline={str(inline).lower()}")
            print(f"        stepSeqNo={a.get('stepSeqNo')} · "
                  f"stepExecutionSeqNo={a.get('stepExecutionSeqNo')}")
            url = a.get("url")
            if url:
                print(f"        url={url[:100]}…")
    if total == 0:
        print("    (ningún paso reporta adjuntos)")

    # ── 3. Adjuntos a nivel de ejecución ────────────────────────────────────
    print("\n[3] ADJUNTOS a nivel de EJECUCIÓN del caso")
    try:
        for inline in (False, True):
            lista = q.listar_adjuntos_ejecucion(cid, exec_id, inline=inline)
            print(f"    inline={str(inline).lower()}: {len(lista)} adjunto(s)")
            for a in lista:
                print(f"      · {a.get('name')} · size={a.get('size')} · "
                      f"level={a.get('level')}")
    except QMetryError as e:
        print(f"    ⚠ {str(e)[:120]}")

    # ── 4. ¿La URL descarga la imagen? ──────────────────────────────────────
    print("\n[4] ¿La URL del primer adjunto devuelve la imagen?")
    primera_url = None
    for p in pasos:
        try:
            for a in q.listar_adjuntos_paso(cid, p.get("testStepExecutionId")):
                if a.get("url"):
                    primera_url = a["url"]
                    nombre = a.get("name")
                    break
        except QMetryError:
            pass
        if primera_url:
            break
    if not primera_url:
        print("    (no hay URL para probar)")
    else:
        try:
            r = requests.get(primera_url, timeout=30)
            print(f"    '{nombre}' → HTTP {r.status_code} · "
                  f"{len(r.content)} bytes · {r.headers.get('Content-Type')}")
            if r.status_code == 200 and len(r.content) < 100:
                print("    ⚠ La imagen pesa casi nada: probablemente se subió VACÍA.")
            elif r.status_code == 200:
                print("    ✓ La imagen se descarga bien (el archivo en S3 está correcto).")
            else:
                print("    ⚠ La URL no sirve para descargar (puede requerir firma).")
        except Exception as e:
            print(f"    ⚠ No se pudo descargar: {str(e)[:100]}")

    print("\n" + "─" * 78)
    print("Interpretación rápida:")
    print(" • Si [2] muestra los adjuntos con size > 0 y [1] tiene UNA sola")
    print("   ejecución → el dato está bien y es un tema de la vista en QMetry")
    print("   (abre el detalle del PASO dentro de la ejecución, no el caso).")
    print(" • Si [1] muestra VARIAS ejecuciones → hay que subir a la última.")
    print(" • Si size = 0 → el archivo llegó vacío: revisar el multipart.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except QMetryError as e:
        print(f"✖ {e}")
        sys.exit(1)
