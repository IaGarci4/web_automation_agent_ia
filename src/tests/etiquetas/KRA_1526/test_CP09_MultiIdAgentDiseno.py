"""
CP09 — MULTI-AGENTE: IdAgent DISTINTO → HTTP 200 (por diseño, NO se valida).

Comportamiento esperado confirmado por DEV (Eduardo López): para un usuario
MULTI-AGENTE el middleware NO valida el IdAgent. Se reproduce la búsqueda
cambiando el IdAgent por otro valor y debe seguir respondiendo 200 con los datos
del usuario (el IdAgent se ignora). Un 403 aquí sería un hallazgo (la regla
cambió).

Corre en la agencia 0040 y SOLO si KRA1526_MULTI=1. Separado del run mono.
"""

import pytest

from . import parametros as P
from .flujos import idor_api as API

pytestmark = [pytest.mark.etiqueta, pytest.mark.idor_multi]


@pytest.mark.caso_kra1526(P.CP09, "Multi-agente: IdAgent distinto responde 200 "
                                  "(por diseño, no se valida)")
def test_CP09_multi_idagent_diseno(caso, baseline_multi):
    b = baseline_multi
    r = API.replay_busqueda(b, {"IdAgent": P.ID_AGENT_DISTINTO})
    ev = caso.evi.http("multi_idagent_distinto", url=r.url,
                       peticion={"IdUser": b.id_user, "IdAgent": P.ID_AGENT_DISTINTO,
                                 "agencia": P.AGENCY_MULTI},
                       respuesta=r.body or r.texto[:800],
                       estado=r.status, ms=r.ms, paso=1,
                       modificado=f"IdAgent = {P.ID_AGENT_DISTINTO} (distinto al de "
                                  f"la agencia {P.AGENCY_MULTI}); IdUser propio")

    resultado, detalle = API.veredicto_disenio_idagent(r)
    caso.paso("Cambiar el IdAgent NO bloquea (200, por diseño multi-agente)",
              resultado, detalle + f" · MODIFICADO: IdAgent={P.ID_AGENT_DISTINTO}.", ev)

    # Refuerzo: si respondió 200, idealmente devuelve el MISMO universo que el
    # baseline (el IdAgent se ignoró de verdad, no cambió el resultado).
    if r.status == 200:
        base_total = b.total_records
        now_total = r.total_records()
        if isinstance(base_total, int) and isinstance(now_total, int):
            caso.anotar(f"IdAgent ignorado: totalRecords baseline={base_total} · "
                        f"con IdAgent distinto={now_total} "
                        f"({'igual' if base_total == now_total else 'DIFERENTE'})")
    caso.anotar(f"Regla DEV: multi-agente valida IdUser, NO IdAgent. "
                f"Agencia {P.AGENCY_MULTI}.")
    caso.exigir()
