"""
Executor — ejecuta los planes que decide el brain.

Hoy: corre tests completos vía pytest (subprocess) con salida en vivo,
y reporta resultado + carpeta de evidencias.

Mañana (Fase 2b): ejecutar secuencias ad-hoc de métodos POM sobre una
sesión viva (SessionHelper + smart_click) sin necesidad de un test.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def ejecutar_test(archivo: str, test: str = None, overrides: dict = None,
                  cancelar: bool = False, kexpr: str = None, idioma: str = "es",
                  tipo: str = None, ambiente: str = None, marker: str = None,
                  extra_args: list = None) -> dict:
    """
    Corre `pytest <archivo> -v -s` mostrando la salida en vivo.

    Si `overrides` trae datos fijados por el usuario (cliente, monto,
    beneficiario...), se pasan al test vía la variable de entorno
    FLOW_OVERRIDES; el resto de campos los aleatoriza Faker (ver Datos).

    `cancelar`: si la instrucción pidió cancelar, se pasa FLOW_CANCEL=1 y el
    flujo cancela la transacción; por defecto la deja activa.

    `kexpr`: expresión para `pytest -k` (ej. "banorte" o "walmart or aurrera")
    — se usa para correr SOLO ciertos pagadores de un archivo con muchos
    tests generados (test_envio_normal_<pais>.py), sin abrir el navegador
    para los demás.

    Returns:
        dict: {ok, duracion, evidencias, comando}
    """
    # KRA-1526 (IDOR): al invocar cualquier CP por nombre, correr la etiqueta con
    # su marker — los casos comparten una captura de sesión, así que van juntos y
    # producen un reporte. MONO (CP01–07) y MULTI (CP08/09) están SEPARADOS: el
    # multi lleva su propio marker y reporte, y corre en la agencia 0040.
    _al = str(archivo).lower()
    _kra1526_multi = False
    if "kra_1526" in _al:
        _kra1526_multi = ("multi" in _al) or ("cp08" in _al) or ("cp09" in _al)
        archivo = "src/tests/etiquetas/KRA_1526"
        marker = marker or ("idor_multi" if _kra1526_multi else "idor")

    comando = [sys.executable, "-m", "pytest", archivo, "-v", "-s"]
    if marker:
        comando += ["-m", marker]
    if kexpr:
        comando += ["-k", kexpr]
    if extra_args:
        comando += list(extra_args)
    env = os.environ.copy()
    # KRA-1526 multi-agente: activa el gate y la agencia 0040 al invocarlo por NL.
    if _kra1526_multi:
        env.setdefault("KRA1526_MULTI", "1")
        env.setdefault("KRA1526_AGENCY", "0040")
        print("  👥 KRA-1526 MULTI-AGENTE ACTIVADO (KRA1526_MULTI=1, agencia "
              f"{env['KRA1526_AGENCY']})")
    # Herramientas de direcciones (KRA-1527): se auto-activan al ejecutarlas por
    # nombre desde el agente (si no, se saltan por diseño). No afecta a otros tests.
    _arch = str(archivo).lower()
    if "valida_direccion" in _arch:
        env.setdefault("KRA1527_VALIDA_DIR", "1")
        env.setdefault("KRA1527_DIR_ITER", "20")
        print(f"  🏠 Validación de direcciones ACTIVADA "
              f"(KRA1527_VALIDA_DIR=1, {env['KRA1527_DIR_ITER']} vueltas)")
    elif "reproduce_direccion_bank" in _arch:
        env.setdefault("KRA1527_REPRO_DIR", "1")
        print("  🏠 Reproductor del banco de direcciones ACTIVADO (KRA1527_REPRO_DIR=1)")
    elif "auditar_validacion" in _arch:
        env.setdefault("KRA1527_AUDIT", "1")
        env.setdefault("KRA1527_AUDIT_ITER", "5")
        print(f"  🔬 Auditoría DevTools del validador ACTIVADA "
              f"(KRA1527_AUDIT=1, {env['KRA1527_AUDIT_ITER']} muestras)")
    if overrides:
        env["FLOW_OVERRIDES"] = json.dumps(overrides, ensure_ascii=False)
        print(f"  🎯 Datos fijados: {overrides}  (lo demás → Faker)")
    if ambiente:
        env["HERMES_ENV"] = ambiente
        print(f"  🌎 Ambiente: {ambiente.upper()}")
    env["FLOW_CANCEL"] = "1" if cancelar else "0"
    print(f"  🧾 Cancelar transacción: {'SÍ' if cancelar else 'no (queda activa)'}")
    env["FLOW_LANG"] = idioma
    print(f"  🌐 Idioma: {'English (2 clics)' if idioma == 'en' else 'Español (default, sin cambio)'}")
    if tipo is not None:
        env["FLOW_TYPE"] = tipo
        print(f"  💳 Tipo de envío: {tipo}")
    print(f"\n▶ Ejecutando: {' '.join(comando)}\n" + "─" * 60)

    inicio = time.monotonic()
    proceso = subprocess.run(comando, cwd=str(PROJECT_ROOT), env=env)
    duracion = round(time.monotonic() - inicio, 1)

    ok = proceso.returncode == 0

    # Carpeta de evidencias del flujo (si existe)
    evidencias = None
    if test:
        nombre_flujo = test.replace("test_", "")
        carpeta = PROJECT_ROOT / "src" / "tests" / "evidence" / nombre_flujo
        if carpeta.exists():
            evidencias = str(carpeta)

    print("─" * 60)
    estado = "✅ PASÓ" if ok else "❌ FALLÓ"
    print(f"{estado} en {duracion}s")
    if evidencias:
        print(f"📸 Evidencias: {evidencias}")

    return {
        "ok": ok,
        "duracion": duracion,
        "evidencias": evidencias,
        "comando": " ".join(comando),
    }


def ejecutar_iteraciones(archivo: str, test: str = None, veces: int = 2,
                         overrides: dict = None, cancelar: bool = False,
                         montos: list = None, kexpr: str = None, idioma: str = "es",
                         tipo: str = None) -> dict:
    """
    Corre el test `veces` veces seguidas y agrega estadísticas — para cazar
    fallas intermitentes y medir tiempos (lo que QA manual no puede repetir).

    Si `montos` trae varios valores (ej. ['125','345']), cada iteración usa el
    monto que le corresponde — así "dos envíos, uno de 125 y otro de 345" manda
    montos distintos en cada corrida.
    """
    print(f"\n▶ Iterando {veces} veces: {archivo}\n" + "═" * 60)
    corridas = []
    for i in range(veces):
        ov_i = dict(overrides or {})
        if montos and i < len(montos):
            ov_i["monto"] = montos[i]
        etq = f" · monto={ov_i.get('monto')}" if ov_i.get("monto") else ""
        print(f"\n  ── Iteración {i + 1}/{veces}{etq} ──")
        corridas.append(ejecutar_test(archivo, test, ov_i, cancelar, kexpr=kexpr, idioma=idioma, tipo=tipo))

    durs = [c["duracion"] for c in corridas]
    pasaron = sum(1 for c in corridas if c["ok"])
    media = round(sum(durs) / len(durs), 1) if durs else 0
    print("\n" + "═" * 60)
    print(f"  RESUMEN · {pasaron}/{veces} pasaron · tiempo medio {media}s · "
          f"rango {min(durs)}–{max(durs)}s")
    if pasaron < veces:
        print(f"  ⚠ {veces - pasaron} fallo(s) — posible flaky test, revisar diagnóstico.")
    return {"veces": veces, "pasaron": pasaron, "media": media, "corridas": corridas}
