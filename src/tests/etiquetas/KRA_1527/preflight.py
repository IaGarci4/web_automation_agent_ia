"""
Comprobaciones previas de la etiqueta KRA-1527.

## Por qué existe

La primera corrida del CP01 tardó **1 minuto 54** en fallar. Y falló por algo
que se podía saber en el segundo cero: en esa máquina no estaba `procdump` y el
navegador nunca habló con el Hardware Agent. Se hizo un envío real, se imprimió
un recibo y se ensució el ambiente para llegar a una conclusión de entorno.

Este módulo mira el estado de la máquina **antes** de tocar la aplicación:

| Comprobación | Si falta |
|---|---|
| Proceso del agente (`Hermes2Agent.exe`) corriendo | Los casos se **omiten** con el motivo (configurable) |
| `procdump` en `PROCDUMP_PATH` | Se avisa y se corre **solo** la auditoría de tráfico |

La distinción importa y es deliberada:

- **El agente no está corriendo** → problema de entorno. Omitir es lo honesto:
  la etiqueta no puede opinar sobre el fix si el proceso auditado no existe.
- **El agente SÍ corre pero no hubo tráfico** → hallazgo real, y ahí el caso
  **falla**. Ese es el falso negativo del que habla el brief.

Se controla con `KRA1527_SIN_AGENTE`:

    $env:KRA1527_SIN_AGENTE="fallar"    # ejecuta igual y falla al final
    $env:KRA1527_SIN_AGENTE="omitir"    # por defecto
"""

import os
import subprocess
from pathlib import Path

from config import settings
from config.logger import get_logger
from src.helpers import dialogo_impresion as DIALOGO
from src.helpers.memdump_helper import MemDumpHelper

from . import control_negativo as CONTROL

logger = get_logger("KRA-1527.preflight")

_cache = None          # el estado se calcula UNA vez por corrida


def _proceso_corriendo(nombre: str) -> bool:
    """True si el proceso está en la lista de tareas de Windows.

    `tasklist` con filtro devuelve código 0 aunque no encuentre nada, así que
    lo que se comprueba es que el nombre aparezca en la salida."""
    if os.name != "nt":
        return False
    try:
        r = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {nombre}", "/NH"],
            capture_output=True, text=True, timeout=20)
        return nombre.lower() in (r.stdout or "").lower()
    except Exception as e:
        logger.warning("[Preflight] No se pudo consultar tasklist: %s", str(e)[:90])
        return False


def impresoras_de_windows() -> list:
    """Nombres de las impresoras del SPOOLER. Lista vacía si no se pudo leer.

    ## Qué NO es esta lista

    No es el inventario de periféricos del Hardware Agent, y confundir las
    dos cosas costó un caso omitido por error.

    Aquí solo salen las impresoras registradas en la cola de impresión de
    Windows —«MICROSOFT PRINT TO PDF» y compañía—, que son las que usa el
    tipo de impresión WINDOWS PRINTER. La impresora de Money Orders es otra
    cosa: un SATO por USB/IP al que el agente le habla directo en SBPL, sin
    pasar por el spooler. **No aparece aquí y aun así imprime.**

    Se conserva porque es contexto útil en el log —si el spooler está vacío,
    el CP05 y el CP06 no tienen a dónde imprimir—, pero NO sirve para decidir
    si un caso puede correr. Para eso, pregúntale a la pantalla.
    """
    if os.name != "nt":
        return []
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-Printer | Select-Object -ExpandProperty Name"],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace")
        return [l.strip() for l in (r.stdout or "").splitlines() if l.strip()]
    except Exception as e:
        logger.warning("[Preflight] No se pudieron listar las impresoras: %s",
                       str(e)[:80])
        return []


def puertos_en_escucha(pid: int) -> list:
    """Puertos donde ESCUCHA el proceso, leídos de `netstat -ano`.

    Es la pregunta que llevaba dos corridas sin respuesta: *¿a dónde tendría
    que llamar el Front End?* Con el puerto real en la mano, un «SIN
    COMUNICACIÓN» deja de ser un misterio — o el navegador habló con ese puerto
    o no lo intentó, y ambas cosas se pueden comprobar."""
    if os.name != "nt" or not pid:
        return []
    try:
        r = subprocess.run(["netstat", "-ano", "-p", "TCP"],
                           capture_output=True, text=True, timeout=30)
    except Exception as e:
        logger.warning("[Preflight] No se pudo consultar netstat: %s", str(e)[:90])
        return []
    puertos = []
    for linea in (r.stdout or "").splitlines():
        partes = linea.split()
        if len(partes) < 5 or "LISTENING" not in linea.upper():
            continue
        if partes[-1] != str(pid):
            continue
        local = partes[1]                       # 127.0.0.1:41000 · [::]:41000
        puerto = local.rsplit(":", 1)[-1]
        if puerto.isdigit() and puerto not in puertos:
            puertos.append(puerto)
    return sorted(puertos, key=int)


def estado(refrescar: bool = False) -> dict:
    """Estado de la máquina para esta etiqueta (se calcula una sola vez)."""
    global _cache
    if _cache is not None and not refrescar:
        return _cache

    procdump = Path(settings.PROCDUMP_PATH)
    pid = MemDumpHelper.pid_de(settings.HW_AGENT_PROC)
    st = {
        "windows": os.name == "nt",
        "agente": settings.HW_AGENT_PROC,
        "agente_pid": pid,
        "agente_corriendo": bool(pid) or _proceso_corriendo(settings.HW_AGENT_PROC),
        "puertos": puertos_en_escucha(pid) if pid else [],
        "procdump": str(procdump),
        "procdump_ok": procdump.exists() and os.name == "nt",
        "volcado_pedido": settings.KRA1527_DUMP,
        "patron_agente": settings.HW_AGENT_URL_PATTERN,
        "carpeta_dumps": str(settings.DUMP_OUT_DIR),
    }
    # El volcado del proceso ESTABLE ya no necesita procdump: se hace con
    # comsvcs.dll, la misma vía del Administrador de tareas. procdump solo hace
    # falta para el proxy EFÍMERO (su flag -w espera a que el proceso nazca).
    st["volcado_activo"] = st["volcado_pedido"] and st["windows"]
    st["efimero_activo"] = st["volcado_pedido"] and st["procdump_ok"]

    # Escritorio limpio antes de empezar. El diálogo «Guardar impresión como»
    # es modal y sobrevive al proceso de pytest: si una corrida se atoró ahí,
    # la siguiente arranca con la ventana encima y falla en un caso que no
    # tiene la culpa. Cancelarlo aquí evita perseguir un fantasma.
    st["dialogos_huerfanos"] = DIALOGO.cerrar_huerfanos()

    # La compuerta: ¿el detector detecta? Antes esto era un caso más de la
    # suite y su fallo no detenía nada — los demás corrían igual y podían
    # reportar PASS. Aquí sí manda: si el inspector no ve un token plantado,
    # la corrida entera se aborta (lo hace `exigir_entorno` en el conftest).
    st["control_ok"], st["control_motivo"] = CONTROL.verificar()

    # Impresoras que Windows tiene AHORA. Un caso que necesita una concreta
    # —el CP07 necesita la del emulador de Money Orders— puede comprobarlo
    # aquí en un segundo, en vez de navegar 71 s hasta un desplegable vacío.
    st["impresoras"] = impresoras_de_windows()

    _cache = st

    logger.info("─" * 66)
    logger.info("[Preflight] %s corriendo: %s%s", st["agente"],
                "SÍ" if st["agente_corriendo"] else "NO",
                f" (PID {pid})" if pid else "")
    if st["puertos"]:
        logger.info("[Preflight] El agente ESCUCHA en el puerto/los puertos: %s",
                    ", ".join(st["puertos"]))
    elif st["agente_corriendo"]:
        logger.warning("[Preflight] El agente corre pero NO escucha ningún "
                       "puerto TCP: entonces el Front End no le habla por "
                       "HTTP local. Revisa si usa otro mecanismo (protocolo "
                       "propio, named pipe) — eso explicaría un SIN "
                       "COMUNICACIÓN aunque la impresión funcione.")
    logger.info("[Preflight] Volcado del proceso estable: %s",
                "activo (comsvcs.dll)" if st["volcado_activo"] and not st["procdump_ok"]
                else "activo (procdump)" if st["volcado_activo"]
                else "DESACTIVADO")
    logger.info("[Preflight] Volcado del proxy efímero: %s",
                "activo" if st["efimero_activo"] else
                f"NO (procdump no está en {st['procdump']})")
    logger.info("[Preflight] Patrón de agente: %s", st["patron_agente"])
    # Solo las del spooler. La del emulador de Money Orders NO sale aquí y no
    # tiene por qué: el agente le habla directo en SBPL (ver
    # `impresoras_de_windows`). Se muestra como contexto, no como requisito.
    impresoras = st.get("impresoras") or []
    logger.info("[Preflight] Impresoras en la cola de Windows (%d): %s",
                len(impresoras), ", ".join(impresoras) or "(ninguna)")
    if st["control_ok"]:
        logger.info("[Preflight] Control del inspector: OK — %s",
                    st["control_motivo"])
    else:
        logger.error("[Preflight] Control del inspector: FALLÓ — %s",
                     st["control_motivo"])
    logger.info("─" * 66)

    if not st["procdump_ok"] and st["volcado_pedido"]:
        logger.info(
            "[Preflight] Sin procdump el proceso estable se vuelca igual (con "
            "comsvcs.dll, como el Administrador de tareas). Lo que NO se podrá "
            "capturar es el HttpProxy efímero: para eso hace falta procdump "
            "(https://learn.microsoft.com/sysinternals/downloads/procdump) y "
            "apuntar PROCDUMP_PATH en el .env.")
    if not st["agente_corriendo"]:
        logger.warning(
            "[Preflight] El Hardware Agent no está corriendo. Sin él la "
            "aplicación no puede imprimir ni escanear, así que ningún caso de "
            "esta etiqueta prueba nada. Arráncalo (Maxitransfer Hardware "
            "Agent) y repite.")
    return st


def motivo_omision() -> str:
    """Motivo por el que un caso no debería ni intentarse, o "" si puede correr."""
    st = estado()
    if not st["windows"]:
        return ("Esta etiqueta solo corre en Windows: el Hardware Agent y el "
                "volcado de memoria son componentes de escritorio.")
    if not st["agente_corriendo"] and settings.KRA1527_SIN_AGENTE != "fallar":
        return (f"{st['agente']} no está corriendo en esta máquina, así que la "
                f"aplicación no puede invocar al agente y el caso no probaría "
                f"nada. Arranca el Maxitransfer Hardware Agent y repite. "
                f"(Para ejecutarlo igual y ver el fallo real: "
                f"$env:KRA1527_SIN_AGENTE=\"fallar\")")
    return ""
