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
# App de Hermes en TEST y PROD (host o rutas conocidas).
RE_APP = re.compile(
    r"test-hermes\.maxilabs\.net|hermes\.maxiagentes\.net|maxi(labs|agentes)\.net"
    r"|/transfers|/checks|/reports|/billpay|/online-payments", re.I)
# WebView2 de OTRAS apps (Office/Excel/Teams/Outlook) que roban el puerto 9222 por
# la variable global WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS.
RE_OTRO_WEBVIEW2 = re.compile(
    r"microsoft\.com|office\.com|officeapps|insights\.microsoft|teams|outlook", re.I)


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
        print("  ✓ Encontrada la página de la web app (Hermes). Listo para CDP.")
        print(f"    Corre la suite con:  $env:HERMES_AGENT_CDP=\"1\"; pytest ...")
        return 0

    # ¿El puerto lo tomó OTRO WebView2 (Office/Excel/Teams)? Colisión típica.
    intruso = next((t for t in paginas
                    if RE_OTRO_WEBVIEW2.search(t.get("url", ""))), None)
    if intruso:
        print("  ✗ El puerto 9222 lo tomó OTRO WebView2 (Office/Excel/Teams), NO el")
        print("    Hermes2Agent. La variable WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS es")
        print(f"    GLOBAL y ese proceso se quedó con el puerto:  {intruso.get('url','')[:70]}")
        print("    SOLUCIÓN:")
        print("      1. CIERRA Office/Excel/Teams/Outlook (todo lo que use WebView2).")
        print("      2. Cierra y vuelve a abrir el Hermes2Agent (Ejecutar_Hermes2Agent.bat).")
        print("      3. Vuelve a correr:  python tools\\agent_cdp_check.py")
        print("      · Alternativa: usa OTRO puerto solo para el agente, p.ej. 9333:")
        print("        $env:HERMES_AGENT_CDP=\"http://127.0.0.1:9333\"  (y el .bat con ese puerto)")
        return 2

    print("  ⚠ El puerto responde pero NO se ve la web app de Hermes (test ni prod).")
    print("    Inicia sesión y ENTRA a la app (Transfers) en el agente, luego reintenta.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
