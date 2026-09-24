"""
Fixtures de KRA-1526 — etiqueta de autorización IDOR.

Misma forma que TRN-239 (fixture `caso` que se guarda solo, reporte acumulado al
final), pero SIN pegar curl: una única captura EN VIVO al inicio de la corrida
da el token y los IdUser/IdAgent propios que todos los casos reutilizan.

  · `baseline` (session): login + búsqueda real del teléfono de prueba → Baseline.
  · `caso`     (function): un `Caso` ya nombrado por el marcador `caso_kra1526`.
  · gate: si la captura falló por ENTORNO (sesión/VPN), los casos se OMITEN
    (skip), no se marcan FALLA — un entorno caído no dice nada del middleware.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from config.logger import get_logger
from src.helpers import reporte_kra1526 as REPORTE

from . import parametros as P
from .flujos import Evidencia
from .flujos import captura

logger = get_logger("KRA-1526")


class Caso:
    """Acumula los pasos de un caso y emite su veredicto (PASS/FAIL)."""

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
        (logger.info if veredicto == "PASS" else logger.warning)(
            "[%s] %s · %s%s", self.cp, nombre, veredicto,
            f" — {detalle}" if detalle else "")
        return resultado is True

    def anotar(self, texto: str) -> None:
        self.notas = f"{self.notas} · {texto}".strip(" ·")

    @property
    def veredicto(self) -> str:
        return REPORTE.peor([p["veredicto"] for p in self.pasos])

    def guardar(self) -> None:
        # Sin pasos no hay nada que reportar (caso omitido/skip): no se registra
        # un caso vacío para no ensuciar el reporte.
        if not self.pasos:
            return
        REPORTE.registrar(P, self.cp, self.titulo, self.veredicto,
                          subticket=P.SUBTICKETS.get(self.cp, ""),
                          pasos=self.pasos, notas=self.notas)

    def exigir(self) -> None:
        fallos = [p for p in self.pasos if p["veredicto"] == "FAIL"]
        if not fallos:
            return
        detalle = "\n".join(f"    · {p['nombre']}: {p['detalle']}"
                            for p in fallos)
        raise AssertionError(
            f"[{self.cp}] {len(fallos)} paso(s) fallaron:\n{detalle}\n"
            f"  Reporte: {P.REPORTE}")


@pytest_asyncio.fixture(scope="session")
async def baseline():
    """Captura UNA vez el request real de la búsqueda global (token + IDs)."""
    logger.info("═" * 70)
    logger.info("[KRA-1526] Capturando baseline de la búsqueda global "
                "(login + búsqueda del teléfono %s)…", P.TELEFONO_PRUEBA)
    base = await captura.capturar_baseline()
    if base.valido():
        logger.info("[KRA-1526] Baseline capturado. El navegador se CIERRA aquí; "
                    "CP02–CP07 corren por REPLAY HTTP (sin navegador, es normal "
                    "no verlo abierto).")
    logger.info("═" * 70)
    return base


@pytest.fixture(autouse=True)
def _gate(request):
    """Omite los casos MONO (`idor`) si la captura falló por entorno.

    Pide `baseline` de forma PEREZOSA (solo si el test lo necesita) para que un
    run SOLO multi (`-m idor_multi`) NO dispare la captura mono. Sin URL o sin
    token no hay nada que reproducir: es sesión/VPN, no un resultado — `skip`.
    """
    if request.node.get_closest_marker("idor") is None:
        return
    base = request.getfixturevalue("baseline")
    if not base.url or not base.token:
        pytest.skip("[Entorno] No se pudo capturar la búsqueda global "
                    "(¿sesión de Hermes / VPN?). No se probó el middleware.")
    if base.resp_status == 401:
        pytest.skip("[Entorno] La búsqueda respondió 401 — token vencido. "
                    "Reintenta (se toma uno fresco por corrida).")


@pytest_asyncio.fixture(scope="session")
async def baseline_multi():
    """Captura el baseline MULTI-AGENTE en la agencia 0040 (solo si está activo).

    Si KRA1526_MULTI no está activo, devuelve un Baseline vacío SIN abrir
    navegador — los casos multi se omiten en el gate de su propio archivo.
    """
    from . import parametros as _P
    if not _P.MULTI:
        return captura.Baseline()
    logger.info("═" * 70)
    logger.info("[KRA-1526·multi] Capturando baseline en la agencia %s "
                "(login multiagente + búsqueda del teléfono %s)…",
                _P.AGENCY_MULTI, _P.TELEFONO_PRUEBA)
    base = await captura.capturar_baseline(perfil="multi", agency=_P.AGENCY_MULTI)
    if base.valido():
        logger.info("[KRA-1526·multi] Baseline capturado. El navegador se cierra; "
                    "CP08/CP09 corren por replay HTTP.")
    logger.info("═" * 70)
    return base


@pytest.fixture(autouse=True)
def _gate_multi(request):
    """Omite los casos MULTI (`idor_multi`) si no está activo o si la captura
    multi falló por entorno."""
    if request.node.get_closest_marker("idor_multi") is None:
        return
    if not P.MULTI:
        pytest.skip("[Multi] Desactivado. Actívalo con KRA1526_MULTI=1 "
                    "(corre en la agencia 0040; requiere credenciales multiagente).")
    base = request.getfixturevalue("baseline_multi")
    if not base.url or not base.token:
        pytest.skip("[Entorno·multi] No se pudo capturar la búsqueda global en "
                    f"la agencia {P.AGENCY_MULTI} (¿credenciales multiagente / "
                    "selección de agencia / VPN?).")
    if base.resp_status == 401:
        pytest.skip("[Entorno·multi] La búsqueda respondió 401 — token vencido. "
                    "Reintenta.")


@pytest.fixture
def caso(request):
    marca = request.node.get_closest_marker("caso_kra1526")
    cp = marca.args[0] if marca else request.node.name
    titulo = marca.args[1] if marca and len(marca.args) > 1 else ""
    c = Caso(cp, titulo)
    try:
        yield c
    finally:
        c.guardar()


@pytest.fixture(scope="session", autouse=True)
def reporte_kra1526():
    """Genera el HTML al terminar la corrida."""
    yield
    ruta = REPORTE.generar(P)
    datos = REPORTE.leer(P)
    fallos = [d["caso"] for d in datos if d.get("veredicto") == "FAIL"]
    logger.info("═" * 70)
    logger.info("REPORTE KRA-1526: %s", ruta)
    if fallos:
        logger.warning("⚠ %d caso(s) con FALLA: %s", len(fallos), ", ".join(fallos))
    else:
        logger.info("Todos los casos ejecutados en OK.")
    logger.info("═" * 70)
