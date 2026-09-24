"""
Fixtures de TRN-239.

Esta etiqueta no abre navegador: no hay `logged_page`, no hay sesión de
Hermes, no hay capturas. Lo que comparte con las demás es la forma —
preflight, evidencia por caso, reporte acumulado— para que quien ya conoce
KRA-1527 sepa leerla sin explicación.

## `caso` — la fixture que hace el trabajo

Cada test pide `caso` y recibe un objeto que sabe registrar pasos y, al
terminar, escribe el resultado en el reporte. Así el test se lee como la
prueba y no como la contabilidad:

    def test_CP01_Healthcheck(caso):
        r = API.healthcheck()
        caso.paso("healthcheck", r.estado == 200, r.resumen())
        caso.exigir()
"""

from __future__ import annotations

import pytest

from config.logger import get_logger
from src.helpers import reporte_trn239 as REPORTE

from . import parametros as P
from . import preflight
from .flujos import Evidencia
from .flujos import bd as BD
from .flujos import bodies as B

logger = get_logger("TRN-239")


class Caso:
    """Acumula los pasos de un caso y emite su veredicto.

    El reporte solo tiene DOS estados: PASS o FAIL. `paso()` sigue aceptando
    `None` por compatibilidad, pero se colapsa a PASS (con su nota) al pintar.
    Lo que de verdad importa —«no pude validar contra BD»— ya no se esconde
    como un tercer color tibio: se marca FAIL en el propio caso, con el motivo,
    porque sin esa validación la migración no se puede dar por buena.

      · `True`  → PASS
      · `False` → FAIL (el detalle dice por qué; es lo que se revisa)
      · `None`  → PASS con nota (compatibilidad; evítalo en pasos nuevos)
    """

    def __init__(self, cp: str, titulo: str):
        self.cp = cp
        self.titulo = titulo
        self.evi = Evidencia(cp)
        self.pasos = []
        self.notas = ""

    def paso(self, nombre: str, resultado, detalle: str = "",
             evidencia: str = "") -> bool:
        veredicto = ("PASS" if resultado is True
                     else "NO_VERIFICADO" if resultado is None else "FAIL")
        self.pasos.append({"nombre": nombre, "veredicto": veredicto,
                           "detalle": detalle, "evidencia": evidencia})
        registro = (logger.info if veredicto == "PASS"
                    else logger.warning)
        registro("[%s] %s · %s%s", self.cp, nombre, veredicto,
                 f" — {detalle}" if detalle else "")
        return resultado is True

    def anotar(self, texto: str) -> None:
        self.notas = f"{self.notas} · {texto}".strip(" ·")

    @property
    def veredicto(self) -> str:
        return REPORTE.peor([p["veredicto"] for p in self.pasos])

    def guardar(self) -> None:
        REPORTE.registrar(P, self.cp, self.titulo, self.veredicto,
                          subticket=P.SUBTICKETS.get(self.cp, ""),
                          pasos=self.pasos, notas=self.notas)

    def exigir(self) -> None:
        """Falla el test si algún paso falló. NO_VERIFICADO no falla.

        Misma regla que el resto del proyecto: pytest dice si la prueba pudo
        ejecutarse y si lo comprobado salió bien; lo que no se pudo comprobar
        se reporta, no se inventa.
        """
        fallos = [p for p in self.pasos if p["veredicto"] == "FAIL"]
        if not fallos:
            return
        detalle = "\n".join(f"    · {p['nombre']}: {p['detalle']}"
                            for p in fallos)
        raise AssertionError(
            f"[{self.cp}] {len(fallos)} paso(s) fallaron:\n{detalle}\n"
            f"  Reporte: {P.REPORTE}")


@pytest.fixture(scope="session", autouse=True)
def preflight_trn239():
    """Estado del entorno, una vez por corrida."""
    preflight.estado()
    yield


@pytest.fixture(autouse=True)
def exigir_api(request):
    """Omite los casos si la API no responde.

    Es un `skip` y no un `fail` a propósito: que el gateway esté caído o la
    VPN desconectada no dice nada sobre la migración, y ocho rojos idénticos
    solo entierran la señal.
    """
    if request.node.get_closest_marker("api_lunex") is None:
        return
    motivo = preflight.motivo_omision()
    if motivo:
        pytest.skip(f"[Entorno] {motivo}")


@pytest.fixture
def caso(request):
    """Un `Caso` ya nombrado, que se guarda solo al terminar.

    El nombre y el título salen del marcador `caso_trn239` del test, así que
    no hay forma de que el archivo diga CP03 y el reporte CP04.
    """
    marca = request.node.get_closest_marker("caso_trn239")
    cp = marca.args[0] if marca else request.node.name
    titulo = marca.args[1] if marca and len(marca.args) > 1 else ""
    c = Caso(cp, titulo)
    try:
        yield c
    finally:
        c.guardar()


@pytest.fixture(scope="session")
def cnt():
    """Contadores de `Key` y `TransactionID`, compartidos por la corrida."""
    return B.Contadores()


@pytest.fixture(scope="session")
def bd():
    """Conexión a SQL Server, o None. Se abre una vez y se cierra al final."""
    cn = BD.conectar()
    yield cn
    if cn is not None:
        try:
            cn.close()
        except Exception:
            pass


@pytest.fixture(scope="session")
def productos(bd):
    """Catálogo para randomizar: el vivo de `lunex.Product` si hay BD."""
    return BD.productos_activos(bd)


@pytest.fixture(scope="session", autouse=True)
def reporte_trn239():
    """Genera el HTML al terminar la corrida."""
    yield
    ruta = REPORTE.generar(P)
    datos = REPORTE.leer(P)
    fallos = [d["caso"] for d in datos if d.get("veredicto") == "FAIL"]
    logger.info("═" * 70)
    logger.info("REPORTE TRN-239: %s", ruta)
    if fallos:
        logger.warning("⚠ %d caso(s) con FALLA (revisa el motivo en el "
                       "reporte): %s", len(fallos), ", ".join(fallos))
    else:
        logger.info("Todos los casos en OK.")
    logger.info("═" * 70)
