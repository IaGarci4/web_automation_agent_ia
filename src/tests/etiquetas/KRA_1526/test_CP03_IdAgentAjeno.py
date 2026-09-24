"""
CP03 — IdAgent ajeno en la búsqueda global → HTTP 403 y SIN datos (mono-agente).

Se cambia SOLO el IdAgent por uno ajeno, dejando el IdUser propio. Para un
usuario MONO-AGENTE el middleware valida también el IdAgent, así que debe
rechazar (403). (El caso multi-agente, donde esto respondería 200 por diseño,
quedó fuera de alcance.)
"""

import pytest

from . import parametros as P
from .flujos import idor_api as API

pytestmark = [pytest.mark.etiqueta, pytest.mark.idor]


@pytest.mark.caso_kra1526(P.CP03, "IdAgent ajeno en la búsqueda global es "
                                  "rechazado (403) — mono-agente")
def test_CP03_idagent_ajeno(caso, baseline):
    r = API.replay_busqueda(baseline, {"IdAgent": P.ID_AGENT_AJENO})
    ev = caso.evi.http("idagent_ajeno", url=r.url,
                       peticion={"IdUser": baseline.id_user,
                                 "IdAgent": P.ID_AGENT_AJENO},
                       respuesta=r.body or r.texto[:800],
                       estado=r.status, ms=r.ms, paso=1,
                       modificado=f"IdAgent = {P.ID_AGENT_AJENO} (ajeno); "
                                  f"IdUser propio ({baseline.id_user}) sin tocar")

    resultado, detalle = API.veredicto_idor(r, baseline.resp_body, "un IdAgent ajeno (mono-agente)")
    caso.paso("La API rechaza el IdAgent ajeno sin filtrar datos", resultado,
              detalle + f" · MODIFICADO: IdAgent={P.ID_AGENT_AJENO}.", ev)
    caso.anotar("Alcance: mono-agente. En multi-agente el IdAgent no se valida "
                "(200 por diseño), fuera de esta prueba.")
    caso.exigir()
