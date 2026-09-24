"""
¿Por qué Hermes no ve el emulador? — inventario de los periféricos simulados.

## El problema que resuelve

El CP07 falló con «'S SATO WS412-DT_sim' no está entre las impresoras.
Disponibles: (ninguna)» y la sospecha es que los dos emuladores —el del
escáner de cheques y el de la impresora de Money Orders— se pelean por
USB/IP.

Puede ser. Pero «puede ser» ya nos costó tres corridas persiguiendo un
antivirus que no existía cuando el problema era una ACL. Así que esto no
adivina: recoge los hechos y deja que el hecho hable.

## La cadena, y dónde se puede romper

    Emulador  →  usbipd (TCP 3240)  →  Windows (driver + cola de impresión)
                                            │
                                            ▼
                              Hermes2Agent.exe  ── GetPrinters ──►  Hermes 2
                                                                    (combo MO Printer)

Cada eslabón se comprueba por separado, porque el síntoma es el mismo en
todos: un desplegable vacío.

  1. ¿Corren los emuladores?           procesos por nombre
  2. ¿Hay conflicto de puerto?         quién escucha en 3240 y en los vecinos
  3. ¿Está el dispositivo enchufado?   `usbipd list` (Shared / Attached)
  4. ¿Windows ve la impresora?         `Get-Printer` — si no está aquí, el
                                       agente NO puede inventarla
  5. ¿El agente responde?              proceso, puertos y consulta HTTP

## Sobre el conflicto de puerto

`usbipd-win` escucha en **TCP 3240**. Si cada emulador trae su propio
servidor USB/IP, el segundo en arrancar no puede enlazar el puerto y se queda
mudo — sin error visible en la interfaz del emulador, que es justo lo que
hace que parezca «que uno tumba al otro». El punto 2 lo confirma o lo
descarta en un vistazo: si 3240 aparece con UN dueño y los dos emuladores
corren, no hay conflicto de puerto y hay que mirar el punto 3 (un dispositivo
USB/IP solo puede estar *attached* a un cliente a la vez).

    python tools/kra1527_diagnostico_perifericos.py
"""

import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings                                    # noqa: E402

# Puerto estándar de usbipd-win. Se miran también los vecinos por si algún
# emulador usa uno propio y documenta mal cuál.
PUERTOS_USBIP = ("3240", "3241", "3242")

# Fragmentos de nombre de proceso, en minúsculas. La lista es amplia a
# propósito: más vale un falso positivo en un inventario que un emulador que
# no aparece porque se llamaba distinto de lo que suponíamos.
PROCESOS_INTERES = (
    "usbip", "vhci", "sato", "panini", "canon", "scanner", "escaner",
    "emulator", "emulador", "simulator", "sim", "printer", "spool",
    "hermes2agent", "rulesoffice",
)


def _ps(comando: str, timeout: int = 30) -> str:
    """Ejecuta PowerShell y devuelve la salida (vacía si falla)."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", comando],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace")
        return ((r.stdout or "") + (r.stderr or "")).strip()
    except Exception as e:
        return f"(no se pudo ejecutar: {str(e)[:80]})"


def _cmd(args: list, timeout: int = 30) -> str:
    try:
        r = subprocess.run(args, capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace")
        return ((r.stdout or "") + (r.stderr or "")).strip()
    except FileNotFoundError:
        return "(no instalado)"
    except Exception as e:
        return f"(no se pudo ejecutar: {str(e)[:80]})"


def titulo(n: int, texto: str) -> None:
    print()
    print("─" * 74)
    print(f"  {n}. {texto}")
    print("─" * 74)


def procesos() -> dict:
    """Procesos vivos que casen con los fragmentos de interés."""
    titulo(1, "¿Qué emuladores están corriendo?")
    salida = _ps("Get-Process | Select-Object Id,ProcessName,Path | "
                 "Format-Table -AutoSize | Out-String -Width 200")
    encontrados = {}
    for linea in salida.splitlines():
        bajo = linea.lower()
        for frag in PROCESOS_INTERES:
            if frag in bajo:
                encontrados.setdefault(frag, []).append(linea.strip())
                break
    if not encontrados:
        print("  No se encontró ningún proceso con nombre de emulador.")
        print("  Si los emuladores están abiertos, se llaman de otra forma:")
        print("  añade el nombre a PROCESOS_INTERES en este archivo.")
    for frag, lineas in sorted(encontrados.items()):
        print(f"  [{frag}]")
        for l in lineas[:6]:
            print(f"      {l}")
    return encontrados


def puertos() -> None:
    """Quién escucha en los puertos de USB/IP — el punto del conflicto."""
    titulo(2, "¿Hay conflicto de puerto en USB/IP?")
    salida = _cmd(["netstat", "-ano", "-p", "TCP"])
    if salida.startswith("("):
        print(f"  {salida}")
        return
    filas = []
    for linea in salida.splitlines():
        if "LISTENING" not in linea.upper():
            continue
        for p in PUERTOS_USBIP:
            if re.search(rf"[:.]{p}\b", linea):
                filas.append((p, linea.split()))
                break
    if not filas:
        print(f"  NADIE escucha en {', '.join(PUERTOS_USBIP)}.")
        print("  Si los emuladores usan USB/IP, esto ya es el problema: el")
        print("  servidor no está levantado, así que Windows no recibe el")
        print("  dispositivo y el agente no tiene nada que enumerar.")
        return
    # La DIRECCIÓN LOCAL es el dato que convierte el indicio en prueba.
    # Dos procesos en el mismo puerto pueden convivir sin pisarse si escuchan
    # en interfaces distintas (127.0.0.1 vs 0.0.0.0, o IPv4 vs IPv6). Sin
    # esta columna, «dos en el 3240» no decide nada.
    por_puerto = {}
    for p, campos in filas:
        pid = campos[-1]
        local = campos[1] if len(campos) > 1 else "?"
        nombre = _ps(f"(Get-Process -Id {pid} -ErrorAction SilentlyContinue)"
                     f".ProcessName") or "?"
        print(f"  {local:<28}  PID {pid:<7} {nombre}")
        por_puerto.setdefault(p, []).append((local, pid, nombre))

    print()
    for p, escuchas in por_puerto.items():
        if len(escuchas) < 2:
            continue
        direcciones = {l.rsplit(":", 1)[0] for l, _, _ in escuchas}
        print(f"  ⚠ {len(escuchas)} procesos escuchando en el puerto {p}.")
        if len(direcciones) == 1:
            print(f"    Y en la MISMA dirección ({direcciones.pop()}).")
            print("    En Windows esto se puede dar cuando el primero no pone")
            print("    SO_EXCLUSIVEADDRUSE y el segundo abre con SO_REUSEADDR:")
            print("    el enlace no falla, pero las conexiones entrantes se las")
            print("    queda UNO SOLO de los dos —normalmente el último—, y el")
            print("    otro se queda escuchando un puerto que nunca le habla.")
            print("    Eso explica que abrir un emulador «tumbe» al otro sin")
            print("    que ninguno muestre un error.")
        else:
            print(f"    En direcciones distintas: {', '.join(sorted(direcciones))}.")
            print("    Pueden convivir. Si aun así se pisan, el choque no es")
            print("    el enlace sino el DISPOSITIVO — mira el punto 3.")
    if all(len(v) < 2 for v in por_puerto.values()):
        print("  UN solo dueño por puerto: NO hay conflicto de enlace.")
        print("  Si aun así un emulador tumba al otro, el choque no es el")
        print("  puerto sino el DISPOSITIVO — mira el punto 3: un device")
        print("  USB/IP solo puede estar 'Attached' a un cliente a la vez.")


# Hay DOS implementaciones de USB/IP en Windows y no comparten CLI:
#   · usbipd-win (dorssel)  → `usbipd list`, suele estar en el PATH
#   · el cliente clásico    → `usbip.exe`, se instala en Program Files\USBip
#                             y NO se añade al PATH
# Buscar solo la primera daba «no instalado» en una máquina que sí lo tiene.
USBIP_CANDIDATOS = (
    ["usbipd", "list"],
    [r"C:\Program Files\USBip\usbip.exe", "-l"],
    [r"C:\Program Files (x86)\USBip\usbip.exe", "-l"],
)


def usbip() -> None:
    """Estado de los dispositivos compartidos/enchufados."""
    titulo(3, "¿Está el dispositivo compartido y enchufado?")
    for args in USBIP_CANDIDATOS:
        exe = args[0]
        if exe != "usbipd" and not Path(exe).is_file():
            continue
        salida = _cmd(args)
        if salida == "(no instalado)":
            continue
        print(f"  $ {' '.join(args)}")
        print(salida[:2500] or "  (sin salida)")
        bajo = salida.lower()
        print()
        if "attached" not in bajo:
            print("  ⚠ Ningún dispositivo aparece como ATTACHED. 'Shared' sola")
            print("    no basta: mientras no se enchufe, Windows no crea el")
            print("    device y la impresora no existe para nadie.")
        return
    print("  No se encontró ningún cliente USB/IP (`usbipd` ni `usbip.exe`).")
    print("  Si el punto 1 sí muestra un proceso usbip, está instalado en una")
    print("  ruta distinta: añádela a USBIP_CANDIDATOS en este archivo.")


def impresoras() -> None:
    """Lo que WINDOWS ve. Si no está aquí, el agente no la puede inventar."""
    titulo(4, "¿Windows ve la impresora del emulador?")
    esperada = os.getenv("MO_PRINTER", "S SATO WS412-DT_sim")
    salida = _ps("Get-Printer | Select-Object Name,DriverName,PortName,"
                 "PrinterStatus | Format-Table -AutoSize | Out-String -Width 200")
    print(salida[:3000] or "  (sin salida)")
    print()
    if esperada.lower() in salida.lower():
        print(f"  ✓ '{esperada}' ESTÁ instalada en Windows.")
        print("    Entonces el problema NO es el emulador: es que el agente no")
        print("    la reporta o Hermes no la muestra. Sigue por el punto 5.")
    else:
        print(f"  ⚠ '{esperada}' NO aparece en Windows.")
        print("    Esta es la explicación más simple del combo vacío: Hermes")
        print("    muestra lo que el agente enumera, y el agente enumera lo")
        print("    que Windows tiene. Sin impresora en Windows no hay nada")
        print("    que mostrar — el fallo está AGUAS ARRIBA de la automatización.")
    cola = _ps("(Get-Service -Name Spooler).Status")
    print(f"\n  Cola de impresión (Spooler): {cola or '?'}")
    if cola and cola.strip().lower() != "running":
        print("    ⚠ Con el Spooler parado no hay impresoras para nadie.")


def agente() -> None:
    """El último eslabón: el Hardware Agent."""
    titulo(5, "¿El Hardware Agent está sirviendo?")
    proc = settings.HW_AGENT_PROC
    salida = _ps(f"Get-Process -Name '{Path(proc).stem}' -ErrorAction "
                 f"SilentlyContinue | Select-Object Id,ProcessName | "
                 f"Format-Table -AutoSize | Out-String")
    print(f"  Proceso {proc}:")
    print("   ", (salida or "(no está corriendo)").replace("\n", "\n    "))
    pid = ""
    m = re.search(r"^\s*(\d+)\s", salida, re.M)
    if m:
        pid = m.group(1)
    if not pid:
        print("  ⚠ El agente no corre. Nada de lo anterior importa hasta que arranque.")
        return
    net = _cmd(["netstat", "-ano", "-p", "TCP"])
    puertos_agente = sorted({
        re.search(r"[:.](\d+)\s", l).group(1)
        for l in net.splitlines()
        if l.strip().endswith(pid) and "LISTENING" in l.upper()
        and re.search(r"[:.](\d+)\s", l)})
    print(f"  Escucha en: {', '.join(puertos_agente) or '(ningún puerto TCP)'}")
    if not puertos_agente:
        print("    ⚠ El agente corre pero no escucha: el Front End no puede")
        print("      pedirle la lista de impresoras.")


def main() -> int:
    print()
    print("=" * 74)
    print("  KRA-1527 · Diagnóstico de periféricos simulados")
    print("=" * 74)
    if os.name != "nt":
        print("\n  Esto solo tiene sentido en Windows.\n")
        return 1

    procesos()
    puertos()
    usbip()
    impresoras()
    agente()

    print()
    print("─" * 74)
    print("  CÓMO LEERLO")
    print("─" * 74)
    print("  Se sigue la cadena de arriba abajo y se para en el PRIMER punto")
    print("  que falle: los de abajo fallan por arrastre y despistan.")
    print()
    print("   · Punto 4 sin la impresora  →  el problema está en el emulador")
    print("     o en USB/IP, NO en la automatización. Puntos 2 y 3.")
    print("   · Punto 4 CON la impresora y el combo de Hermes vacío  →  el")
    print("     problema está entre el agente y Hermes. Punto 5.")
    print()
    print("  Para la sospecha de que un emulador tumba al otro: corre esto")
    print("  TRES veces —solo el de cheques, solo el de MO, y los dos— y")
    print("  compara los puntos 2, 3 y 4. La diferencia entre las tres")
    print("  salidas es la respuesta; una sola foto no la tiene.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
