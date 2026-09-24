"""
CP02 — IdUser ajeno en la búsqueda global → HTTP 403 y SIN datos.

El núcleo del pentesting IDOR: se reproduce el MISMO request cambiando SOLO el
IdUser por uno ajeno. El middleware debe rechazar (403) y no filtrar clientes.
Si devuelve datos, es la fuga que el ticket vino a cerrar.
"""

import pytest

from . import parametros as P
from .flujos import idor_api as API

pytestmark = [pytest.mark.etiqueta, pytest.mark.idor]


@pytest.mark.caso_kra1526(P.CP02, "IdUser ajeno en la búsqueda global es "
                                  "rechazado (403) y no filtra datos")
def test_CP02_iduser_ajeno(caso, baseline):
    r = API.replay_busqueda(baseline, {"IdUser": P.ID_USER_AJENO})
    ev = caso.evi.http("iduser_ajeno", url=r.url,
                       peticion={"IdUser": P.ID_USER_AJENO,
                                 "IdAgent": baseline.id_agent},
                       respuesta=r.body or r.texto[:800],
                       estado=r.status, ms=r.ms, paso=1,
                       modificado=f"IdUser = {P.ID_USER_AJENO} (ajeno); "
                                  f"IdAgent propio ({baseline.id_agent}) sin tocar")

    resultado, detalle = API.veredicto_idor(r, baseline.resp_body, "un IdUser ajeno")
    caso.paso("La API rechaza el IdUser ajeno sin filtrar datos", resultado,
              detalle + f" · MODIFICADO: IdUser={P.ID_USER_AJENO}.", ev)
    caso.exigir()
