"""
Prueba de la integración con QMetry: sube una imagen a un PASO de un caso
dentro de un Test Cycle, mostrando cada etapa para diagnosticar.

Uso (ambiente TEST, no afecta nada):
    python tools/qmetry_probe.py                       # ciclo/caso por defecto, último paso
    python tools/qmetry_probe.py --paso 7              # paso 7
    python tools/qmetry_probe.py --paso 3 --imagen reports/evidence/.../01_x.png
    python tools/qmetry_probe.py --solo-leer          # NO sube nada: solo consulta
    python tools/qmetry_probe.py --caso BM-TC-4644 --ciclo BM-TR-1370

Etapas:
  1) Ciclo por key            → id interno
  2) Caso dentro del ciclo    → testCaseExecutionId
  3) Pasos de la ejecución    → testStepExecutionId de cada paso
  4) Credenciales de subida   → endpoint S3 + params firmados
  5) POST multipart a S3      → 201
  6) Verificación             → lista los adjuntos del paso
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings                                  # noqa: E402
from src.helpers.qmetry_client import QMetryClient, QMetryError   # noqa: E402

CICLO_DEF = settings.QMETRY_TEST_CYCLE          # BM-TR-1370 en test
CASO_DEF = "BM-TC-4644"


def _arg(nombre: str, defecto=None):
    if nombre in sys.argv:
        try:
            return sys.argv[sys.argv.index(nombre) + 1]
        except IndexError:
            pass
    return defecto


def _imagen_de_prueba() -> Path:
    """Usa la imagen indicada, o la primera evidencia del CP02, o crea un PNG."""
    dado = _arg("--imagen")
    if dado:
        return Path(dado)
    base = settings.EVIDENCE_DIR / "sanity_general"
    for carpeta in sorted(base.glob("CP02*")):
        for png in sorted(carpeta.glob("*.png")):
            return png
    # Sin evidencias todavía: PNG mínimo generado al vuelo.
    destino = Path(__file__).parent / "qmetry_prueba.png"
    if not destino.exists():
        import base64
        png_1x1 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42m"
                   "P8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==")
        destino.write_bytes(base64.b64decode(png_1x1))
    return destino


def main() -> int:
    ciclo_key = _arg("--ciclo", CICLO_DEF)
    caso_key = _arg("--caso", CASO_DEF)
    solo_leer = "--solo-leer" in sys.argv
    paso_pedido = _arg("--paso")

    print("─" * 74)
    print(f"  QMetry · {settings.QMETRY_BASE_URL}")
    print(f"  Proyecto : {settings.QMETRY_PROJECT_KEY} (id {settings.QMETRY_PROJECT_ID})")
    print(f"  Ciclo    : {ciclo_key}")
    print(f"  Caso     : {caso_key}")
    print(f"  API Key  : {'definida' if settings.QMETRY_API_KEY else 'FALTA en .env'}")
    print(f"  Jira auth: {'sí (' + settings.QMETRY_JIRA_EMAIL + ')' if settings.QMETRY_JIRA_EMAIL and settings.QMETRY_JIRA_TOKEN else 'no configurado'}")
    print("─" * 74)

    try:
        q = QMetryClient()
    except QMetryError as e:
        print(f"✖ {e}")
        return 1

    # 1) Ciclo
    print("\n[1/6] Buscando el Test Cycle…")
    try:
        ciclo = q.obtener_ciclo(ciclo_key)
    except QMetryError as e:
        print(f"✖ No se pudo leer el ciclo: {e}")
        print("   • Si es 401/403: revisa QMETRY_API_KEY y, si tu tenant lo exige,")
        print("     agrega QMETRY_JIRA_EMAIL + QMETRY_JIRA_TOKEN al .env.")
        return 1
    ciclo_id = ciclo["id"]
    print(f"   ✓ id={ciclo_id} · {ciclo.get('summary','')}")

    # 2) Caso dentro del ciclo
    print("\n[2/6] Buscando el caso dentro del ciclo…")
    try:
        caso = q.buscar_caso_en_ciclo(ciclo_id, caso_key)
    except QMetryError as e:
        print(f"✖ {e}")
        return 1
    exec_id = caso.get("testCaseExecutionId")
    print(f"   ✓ testCaseExecutionId={exec_id} · {caso.get('summary','')}")

    # 3) Pasos
    print("\n[3/6] Leyendo los pasos de la ejecución…")
    pasos = q.obtener_pasos(ciclo_id, exec_id)
    if not pasos:
        print("✖ La ejecución no devolvió pasos.")
        return 1
    for p in pasos:
        det = (p.get("stepDetail") or "").replace("\n", " ")[:58]
        print(f"   · #{p.get('testStepSeqNo')} id={p.get('testStepExecutionId')} · {det}")

    # Paso objetivo: el pedido por --paso (por seqNo) o el ÚLTIMO
    if paso_pedido:
        objetivo = next((p for p in pasos
                         if str(p.get("testStepSeqNo")) == str(paso_pedido)), None)
        if objetivo is None:
            print(f"✖ No hay un paso con seqNo={paso_pedido}.")
            return 1
    else:
        objetivo = pasos[-1]
    step_id = objetivo.get("testStepExecutionId")
    print(f"\n   → Paso objetivo: #{objetivo.get('testStepSeqNo')} "
          f"(testStepExecutionId={step_id})")

    if solo_leer:
        print("\n[4-5/6] --solo-leer: no se sube nada.")
        print("\n[6/6] Adjuntos actuales del paso:")
        for a in q.listar_adjuntos_paso(ciclo_id, step_id):
            print(f"   · {a.get('name') or a.get('fileName')} ({a.get('id')})")
        return 0

    # 4-5) Credenciales + subida
    imagen = _imagen_de_prueba()
    print(f"\n[4/6] Pidiendo credenciales de subida para '{imagen.name}'…")
    if not imagen.exists():
        print(f"✖ No existe la imagen {imagen}")
        return 1
    try:
        cred = q._credenciales_paso(ciclo_id, step_id, imagen.name)
        print(f"   ✓ endpoint: {cred.get('endpoint_url')}")
        print(f"   ✓ params  : {len(cred.get('params') or {})} campos firmados")
        print("\n[5/6] Subiendo el archivo a S3…")
        code = q._subir_a_s3(cred, imagen)
        print(f"   ✓ HTTP {code} — archivo subido")
    except QMetryError as e:
        print(f"✖ Falló la subida: {e}")
        print("   • Si S3 responde 403: revisa que se envíen TODOS los params y que")
        print("     el binario vaya al final del multipart.")
        print("   • Si dice 'field file not found': el campo del archivo tiene otro")
        print("     nombre; prueba _subir_a_s3(..., campo_archivo='attachment').")
        return 1

    # 6) Verificación (el indexado del adjunto es ASÍNCRONO → reintentos)
    print("\n[6/6] Verificando en QMetry (el registro puede tardar unos segundos)…")
    try:
        hallado = q.esperar_adjunto(ciclo_id, step_id, imagen.name)
        if hallado:
            print(f"   ✓ '{hallado.get('name') or hallado.get('fileName')}' "
                  f"registrado (id={hallado.get('id')}, level={hallado.get('level')})")
        else:
            print("   ⚠ Todavía no aparece. Detalle de lo que ve la API:")
            for modo in (False, True):
                lista = q.listar_adjuntos_paso(ciclo_id, step_id, inline=modo)
                print(f"     · inline={str(modo).lower()}: {len(lista)} adjunto(s)"
                      + (": " + ", ".join(
                          str(a.get('name') or a.get('fileName')) for a in lista)
                         if lista else ""))
            ejec = q.listar_adjuntos_ejecucion(ciclo_id, exec_id)
            print(f"     · a nivel de EJECUCIÓN: {len(ejec)} adjunto(s)")
    except QMetryError as e:
        print(f"   ⚠ No se pudo listar: {e}")

    print("\n✅ Listo. Revisa el paso en QMetry para ver la imagen adjunta.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n👋 Cancelado.")
        sys.exit(130)
