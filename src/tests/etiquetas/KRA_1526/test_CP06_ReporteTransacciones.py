"""
CP06 [Mono-agente] — Cobertura endpoint Reporte de transacciones
(body + isMonoAgent): IdAgent ajeno → 403.

Este endpoint cambia la mecánica: el IdAgent va en el CUERPO JSON, junto al flag
`isMonoAgent`. Cubre el tercer patrón del middleware. Se prueba con el IdAgent
propio (baseline) y luego con uno ajeno → debe rechazar (403).

Preferimos el request CAPTURADO en vivo (al abrir Reportes → Transacciones). Si
no se capturó, se cae a la ruta inferida; si esa no da 200 con el IdAgent propio,
el caso se OMITE con nota.

QMetry: KRA-1526 CP06 [Mono-agente].
"""

import pytest

from . import parametros as P
from .flujos import idor_api as API

pytestmark = [pytest.mark.etiqueta, pytest.mark.idor]


@pytest.mark.caso_kra1526(P.CP06, "Reporte de transacciones rechaza un IdAgent "
                                  "ajeno en el body (403)")
def test_CP06_reporte_transacciones(caso, baseline):
    cap = baseline.extra.get("money_transfers")

    # ── Camino preferente: endpoint CAPTURADO en vivo ──────────────────────
    if cap and cap.get("resp_status") == 200 and cap.get("id_agent"):
        caso.evi.http("mt_propios_capturado", url=cap["url"],
                      peticion={"idAgent": cap.get("id_agent"),
                                "body": cap.get("post_data")},
                      respuesta=cap.get("resp_body"), estado=cap.get("resp_status"),
                      paso=1)
        caso.anotar(f"Endpoint capturado en vivo: {cap['metodo']} {cap['url'][:90]}")

        r = API.replay_capturado(cap, {"IdAgent": P.ID_AGENT_AJENO})
        ev = caso.evi.http("mt_idagent_ajeno", url=r.url,
                           peticion={"idAgent": P.ID_AGENT_AJENO, "body": r.url},
                           respuesta=r.body or r.texto[:800], estado=r.status,
                           ms=r.ms, paso=2,
                           modificado=f"idAgent(body) = {P.ID_AGENT_AJENO} (ajeno)")
        resultado, detalle = API.veredicto_bloqueo(
            r, "un IdAgent ajeno en el body (mono-agente)")
        caso.paso("El reporte rechaza el IdAgent ajeno del body", resultado,
                  detalle + f" · MODIFICADO: idAgent(body)={P.ID_AGENT_AJENO}.", ev)
        caso.exigir()
        return

    # ── Fallback: ruta inferida ────────────────────────────────────────────
    propios = API.reporte_transacciones(baseline, baseline.id_agent, is_mono=True)
    if propios.status != 200:
        pytest.skip(f"[Ruta inferida] {P.RUTA_MONEY_TRANSFERS} no dio 200 con el "
                    f"IdAgent propio (HTTP {propios.status}) y no se capturó el "
                    f"endpoint al abrir el reporte. Confírmala/ajusta y reintenta.")

    caso.evi.http("mt_propios", url=propios.url,
                  peticion={"idAgent": baseline.id_agent, "isMonoAgent": True},
                  respuesta=propios.body or propios.texto[:800],
                  estado=propios.status, ms=propios.ms, paso=1)
    caso.anotar(f"Ruta inferida (no capturada). Reporte propio: {propios.resumen()}")

    ajeno = API.reporte_transacciones(baseline, P.ID_AGENT_AJENO, is_mono=True)
    ev = caso.evi.http("mt_idagent_ajeno", url=ajeno.url,
                       peticion={"idAgent": P.ID_AGENT_AJENO, "isMonoAgent": True},
                       respuesta=ajeno.body or ajeno.texto[:800],
                       estado=ajeno.status, ms=ajeno.ms, paso=2,
                       modificado=f"idAgent(body) = {P.ID_AGENT_AJENO} (ajeno)")
    resultado, detalle = API.veredicto_idor(
        ajeno, propios.body, "un IdAgent ajeno en el body (mono-agente)")
    caso.paso("El reporte rechaza el IdAgent ajeno del body", resultado,
              detalle + f" · MODIFICADO: idAgent(body)={P.ID_AGENT_AJENO}.", ev)
    caso.exigir()
