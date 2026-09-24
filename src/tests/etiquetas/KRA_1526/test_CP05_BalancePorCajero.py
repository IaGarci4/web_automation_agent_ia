"""
CP05 [Mono-agente] — Cobertura endpoint Balance por Cajero: IdUser ajeno → 403.

`balance_by_cashier` lleva IdUser E IdAgent, así que es un segundo punto para la
validación IDOR. Mismo flujo que la búsqueda global:
  1. Happy path: balance con IdUser e IdAgent PROPIOS → 200 con datos.
  2. Cambiar SOLO el IdUser por uno ajeno → 403 (o rechazo) sin datos.

100% automático (sin intervención): el endpoint real vive en el host de LAMBDAS
y su auth es el header `authorizer` (JWT sin 'Bearer'). Ambos se resuelven desde
la sesión capturada — el token se toma FRESCO en cada corrida, nunca se
hardcodea. Contrato confirmado con el request real de DevTools.

Para fijar ids/fechas exactos puede definirse KRA1526_BALANCE_URL (una sola vez);
el token igual se inyecta fresco.

QMetry: BM-TC-7449 · KRA-1526 CP05 [Mono-agente].
"""

import re

import pytest

from . import parametros as P
from .flujos import idor_api as API

pytestmark = [pytest.mark.etiqueta, pytest.mark.idor]


def _iduser_de_url(url: str) -> str:
    m = re.search(r"(?i)[?&]idUser=(\d+)", url or "")
    return m.group(1) if m else ""


@pytest.mark.caso_kra1526(P.CP05, "Balance por Cajero rechaza un IdUser ajeno (403)")
def test_CP05_balance_por_cajero(caso, baseline):
    usa_url = bool(P.BALANCE_URL)
    iduser_propio = _iduser_de_url(P.BALANCE_URL) if usa_url else baseline.id_user

    # ── 1) Happy path: balance con IDs propios → 200 ───────────────────────
    if usa_url:
        propios = API.balance_por_cajero(baseline, None, None, url=P.BALANCE_URL)
        caso.anotar("Endpoint fijado por KRA1526_BALANCE_URL (token fresco de sesión).")
    else:
        propios = API.balance_por_cajero(baseline, baseline.id_user, baseline.id_agent)

    caso.evi.http("balance_propios", url=propios.url,
                  peticion={"idUser": iduser_propio, "idAgent": baseline.id_agent,
                            "authorizer": "JWT fresco de la sesión"},
                  respuesta=propios.body or propios.texto[:800],
                  estado=propios.status, ms=propios.ms, paso=1)

    if propios.status != 200:
        caso.paso(
            "Balance por Cajero con IDs propios responde 200", False,
            f"Se esperaba 200 con los IDs propios y respondió HTTP {propios.status}. "
            f"Revisa host/authorizer o fija KRA1526_BALANCE_URL con el request real. "
            f"· {propios.resumen()}")
        caso.exigir()
        return
    caso.paso("Balance por Cajero con IDs propios responde 200", True, propios.resumen())

    # ── 2) IdUser ajeno → debe rechazar (403) sin datos ────────────────────
    if usa_url:
        url_ajeno = API._sub_query(P.BALANCE_URL, "idUser", P.ID_USER_AJENO)
        ajeno = API.balance_por_cajero(baseline, None, None, url=url_ajeno)
    else:
        ajeno = API.balance_por_cajero(baseline, P.ID_USER_AJENO, baseline.id_agent)

    ev = caso.evi.http("balance_iduser_ajeno", url=ajeno.url,
                       peticion={"idUser": P.ID_USER_AJENO, "idAgent": baseline.id_agent},
                       respuesta=ajeno.body or ajeno.texto[:800],
                       estado=ajeno.status, ms=ajeno.ms, paso=2,
                       modificado=f"idUser {iduser_propio} → {P.ID_USER_AJENO} (ajeno)")
    resultado, detalle = API.veredicto_idor(ajeno, propios.body, "un IdUser ajeno en Balance por Cajero")
    caso.paso("Balance por Cajero rechaza el IdUser ajeno", resultado,
              detalle + f" · MODIFICADO: idUser={P.ID_USER_AJENO}.", ev)
    caso.exigir()
