"""
Lanzador de MÚLTIPLES instancias AISLADAS del Hermes2Agent (WebView2) para el
paralelo real en equipos CON el HA — respetando el control de seguridad
'kerberoswebviewprotection' (que exige el WebView nativo; no se puede falsificar
desde un navegador normal, ver tools/probe_loginaction.py).

IDEA (la que pediste)
---------------------
Cada instancia del HA se abre con:
  · su PROPIO perfil/caché  → WEBVIEW2_USER_DATA_FOLDER distinto (sesiones aisladas)
  · su PROPIO puerto CDP     → --remote-debugging-port distinto (9222, 9223, ...)
Así corren varias sesiones a la vez y cada worker de pytest se engancha a la suya.
No se usa Chrome en ningún momento: el handoff se queda dentro del WebView.

QUÉ HACE
--------
  1. (opcional) mata instancias previas de Hermes2Agent.exe  (--kill)
  2. lanza N instancias, cada una con su perfil y su puerto
  3. espera y verifica que cada puerto CDP responda (y que sean N procesos vivos)
  4. reporta el mapeo worker→puerto para el paralelo

Esto VALIDA lo único que no controlamos por código: que el exe del HA permita
varias instancias a la vez y respete el perfil aislado. Si el HA hace
'single-instance lock' (solo deja una), lo veremos aquí y hay que pedir al equipo
dev un cliente/flow de Keycloak sin el protector para QA (alternativa limpia).

USO
---
    # Lanzar 3 instancias aisladas (mata las previas primero):
    python tools/lanzar_agentes.py --n 3 --kill

    # Solo verificar puertos ya abiertos:
    python tools/lanzar_agentes.py --n 3 --check

    # Cerrar todo:
    python tools/lanzar_agentes.py --kill-only

Tras verlas arriba, en CADA ventana del HA inicia sesión con un usuario DISTINTO
(para evitar multisesión de un mismo usuario). Luego corremos el sanity en
paralelo mapeando worker→puerto (te lo cableo en conftest cuando confirmes que
las N instancias quedaron vivas).
"""
import argparse
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_EXE = r"C:\MaxiInstall\Maxi\HERMES2_agent.Installer\Hermes2Agent.exe"
DEFAULT_DATA_ROOT = ROOT / "session_state" / "ha_profiles"
PROC_NAME = "Hermes2Agent.exe"


def _cdp_ok(port: int, timeout: float = 2.0):
    """Devuelve el JSON de /json/version si el puerto CDP responde, o None."""
    try:
        url = f"http://127.0.0.1:{port}/json/version"
        with urllib.request.urlopen(url, timeout=timeout) as r:
            if r.status == 200:
                import json
                return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None
    return None


def _contar_procesos() -> int:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {PROC_NAME}", "/NH"],
            capture_output=True, text=True)
        return sum(1 for ln in out.stdout.splitlines() if PROC_NAME.lower() in ln.lower())
    except Exception:
        return -1


def matar_agentes():
    print(f"[kill] Cerrando instancias de {PROC_NAME}...")
    subprocess.run(["taskkill", "/F", "/IM", PROC_NAME, "/T"],
                   capture_output=True, text=True)
    time.sleep(2)
    print(f"[kill] Procesos {PROC_NAME} restantes: {_contar_procesos()}")


def lanzar_una(exe: str, port: int, data_folder: Path):
    data_folder.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
        f"--remote-debugging-port={port} --remote-allow-origins=*")
    env["WEBVIEW2_USER_DATA_FOLDER"] = str(data_folder)
    # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP → ventana propia, no atada a python
    flags = 0x00000008 | 0x00000200
    subprocess.Popen([exe], env=env, creationflags=flags, close_fds=True)
    print(f"  · instancia lanzada  puerto={port}  perfil={data_folder.name}")


def verificar(n: int, base_port: int, espera_s: int = 40):
    print(f"\n[check] Esperando a que {n} puertos CDP respondan (máx {espera_s}s)...")
    puertos = [base_port + i for i in range(n)]
    vivos = {}
    t0 = time.time()
    while time.time() - t0 < espera_s:
        for p in puertos:
            if p not in vivos:
                info = _cdp_ok(p)
                if info:
                    vivos[p] = info.get("Browser", "?")
        if len(vivos) == n:
            break
        time.sleep(2)

    print("\n" + "=" * 70)
    print("RESULTADO")
    print("=" * 70)
    procs = _contar_procesos()
    print(f"  Procesos {PROC_NAME} vivos : {procs}")
    for p in puertos:
        if p in vivos:
            print(f"  ✅ puerto {p}  →  {vivos[p]}")
        else:
            print(f"  ⛔ puerto {p}  →  sin respuesta")
    ok = len(vivos)
    if ok == n and procs >= n:
        print(f"\n  ✅ {n} instancias AISLADAS vivas. El HA SÍ permite multi-instancia.")
        print("     Mapeo para el paralelo:")
        for i, p in enumerate(puertos):
            print(f"       gw{i}  →  http://127.0.0.1:{p}")
        print("\n     SIGUIENTE: inicia sesión en cada ventana del HA con un usuario")
        print("     DISTINTO y avísame para cablear conftest (worker→puerto) y correr:")
        print("       python -m pytest -m sanity_general -n {} --html=report.html --self-contained-html".format(n))
    elif ok <= 1:
        print("\n  ⚠ Solo respondió 1 (o ninguno). Probable 'single-instance lock' del HA:")
        print("     el exe no deja abrir varias copias a la vez. En ese caso la vía")
        print("     limpia es pedir al equipo dev un cliente/flow de Keycloak SIN el")
        print("     'kerberoswebviewprotection' para el usuario/IP de QA (o un build QA).")
    else:
        print(f"\n  ⚠ Respondieron {ok}/{n}. Parcial — puede ser timing o límite del HA.")
        print("     Reintenta con más espera (--espera 60) o menos instancias (--n 2).")


def main():
    ap = argparse.ArgumentParser(description="Lanza N instancias aisladas del Hermes2Agent.")
    ap.add_argument("--n", type=int, default=3, help="Número de instancias (default 3).")
    ap.add_argument("--base-port", type=int, default=9222, help="Puerto CDP base (default 9222).")
    ap.add_argument("--exe", default=DEFAULT_EXE, help="Ruta al Hermes2Agent.exe.")
    ap.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT),
                    help="Carpeta raíz de los perfiles aislados.")
    ap.add_argument("--espera", type=int, default=40, help="Segundos a esperar los puertos.")
    ap.add_argument("--kill", action="store_true", help="Mata instancias previas antes de lanzar.")
    ap.add_argument("--kill-only", action="store_true", help="Solo cierra instancias y sale.")
    ap.add_argument("--check", action="store_true", help="Solo verifica puertos (no lanza).")
    args = ap.parse_args()

    if args.kill_only:
        matar_agentes()
        return

    if args.check:
        verificar(args.n, args.base_port, args.espera)
        return

    if not Path(args.exe).exists():
        print(f"[!] No se encontró el exe del HA en: {args.exe}")
        print("    Pásalo con --exe \"C:\\ruta\\a\\Hermes2Agent.exe\".")
        return

    if args.kill:
        matar_agentes()

    data_root = Path(args.data_root)
    print(f"[lanzar] {args.n} instancias · exe={args.exe}")
    print(f"[lanzar] perfiles aislados bajo: {data_root}")
    for i in range(args.n):
        port = args.base_port + i
        lanzar_una(args.exe, port, data_root / f"gw{i}")
        time.sleep(3)   # darle aire al arranque para evitar carreras de mutex

    verificar(args.n, args.base_port, args.espera)


if __name__ == "__main__":
    main()
