"""
CP08 — MULTI-AGENTE: IdUser ajeno en la búsqueda global → HTTP 403 y sin datos.

Para un usuario MULTI-AGENTE el IdUser SÍ se valida (igual que en mono). Se
reproduce la búsqueda cambiando SOLO el IdUser por uno ajeno → debe rechazar.

Corre en la agencia 0040 y SOLO si KRA1526_MULTI=1 (ver conftest `_gate_multi`).
Separado del run mono: marcador `idor_multi`, reporte aparte.
"""

import pytest

from . import parametros as P
from .flujos import idor_api as API

pytestmark = [pytest.mark.etiqueta, pytest.mark.idor_multi]


@pytest.mark.caso_kra1526(P.CP08, "Multi-agente: IdUser ajeno es rechazado (403) "
                                  "— el IdUser sí se valida")
def test_CP08_multi_iduser_ajeno(caso, baseline_multi):
    b = baseline_multi
    r = API.replay_busqueda(b, {"IdUser": P.ID_USER_AJENO})
    ev = caso.evi.http("multi_iduser_ajeno", url=r.url,
                       peticion={"IdUser": P.ID_USER_AJENO, "IdAgent": b.id_agent,
                                 "agencia": P.AGENCY_MULTI},
                       respuesta=r.body or r.texto[:800],
                       estado=r.status, ms=r.ms, paso=1,
                       modificado=f"IdUser = {P.ID_USER_AJENO} (ajeno); perfil "
                                  f"multiagente, agencia {P.AGENCY_MULTI}")

    resultado, detalle = API.veredicto_idor(r, b.resp_body, "un IdUser ajeno (multi-agente)")
    caso.paso("La API rechaza el IdUser ajeno también en multi-agente", resultado,
              detalle + f" · MODIFICADO: IdUser={P.ID_USER_AJENO}.", ev)
    caso.anotar(f"Perfil multi-agente, agencia {P.AGENCY_MULTI}. Baseline: {b.resumen()}")
    caso.exigir()
