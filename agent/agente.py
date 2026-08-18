"""
AGENTE QA HERMES2 — interfaz de lenguaje natural.

Uso:
    python agent/agente.py                       → chat interactivo
    python agent/agente.py "corre el agent balance"  → comando único

El agente:
  1. Descubre sus capacidades escaneando el proyecto (registry)
  2. Interpreta tu instrucción (brain — offline hoy, Claude API mañana)
  3. Ejecuta el plan (executor) y reporta resultado + evidencias
  4. APRENDE: las instrucciones que funcionan quedan en memoria.json
     y la próxima vez el match es directo

Cada CP nuevo que grabes y generes con json_to_pom amplía lo que el
agente sabe hacer, sin tocar este código.
"""

import sys
from pathlib import Path

# Permitir ejecutar desde la raíz del proyecto
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.registry import construir_catalogo, resumen_capacidades       # noqa: E402
from agent.brain import interpretar, recordar_exito, detectar_idioma, detectar_tipo_envio  # noqa: E402
from agent.executor import ejecutar_test, ejecutar_iteraciones           # noqa: E402

BANNER = """
╔══════════════════════════════════════════════════════╗
║   🤖 AGENTE QA HERMES2 — lenguaje natural             ║
║   'capacidades' → qué sé hacer   |   'salir' → fin    ║
╚══════════════════════════════════════════════════════╝"""


def procesar(instruccion: str, catalogo: dict) -> None:
    """Una instrucción → plan → acción → aprendizaje."""
    plan = interpretar(instruccion, catalogo)

    if plan["tipo"] == "ejecutar_test":
        veces = plan.get("veces", 1)
        overrides = plan.get("overrides") or {}
        montos = plan.get("montos") or []
        cancelar = plan.get("cancelar", False)
        kexpr = plan.get("kexpr")
        ambiente = plan.get("ambiente")
        marker = plan.get("marker")
        idioma = detectar_idioma(instruccion)
        # Para etiquetas el tipo está definido dentro del test; no inferirlo
        # de la instrucción (podría mostrar "cash" aunque el test sea deposit).
        es_etiqueta = "etiquetas" in plan.get("archivo", "")
        tipo = None if es_etiqueta else detectar_tipo_envio(instruccion)
        suf = f" ×{veces}" if veces > 1 else ""
        print(f"\n🧠 Entendido: ejecutar {plan['test']}{suf}  ({plan['razon']})")
        if es_etiqueta:
            print(f"  💳 Tipo de envío: definido en el test")
        else:
            print(f"  💳 Tipo de envío: {tipo}")
        if veces > 1:
            res = ejecutar_iteraciones(plan["archivo"], plan["test"], veces, overrides, cancelar, montos, kexpr=kexpr, idioma=idioma, tipo=tipo)
            if res["pasaron"] > 0:
                recordar_exito(instruccion, plan["test"])
        else:
            resultado = ejecutar_test(plan["archivo"], plan["test"], overrides, cancelar,
                                      kexpr=kexpr, idioma=idioma, tipo=tipo,
                                      ambiente=ambiente, marker=marker)
            if resultado["ok"]:
                recordar_exito(instruccion, plan["test"])
                print("🧠 Aprendido: la próxima vez esta instrucción será directa.")
    elif plan["tipo"] in ("respuesta", "sugerencia"):
        print(f"\n{plan['mensaje']}")
    else:
        print(f"\n(plan no reconocido: {plan})")


def modo_chat(catalogo: dict) -> None:
    print(BANNER)
    tests = len(catalogo.get("tests", {}))
    pages = len(catalogo.get("pages", {}))
    print(f"  Catálogo cargado: {tests} flujo(s), {pages} POM(s)\n")

    while True:
        try:
            instruccion = input("tú> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 Hasta luego.")
            break
        if not instruccion:
            continue
        if instruccion.lower() in ("salir", "exit", "quit", "q"):
            print("👋 Hasta luego.")
            break
        procesar(instruccion, catalogo)
        print()


def main() -> None:
    catalogo = construir_catalogo()

    if len(sys.argv) > 1:
        # Comando único: python agent/agente.py "instrucción"
        instruccion = " ".join(sys.argv[1:])
        procesar(instruccion, catalogo)
    else:
        # Chat interactivo
        modo_chat(catalogo)


if __name__ == "__main__":
    main()
