"""
Registry — catálogo de capacidades del agente.

Escanea el proyecto y descubre automáticamente qué sabe hacer el bot:
  - src/tests/test_*.py  → flujos completos ejecutables (CPs)
  - src/pages/*_page.py  → métodos POM disponibles (acciones individuales)

El catálogo se reconstruye en cada arranque: cada CP nuevo que grabes y
generes con json_to_pom amplía las capacidades del agente SIN tocar nada.
Ese es el mecanismo de aprendizaje estructural.
"""

import ast
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
PAGES_DIR    = PROJECT_ROOT / "src" / "pages"
TESTS_DIR    = PROJECT_ROOT / "src" / "tests"

# Pages de infraestructura — no son flujos grabados
PAGES_EXCLUIDAS = {"base_page.py", "pages.py"}


def escanear_pages() -> dict:
    """Descubre los Page Objects y sus métodos públicos (acciones)."""
    pages = {}
    if not PAGES_DIR.exists():
        return pages

    for f in sorted(PAGES_DIR.glob("*_page.py")):
        if f.name in PAGES_EXCLUIDAS:
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            metodos = []
            for m in node.body:
                if (isinstance(m, (ast.AsyncFunctionDef, ast.FunctionDef))
                        and not m.name.startswith("_")):
                    params = [a.arg for a in m.args.args if a.arg != "self"]
                    metodos.append({
                        "nombre": m.name,
                        "params": params,
                        "doc"   : (ast.get_docstring(m) or "").split("\n")[0],
                    })
            if metodos:
                pages[node.name] = {
                    "archivo": str(f.relative_to(PROJECT_ROOT)),
                    "modulo" : f"src.pages.{f.stem}",
                    "metodos": metodos,
                }
    return pages


def escanear_tests() -> dict:
    """Descubre los tests ejecutables (CPs) con sus pasos.

    El barrido es **recursivo**. Antes era `glob("test_*.py")`, que solo mira
    el primer nivel de `src/tests/`, así que todo lo que vive en subcarpetas
    —`etiquetas/KRA_1527/`, `etiquetas/TRN_239/`, `sanity_general/`,
    `deploy/`— quedaba fuera del catálogo. El agente decía no conocer casos
    que llevaban meses en el repo, y la causa no era el agente: era un
    asterisco de más.
    """
    tests = {}
    if not TESTS_DIR.exists():
        return tests

    for f in sorted(TESTS_DIR.rglob("test_*.py")):
        if "__pycache__" in f.parts:
            continue
        try:
            src  = f.read_text(encoding="utf-8")
            tree = ast.parse(src)
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue
        mod_doc = ast.get_docstring(tree) or ""
        # La carpeta padre distingue a qué suite pertenece: hay CP01 en el
        # sanity, en KRA-1527 y en TRN-239, y sin esto el último en leerse
        # pisaba a los anteriores en el catálogo.
        grupo = f.parent.name if f.parent != TESTS_DIR else "general"
        for node in ast.walk(tree):
            if (isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
                    and node.name.startswith("test_")):
                pasos = re.findall(r"await flow\.(\w+)\(", src)
                clave = node.name if node.name not in tests \
                    else f"{grupo}::{node.name}"
                tests[clave] = {
                    "archivo": str(f.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                    "grupo"  : grupo,
                    "doc"    : (ast.get_docstring(node) or mod_doc).strip().split("\n")[0],
                    "pasos"  : pasos,
                    "usa_sesion": "logged_page" in src,
                    # TRN-239 no usa navegador: llama a la API directo. El
                    # agente necesita saberlo para no prometer capturas.
                    "usa_api": "lunex_api" in src or "api_lunex" in src,
                }
    return tests


def construir_catalogo() -> dict:
    """Catálogo completo de capacidades del agente."""
    return {
        "tests": escanear_tests(),
        "pages": escanear_pages(),
    }


def resumen_capacidades(catalogo: dict) -> str:
    """Texto legible con todo lo que el agente sabe hacer."""
    lineas = ["🤖 CAPACIDADES ACTUALES DEL AGENTE", ""]

    tests = catalogo.get("tests", {})
    if tests:
        lineas.append(f"━━ Flujos ejecutables ({len(tests)}) ━━")
        for nombre, info in tests.items():
            sesion = "sesión persistente" if info.get("usa_sesion") else "login explícito"
            lineas.append(f"  • {nombre}  [{sesion}]")
            if info.get("doc"):
                lineas.append(f"      {info['doc']}")
            if info.get("pasos"):
                lineas.append(f"      pasos: {' → '.join(info['pasos'][:8])}")
        lineas.append("")

    pages = catalogo.get("pages", {})
    if pages:
        lineas.append(f"━━ Acciones individuales (POMs: {len(pages)}) ━━")
        for cls, info in pages.items():
            nombres = [m["nombre"] for m in info["metodos"]]
            lineas.append(f"  • {cls}: {', '.join(nombres[:10])}")
        lineas.append("")

    lineas.append("Para enseñarme un flujo nuevo: grabalo con la extensión y")
    lineas.append("genera con: python tools/json_to_pom.py <grabacion.json>")
    return "\n".join(lineas)
