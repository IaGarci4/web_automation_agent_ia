"""
Volcado de memoria de los procesos del Hardware Agent — KRA-1527.

Playwright no puede volcar memoria: es una operación del sistema operativo. Este
helper encapsula esa parte para que los tests queden limpios.

Dos procesos, dos estrategias:

  • `Hermes2Agent.exe` — corre permanentemente → se vuelca DESPUÉS de la acción.
  • `Maxi.RulesOffice.Security.HttpProxy.exe` — **efímero**: nace con el request
    y muere al terminar. No se le persigue con un bucle: `procdump -w` se ARMA
    ANTES de disparar la acción y lo atrapa en cuanto aparece. Eso elimina la
    carrera y hace la prueba determinista.

Si `procdump` no está instalado, NADA falla: se registra 'no disponible' y el
caso se apoya en la auditoría de tráfico (`ha_audit`). Un volcado ausente no es
un aprobado ni un fallo — es una comprobación que no se pudo hacer, y así se
reporta.

Los .DMP pesan cientos de MB y contienen datos sensibles: se borran tras
inspeccionarlos. Nunca deben acabar en el repo ni subirse como evidencia; lo
que se comparte es el reporte HTML.
"""

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from config import settings
from config.logger import get_logger

logger = get_logger("kra1527.dump")

INSPECTOR = Path(settings.PROJECT_ROOT) / "tools" / "dump_token_inspector.py"

# Carpeta de evidencia del ticket (junto al reporte y las capturas, en
# `reports/evidence/KRA-1527/`). El volcado se ESCRIBE aquí directamente: no
# pasa por %TEMP% ni se mueve después.
#
# Por qué se conserva: el volcado ES la evidencia del ticket. Borrarlo en
# cuanto se analiza obliga a repetir el caso completo —envío real incluido—
# cada vez que alguien quiere revisar un detalle a mano. Se conservan hasta que
# los nueve casos hayan pasado y el reporte esté cerrado; entonces se purgan de
# una vez:
#
#     python tools/kra1527_volcar.py --purgar
RESPALDO_DIR = Path(getattr(settings, "KRA1527_RESPALDO_DIR",
                            Path(settings.PROJECT_ROOT) / "reports" /
                            "evidence" / "KRA-1527" / "VolcadoMemoriaDMP"))


_RE_TOTAL = re.compile(
    r"TOTAL:\s*FAIL=(\d+)\s+WARN=(\d+)\s+PASS=(\d+)(?:\s+ERROR=(\d+))?", re.I)


def _veredicto_del_inspector(codigo: int, salida: str) -> str:
    """Traduce la salida del inspector a un veredicto, SIN adivinar.

    Esto costó un falso positivo de los caros: el inspector no pudo leer un
    volcado (lo tenía retenido el antivirus), su resumen explotó, Python salió
    con código 1 — y la lógica de aquí leía «1 = hay FAIL». Resultado: se
    reportó un token en claro que nadie había visto nunca.

    Dos reglas para que no vuelva a pasar:

    1. Se hace caso al RECUENTO que imprime el inspector (`TOTAL: FAIL=n …`),
       no al código de salida. El recuento no miente: si dice `FAIL=0`, no hay
       hallazgo, pase lo que pase con el proceso.
    2. Ante la duda, el veredicto es **ERROR**, nunca FAIL. Un análisis que no
       se pudo hacer es una comprobación pendiente; decir que hay una fuga
       cuando no se sabe es peor que no decir nada."""
    m = _RE_TOTAL.search(salida or "")
    if m:
        fail, warn, ok, err = (int(m.group(i) or 0) for i in (1, 2, 3, 4))
        if fail:
            return "FAIL"
        if err and not (ok or warn):
            return "ERROR"
        if warn:
            return "WARN"
        if ok:
            return "PASS"
        return "ERROR"
    # Sin recuento (el inspector ni llegó a imprimirlo): se decide por código,
    # y el 1 SIN recuento es un fallo del inspector, no un hallazgo.
    if codigo == 0:
        return "PASS"
    if codigo == 2:
        return "NO_CAPTURADO"
    return "ERROR"


# Cómo se LEE la salida del inspector.
#
# El inspector fuerza UTF-8 en su stdout —tuvo que hacerlo: la consola de
# Windows es cp1252 y un solo carácter fuera de ese juego reventaba el análisis
# entero con UnicodeEncodeError—. Pero `subprocess.run(text=True)` sin
# `encoding` descodifica con el locale del padre, que aquí también es cp1252.
# UTF-8 escrito y cp1252 leído es exactamente el mojibake que salía en el log:
#
#     sesiÃ³n · Ã—1769 · â€¦rect%3Dtrue
#
# Y no se quedaba en la consola: ese texto es el que va al reporte HTML y a las
# notas del caso. `errors="replace"` para que un byte raro nunca vuelva a tirar
# una inspección de 700 MB.
_TEXTO_INSPECTOR = {"encoding": "utf-8", "errors": "replace"}

_RE_ACTIVIDAD = re.compile(r"ACTIVIDAD_HA=(\d+)(?:\s*::\s*(.+))?")


def _actividad_del_inspector(salida: str) -> list:
    """Marcadores de trabajo del agente que el inspector halló en el volcado.

    Es lo que permite afirmar en el reporte que **sí hubo comunicación** con el
    Hardware Agent. La auditoría HTTP observa el navegador; si el canal con el
    agente local no pasa por ahí, ve cero llamadas aunque el agente haya
    impreso. La memoria del agente no tiene esa ceguera: si procesó la
    petición, sus endpoints están en el volcado."""
    m = _RE_ACTIVIDAD.search(salida or "")
    if not m or not m.group(2):
        return []
    return [t.strip() for t in m.group(2).split(";") if t.strip()]


_NOTA = """# VolcadoMemoriaDMP — evidencia de KRA-1527

Los `.DMP` de esta carpeta son la evidencia del hallazgo 5.2.1 del pentest: la
memoria del Hardware Agent, capturada justo después de la acción que lo
ejercita, para comprobar que el JWT ya **no** está en claro.

## El nombre dice lo que es

```
CP01-EnvioMoneyTransfer_Hermes2Agent_20260902_200448.dmp
└─ caso ──────────────┘ └─ proceso ─┘ └─ fecha y hora ─┘
```

Dos corridas nunca chocan. El volcado manual del Administrador de tareas, en
cambio, siempre usa el mismo nombre, y cuando ya existe uno Windows crea
`Hermes2Agent (2).DMP` — ese «(2)» no dice nada de qué contiene ni de cuándo se
tomó, y son archivos **distintos**: un volcado es una foto de la memoria en ese
instante, y `Hermes2Agent.exe` es un proceso de larga vida.

## No aparecen en git — es a propósito

`reports/` está en `.gitignore` y los `.DMP` también (`*.dmp`, `*.DMP`): son
cientos de MB y pueden contener un token vivo. Están en disco; ábrelos desde el
Explorador, no desde el panel de cambios.

## Revisar uno

```powershell
python tools/kra1527_volcar.py --archivo "<ruta del .dmp>"   # inspector
findstr /i /c:"eyJ" "<archivo>.dmp"                          # a la antigua
findstr /i /c:"Authorizer" "<archivo>.dmp"
```

## Purgar, al cerrar el ciclo

```powershell
python tools/kra1527_volcar.py --respaldo    # inventario y peso
python tools/kra1527_volcar.py --purgar      # borrar (pide confirmación)
```

No se purga solo: perder la evidencia por una limpieza automática cuesta más
que el disco.

## Seguridad

Un `.DMP` con un JWT vivo dentro es material sensible. **No se sube a QMetry**
—lo que se adjunta es el reporte HTML, que muestra los *claims* y la longitud,
nunca el token— y si dio `FAIL`, trátalo como una credencial.
"""


def _asegurar_nota(destino_dir: Path) -> None:
    """Deja el README dentro de la carpeta de evidencia.

    Vive aquí, y no en el repo, porque `reports/` está ignorado por git:
    versionarlo obligaría a desbloquear toda la carpeta de salida con
    negaciones en cascada, y eso arrastraría los HTML y las capturas de cada
    corrida. Escribirlo al crear la carpeta deja la explicación donde alguien
    la va a leer —al lado de los archivos— sin ensuciar el control de versiones.
    """
    try:
        nota = destino_dir / "README.md"
        if not nota.exists():
            nota.write_text(_NOTA, encoding="utf-8")
    except Exception:
        pass        # la nota es una cortesía; nunca debe romper una corrida


def _usuario_actual() -> str:
    """`DOMINIO\\usuario` de la cuenta que corre la prueba."""
    usuario = os.environ.get("USERNAME") or ""
    dominio = os.environ.get("USERDOMAIN") or ""
    return f"{dominio}\\{usuario}" if dominio and usuario else usuario


def conceder_lectura(ruta, es_carpeta=False) -> bool:
    """Concede al usuario actual permiso de LECTURA sobre `ruta`.

    ## El diagnóstico que nos costó tres corridas

    Los volcados salían con esta ACL y nada más:

        NT AUTHORITY\\SYSTEM:(OI)(F)
        BUILTIN\\Administradores:(OI)(F)

    El usuario que corre las pruebas NO figura. No era el antivirus (cero
    detecciones), no era la escritura a medias (tamaño estable 300 s): era un
    permiso denegado, sin más. `ERROR_ACCESS_DENIED (5)`, que Python muestra
    como el mismo `[Errno 13]` que una violación de compartición — y ese
    parecido nos tuvo mirando al sitio equivocado. La pista definitiva fue que
    el `findstr` a mano SÍ leía el archivo: esa consola estaba elevada.

    El volcado hereda esa ACL de la carpeta, y la carpeta la heredó de la raíz
    del repo. Se arregla concediendo el permiso explícitamente. Funciona aunque
    el archivo no se pueda leer: el DUEÑO de un objeto siempre conserva el
    derecho de cambiar su ACL, y el dueño somos nosotros porque lo creamos.

    Sobre carpetas se marca `(OI)(CI)` para que lo hereden los volcados
    futuros: así se arregla una vez y no vuelve a aparecer.
    """
    if os.name != "nt":
        return True
    usuario = _usuario_actual()
    if not usuario:
        return False
    permiso = "(OI)(CI)(M)" if es_carpeta else "(M)"
    try:
        r = subprocess.run(
            ["icacls", str(ruta), "/grant", f"{usuario}:{permiso}"],
            capture_output=True, text=True, timeout=60)
    except Exception as e:
        logger.warning("[Dump] No se pudo ajustar permisos de %s: %s",
                       ruta, str(e)[:80])
        return False
    if r.returncode == 0:
        return True
    logger.warning("[Dump] icacls no pudo conceder acceso a %s: %s",
                   ruta, ((r.stdout or "") + (r.stderr or ""))[-160:])
    return False


def asegurar_legible(dmp) -> bool:
    """Comprueba que el `.DMP` se puede leer y, si no, intenta conceder el
    permiso. Devuelve True si al final es legible.

    Vive aparte de `esperar_volcado_completo` porque hace falta en DOS sitios y
    al principio solo estaba en uno: el flujo del test lo arreglaba y la
    inspección manual (`--archivo`) no, así que analizar a mano un volcado
    bloqueado seguía fallando igual. Peor: el mensaje de error decía que «el
    ajuste automático no bastó» cuando en esa ruta nunca se había intentado.
    """
    dmp = Path(dmp)
    try:
        with open(dmp, "rb") as f:
            f.read(1)
        return True
    except OSError:
        pass
    logger.info("[Dump] %s no se puede abrir — concediendo permiso de lectura.",
                dmp.name)
    conceder_lectura(dmp)
    try:
        with open(dmp, "rb") as f:
            f.read(1)
        logger.info("[Dump] ✓ Permiso concedido: el volcado ya es legible.")
        return True
    except OSError as e:
        logger.warning("[Dump] Sigue ilegible tras conceder permiso: %s",
                       str(e)[:120])
        return False


def esperar_volcado_completo(dmp, timeout=None, espera_apertura=30):
    """Espera a que un `.DMP` esté ENTERO y legible. Devuelve (listo, bytes).

    Son DOS esperas distintas y se cortan por separado, porque las dos corridas
    de hoy demostraron que se comportan muy diferente:

        crecimiento →  el tamaño se queda quieto en segundos. Esperar aquí
                       sirve, y es rápido.
        apertura    →  si el archivo está bloqueado, lo está de forma
                       PERSISTENTE: los 300 s completos fallaron dos veces
                       seguidas sobre un archivo que ya no cambiaba.

    Esperar 300 s por la apertura costaba 5 de los 7,5 minutos de la corrida
    para acabar exactamente igual. Se le da un margen corto y se deja que el
    inspector, que reintenta por su cuenta, remate.
    """
    dmp = Path(dmp)
    timeout = (timeout if timeout is not None
               else getattr(settings, "KRA1527_ESPERA_VOLCADO", 300))

    def _tam():
        try:
            return dmp.stat().st_size
        except OSError:
            return -1

    def _se_abre(tam):
        """Lectura de prueba del FINAL del archivo, que es la parte que en un
        volcado a medias todavía no existe."""
        try:
            with open(dmp, "rb") as f:
                f.seek(max(0, tam - 4096))
                f.read(1)
            return True
        except OSError:
            return False

    # ── Fase 1: que deje de crecer ──────────────────────────────────────────
    inicio = time.time()
    ultimo, estables, crecio = -1, 0, False
    while time.time() - inicio < timeout:
        tam = _tam()
        if tam > 0 and tam == ultimo:
            estables += 1
            if estables >= 2:                 # ~4 s sin cambiar
                break
        else:
            if ultimo > 0 and tam > ultimo and not crecio:
                logger.info("[Dump] El volcado aún se está escribiendo "
                            "(%.1f MB y subiendo).", tam / 1e6)
                crecio = True
            estables, ultimo = 0, tam
        time.sleep(2)
    tam = max(_tam(), 0)
    if crecio:
        logger.info("[Dump] Escritura terminada: %.1f MB en %.0f s.",
                    tam / 1e6, time.time() - inicio)

    # ── Fase 2: que se pueda abrir ──────────────────────────────────────────
    # Margen CORTO a propósito. Si un archivo que ya no cambia no se abre, no
    # se va a abrir esperando: dos corridas seguidas agotaron los 300 s enteros
    # sobre volcados completos y quietos, y acabaron igual de ilegibles. Esos 5
    # minutos eran dos tercios del tiempo de la prueba, tirados.
    if _se_abre(tam):
        return True, tam

    # No se abre. Antes de esperar, INTENTAR ARREGLARLO: la causa medida en
    # esta máquina no era un bloqueo temporal sino una ACL que no incluía al
    # usuario. Esperar no cura un permiso; concederlo sí.
    logger.info("[Dump] El volcado no se puede abrir — ajustando permisos.")
    conceder_lectura(dmp)
    if _se_abre(tam):
        logger.info("[Dump] Permisos corregidos: el volcado ya se puede leer.")
        return True, tam

    # Sigue sin abrirse: ahora sí puede ser un bloqueo temporal (antivirus
    # escaneando). Se le da el margen corto y se deja que el inspector, que
    # reintenta por su cuenta, remate.
    limite = time.time() + max(2, espera_apertura)
    while time.time() < limite:
        time.sleep(2)
        if _se_abre(tam):
            return True, tam
    return False, tam


_RE_VECTOR = re.compile(r"VECTOR_HA=([\w,]+)\s+VIVO=(si|no)")

# Cómo se escala cada vector. La distinción no es cosmética: el hallazgo 5.2.1
# del pentest es el token de la CABECERA del canal con el agente, y el fix lo
# protege ahí. Un token que aparece por otra vía es un hallazgo NUEVO, y
# llamarlo 5.2.1 hace que desarrollo revise el sitio equivocado, lo vea
# correcto, y lo cierre como no reproducible.
_ESCALACION = {
    "cabecera": "Es el hallazgo 5.2.1 del pentest: el fix NO está cumpliendo.",
    "bearer":   "Es el hallazgo 5.2.1 del pentest: el fix NO está cumpliendo.",
    "url":      ("Vector DISTINTO al 5.2.1: el token va en una URL (típicamente "
                 "`id_token_hint=` del logout OIDC en el WebView del SSO), no "
                 "en la cabecera que protege SecureJsonProcessor. Repórtalo "
                 "como hallazgo NUEVO y adjunta el contexto."),
    "json":     ("El token está en un campo JSON. Si ese payload debía pasar "
                 "por SecureJsonProcessor, es una ruta no cubierta por el fix."),
    "suelto":   ("Sin contexto reconocible en memoria. Antes de escalar, abre "
                 "el reporte del inspector y mira el contexto crudo."),
}


def _vector_del_inspector(salida: str) -> dict:
    """Vector de exposición y vigencia del token, leídos de la salida."""
    m = _RE_VECTOR.search(salida or "")
    if not m:
        return {}
    vectores = [v for v in m.group(1).split(",") if v]
    return {"vector": vectores, "token_vivo": m.group(2) == "si",
            "escalacion": " ".join(_ESCALACION.get(v, "") for v in vectores).strip()}


def respaldar(dmp, destino_dir=None):
    """Mueve un .DMP analizado al respaldo de la etiqueta. Devuelve la ruta.

    El nombre YA lleva caso y sello de tiempo
    (`CP01-EnvioMoneyTransfer_Hermes2Agent_20260902_200448.dmp`), así que dos
    corridas nunca chocan. Es distinto del volcado manual del Administrador de
    tareas, que siempre usa el mismo nombre y por eso Windows lo renombra a
    `Hermes2Agent (2).DMP`: ahí el «(2)» no dice nada de su contenido, y ese es
    justo el problema que este nombre evita."""
    dmp = Path(dmp)
    destino_dir = Path(destino_dir or RESPALDO_DIR)
    # Ya está donde debe: el volcado se escribe directamente en la carpeta de
    # evidencia. Mover un archivo sobre sí mismo puede borrarlo en algunos
    # sistemas, y aquí lo que está en juego son 500 MB de evidencia.
    try:
        if dmp.parent.resolve() == destino_dir.resolve():
            _asegurar_nota(destino_dir)
            logger.info("[Dump] Evidencia en %s", dmp)
            return dmp
    except Exception:
        pass
    try:
        destino_dir.mkdir(parents=True, exist_ok=True)
        _asegurar_nota(destino_dir)
    except Exception as e:
        logger.warning("[Dump] No se pudo preparar el respaldo %s: %s",
                       destino_dir, str(e)[:80])
        return None
    destino = destino_dir / dmp.name
    try:
        # `replace` primero: en el mismo volumen es un rename, instantáneo.
        dmp.replace(destino)
    except OSError:
        try:
            shutil.move(str(dmp), str(destino))    # volúmenes distintos
        except Exception as e:
            logger.warning("[Dump] No se pudo respaldar %s: %s. El volcado "
                           "sigue en %s.", dmp.name, str(e)[:80], dmp.parent)
            return None
    except Exception as e:
        logger.warning("[Dump] No se pudo respaldar %s: %s", dmp.name, str(e)[:80])
        return None
    logger.info("[Dump] Volcado respaldado en %s", destino)
    return destino


def purgar_respaldo(destino_dir=None) -> tuple:
    """Borra los .DMP del respaldo. Devuelve (borrados, GB liberados).

    Se llama a mano y al final del ciclo, no automáticamente: mientras la
    etiqueta se está estabilizando, estos archivos son la única forma de
    revisar un resultado sin repetir la transacción."""
    destino_dir = Path(destino_dir or RESPALDO_DIR)
    borrados, peso = 0, 0
    try:
        archivos = sorted(set(destino_dir.glob("*.dmp")) |
                          set(destino_dir.glob("*.DMP")))
    except Exception:
        return 0, 0.0
    for f in archivos:
        try:
            peso += f.stat().st_size
            f.unlink()
            borrados += 1
        except Exception as e:
            logger.warning("[Dump] No se pudo borrar %s: %s", f.name, str(e)[:70])
    return borrados, round(peso / 1e9, 2)


def _carpeta_usable(candidatas=None):
    """Primera carpeta donde de verdad se puede escribir, LEER y borrar.

    No basta con poder escribir: el volcado se escribió perfectamente en
    `reports/dumps` y después no se pudo ni leer ni borrar (`Permission denied`
    al abrirlo, `WinError 5` al eliminarlo, en archivos de horas antes). Una
    carpeta dentro del repo está vigilada por el editor, el indexador y las
    reglas de Defender; escribir un archivo de 500 MB ahí es pedir problemas.

    Elegir la carpeta «a mano» ya falló dos veces —%TEMP% y luego el repo—, así
    que aquí no se elige: se PRUEBA. Se escribe un archivo pequeño, se relee y
    se borra. La primera que pase el ciclo completo es la buena.
    """
    for carpeta in (candidatas or getattr(settings, "DUMP_DIRS_CANDIDATAS",
                                          [settings.DUMP_OUT_DIR])):
        carpeta = Path(carpeta)
        prueba = carpeta / ".kra1527_prueba_escritura"
        try:
            carpeta.mkdir(parents=True, exist_ok=True)
            prueba.write_bytes(b"kra1527")
            if prueba.read_bytes() != b"kra1527":
                raise OSError("lo leído no coincide con lo escrito")
            prueba.unlink()
            # Escribir no basta: los volcados heredan la ACL de la carpeta, y
            # si esa ACL solo cubre SYSTEM y Administradores, el archivo nace
            # ilegible para nosotros. Se concede el permiso UNA vez, heredable.
            conceder_lectura(carpeta, es_carpeta=True)
            if carpeta.resolve() == RESPALDO_DIR.resolve():
                _asegurar_nota(carpeta)
            return carpeta
        except Exception as e:
            logger.info("[Dump] %s no sirve para volcados (%s) — pruebo la "
                        "siguiente.", carpeta, str(e)[:80])
            try:
                prueba.unlink(missing_ok=True)
            except Exception:
                pass
    # Ninguna pasó: se devuelve la preferida y que el error salga con su motivo
    # real, en vez de inventar una ruta que tampoco va a funcionar.
    return Path(settings.DUMP_OUT_DIR)


def borrar_volcados(carpeta=None, prefijo: str = "CP") -> int:
    """Borra los `.DMP` de la carpeta de volcados. Devuelve cuántos borró.

    Existe para que la limpieza ocurra UNA vez al final de la corrida, no en
    cada caso: si cada caso borra los suyos, la inspección consolidada llega y
    no encuentra nada que consolidar. Los deja borrar el caso final o, si la
    corrida se cortó antes, la red de seguridad de la sesión.

    Solo toca archivos con el prefijo de los casos, para no borrar un volcado
    que alguien haya hecho a mano y esté analizando."""
    carpeta = Path(carpeta or settings.DUMP_OUT_DIR)
    # 🔒 SALVAGUARDA: nunca barrer la carpeta de evidencia de la etiqueta.
    # Al pasar a escribir los volcados directamente ahí, este barrido «de
    # limpieza» habría borrado justo lo que hay que conservar — y sin avisar,
    # porque su trabajo es precisamente borrar .DMP. Se compara resuelto para
    # que no dependa de cómo venga escrita la ruta.
    try:
        if carpeta.resolve() == RESPALDO_DIR.resolve():
            logger.info("[Dump] La carpeta de la etiqueta NO se barre: es la "
                        "evidencia. Para purgarla: python "
                        "tools/kra1527_volcar.py --purgar")
            return 0
    except Exception:
        pass
    borrados = 0
    try:
        # `set` a propósito: en Windows el glob NO distingue mayúsculas, así que
        # `*.dmp` y `*.DMP` devuelven el MISMO archivo dos veces. Sin deduplicar,
        # el segundo intento de borrado fallaba con «no se encuentra el archivo»
        # (ya lo había borrado el primero) y ensuciaba el log con un error que
        # no existía. También inflaba el recuento de la inspección consolidada.
        candidatos = sorted(set(carpeta.glob("*.dmp")) | set(carpeta.glob("*.DMP")))
    except Exception:
        return 0
    retenidos = []
    for f in candidatos:
        if prefijo and not f.name.startswith(prefijo):
            continue
        try:
            f.unlink(missing_ok=True)
            borrados += 1
        except Exception as e:
            retenidos.append((f, str(e)[:60]))
    if retenidos:
        # UN aviso, no uno por archivo: la corrida anterior escupió tres
        # warnings idénticos y el motivo era el mismo para los tres. Y se dice
        # cuánto espacio está en juego, que es lo que de verdad importa cuando
        # son volcados de medio giga.
        peso = 0
        for f, _ in retenidos:
            try:
                peso += f.stat().st_size
            except Exception:
                pass
        logger.warning(
            "[Dump] %d volcado(s) NO se pudieron borrar (%.1f GB ocupados). "
            "Los retiene otro proceso, casi siempre el antivirus. Bórralos a "
            "mano o excluye la carpeta:\n"
            "    Remove-Item \"%s\\*.dmp\" -Force\n"
            "    Add-MpPreference -ExclusionPath \"%s\"   (como Administrador)",
            len(retenidos), peso / 1e9, carpeta, carpeta)
    return borrados


class MemDumpHelper:
    """Orquesta procdump + el inspector de volcados para un caso de prueba."""

    def __init__(self, caso: str, out_dir=None, procdump=None,
                 conservar_dmp: bool = False):
        self.caso = caso
        self.procdump = Path(procdump or settings.PROCDUMP_PATH)
        self.out_dir = Path(out_dir) if out_dir else _carpeta_usable()
        self.reportes_dir = settings.EVIDENCE_DIR / "KRA-1527" / caso
        self.conservar_dmp = conservar_dmp
        self._creados = []          # .DMP generados (para limpiar al final)
        self.resultados = []        # un dict por inspección
        self._armados = []          # (Popen, proceso, ruta) pendientes
        self._por_inspeccionar = []  # (ruta, proceso, marcador) capturados
        try:
            self.out_dir.mkdir(parents=True, exist_ok=True)
            self.reportes_dir.mkdir(parents=True, exist_ok=True)
            # Se deja dicho DÓNDE van los volcados: cuando uno no se puede leer,
            # lo primero que hace falta saber es en qué carpeta buscarlo.
            logger.info("[Dump] Carpeta de volcados: %s", self.out_dir)
        except Exception as e:
            logger.warning("[Dump] No se pudo preparar la carpeta: %s", str(e)[:90])

    # ── disponibilidad ──────────────────────────────────────────────────────
    @property
    def tiene_procdump(self) -> bool:
        return os.name == "nt" and self.procdump.exists()

    @property
    def disponible(self) -> bool:
        """True si se puede volcar un proceso ESTABLE por cualquier vía.

        No hace falta procdump para eso: Windows trae `comsvcs.dll`, que es
        justo lo que usa el «Crear archivo de volcado de memoria» del
        Administrador de tareas — el procedimiento manual que esta etiqueta
        automatiza. Así el caso base funciona en cualquier máquina de QA sin
        instalar nada.

        procdump sigue siendo necesario para el proceso EFÍMERO (su flag `-w`
        espera a que el proceso nazca, y eso comsvcs no lo hace)."""
        return os.name == "nt"

    def _motivo_no_disponible(self) -> str:
        if os.name != "nt":
            return "el volcado de memoria solo aplica en Windows"
        return f"no se encontró procdump en {self.procdump}"

    @staticmethod
    def pid_de(proceso: str):
        """PID del proceso por nombre de imagen, o None."""
        if os.name != "nt":
            return None
        try:
            r = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {proceso}", "/FO", "CSV",
                 "/NH"], capture_output=True, text=True, timeout=20)
        except Exception:
            return None
        for linea in (r.stdout or "").splitlines():
            partes = [p.strip('" ') for p in linea.split('","')]
            if len(partes) >= 2 and proceso.lower() in partes[0].lower():
                try:
                    return int(partes[1])
                except ValueError:
                    continue
        return None

    def _volcar_con_comsvcs(self, proceso: str, destino: Path):
        """Volcado con `comsvcs.dll MiniDump` — sin instalar nada.

        Es la misma API (`MiniDumpWriteDump`) que usa el Administrador de
        tareas. Se llama con el rundll32 de System32 a propósito: con el de
        SysWOW64 falla al volcar un proceso de 64 bits."""
        pid = self.pid_de(proceso)
        if not pid:
            logger.warning("[Dump] %s no está corriendo: no hay nada que "
                           "volcar.", proceso)
            return None, f"{proceso} no está en ejecución"
        rundll = Path(os.environ.get("SystemRoot", r"C:\Windows")) / \
            "System32" / "rundll32.exe"
        try:
            r = subprocess.run(
                [str(rundll), r"C:\Windows\System32\comsvcs.dll", "MiniDump",
                 str(pid), str(destino), "full"],
                capture_output=True, text=True, timeout=300)
        except Exception as e:
            return None, str(e)[:150]
        if destino.exists() and destino.stat().st_size > 0:
            # El volcado nace con la ACL de quien lo escribió, que no siempre
            # nos incluye. Se corrige aquí mismo, recién creado.
            conceder_lectura(destino)
            # «al menos» a propósito: rundll32 puede haber vuelto antes de que
            # Windows acabe de volcar el archivo a disco, así que este tamaño
            # es un mínimo, no el definitivo. El tamaño real se mide al
            # inspeccionar, después de esperar a que se quede quieto.
            logger.info("[Dump] ✓ %s volcado con comsvcs (PID %d, al menos "
                        "%.1f MB).", proceso, pid,
                        destino.stat().st_size / 1e6)
            return destino, ""
        salida = ((r.stdout or "") + (r.stderr or "")).strip()
        motivo = (salida[-200:] if salida else
                  "comsvcs no generó el archivo (suele faltar el privilegio "
                  "SeDebugPrivilege: prueba la consola como Administrador)")
        return None, motivo

    def _ruta(self, proceso: str) -> Path:
        sello = time.strftime("%Y%m%d_%H%M%S")
        limpio = proceso.replace(".exe", "").replace(".", "_")
        return self.out_dir / f"{self.caso}_{limpio}_{sello}.dmp"

    # ── captura ─────────────────────────────────────────────────────────────
    def armar_efimero(self, proceso: str = None):
        """`procdump -ma -w <proc>`: queda ESPERANDO a que el proceso arranque.

        Hay que llamarlo ANTES de disparar la acción en el Front End."""
        proceso = proceso or settings.HW_PROXY_PROC
        # Aquí sí hace falta procdump: comsvcs no sabe ESPERAR a que el proceso
        # nazca, y este muere con el request.
        if not self.tiene_procdump:
            logger.info("[Dump] Sin volcado del proceso efímero (%s). Para "
                        "capturarlo hace falta procdump y su flag -w.",
                        self._motivo_no_disponible())
            return None
        destino = self._ruta(proceso)
        try:
            p = subprocess.Popen(
                [str(self.procdump), "-accepteula", "-ma", "-w", proceso,
                 str(destino)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            self._armados.append((p, proceso, destino))
            logger.info("[Dump] procdump ARMADO esperando a %s → %s",
                        proceso, destino.name)
            return p
        except Exception as e:
            logger.warning("[Dump] No se pudo armar procdump para %s: %s",
                           proceso, str(e)[:100])
            return None

    def recoger_efimeros(self, timeout: int = 60) -> None:
        """Espera a los procdump armados y registra lo que hayan capturado."""
        for p, proceso, destino in self._armados:
            try:
                p.wait(timeout=timeout)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
                logger.info("[Dump] %s no se capturó en %ds — el proceso fue "
                            "demasiado efímero.", proceso, timeout)
                self.resultados.append(self._no_capturado(
                    proceso, "el proceso no llegó a arrancar o duró menos que la "
                             "ventana de captura"))
                continue
            if destino.exists() and destino.stat().st_size > 0:
                self._creados.append(destino)
                logger.info("[Dump] ✓ %s capturado (%.1f MB).", proceso,
                            destino.stat().st_size / 1e6)
                self.inspeccionar(destino, proceso)
            else:
                self.resultados.append(self._no_capturado(
                    proceso, "procdump terminó sin generar el archivo"))
        self._armados = []

    def volcar_ahora(self, proceso: str = None, inspeccionar: bool = True):
        """Vuelca un proceso estable (Hermes2Agent).

        `inspeccionar=False` CAPTURA y no analiza: deja el volcado apuntado
        como pendiente para `inspeccionar_pendientes()`. Se separan a propósito,
        por dos razones que apuntan al mismo sitio:

        1. **El flujo no debe esperar al análisis.** Capturar tarda ~1 s;
           inspeccionar 500 MB tardaba casi un minuto, y ese minuto se comía
           entre el envío y la cancelación — se veía como si el caso se hubiera
           colgado justo después de la transacción.
        2. **Al análisis le conviene esperar.** Un volcado recién nacido está
           retenido por quien lo escanea. Inspeccionarlo 0 segundos después es
           pelearse con el antivirus; hacerlo cuando el caso ya terminó su
           trabajo funcional le da ese margen gratis.
        """
        proceso = proceso or settings.HW_AGENT_PROC
        if not self.disponible:
            logger.info("[Dump] Sin volcado de %s (%s).", proceso,
                        self._motivo_no_disponible())
            self.resultados.append(self._no_capturado(
                proceso, self._motivo_no_disponible()))
            return None
        destino = self._ruta(proceso)

        # Sin procdump se usa comsvcs.dll, que ya viene en Windows: es la
        # misma vía del «Crear archivo de volcado» del Administrador de tareas.
        if not self.tiene_procdump:
            logger.info("[Dump] procdump no está en %s — volcando %s con "
                        "comsvcs.dll (vía del Administrador de tareas).",
                        self.procdump, proceso)
            archivo, motivo = self._volcar_con_comsvcs(proceso, destino)
            if archivo:
                self._creados.append(archivo)
                if not inspeccionar:
                    return self._pendiente(archivo, proceso)
                return self.inspeccionar(archivo, proceso)
            self.resultados.append(self._no_capturado(proceso, motivo))
            return None

        try:
            r = subprocess.run(
                [str(self.procdump), "-accepteula", "-ma", proceso, str(destino)],
                capture_output=True, text=True, timeout=180)
        except Exception as e:
            logger.warning("[Dump] procdump falló con %s: %s", proceso, str(e)[:100])
            self.resultados.append(self._no_capturado(proceso, str(e)[:120]))
            return None
        if destino.exists() and destino.stat().st_size > 0:
            self._creados.append(destino)
            logger.info("[Dump] ✓ %s volcado (%.1f MB).", proceso,
                        destino.stat().st_size / 1e6)
            if not inspeccionar:
                return self._pendiente(destino, proceso)
            return self.inspeccionar(destino, proceso)
        salida = (r.stdout or r.stderr or "").strip().splitlines()
        motivo = salida[-1] if salida else "procdump no generó el archivo"
        logger.warning("[Dump] %s no se pudo volcar: %s", proceso, motivo[:120])
        self.resultados.append(self._no_capturado(proceso, motivo[:200]))
        return None

    # ── inspección ──────────────────────────────────────────────────────────
    def _pendiente(self, dmp: Path, proceso: str) -> dict:
        """Apunta un volcado CAPTURADO pero todavía sin analizar.

        Se registra como capturado —porque lo está— con veredicto PENDIENTE.
        Importa la distinción: `exigir_comunicacion` necesita saber que el caso
        SÍ ejercitó al agente (hay volcado), mientras que el reporte no debe
        tomar «pendiente» por un resultado."""
        res = {"proceso": proceso, "archivo": Path(dmp).name,
               "tam_mb": round(Path(dmp).stat().st_size / 1e6, 1),
               "veredicto": "PENDIENTE", "capturado": True, "reporte": "",
               "salida": "capturado; se analiza al terminar el caso",
               "ruta": str(dmp)}
        self.resultados.append(res)
        self._por_inspeccionar.append((Path(dmp), proceso, res))
        logger.info("[Dump] ✓ %s capturado (~%.0f MB, aún escribiéndose) — se "
                    "inspecciona al terminar el caso, para no frenar el flujo.",
                    proceso, res["tam_mb"])
        return res

    @property
    def hay_pendientes(self) -> bool:
        return bool(self._por_inspeccionar)

    def inspeccionar_pendientes(self) -> list:
        """Analiza los volcados capturados que quedaron a la espera.

        Se llama cuando el caso ya hizo su trabajo funcional (envío y limpieza
        incluidos). Cada resultado SUSTITUYE en el sitio la entrada PENDIENTE,
        así el reporte no acumula duplicados del mismo volcado."""
        if not self._por_inspeccionar:
            return []
        logger.info("[Dump] Analizando %d volcado(s) pendiente(s)…",
                    len(self._por_inspeccionar))
        nuevos = []
        for dmp, proceso, marcador in self._por_inspeccionar:
            # ANTES de leer: asegurarse de que el volcado ya está entero.
            # Lanzar el inspector contra un archivo que todavía se está
            # escribiendo garantiza un «Permission denied» y un ERROR que
            # parece de permisos. Esperar aquí no le quita tiempo al flujo:
            # el caso ya terminó su parte funcional.
            listo, tam = esperar_volcado_completo(dmp)
            if not listo:
                logger.warning(
                    "[Dump] %s está COMPLETO (%.1f MB, tamaño estable) pero no "
                    "se puede abrir. No es la escritura: algo le tiene "
                    "denegado el acceso. Diagnostícalo en segundos con\n"
                    "    python tools/kra1527_diagnostico_dmp.py\n"
                    "  que distingue ACCESS_DENIED (antivirus o ACL) de "
                    "SHARING_VIOLATION (otro proceso con el archivo abierto) "
                    "— Python los muestra a los dos como el mismo Errno 13.",
                    Path(dmp).name, tam / 1e6)
            real = self.inspeccionar(dmp, proceso, registrar=False)
            # Analizado → se asegura el respaldo en la carpeta de la etiqueta.
            # Normalmente ya está ahí (es donde se escribe el volcado), y esta
            # llamada solo confirma la ruta; si por lo que sea se capturó en
            # una carpeta de paso, aquí es donde se trae. Nunca se borra nada
            # antes de este punto: el respaldo precede a la limpieza, siempre.
            respaldado = respaldar(dmp)
            if respaldado:
                real["ruta"] = str(respaldado)
                real["respaldo"] = str(respaldado)
                if dmp in self._creados:
                    self._creados.remove(dmp)
            try:
                self.resultados[self.resultados.index(marcador)] = real
            except ValueError:
                self.resultados.append(real)
            nuevos.append(real)
        self._por_inspeccionar = []
        return nuevos

    def inspeccionar(self, dmp: Path, proceso: str,
                     registrar: bool = True) -> dict:
        """Corre `dump_token_inspector.py` sobre el .DMP.

        El inspector devuelve exit code 1 cuando encuentra un JWT de auth
        decodificable; ese código es el veredicto."""
        html_out = self.reportes_dir / f"inspector_{Path(dmp).stem}.html"
        # Antes de gastar un minuto escaneando medio giga: que se pueda leer.
        # Cubre también la inspección manual, que antes se quedaba fuera.
        legible = asegurar_legible(dmp)
        try:
            r = subprocess.run(
                [sys.executable, str(INSPECTOR), str(dmp),
                 "--caso", self.caso, "--proceso", proceso,
                 "--out", str(html_out)],
                capture_output=True, text=True, timeout=1800,
                **_TEXTO_INSPECTOR)
            salida = (r.stdout or "") + (r.stderr or "")
            veredicto = _veredicto_del_inspector(r.returncode, salida)
        except Exception as e:
            salida, veredicto = str(e)[:300], "ERROR"
            html_out = None
        res = {
            "proceso": proceso,
            "archivo": Path(dmp).name,
            "tam_mb": round(Path(dmp).stat().st_size / 1e6, 1) if Path(dmp).exists() else 0,
            "veredicto": veredicto,
            "capturado": True,
            "reporte": str(html_out) if html_out else "",
            "salida": salida[-3000:],
            "ruta": str(dmp),
            "actividad": _actividad_del_inspector(salida),
            **_vector_del_inspector(salida),
        }
        if registrar:
            self.resultados.append(res)
        logger.info("[Dump] Inspección de %s → %s", res["archivo"], veredicto)
        if veredicto == "ERROR":
            # Un volcado ilegible es el fallo más frustrante de esta suite: el
            # dato está capturado y aun así no se puede concluir. Se dice CÓMO
            # salir del paso, con la ruta exacta, en vez de dejar solo el
            # «Permission denied».
            if not legible:
                # El diagnóstico ya lo hizo `asegurar_legible`: no se pudo
                # abrir y conceder el permiso tampoco funcionó. Eso significa
                # que no somos el dueño del archivo (el dueño sí podría), así
                # que hace falta una consola ELEVADA una sola vez.
                logger.warning(
                    "[Dump] El volcado no se puede leer y tampoco pudimos "
                    "concedernos el permiso: el archivo no es nuestro. Ábrelo "
                    "una vez desde PowerShell COMO ADMINISTRADOR:\n"
                    "    icacls \"%s\" /grant \"$env:USERNAME:(OI)(CI)M\" /T\n"
                    "  Con eso queda arreglado también para las próximas "
                    "corridas. Después, sin elevar:\n"
                    "    python tools/kra1527_volcar.py --archivo \"%s\"",
                    Path(dmp).parent, dmp)
            else:
                logger.warning(
                    "[Dump] El volcado SÍ se puede abrir, pero el inspector "
                    "falló al analizarlo. Mira su salida arriba; el archivo NO "
                    "se borra:\n    python tools/kra1527_volcar.py --archivo "
                    "\"%s\"", dmp)
        if veredicto in ("FAIL", "WARN", "ERROR"):
            # El resumen del inspector, a la vista, sin tener que abrir el HTML.
            # No filtra nada: su salida imprime recuentos y nombres de archivo,
            # nunca el token (los claims solo van al reporte).
            # Sin recortar. El límite de 180 caracteres cortaba justo la línea
            # de ACTIVIDAD_HA —«…Procesador seguro de JSO»—, que es la que
            # demuestra que el agente estaba trabajando cuando se tomó el
            # volcado. Es el dato que sostiene el hallazgo frente a «eso es
            # memoria vieja»; recortarlo por estética no sale a cuenta.
            for linea in [l for l in salida.splitlines() if l.strip()][-8:]:
                logger.warning("[Dump]   %s", linea)
            if veredicto == "FAIL":
                logger.warning("[Dump] ⚠ HALLAZGO: hay un JWT de autenticación "
                               "decodificable en la memoria de %s. Reporte con "
                               "los claims: %s", proceso, html_out)
        return res

    def inspeccionar_carpeta(self, carpeta=None, etiqueta: str = "consolidado"):
        """Barre TODOS los .DMP de una carpeta en una sola pasada (CP07).

        Es la versión automatizada de lo que hoy se hace a mano: abrir cada
        volcado y buscar 'eyJ' con findstr. El inspector acepta carpetas, así
        que una sola llamada cubre los volcados de toda la corrida y produce un
        único reporte — y su exit code sigue siendo el veredicto."""
        carpeta = Path(carpeta or self.out_dir)
        # `set`: en Windows el glob es insensible a mayúsculas y los dos
        # patrones devolverían el mismo archivo, duplicando el recuento.
        dmps = sorted(set(carpeta.glob("*.dmp")) | set(carpeta.glob("*.DMP")))
        if not dmps:
            logger.info("[Dump] No hay volcados que consolidar en %s.", carpeta)
            return {"veredicto": "NO_CAPTURADO", "archivos": 0, "reporte": "",
                    "salida": f"sin archivos .DMP en {carpeta}"}
        html_out = self.reportes_dir / f"inspector_{etiqueta}.html"
        logger.info("[Dump] Consolidando %d volcado(s) de %s…", len(dmps), carpeta)
        try:
            r = subprocess.run(
                [sys.executable, str(INSPECTOR), str(carpeta),
                 "--caso", f"{self.caso} · {etiqueta}",
                 "--proceso", "(todos)", "--out", str(html_out)],
                capture_output=True, text=True, timeout=1800,
                **_TEXTO_INSPECTOR)
            salida = (r.stdout or "") + (r.stderr or "")
            # Se usa el MISMO mapeo que la inspección por caso. El anterior
            # tenía un fallo silencioso: preguntaba `"WARN" in salida`, y el
            # resumen del inspector SIEMPRE imprime «WARN=0» — así que la
            # consolidación salía WARN incluso con todo limpio. Un reporte que
            # siempre dice «revisar» no se revisa nunca.
            veredicto = _veredicto_del_inspector(r.returncode, salida)
        except Exception as e:
            salida, veredicto, html_out = str(e)[:300], "ERROR", None
        res = {"proceso": "(todos los volcados)", "archivo": f"{len(dmps)} .DMP",
               "tam_mb": round(sum(f.stat().st_size for f in dmps) / 1e6, 1),
               "veredicto": veredicto, "capturado": True,
               "reporte": str(html_out) if html_out else "",
               "salida": salida[-4000:], "archivos": len(dmps)}
        self.resultados.append(res)
        logger.info("[Dump] Consolidado de %d volcado(s) → %s",
                    len(dmps), veredicto)
        return res

    def _no_capturado(self, proceso: str, motivo: str) -> dict:
        return {"proceso": proceso, "archivo": "", "tam_mb": 0,
                "veredicto": "NO_CAPTURADO", "capturado": False,
                "reporte": "", "salida": motivo}

    # ── resultado y limpieza ────────────────────────────────────────────────
    @property
    def veredicto(self) -> str:
        """Peor veredicto de todas las inspecciones."""
        if not self.resultados:
            return "SIN_VOLCADO"
        vs = [r["veredicto"] for r in self.resultados]
        for grave in ("FAIL", "ERROR", "WARN"):
            if grave in vs:
                return grave
        if "PASS" in vs:
            return "PASS"
        return "PENDIENTE" if "PENDIENTE" in vs else "NO_CAPTURADO"

    @property
    def hay_token_expuesto(self) -> bool:
        return any(r["veredicto"] == "FAIL" for r in self.resultados)

    def limpiar(self) -> None:
        """Borra los .DMP: pesan cientos de MB y llevan datos sensibles.

        EXCEPCIÓN: si un volcado quedó con veredicto ERROR no se borra. Es el
        único caso en que el archivo sigue teniendo valor — es la evidencia que
        todavía no se pudo leer, y borrarla obligaría a repetir el caso entero
        para volver a capturarla."""
        ilegibles = {r.get("ruta") for r in self.resultados
                     if r.get("veredicto") == "ERROR"}
        if ilegibles:
            conservados = [f for f in self._creados if str(f) in ilegibles]
            if conservados:
                logger.warning(
                    "[Dump] %d volcado(s) CONSERVADOS porque no se pudieron "
                    "analizar: son la evidencia pendiente. Analízalos con "
                    "`python tools/kra1527_volcar.py --archivo <ruta>` y "
                    "bórralos después.", len(conservados))
            self._creados = [f for f in self._creados
                             if str(f) not in ilegibles]
        if self.conservar_dmp:
            logger.warning("[Dump] %d .DMP CONSERVADOS por configuración — "
                           "contienen datos sensibles, bórralos a mano.",
                           len(self._creados))
            return
        # 🔒 SALVAGUARDA: nunca borrar lo que está en la carpeta de respaldo.
        #
        # Aquí se perdió una evidencia real. Los volcados pasaron a escribirse
        # directamente en la carpeta de evidencia, y esta limpieza —escrita cuando
        # el .DMP era un archivo desechable de %TEMP%— siguió borrando por ruta
        # sin preguntar dónde estaba. Resultado: el volcado desaparecía del
        # temporal Y del repo, y el reporte quedaba sin el documento que lo
        # sostiene. Un `unlink` no puede depender de que la contabilidad de
        # `_creados` sea correcta: se comprueba la carpeta.
        respaldados, borrables = [], []
        for f in self._creados:
            try:
                en_respaldo = f.parent.resolve() == RESPALDO_DIR.resolve()
            except Exception:
                en_respaldo = False
            (respaldados if en_respaldo else borrables).append(f)
        if respaldados:
            logger.info(
                "[Dump] %d volcado(s) CONSERVADOS como evidencia en %s "
                "(%.2f GB). Se purgan al cerrar el ticket con "
                "`python tools/kra1527_volcar.py --purgar`.",
                len(respaldados), RESPALDO_DIR,
                sum(f.stat().st_size for f in respaldados
                    if f.exists()) / 1e9)
        for f in borrables:
            try:
                f.unlink()
            except Exception as e:
                logger.warning("[Dump] No se pudo borrar %s: %s", f.name, str(e)[:80])
        if borrables:
            logger.info("[Dump] %d volcado(s) borrado(s) del temporal tras "
                        "inspeccionar (ya respaldados).", len(borrables))
        self._creados = []
