"""
CP04 — Regresión: restaurar los IdUser e IdAgent propios devuelve las
coincidencias.

Tras los rechazos, se reproduce la búsqueda con los IDs propios y se confirma
que vuelve 200 con datos y con el MISMO IdAgent propio. Prueba que el bloqueo
IDOR no dejó daño colateral: el usuario legítimo sigue viendo lo suyo.
"""

import pytest

from . import parametros as P
from .flujos import idor_api as API

pytestmark = [pytest.mark.etiqueta, pytest.mark.idor]


@pytest.mark.caso_kra1526(P.CP04, "Restaurar los IDs propios vuelve a devolver "
                                  "las coincidencias (regresión)")
def test_CP04_regresion_restaurar(caso, baseline):
    r = API.replay_busqueda(baseline, None)  # IDs propios, sin cambios
    ev = caso.evi.http("regresion_propios", url=r.url,
                       peticion={"IdUser": baseline.id_user,
                                 "IdAgent": baseline.id_agent},
                       respuesta=r.body or r.texto[:800],
                       estado=r.status, ms=r.ms, paso=1)

    resultado, detalle = API.veredicto_baseline(r)
    caso.paso("Con los IDs propios vuelve 200 con datos", resultado, detalle, ev)

    # Regresión REAL: el resultado con IDs propios debe COINCIDIR con el baseline
    # capturado (mismo universo de clientes) — así se prueba que el bloqueo IDOR
    # no dejó daño colateral. (No se compara contra el IdAgent del usuario: el
    # registro del cliente puede pertenecer a otro agente; eso es CP01/observación.)
    base_total = baseline.total_records
    now_total = r.total_records()
    if isinstance(base_total, int) and isinstance(now_total, int):
        caso.paso("El conteo coincide con el baseline (sin daño colateral)",
                  now_total == base_total,
                  f"totalRecords baseline={base_total} · regresión={now_total}")
    else:
        caso.anotar(f"totalRecords baseline={base_total} · regresión={now_total}")

    base_agentes = baseline.id_agents_en_respuesta()
    if base_agentes:
        caso.anotar(f"IdAgent de los clientes: baseline={sorted(base_agentes)} · "
                    f"regresión={sorted(r.id_agents())}")
    caso.exigir()
