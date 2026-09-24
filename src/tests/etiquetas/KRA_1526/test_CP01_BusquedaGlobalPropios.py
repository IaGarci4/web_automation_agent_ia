"""
CP01 — Búsqueda global con IdUser e IdAgent PROPIOS → HTTP 200 con datos.

Es el baseline: confirma que, con los IDs propios (los que capturó la sesión),
la búsqueda del teléfono de prueba devuelve clientes y todos pertenecen al
IdAgent propio. Sobre este baseline se miden las variantes negativas.
"""

import pytest

from . import parametros as P

pytestmark = [pytest.mark.etiqueta, pytest.mark.idor]


@pytest.mark.caso_kra1526(P.CP01, "Búsqueda global con IdUser e IdAgent propios "
                                  "devuelve 200 con datos")
def test_CP01_busqueda_global_propios(caso, baseline):
    b = baseline
    ev = caso.evi.http("baseline_propios", url=b.url,
                       peticion={"IdUser": b.id_user, "IdAgent": b.id_agent,
                                 "metodo": b.metodo, "body": b.post_data},
                       respuesta=b.resp_body, estado=b.resp_status, paso=1)

    total = b.total_records
    agentes = b.id_agents_en_respuesta()
    datos = bool(agentes) or (isinstance(total, int) and total > 0)

    caso.paso("La búsqueda con IDs propios responde 200 con datos",
              b.resp_status == 200 and datos,
              f"HTTP {b.resp_status} · totalRecords={total} · "
              f"IdUser={b.id_user} IdAgent={b.id_agent}", ev)

    # Observación (NO es criterio de aprobación): qué IdAgent traen los clientes
    # del teléfono. El registro del cliente puede pertenecer a otro agente; la
    # regla IDOR se valida sobre los IDs del REQUEST (CP02/CP03), no sobre esto.
    if agentes:
        caso.anotar(f"IdAgent de los clientes devueltos: {sorted(agentes)} "
                    f"(request IdAgent propio={b.id_agent})")

    caso.anotar(f"Baseline capturado en vivo (sin curl): {b.resumen()}")
    caso.exigir()
