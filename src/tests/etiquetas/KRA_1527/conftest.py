"""
Fixtures, política de volcados y orden de ejecución de KRA-1527.

Cada flujo hace lo mismo alrededor de la acción que dispara al Hardware Agent:
armar el volcado del proceso efímero ANTES, auditar el tráfico DURANTE, volcar
el proceso estable DESPUÉS, y registrar todo en el reporte. Eso vive aquí para
que los tests solo describan el flujo funcional.

## Política de volcados (la parte que estaba mal)

Antes, cada caso borraba sus `.DMP` al terminar. Con eso, la inspección
consolidada **nunca podía funcionar**: llegaba al final y no había nada que
consolidar, así que se omitía siempre. El volcado se hacía «en cada uno» y a la
vez se pedía «en todos» — incompatible.

Ahora es una sola política, coherente:

```
cada caso        →  captura .DMP + lo inspecciona (su veredicto)  + LO CONSERVA
caso final       →  consolida todo en un reporte  + BORRA todos los .DMP
red de seguridad →  al cerrar la sesión, borra lo que haya quedado
```

Así el volcado se hace **en cada uno Y en todos**, y los `.DMP` —cientos de MB
con datos sensibles— se borran una sola vez, al final, sin que nadie tenga que
acordarse. `KRA1527_CONSERVAR_DMP=1` los deja para depurar.

## El reporte NO se borra solo

Se acumula entre corridas, para poder estabilizar un caso a la vez sin perder
los resultados de los anteriores. Para empezar de cero:

    python tools/kra1527_reset.py
"""

import tempfile
from pathlib import Path

import pytest

from config import settings
from config.logger import get_logger
from src.helpers import reporte_kra1527 as REPORTE
from src.helpers.ha_audit import AuditoriaHA
from src.helpers.memdump_helper import (MemDumpHelper, borrar_volcados,
                                        respaldar, RESPALDO_DIR as REPALDO)

from . import preflight

logger = get_logger("KRA-1527")


class VigilanciaHA:
    """Auditoría + volcados de un flujo, con el reporte al final."""

    def __init__(self, page, caso: str, titulo: str):
        self.caso = caso
        self.titulo = titulo
        # Los puertos que el preflight vio ESCUCHAR al agente se pasan como
        # pistas al patrón: descubrir el puerto real y luego no usarlo sería
        # absurdo.
        self.auditoria = AuditoriaHA(page, caso,
                                     pistas=preflight.estado().get("puertos"))
        # conservar_dmp=True: los borra el caso final (o la red de seguridad),
        # no cada caso — si no, no habría nada que consolidar.
        self.dumps = MemDumpHelper(caso, conservar_dmp=True)
        self.notas = ""

    async def __aenter__(self):
        # ORDEN CLAVE: procdump -w se arma ANTES de la acción. El proxy nace y
        # muere con el request; si se arma después, ya no hay nada que volcar.
        if preflight.estado()["volcado_activo"]:
            self.dumps.armar_efimero(settings.HW_PROXY_PROC)
        await self.auditoria.iniciar()
        return self

    async def __aexit__(self, *exc):
        self.auditoria.detener()
        if preflight.estado()["volcado_activo"]:
            self.dumps.recoger_efimeros(timeout=45)
            # CAPTURA sí, análisis no todavía. La captura tarda ~1 s y tiene
            # que ocurrir aquí, pegada a la acción, mientras la memoria aún
            # contiene lo que se quiere mirar. El análisis de 500 MB tardaba
            # casi un minuto justo entre el envío y la cancelación: el caso
            # parecía colgado, y encima peleaba con el antivirus por un archivo
            # recién escrito. Se hace al final, en `exigir_sin_token`.
            self.dumps.volcar_ahora(settings.HW_AGENT_PROC, inspeccionar=False)
        REPORTE.registrar(self.caso, self.titulo,
                          self.auditoria.resumen(), self.dumps.resultados,
                          notas=self.notas)
        return False        # no se tragan las excepciones del test

    def anotar(self, texto: str) -> None:
        """Añade una nota al reporte DESPUÉS de haber cerrado la vigilancia.

        La limpieza (cancelar lo que el caso creó) ocurre fuera del bloque
        auditado, y su resultado importa: si quedó una transacción viva en TEST
        hay que verlo en el reporte, no solo en el log de esa corrida."""
        if not texto:
            return
        self.notas = f"{self.notas} · {texto}".strip(" ·")
        REPORTE.registrar(self.caso, self.titulo, self.auditoria.resumen(),
                          self.dumps.resultados, notas=self.notas)

    # ── veredicto del flujo ─────────────────────────────────────────────────
    @property
    def volcados_capturados(self) -> list:
        """Volcados que SÍ se consiguieron en este caso."""
        return [r for r in self.dumps.resultados if r.get("capturado")]

    def exigir_sin_token(self):
        """Analiza los volcados y **registra** el hallazgo. No falla por él.

        ## Quién dice qué

        - **pytest** responde una sola pregunta: ¿la automatización hizo su
          trabajo? Escaneó, procesó, limpió, capturó el volcado y pudo leerlo.
        - **El reporte** responde la otra: ¿hay un token expuesto? Ahí van el
          vector, la vigencia y el enlace al análisis del inspector.

        Mezclarlas hacía que un hallazgo REAL —el que hay que reportar— se
        viera igual que un selector roto: rojo, en pytest, entre trazas. Y
        obligaba a que la suite no cerrara nunca en verde mientras el bug
        siguiera abierto, que es justo cuando más falta hace poder correrla
        entera para ver si algo más se rompió.

        Un hallazgo no desaparece por no romper la corrida: queda en el HTML
        del ticket, en el resumen de cierre, en WARNING en el log, y el .DMP
        que lo prueba se conserva en disco.

        Sí falla cuando el volcado se capturó pero NO se pudo leer: eso no es
        un hallazgo ni un aprobado, es una comprobación que no se hizo."""
        # Aquí es donde se analizan los volcados: el caso ya terminó su parte
        # funcional (envío y limpieza), así que analizar no le quita tiempo a
        # nada, y el archivo ha tenido un rato para que lo suelte quien lo
        # estuviera escaneando.
        if self.dumps.hay_pendientes:
            self.dumps.inspeccionar_pendientes()
            REPORTE.registrar(self.caso, self.titulo,
                              self.auditoria.resumen(), self.dumps.resultados,
                              notas=self.notas)

        expuestos = self.auditoria.tokens_expuestos
        if expuestos:
            logger.warning(
                "[%s] ⚠ HALLAZGO · TOKEN EN CLARO EN EL TRÁFICO con el "
                "Hardware Agent: %d JWT decodificable(s). Claims: %s",
                self.caso, len(expuestos), expuestos[0].get("claims"))
            self.anotar(f"Hallazgo: {len(expuestos)} JWT en claro en el "
                        f"tráfico con el Hardware Agent.")

        if self.dumps.hay_token_expuesto:
            fallidos = [r for r in self.dumps.resultados
                        if r.get("veredicto") == "FAIL"]
            # El VECTOR decide cómo se reporta. Este texto llegó a afirmar
            # «esto es exactamente el hallazgo 5.2.1» para cualquier JWT, y eso
            # es falso cuando el token llega por otra vía (p. ej. una URL de
            # logout OIDC): desarrollo revisa la cabecera, la ve protegida, y
            # cierra el ticket como no reproducible.
            vectores, escalaciones = [], []
            vivo = False
            for r in fallidos:
                vectores += r.get("vector") or []
                if r.get("escalacion"):
                    escalaciones.append(r["escalacion"])
                vivo = vivo or bool(r.get("token_vivo"))
            vectores = sorted(set(vectores))

            logger.warning("─" * 70)
            logger.warning("[%s] ⚠ HALLAZGO · TOKEN EN CLARO EN EL VOLCADO DE "
                           "MEMORIA", self.caso)
            for r in fallidos:
                logger.warning("[%s]   · %s · %s (%s MB)", self.caso,
                               r.get("proceso"), r.get("archivo"),
                               r.get("tam_mb"))
                logger.warning("[%s]     Análisis: %s", self.caso,
                               r.get("reporte") or "sin reporte")
            logger.warning("[%s]   Vector: %s", self.caso,
                           ", ".join(vectores) or "no determinado")
            for texto in dict.fromkeys(escalaciones):
                logger.warning("[%s]   %s", self.caso, texto)
            logger.warning(
                "[%s]   %s", self.caso,
                "Token VIGENTE al tomar el volcado: credencial viva, no "
                "residuo de una sesión anterior al fix." if vivo else
                "Token ya EXPIRADO al tomar el volcado: sigue siendo una "
                "fuga, pero confirma cuándo se reinició el agente antes de "
                "escalarlo como incumplimiento del fix.")
            logger.warning("[%s]   El CP no falla por esto: la ejecución fue "
                           "correcta y el hallazgo queda en el reporte.",
                           self.caso)
            logger.warning("─" * 70)

            # Al reporte, que es quien dicta el veredicto del ticket.
            self.anotar(
                "Hallazgo: JWT decodificable en la memoria de "
                + ", ".join(sorted({r.get("proceso", "?") for r in fallidos}))
                + f". Vector: {', '.join(vectores) or 'no determinado'}."
                + (" Token vigente al momento del volcado." if vivo else
                   " Token ya expirado al momento del volcado."))

        # ── Volcado capturado pero ILEGIBLE ────────────────────────────────
        # No es un hallazgo ni un aprobado: es una comprobación que no se pudo
        # hacer. Si además no hubo tráfico auditable, el caso no verificó el
        # criterio del ticket, y decir PASSED sería mentir con buena letra.
        ilegibles = [r for r in self.dumps.resultados
                     if r.get("veredicto") == "ERROR"]
        concluyentes = [r for r in self.dumps.resultados
                        if r.get("veredicto") in ("PASS", "WARN", "FAIL")]
        if ilegibles and not concluyentes and not self.auditoria.hubo_trafico:
            detalle = "\n".join(f"    · {r.get('ruta') or r.get('archivo')}"
                                for r in ilegibles)
            aviso = (
                f"[{self.caso}] El volcado se CAPTURÓ pero no se pudo LEER, así "
                f"que el criterio del ticket no se verificó.\n{detalle}\n"
                f"  La causa medida en esta máquina fue una ACL que NO incluía "
                f"al usuario (solo SYSTEM y Administradores). No es el "
                f"antivirus ni una escritura a medias: es un permiso. La suite "
                f"ya intenta concederlo sola; si aun así falla:\n"
                f"    icacls \"{settings.DUMP_OUT_DIR}\" /grant "
                f"\"%USERNAME%\":(OI)(CI)M\n"
                f"  Para ver exactamente qué lo impide:\n"
                f"    python tools/kra1527_diagnostico_dmp.py\n"
                f"  Para analizarlo a mano —el archivo NO se borra—:\n"
                f"    python tools/kra1527_volcar.py --archivo <ruta del .DMP>\n"
                f"  Y si ahora mismo lo que quieres es estabilizar el FLUJO sin "
                f"que esto lo tape:\n"
                f"    $env:KRA1527_TOLERAR_ERROR_VOLCADO=\"1\"")
            if settings.KRA1527_TOLERAR_ERROR_VOLCADO:
                logger.warning("⚠ %s", aviso)
                self.anotar("Volcado capturado pero ilegible: el caso NO "
                            "verificó el criterio del ticket (tolerado por "
                            "KRA1527_TOLERAR_ERROR_VOLCADO=1).")
            else:
                raise AssertionError(aviso)

    def exigir_comunicacion(self):
        """Falla solo si el caso no ejercitó al agente **de ninguna forma**.

        Antes exigía tráfico HTTP y nada más. Eso era un error de diseño: la
        auditoría de tráfico es un APOYO —demuestra que el token tampoco viaja
        en claro—, pero el criterio de aceptación del ticket es el **volcado de
        memoria**. Si se consiguió volcar el proceso del agente justo después
        de la acción, el caso tiene la evidencia que le pedían, y bloquearlo por
        no haber visto peticiones HTTP tira a la basura un resultado válido.

        Peor todavía: al fallar aquí, `exigir_sin_token` no llegaba a
        ejecutarse, así que un volcado con veredicto FAIL —un hallazgo real— se
        reportaba como «el flujo no verifica nada».

        Se sigue fallando cuando NO hubo ni tráfico ni volcado: eso sí es un
        caso que no probó nada, y es el falso negativo del que avisa el brief."""
        if self.auditoria.hubo_trafico:
            return
        capturados = self.volcados_capturados
        if capturados:
            procesos = ", ".join(sorted({r.get("proceso", "?")
                                         for r in capturados}))
            logger.info(
                "[%s] Sin tráfico HTTP con el agente, pero SÍ se volcó su "
                "memoria (%s): el criterio del ticket se puede evaluar. %s",
                self.caso, procesos,
                self.auditoria.diagnostico_sin_trafico())
            # A propósito NO se anota nada en el reporte: el caso pasó y el
            # volcado está capturado. La nota anterior («sin tráfico HTTP
            # observable…») aparecía en la evidencia que revisan los analistas
            # y les hacía preguntar por algo que no es el alcance del ticket.
            # Queda en el log, que es donde sirve.
            return
        raise AssertionError(
            f"[{self.caso}] El caso no ejercitó al Hardware Agent de ninguna "
            f"forma: ni se observó tráfico ni se pudo volcar su memoria, así "
            f"que no verifica nada.\n"
            f"  {self.auditoria.diagnostico_sin_trafico()}\n"
            f"  Comprueba el volcado con: python tools/kra1527_volcar.py --estado")


@pytest.fixture(scope="session", autouse=True)
def preflight_kra1527():
    """Mira el estado de la máquina UNA vez, antes de tocar la aplicación."""
    return preflight.estado()


@pytest.fixture(autouse=True)
def exigir_entorno(request):
    """Omite los casos que necesitan el agente cuando el agente no está.

    Vale la pena la distinción: si el proceso no existe, el caso no puede
    opinar sobre el fix y omitirlo es lo honesto — además ahorra los dos
    minutos de flujo que antes se gastaban para fallar al final. Si el proceso
    SÍ existe y no hubo tráfico, eso es un hallazgo y el caso falla."""
    # ── La compuerta del inspector, ANTES que nada ──────────────────────────
    # Se aplica a TODOS los casos, lleven o no el marcador `hardware_agent`:
    # si el detector no detecta, ningún veredicto de esta suite significa
    # nada. Es un `fail`, no un `skip`, y a propósito: un skip se lee como
    # «no aplica» y esto es «no te fíes de nada de lo que salga hoy».
    st = preflight.estado()
    if not st.get("control_ok", True):
        pytest.fail(
            "[Entorno] CONTROL DEL INSPECTOR FALLIDO — la corrida se aborta.\n"
            f"  {st.get('control_motivo')}\n"
            "  El inspector no reconoció un JWT de autenticación plantado a\n"
            "  propósito. Mientras eso siga así, un 'sin token en claro' de\n"
            "  cualquier caso NO prueba que el fix cumpla: prueba que el\n"
            "  detector está ciego.\n"
            "  Para depurar el propio inspector saltando esta compuerta:\n"
            "      $env:KRA1527_SIN_CONTROL=\"1\"",
            pytrace=False)

    if request.node.get_closest_marker("hardware_agent") is None:
        return
    motivo = preflight.motivo_omision()
    if motivo:
        pytest.skip(f"[Entorno] {motivo}")


@pytest.fixture
def vigilancia(logged_page):
    """Devuelve una fábrica: `async with vigilancia('CP01', 'título') as v:`"""
    def _crear(caso: str, titulo: str) -> VigilanciaHA:
        return VigilanciaHA(logged_page, caso, titulo)
    return _crear


@pytest.fixture(scope="session", autouse=True)
def reporte_kra1527():
    """Genera el HTML al terminar y barre los `.DMP` que hayan quedado.

    El acumulado NO se borra al empezar: así se puede estabilizar un caso a la
    vez sin perder los resultados de los otros. Para empezar de cero:
    `python tools/kra1527_reset.py`."""
    if settings.KRA1527_RESET:
        REPORTE.limpiar()
        logger.info("[Reporte] Acumulado borrado por KRA1527_RESET=1.")
    yield
    ruta = REPORTE.generar()
    hallazgos = [d for d in REPORTE.leer() if d.get("veredicto") == "FAIL"]
    logger.info("═" * 70)
    logger.info("REPORTE KRA-1527: %s", ruta)
    if hallazgos:
        logger.warning("⚠ %d caso(s) con TOKEN EN CLARO: %s", len(hallazgos),
                       ", ".join(d["caso"] for d in hallazgos))
        # El resumen de cierre también tiene que distinguir el vector. Decir
        # «es el 5.2.1» cuando el token salió por una URL manda la escalación
        # al sitio equivocado, y este mensaje es el que se lee de un vistazo.
        vectores = sorted({v for d in hallazgos
                           for vol in (d.get("volcados") or [])
                           for v in (vol.get("vector") or [])})
        if vectores == ["url"]:
            logger.warning("  Vector: URL (id_token_hint del logout OIDC). NO "
                           "es el 5.2.1 —que es la cabecera Authorizer, ya "
                           "protegida—: repórtalo como hallazgo NUEVO.")
        elif vectores and set(vectores) <= {"cabecera", "bearer"}:
            logger.warning("  Vector: cabecera de autorización → es el hallazgo "
                           "5.2.1 del pentest: el fix NO está cumpliendo.")
        else:
            logger.warning("  Vector(es): %s. Revisa el contexto del token en "
                           "el reporte antes de escalarlo.",
                           ", ".join(vectores) or "no determinado")
    logger.info("═" * 70)
    # Red de seguridad: si la corrida se cortó antes del caso consolidado,
    # los .DMP seguirían ahí ocupando cientos de MB.
    #
    # Los volcados ANALIZADOS están en la carpeta de evidencia
    # (reports/evidence/KRA-1527/VolcadoMemoriaDMP) y NO se borran aquí: son la
    # evidencia del ticket y la única forma de revisar un detalle a mano sin
    # repetir la transacción completa. Se purgan cuando el ciclo termine, a
    # mano y a conciencia:
    #
    #     python tools/kra1527_volcar.py --purgar
    #
    # Lo que sí se barre de %TEMP% es lo que quedó a medias (un caso que se
    # cortó antes de inspeccionar). Y solo los que empiezan por «CP»: el
    # volcado manual del Administrador de tareas se llama `Hermes2Agent.DMP` y
    # nunca se toca.
    if not settings.KRA1527_CONSERVAR_DMP:
        # RESPALDAR ANTES DE BORRAR. Esta red de seguridad barría las carpetas
        # de paso a saco, y ahí se perdió un volcado real: el archivo se borró
        # del temporal sin haber llegado nunca al repo, y el caso quedó sin el
        # documento que lo sostiene. Ahora lo que se encuentra se trae primero
        # a la carpeta de la etiqueta; solo se borra lo que no se pudo traer.
        for carpeta in {*settings.DUMP_DIRS_CANDIDATAS} - {REPALDO}:
            if not carpeta.exists():
                continue
            sueltos = sorted(set(carpeta.glob("*.dmp")) |
                             set(carpeta.glob("*.DMP")))
            rescatados = 0
            for f in sueltos:
                if not f.name.startswith("CP"):
                    continue        # volcado manual del usuario: no se toca
                if respaldar(f):
                    rescatados += 1
            if rescatados:
                logger.info("[Dump] %d volcado(s) a medias rescatado(s) de %s "
                            "→ %s", rescatados, carpeta, REPALDO)
            n = borrar_volcados(carpeta)
            if n:
                logger.info("[Dump] %d volcado(s) irrecuperable(s) barrido(s) "
                            "de %s.", n, carpeta)
        # La carpeta que se usó antes en %TEMP% ya no hace falta: si quedó
        # vacía, se retira para no dejar rastro fuera del repo.
        temporal = Path(tempfile.gettempdir()) / "kra1527_dumps"
        try:
            if temporal.exists() and not any(temporal.iterdir()):
                temporal.rmdir()
                logger.info("[Dump] Carpeta temporal en desuso eliminada: %s",
                            temporal)
        except Exception:
            pass
    respaldados = sorted(set(REPALDO.glob("*.dmp")) |
                         set(REPALDO.glob("*.DMP"))) if REPALDO.exists() else []
    if respaldados:
        peso = sum(f.stat().st_size for f in respaldados) / 1e9
        logger.info("[Dump] %d volcado(s) guardados para revisión manual "
                    "(%.1f GB) en %s", len(respaldados), peso, REPALDO)
        # Uno por uno, con ruta completa. Sin esto había que fiarse de un
        # recuento: el .DMP está en el repo pero `*.DMP` va en .gitignore —a
        # propósito, son cientos de MB—, así que no aparece en el panel de
        # control de código y es fácil concluir que no se guardó.
        for f in respaldados:
            logger.info("[Dump]   · %s  (%.1f MB)", f, f.stat().st_size / 1e6)
        logger.info("[Dump] Están en disco aunque git los ignore (regla "
                    "`*.DMP`): ábrelos desde el Explorador, no desde el panel "
                    "de cambios.")
        logger.info("[Dump] Cuando cierres el ciclo de los 9 casos: "
                    "python tools/kra1527_volcar.py --purgar")


# ── Orden de ejecución ──────────────────────────────────────────────────────
# Hoy NINGÚN caso necesita una posición fija: los siete son flujos reales e
# independientes entre sí, cada uno captura e inspecciona su propio volcado.
#
# El mecanismo se conserva porque hubo dos inquilinos y podría haber un
# tercero. `ControlNegativo` iba primero —comprobar el detector antes de
# gastar media hora de flujos— y ahora es una compuerta del preflight, que
# corre antes que cualquier caso y además puede abortar. `InspeccionConsolidada`
# iba al final y se eliminó por duplicar hallazgos.
_PRIMEROS = ()
_ULTIMOS = ()


def pytest_collection_modifyitems(session, config, items):
    def rango(item) -> int:
        nombre = item.nodeid
        if any(c in nombre for c in _PRIMEROS):
            return 0
        if any(c in nombre for c in _ULTIMOS):
            return 2
        return 1

    # Solo se reordenan los casos de ESTA etiqueta: `items` puede traer los
    # tests de todo el proyecto cuando se corre `pytest` sin ruta.
    mios = [i for i in items if "KRA_1527" in i.nodeid]
    if len(mios) < 2:
        return
    posiciones = [items.index(i) for i in mios]
    for pos, item in zip(posiciones, sorted(mios, key=rango)):
        items[pos] = item
