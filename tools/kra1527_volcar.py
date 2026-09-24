"""
Volcado + inspección del Hardware Agent, a mano y sin pytest.

Es el procedimiento manual del ticket —Administrador de tareas → *Crear archivo
de volcado* → `findstr /i /c:"eyJ"`— en un solo comando, y con la diferencia
que importa: el inspector **decodifica** el JWT y valida sus claims, así que
distingue un token de autenticación real de cualquier cadena que empiece por
`eyJ`.

Sirve para tres cosas:

1. **Comprobar que el volcado funciona en esta máquina** sin gastar un flujo
   completo de dos minutos.
2. **Analizar un `.DMP` que ya tengas**, por ejemplo el que sacaste con el
   Administrador de tareas.
3. **Ver dónde escucha el agente** — el dato que decide si un «SIN
   COMUNICACIÓN» es un problema del patrón o de que la app no llamó.

```powershell
# Volcar el agente ahora e inspeccionarlo
python tools/kra1527_volcar.py

# Analizar un volcado existente (el que hiciste a mano)
python tools/kra1527_volcar.py --archivo "$env:TEMP\Hermes2Agent.DMP"

# Solo mirar el estado: PID, puertos, si hay procdump
python tools/kra1527_volcar.py --estado
```

No borra nada: los `.DMP` que analices siguen donde estaban. Para limpiarlos,
`python tools/kra1527_reset.py --solo-dmp`.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings                                    # noqa: E402
from src.helpers.memdump_helper import (MemDumpHelper,         # noqa: E402
                                        RESPALDO_DIR, purgar_respaldo)


def _estado() -> None:
    from src.tests.etiquetas.KRA_1527 import preflight
    st = preflight.estado(refrescar=True)
    print()
    print(f"  Agente        : {st['agente']}")
    print(f"  Corriendo     : {'SÍ' if st['agente_corriendo'] else 'NO'}"
          + (f" (PID {st['agente_pid']})" if st.get("agente_pid") else ""))
    print(f"  Puertos       : {', '.join(st['puertos']) or '(ninguno en escucha)'}")
    print(f"  procdump      : {st['procdump'] if st['procdump_ok'] else 'NO instalado'}")
    print(f"  Volcado       : {'sí' if st['volcado_activo'] else 'no'}"
          + ("  (por comsvcs.dll)" if st["volcado_activo"] and not st["procdump_ok"]
             else ""))
    print(f"  Proxy efímero : {'sí' if st['efimero_activo'] else 'no (necesita procdump)'}")
    print(f"  Carpeta .DMP  : {st['carpeta_dumps']}")
    print()
    if st["puertos"]:
        print("  Si la auditoría dice SIN COMUNICACIÓN, comprueba que")
        print(f"  HW_AGENT_URL_PATTERN cubra alguno de estos puertos: "
              f"{', '.join(st['puertos'])}")
    elif st["agente_corriendo"]:
        print("  El agente corre pero no escucha ningún puerto TCP: el Front")
        print("  End no le habla por HTTP local, así que la auditoría de")
        print("  tráfico no puede verlo. El volcado de memoria sigue siendo")
        print("  válido — es lo que pide el criterio de aceptación.")
    print()


def _respaldo(purgar: bool = False) -> int:
    """Lista —o purga— los volcados guardados para revisión manual."""
    archivos = sorted(set(RESPALDO_DIR.glob("*.dmp")) |
                      set(RESPALDO_DIR.glob("*.DMP"))) \
        if RESPALDO_DIR.exists() else []
    if not archivos:
        print(f"\n  No hay volcados en el respaldo.\n  {RESPALDO_DIR}\n")
        return 0
    peso = sum(f.stat().st_size for f in archivos) / 1e9
    print(f"\n  Respaldo: {RESPALDO_DIR}")
    print(f"  {len(archivos)} volcado(s) · {peso:.2f} GB\n")
    for f in archivos:
        print(f"    {f.stat().st_size / 1e6:>8.1f} MB  {f.name}")
    if not purgar:
        print("\n  Para analizar uno:")
        print(f"    python tools/kra1527_volcar.py --archivo \"{archivos[0]}\"")
        print("\n  Para borrarlos todos (al cerrar el ciclo de los 9 casos):")
        print("    python tools/kra1527_volcar.py --purgar\n")
        return 0
    # Purgar es destructivo y son la evidencia del ticket: se confirma.
    print("  Estos archivos son la EVIDENCIA del ticket. Bórralos solo cuando")
    print("  el reporte esté cerrado y los resultados documentados.")
    if input("\n  ¿Borrar? escribe 'si' para confirmar: ").strip().lower() != "si":
        print("\n  Cancelado. No se borró nada.\n")
        return 0
    borrados, gb = purgar_respaldo()
    print(f"\n  {borrados} volcado(s) borrado(s) · {gb} GB liberados\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Volcado e inspección del Hardware Agent (KRA-1527)")
    ap.add_argument("--archivo", help="analizar un .DMP existente")
    ap.add_argument("--proceso", default=settings.HW_AGENT_PROC,
                    help=f"proceso a volcar (defecto: {settings.HW_AGENT_PROC})")
    ap.add_argument("--estado", action="store_true",
                    help="solo mostrar el estado de la máquina")
    ap.add_argument("--respaldo", action="store_true",
                    help="listar los .DMP guardados para revisión manual")
    ap.add_argument("--purgar", action="store_true",
                    help="borrar los .DMP del respaldo (al cerrar el ciclo)")
    args = ap.parse_args()

    print("KRA-1527 · volcado e inspección")
    print("─" * 62)

    if args.estado:
        _estado()
        return 0

    if args.respaldo or args.purgar:
        return _respaldo(purgar=args.purgar)

    # `conservar_dmp=True`: esta herramienta no borra nada. Quien decide qué se
    # borra es `kra1527_reset.py`, explícitamente.
    dumps = MemDumpHelper("manual", conservar_dmp=True)

    if args.archivo:
        dmp = Path(args.archivo)
        if not dmp.exists():
            print(f"✗ No existe: {dmp}")
            return 2
        print(f"  Analizando {dmp.name} ({dmp.stat().st_size / 1e6:.1f} MB)…")
        res = dumps.inspeccionar(dmp, f"{args.proceso} (volcado manual)")
    else:
        _estado()
        print(f"  Volcando {args.proceso}…")
        res = dumps.volcar_ahora(args.proceso)
        if not res:
            print("✗ No se pudo volcar. El motivo está en el log de arriba.")
            print("  Prueba la consola como Administrador: el volcado de otro")
            print("  proceso necesita el privilegio SeDebugPrivilege.")
            return 3

    print("─" * 62)
    print(f"  Veredicto : {res['veredicto']}")
    print(f"  Reporte   : {res.get('reporte') or '(no se generó)'}")
    print()
    if res["veredicto"] == "FAIL":
        print("  ⚠️  APARECIÓ UN JWT DE AUTENTICACIÓN EN CLARO.")
        print("      Eso es el hallazgo 5.2.1 del pentest sin corregir.")
        print("      El reporte tiene los claims; el token NO se escribe.")
        return 1
    if res["veredicto"] == "WARN":
        print("  Hay cadenas 'eyJ…' que NO decodifican: probablemente datos")
        print("  cifrados, que es justo lo que el fix promete. Revisa el")
        print("  reporte para confirmarlo.")
        return 0
    # ERROR / PENDIENTE / NO_CAPTURADO no son un aprobado: no se analizó nada.
    # Antes este print caía por defecto y afirmaba «sin token en claro» sobre un
    # volcado ilegible — la conclusión honesta es «no se sabe».
    if res["veredicto"] != "PASS":
        print(f"  El volcado NO se analizó (veredicto {res['veredicto']}), así")
        print("  que esto NO afirma ni niega la presencia de un token.")
        print("  El motivo y el remedio están en el log de arriba.")
        return 3
    print("  Sin token de autenticación en claro en este volcado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
