"""
Diagnóstico del ESTATUS de los pasos en QMetry (Pass / Fail / NA).

Para qué sirve: cuando las imágenes suben pero el estatus del paso NO cambia,
casi siempre es una de dos cosas — el catálogo de resultados no se pudo leer
(ruta distinta según el tenant) o el PUT del paso rechaza el cuerpo. Esta
herramienta separa una de la otra y lo dice en claro.

USO
    python tools/qmetry_estatus.py                    # solo diagnóstico (no escribe)
    python tools/qmetry_estatus.py CP01               # muestra los pasos del CP
    python tools/qmetry_estatus.py CP01 --paso 4 --marcar Pass    # ESCRIBE
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings                                    # noqa: E402
from src.helpers.qmetry_client import QMetryClient, QMetryError  # noqa: E402
from src.helpers import qmetry_sync as S                        # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Diagnóstico de estatus en QMetry")
    ap.add_argument("cp", nargs="?", help="Caso del sanity (ej. CP01)")
    ap.add_argument("--ciclo", default=None, help="Test Cycle (default: el del ambiente)")
    ap.add_argument("--paso", type=int, default=None, help="seqNo del paso a marcar")
    ap.add_argument("--marcar", default=None, help="Pass | Fail | NA")
    args = ap.parse_args()

    if not settings.QMETRY_API_KEY:
        print("✗ Falta QMETRY_API_KEY en el .env.")
        return 2

    q = QMetryClient()

    # ── 1. Catálogo de resultados ────────────────────────────────────────────
    print("\n1) Catálogo de resultados del proyecto")
    try:
        filas = q.resultados_disponibles()
        for r in filas:
            print(f"   • {q._nombre_resultado(r):<24} id={r.get('id')}")
    except QMetryError as e:
        print(f"   ✗ No se pudo leer: {e}")
        print("\n   → Sin catálogo NO hay forma de escribir el estatus.")
        print("     Comparte esta salida y ajusto la ruta del endpoint.")
        return 1

    print("\n2) Resolución de los nombres que usa el proyecto")
    for nombre in ("Pass", "Fail", "NA"):
        rid = q.id_resultado(nombre)
        print(f"   • {nombre:<6} → {rid if rid else '✗ NO RESUELTO'}")

    if not args.cp:
        print("\n(Pasa un CP para ver sus pasos: python tools/qmetry_estatus.py CP01)")
        return 0

    # ── 3. Pasos del caso en el ciclo ────────────────────────────────────────
    cp = args.cp.upper()
    caso_key = S.mapeo_caso(cp)
    if not caso_key or caso_key == "?":
        print(f"\n✗ {cp} no tiene 'test_case' en config/qmetry_mapeo.json.")
        return 2
    ciclo_key = args.ciclo or settings.QMETRY_TEST_CYCLE
    print(f"\n3) Pasos de {cp} → {caso_key} (ciclo {ciclo_key})")
    try:
        ciclo_id = q.obtener_ciclo(ciclo_key)["id"]
        caso = q.buscar_caso_en_ciclo(ciclo_id, caso_key)
        exec_id = caso.get("testCaseExecutionId")
        pasos = q.obtener_pasos(ciclo_id, exec_id)
    except QMetryError as e:
        print(f"   ✗ {e}")
        return 1

    na_declarados = set((S.cargar_mapeo().get(cp, {}) or {}).get("na") or [])
    por_seq = {}
    for p in sorted(pasos, key=lambda x: x.get("testStepSeqNo") or 0):
        seq = p.get("testStepSeqNo")
        por_seq[seq] = p
        estado = (p.get("executionResult") or {}).get("name") if isinstance(
            p.get("executionResult"), dict) else p.get("executionResult")
        tiene_img = "sí" if "inline-attachments" in (p.get("actualResult") or "") else "no"
        marca = "  ← NA declarado" if seq in na_declarados else ""
        print(f"   paso {seq:<3} estatus={str(estado or '—'):<14} "
              f"evidencia={tiene_img:<3}{marca}")

    # ── 4. Escritura de prueba (opcional) ────────────────────────────────────
    if args.paso and args.marcar:
        paso = por_seq.get(args.paso)
        if not paso:
            print(f"\n✗ El caso no tiene el paso {args.paso}.")
            return 2
        rid = q.id_resultado(args.marcar)
        if not rid:
            print(f"\n✗ '{args.marcar}' no existe en el catálogo (mira el punto 1).")
            return 1
        print(f"\n4) Marcando el paso {args.paso} como '{args.marcar}' (id={rid})…")
        try:
            q.actualizar_paso(ciclo_id, paso.get("testStepExecutionId"),
                              resultado_id=rid)
            print("   ✓ Escrito. Refresca QMetry y confírmalo.")
        except QMetryError as e:
            print(f"   ✗ El PUT no fue aceptado: {e}")
            print("     → Comparte este error y ajusto el cuerpo de la petición.")
            return 1
    elif args.paso or args.marcar:
        print("\n(Para escribir necesito ambos: --paso N --marcar Pass)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
