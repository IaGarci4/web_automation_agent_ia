"""
El diálogo de impresión de Windows — el punto ciego de Playwright.

## El problema

La impresora del entorno es `MICROSOFT PRINT TO PDF`. Cuando el Hardware
Agent manda el trabajo, Windows abre **Guardar impresión como** y se queda
esperando un nombre de archivo. Esa ventana no es del navegador: es del
sistema operativo. Playwright no la ve, no la puede cerrar y ni siquiera sabe
que existe.

El resultado era un caso que decía PASSED con la impresión a medias:
`reimprimir()` devolvía `True` porque había pulsado el botón Print, que es
una cosa muy distinta de haber impreso. El log lo insinuaba —`WS/Printer ×54`
frente a `×9` de un caso sin impresión real— pero nadie lo estaba mirando.

Y hay un daño colateral peor: el diálogo es **modal y persiste**. Una corrida
atorada deja la ventana abierta y la siguiente arranca con el escritorio
bloqueado, así que el fallo se propaga a casos que no tienen nada que ver.

## Qué hace este módulo

Tres cosas, todas con `ctypes` sobre la API de Win32 — sin dependencias:

1. `esperar_dialogo()` — ¿apareció la ventana?
2. `guardar_como()` — escribe la ruta y pulsa Guardar. El PDF que queda en
   disco **es la prueba de que la impresión se completó**, y por eso el caso
   lo adjunta como evidencia en vez de fiarse de un clic.
3. `cerrar_huerfanos()` — cancela cualquier diálogo que haya sobrevivido a
   una corrida anterior. Lo llama el preflight.

## Por qué así y no con pywinauto

`pywinauto` haría esto en cuatro líneas y aguanta mejor los cambios de
Windows, pero añade una dependencia solo-Windows a un repo que hoy instala
con un `pip install -r requirements.txt` y nada más. El diálogo de guardado
es de las piezas más estables de Win32 —clase `#32770`, un `ComboBoxEx32` con
su `Edit` dentro, y el botón Guardar con id 1— así que el coste de hacerlo a
mano es bajo y el de mantenerlo, también.

## Anatomía de la ventana

    #32770  "Guardar impresión como"        ← ventana de diálogo
      └─ ComboBoxEx32
           └─ ComboBox
                └─ Edit                     ← el campo «Nombre:»
      └─ Button (id 1)                      ← «Guardar»
      └─ Button (id 2)                      ← «Cancelar»

En Windows en inglés el título es «Save Print Output As», y en algunas
versiones «Save As» a secas. Se buscan los tres: la máquina de QA está en
español pero la de integración puede no estarlo, y un helper que solo
funciona en un idioma es un helper que fallará el día que menos convenga.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from config.logger import get_logger

logger = get_logger("kra1527.dialogo")

ES_WINDOWS = os.name == "nt"

# Fragmentos de título, en minúsculas. Se compara por CONTENIDO, no por
# igualdad: Windows a veces añade sufijos y las traducciones varían.
TITULOS = (
    "guardar impresión como",
    "guardar impresion como",      # sin tilde, por si acaso
    "save print output as",
    "guardar como",
    "save as",
)

CLASE_DIALOGO = "#32770"

# Mensajes Win32
WM_SETTEXT = 0x000C
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
BM_CLICK = 0x00F5

# Los ids clásicos (IDOK=1, IDCANCEL=2) ya no se usan: en el diálogo moderno
# los botones cuelgan del `#32770` ANIDADO, así que un `GetDlgItem` sobre la
# ventana de arriba devuelve nada y el fallo es silencioso. Se buscan por
# texto, que es donde el usuario los ve. Ver `_boton()`.


if ES_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    _ENUM_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                    wintypes.LPARAM)


def _texto_ventana(hwnd) -> str:
    largo = _user32.GetWindowTextLengthW(hwnd)
    if largo <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(largo + 1)
    _user32.GetWindowTextW(hwnd, buf, largo + 1)
    return buf.value


def _clase_ventana(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _texto_control(hwnd) -> str:
    """Texto de un control hijo. `GetWindowText` no vale para los Edit de
    otro proceso; `WM_GETTEXT` sí, porque lo responde el propio control."""
    largo = _user32.SendMessageW(hwnd, WM_GETTEXTLENGTH, 0, 0)
    if largo <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(largo + 1)
    _user32.SendMessageW(hwnd, WM_GETTEXT, largo + 1, buf)
    return buf.value


def buscar_dialogos() -> list:
    """Handles de los diálogos de guardado visibles. Vacío si no hay ninguno.

    Se recorren TODAS las ventanas de nivel superior en vez de usar
    `FindWindowW` con un título exacto: el título cambia con el idioma y con
    la versión de Windows, y una coincidencia exacta fallaría en silencio —
    que es la peor forma de fallar en un helper cuyo trabajo es detectar.
    """
    if not ES_WINDOWS:
        return []
    encontrados = []

    def _visitar(hwnd, _lparam):
        try:
            if not _user32.IsWindowVisible(hwnd):
                return True
            if _clase_ventana(hwnd) != CLASE_DIALOGO:
                return True
            titulo = _texto_ventana(hwnd).lower()
            if any(t in titulo for t in TITULOS):
                encontrados.append(hwnd)
        except Exception:
            pass
        return True

    try:
        _user32.EnumWindows(_ENUM_PROC(_visitar), 0)
    except Exception as e:
        logger.warning("[Diálogo] No se pudieron enumerar las ventanas: %s",
                       str(e)[:80])
    return encontrados


def esperar_dialogo(timeout_s: int = 20):
    """Espera a que aparezca el diálogo. Devuelve el handle o None."""
    if not ES_WINDOWS:
        return None
    limite = time.time() + timeout_s
    while time.time() < limite:
        dialogos = buscar_dialogos()
        if dialogos:
            hwnd = dialogos[0]
            logger.info("[Diálogo] '%s' detectado.", _texto_ventana(hwnd))
            return hwnd
        time.sleep(0.4)
    return None


def _descendientes(hwnd) -> list:
    """TODOS los descendientes, no solo los hijos directos.

    Esta es la lección del primer intento. `FindWindowEx` solo mira un nivel,
    y el diálogo de guardado moderno (Vista en adelante, y desde luego el de
    Windows 11) no es plano: la barra inferior con «Nombre:», «Tipo:» y los
    botones vive dentro de un **`#32770` anidado**, hijo del diálogo:

        #32770  "Guardar impresión como"
          ├─ DUIViewWndClassName        ← la lista de archivos
          └─ #32770                     ← la barra de abajo
               ├─ ComboBoxEx32
               │    └─ ComboBox
               │         └─ Edit        ← el campo «Nombre:»
               └─ Button "Guardar"

    Buscando solo hijos directos, el campo nunca aparecía y el helper
    concluía «¿cambió la estructura?». No había cambiado: estaba mirando
    demasiado arriba. `EnumChildWindows` recorre el árbol entero.
    """
    encontrados = []

    def _visitar(h, _lparam):
        encontrados.append(h)
        return True

    try:
        _user32.EnumChildWindows(hwnd, _ENUM_PROC(_visitar), 0)
    except Exception:
        pass
    return encontrados


def _arbol(hwnd) -> str:
    """El árbol de controles, para el log cuando algo no se encuentra."""
    filas = []
    for h in _descendientes(hwnd)[:60]:
        clase = _clase_ventana(h)
        texto = _texto_ventana(h)[:28]
        visible = "" if _user32.IsWindowVisible(h) else " (oculto)"
        filas.append(f"{clase}{'=' + repr(texto) if texto else ''}{visible}")
    return " | ".join(filas)


def _campo_nombre(hwnd):
    """El `Edit` del campo «Nombre:», esté al nivel que esté.

    Se prefiere el que cuelga de un `ComboBoxEx32` porque el diálogo tiene
    MÁS de un `Edit`: el cuadro «Buscar en Escritorio» de la esquina también
    lo es, y escribir la ruta ahí no guardaría nada — buscaría.
    """
    en_combo, sueltos = [], []
    for h in _descendientes(hwnd):
        if _clase_ventana(h) != "Edit" or not _user32.IsWindowVisible(h):
            continue
        padre = _user32.GetParent(h)
        abuelo = _user32.GetParent(padre) if padre else None
        if abuelo and _clase_ventana(abuelo) == "ComboBoxEx32":
            en_combo.append(h)
        else:
            sueltos.append(h)
    if en_combo:
        return en_combo[0]
    return sueltos[0] if sueltos else None


def _boton(hwnd, patrones, excluir=()):
    """Botón visible cuyo texto casa con alguno de `patrones`.

    Por texto y no por id: el id 1 (IDOK) vive en el diálogo ANIDADO, así que
    un `GetDlgItem` sobre la ventana de arriba devuelve nada. El texto está
    donde se ve.
    """
    for h in _descendientes(hwnd):
        if _clase_ventana(h) != "Button" or not _user32.IsWindowVisible(h):
            continue
        texto = _texto_ventana(h).lower().replace("&", "")
        if not texto:
            continue
        if any(x in texto for x in excluir):
            continue
        if any(p in texto for p in patrones):
            return h
    return None


def _cerrada(hwnd) -> bool:
    return not _user32.IsWindow(hwnd) or not _user32.IsWindowVisible(hwnd)


def _pulsar_boton(hwnd_dialogo, boton) -> bool:
    """Pulsa un botón: BM_CLICK y, si no, WM_COMMAND a su padre real.

    Los dos caminos existen porque no todos los diálogos responden igual:
    `BM_CLICK` va al botón, y `WM_COMMAND` va al diálogo simulando que el
    botón se pulsó. El padre es el ANIDADO, no la ventana de arriba — mandar
    el WM_COMMAND al sitio equivocado es un no-op silencioso.
    """
    if not boton:
        return False
    _user32.SendMessageW(boton, BM_CLICK, 0, 0)
    time.sleep(0.6)
    if _cerrada(hwnd_dialogo):
        return True
    padre = _user32.GetParent(boton) or hwnd_dialogo
    id_ctrl = _user32.GetDlgCtrlID(boton)
    _user32.SendMessageW(padre, WM_COMMAND, id_ctrl, boton)
    time.sleep(0.6)
    return _cerrada(hwnd_dialogo)


def guardar_como(destino, timeout_s: int = 20) -> tuple:
    """Completa el diálogo guardando en `destino`.

    Devuelve `(ok, ruta, motivo)`. Los TRES estados posibles importan y
    confundirlos es fácil:

    - `(True, ruta, …)`  el diálogo salió y el PDF está en disco.
    - `(True, None, …)`  **no hubo diálogo**. No es un fallo: significa que
      la impresora configurada imprime sin preguntar. Devolver aquí un fallo
      —como hacía la primera versión— reprobaría un caso correcto en cuanto
      alguien cambiara MICROSOFT PRINT TO PDF por una impresora de verdad.
    - `(False, None, …)` el diálogo salió y NO se pudo cerrar. Esto sí es el
      flujo a medias: el trabajo de impresión sigue esperando.

    El archivo resultante es la evidencia de que la impresión terminó: si el
    PDF está en disco, el trabajo salió del agente, pasó por el driver y
    Windows lo escribió. Ningún clic prueba tanto.
    """
    if not ES_WINDOWS:
        return True, None, "no es Windows: no hay diálogo que completar"

    hwnd = esperar_dialogo(timeout_s)
    if not hwnd:
        logger.info("[Diálogo] No apareció ningún diálogo de guardado en %d s "
                    "— la impresora no pide archivo.", timeout_s)
        return True, None, "la impresora imprimió sin pedir archivo"

    destino = Path(destino)
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return False, None, f"no se pudo preparar {destino.parent}: {e}"

    edit = _campo_nombre(hwnd)
    if not edit:
        logger.warning("[Diálogo] Árbol de controles: %s", _arbol(hwnd))
        return False, None, ("el diálogo está abierto pero no encontré su "
                             "campo 'Nombre' (el árbol está en el log)")

    # Ruta ABSOLUTA en el campo: el diálogo abre en Escritorio y un nombre
    # suelto dejaría el PDF ahí, fuera del árbol de evidencia.
    _user32.SendMessageW(edit, WM_SETTEXT, 0, str(destino))
    time.sleep(0.3)

    # Releer: si el diálogo ignoró el WM_SETTEXT, mejor saberlo AQUÍ que
    # deducirlo dentro de 20 s por un PDF que no aparece.
    escrito = _texto_control(edit)
    if escrito.strip().lower() != str(destino).strip().lower():
        logger.warning("[Diálogo] El campo quedó con %r en vez de la ruta "
                       "pedida. Se intenta igual.", escrito[:80])

    boton = _boton(hwnd, ("guardar", "save"),
                   excluir=("cancelar", "cancel"))
    if not boton:
        logger.warning("[Diálogo] Árbol de controles: %s", _arbol(hwnd))
        return False, None, "no encontré el botón Guardar del diálogo"

    if not _pulsar_boton(hwnd, boton):
        logger.warning("[Diálogo] Pulsé '%s' y la ventana sigue abierta. "
                       "Espero por si el driver tarda.", _texto_ventana(boton))

    # El driver tarda en escribir: se espera al ARCHIVO, no a la ventana.
    limite = time.time() + 20
    while time.time() < limite:
        if destino.exists() and destino.stat().st_size > 0:
            logger.info("[Diálogo] Impresión completada → %s (%.0f KB)",
                        destino, destino.stat().st_size / 1024)
            return True, destino, f"PDF guardado ({destino.name})"
        time.sleep(0.5)

    if hay_dialogo_abierto():
        return False, None, ("el diálogo sigue abierto tras pulsar Guardar: "
                             "la impresión quedó a medias")
    return False, None, (f"el diálogo se cerró pero no apareció "
                         f"{destino.name}")


def cerrar_huerfanos() -> int:
    """Cancela los diálogos que hayan sobrevivido a una corrida anterior.

    Se cancela, no se guarda: un diálogo huérfano pertenece a un trabajo de
    impresión de otra ejecución y su PDF no le sirve a nadie. Lo que importa
    es dejar el escritorio libre para que la corrida de ahora no herede un
    fallo que no es suyo.
    """
    if not ES_WINDOWS:
        return 0
    cerrados = 0
    for hwnd in buscar_dialogos():
        titulo = _texto_ventana(hwnd)
        boton = _boton(hwnd, ("cancelar", "cancel"))
        if not _pulsar_boton(hwnd, boton):
            # Sin botón reconocible, la X de la ventana. WM_CLOSE equivale a
            # cerrarla a mano y el diálogo lo trata como cancelar.
            _user32.SendMessageW(hwnd, WM_CLOSE, 0, 0)
            time.sleep(0.6)
        if _cerrada(hwnd):
            cerrados += 1
            logger.warning("[Diálogo] Cerrado un diálogo HUÉRFANO de una "
                           "corrida anterior: '%s'. La impresión de aquella "
                           "corrida quedó incompleta.", titulo)
        else:
            logger.warning("[Diálogo] No se pudo cerrar '%s' — ciérralo a "
                           "mano o la corrida se atorará.", titulo)
    return cerrados


def hay_dialogo_abierto() -> bool:
    """True si ahora mismo hay un diálogo de guardado esperando."""
    return bool(buscar_dialogos())


# ── Envoltorio async ────────────────────────────────────────────────────────
# Todo lo de arriba es Win32 síncrono con esperas activas. Llamarlo tal cual
# desde un test async bloquearía el bucle de eventos durante hasta 40 s con
# Playwright a la escucha al otro lado. Se delega a un hilo.

async def completar_impresion(destino, timeout_s: int = 20) -> tuple:
    """Versión async de `guardar_como`. Devuelve `(ok, ruta, motivo)`."""
    import asyncio
    return await asyncio.to_thread(guardar_como, destino, timeout_s)


async def limpiar_huerfanos_async() -> int:
    """Versión async de `cerrar_huerfanos`."""
    import asyncio
    return await asyncio.to_thread(cerrar_huerfanos)
