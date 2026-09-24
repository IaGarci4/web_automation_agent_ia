"""
Diagnóstico de autenticación con QMetry.

Prueba una MATRIZ de combinaciones para aislar por qué la API responde
"API key is invalid":

  • Región   : US (qtmcloud) vs Australia (syd-qtmcloud)  ← si el tenant es de
               otra región, la misma key es "inválida" en el servidor equivocado.
  • Headers  : solo `apiKey`  vs  `apiKey` + Basic auth de Jira.
  • Endpoint : /projects (el más simple) y /testcycles/{key}.

Uso:
    python tools/qmetry_auth_check.py

No modifica nada: solo lecturas.
"""

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests                                   # noqa: E402
from config import settings                       # noqa: E402

REGIONES = {
    "US  (qtmcloud)":      "https://qtmcloud.qmetry.com",
    "AU  (syd-qtmcloud)":  "https://syd-qtmcloud.qmetry.com",
}
API = "/rest/api/latest"
TIMEOUT = 40


def _basic() -> str:
    cred = f"{settings.QMETRY_JIRA_EMAIL}:{settings.QMETRY_JIRA_TOKEN}".encode()
    return "Basic " + base64.b64encode(cred).decode()


def _probar(base: str, con_basic: bool, ruta: str, metodo="GET", body=None):
    h = {"apiKey": settings.QMETRY_API_KEY, "Accept": "application/json"}
    if body is not None:
        h["Content-Type"] = "application/json"
    if con_basic:
        h["Authorization"] = _basic()
    try:
        r = requests.request(metodo, f"{base}{API}{ruta}", headers=h,
                             data=json.dumps(body) if body is not None else None,
                             timeout=TIMEOUT)
        detalle = ""
        try:
            j = r.json()
            detalle = (j.get("errorMessage") or
                       (", ".join(j.get("errors", [])) if isinstance(j.get("errors"), list) else "") or
                       f"{len(j.get('data', []))} registro(s)" if isinstance(j, dict) else "")
        except Exception:
            detalle = (r.text or "")[:80]
        return r.status_code, detalle
    except Exception as e:
        return 0, f"error de red: {str(e)[:70]}"


def main() -> int:
    key = settings.QMETRY_API_KEY
    print("─" * 78)
    print("  DIAGNÓSTICO DE AUTENTICACIÓN — QMetry")
    print(f"  API key  : {'definida (' + str(len(key)) + ' caracteres)' if key else 'FALTA'}")
    print(f"  Jira auth: {settings.QMETRY_JIRA_EMAIL or '(sin configurar)'}")
    print("─" * 78)
    if not key:
        print("✖ Falta QMETRY_API_KEY en el .env")
        return 1

    pruebas = [
        ("POST /projects            ", "POST", "/projects",
         {"search": "", "qmetryEnabled": True, "favorite": False,
          "designTestCycleWithQI": False}),
        (f"GET  /testcycles/{settings.QMETRY_TEST_CYCLE}", "GET",
         f"/testcycles/{settings.QMETRY_TEST_CYCLE}", None),
    ]

    ok_alguna = False
    for nombre_region, base in REGIONES.items():
        print(f"\n▶ {nombre_region}")
        for con_basic in (False, True):
            etiqueta = "apiKey + Basic" if con_basic else "solo apiKey   "
            if con_basic and not (settings.QMETRY_JIRA_EMAIL and settings.QMETRY_JIRA_TOKEN):
                print(f"   [{etiqueta}] omitido (falta email/token de Jira)")
                continue
            for desc, metodo, ruta, body in pruebas:
                code, detalle = _probar(base, con_basic, ruta, metodo, body)
                marca = "✓" if 200 <= code < 300 else "✖"
                if 200 <= code < 300:
                    ok_alguna = True
                print(f"   [{etiqueta}] {desc} → {marca} HTTP {code} {detalle}")

    print("\n" + "─" * 78)
    if ok_alguna:
        print("✅ Alguna combinación FUNCIONÓ (marcada con ✓).")
        print("   Ajusta el .env con esa región (QMETRY_BASE_URL) y, si el Basic")
        print("   auth fue necesario, deja QMETRY_JIRA_EMAIL/TOKEN definidos.")
    else:
        print("✖ Ninguna combinación autenticó. Revisa el TIPO de key:")
        print("   • La correcta es la de **Open API**:")
        print("       Jira → app QMetry → Configuration → Open API → Generate")
        print("   • NO sirve la de 'Automation API' (esa es por proyecto y solo")
        print("     vale para importar resultados de automatización).")
        print("   • Si la generaste hace mucho, vuelve a generarla (puede caducar")
        print("     o invalidarse al cambiar de licencia/instancia).")
        print("   • Verifica que la key sea del MISMO sitio Jira (maxims.atlassian.net).")
    return 0 if ok_alguna else 1


if __name__ == "__main__":
    sys.exit(main())
