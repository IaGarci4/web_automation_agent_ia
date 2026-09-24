#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Preflight del puerto CDP del Hermes2Agent (WebView2).

Comprueba que el agente se lanzó con el puerto de depuración abierto (vía
`Ejecutar_Hermes2Agent.bat`) ANTES de correr la automatización enganchada por CDP.

Uso:
    python tools/agent_cdp_check.py
    python tools/agent_cdp_check.py --url http://127.0.0.1:9222

Qué hace:
  · GET {url}/json/version   → versión del navegador + webSocketDebuggerUrl.
  · GET {url}/json           → lista de targets (type/title/url) y marca cuál es
                               la web app (test-hermes / /transfers).
Salida:
  · exit 0 → el puerto responde y hay un target de la web app: listo para CDP.
  · exit 1 → no respondió (agente sin el .bat correcto, o fija los args por
             código → aplicar el Fallback de docs/AGENTE_CDP_WEBVIEW2.md).
  · exit 2 → respondió pero no se ve la web app todavía (¿login/app sin cargar?).
"""

import argparse
import json
import re
import sys
import urllib.request

DEFAULT_URL = "http://127.0.0.1:9222"
RE_APP = re.compile(r"test-hermes\.maxilabs\.net|/transfers", re.I)


def _get(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def main():
    ap = argparse.ArgumentParser(description="Preflight CDP del Hermes2Agent")
    ap.add_argument("--url", default=DEFAULT_URL, help="Base del endpoint CDP")
    args = ap.parse_args()
    base = args.url.rstrip("/")

    print("=" * 64)
    print(f"  Preflight CDP — {base}")
    print("=" * 64)

    try:
        ver = _get(base + "/json/version")
    except Exception as e:
        print(f"  ✗ No respondió {base}/json/version : {e}")
        print("    → El agente NO tiene el puerto CDP abierto.")
        print("    → Lánzalo con Ejecutar_Hermes2Agent.bat (setea")
        print("      WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9222")
        print("      --remote-allow-origins=*). Si aún así no abre, el agente fija")
        print("      los args por código → aplicar el Fallback (KRA-860).")
        return 1

    print("  ✓ /json/version:")
    for k in ("Browser", "webSocketDebuggerUrl", "User-Agent"):
        if k in ver:
            print(f"      {k}: {ver[k]}")

    try:
        targets = _get(base + "/json")
    except Exception as e:
        print(f"  ⚠ /json falló: {e}")
        return 2

    paginas = [t for t in targets if t.get("type") == "page"]
    print(f"\n  Targets tipo 'page': {len(paginas)}")
    app = None
    for t in paginas:
        u = t.get("url", "")
        marca = "  ← WEB APP" if RE_APP.search(u) else ""
        if marca and app is None:
            app = t
        print(f"    · {t.get('title','')[:40]:40}  {u[:70]}{marca}")

    print("-" * 64)
    if app:
        print("  ✓ Encontrada la página de la web app. Listo para engancharse por CDP.")
        print(f"    Corre la suite con:  $env:HERMES_AGENT_CDP=\"1\"; pytest ...")
        return 0
    print("  ⚠ El puerto responde pero NO se ve la web app (test-hermes/transfers).")
    print("    Inicia sesión y entra a la app en el agente, luego reintenta.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
