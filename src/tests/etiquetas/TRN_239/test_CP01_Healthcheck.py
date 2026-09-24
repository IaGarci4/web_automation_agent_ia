"""
CP01-Healthcheck — ¿el servicio está arriba y ve su base de datos? (TRN-569)

El endpoint devuelve el estado del servicio **y el de su BD por separado**.
Lo que TRN-569 documenta y lo que la API devuelve NO coinciden en los nombres,
y por eso este caso acepta las dos formas:

    documentado (TRN-569)   { "status": "UP|DEGRADED",
                              "parts":   { "database": { "status": "OK|DOWN",
                                                         "error": "timeout" }}}

    real (14-sep-2026)      { "status": "UP", "uptime": 540445,
                              "details": { "database": { "status": "UP",
                                                         "latencyMs": 7 }}}

Esa separación es el valor del caso. Una base caída con el servicio «UP»
significa que la API contesta pero no persiste — y una alta que responde
`Errorcode: 0` sin guardar nada es el peor resultado posible en una migración
de datos. Por eso el healthcheck va primero: da contexto a todo lo demás.

El desajuste de nombres (`details`/`UP` en vez de `parts`/`OK`) NO hace fallar
el caso: la base está arriba, que es lo que importa. Se reporta como una
anotación —un hallazgo de requerimiento para DEV— no como un defecto de servicio.

Consolida los CP01 y CP02 de la guía (BD arriba y BD abajo). No se desconecta
la VPN desde el test: se lee el estado real y se juzga en consecuencia.
"""

import pytest

from config.logger import get_logger

from . import parametros as P
from . import preflight
from .flujos import lunex_api as API

logger = get_logger("TRN-239")


@pytest.mark.etiqueta
@pytest.mark.api_lunex
@pytest.mark.caso_trn239(P.CP01, "Healthcheck del servicio y de su base de datos")
def test_CP01_Healthcheck(caso):
    r = API.healthcheck()
    ev = caso.evi.http("healthcheck", url=r.url, estado=r.estado,
                       respuesta=r.cuerpo or r.texto[:500], ms=r.ms, paso=1)

    if r.estado == 404:
        # 404 no es «el servicio está caído»: es «esa ruta no existe ahí». El
        # host contestó. Es un hallazgo sobre el REQUERIMIENTO de TRN-569, y no
        # tiene por qué arrastrar al resto de la corrida.
        candidatos = preflight.estado().get("health_candidatos") or []
        acertadas = [ruta for ruta, est in candidatos if est == 200]
        caso.paso(
            "El endpoint de salud existe en la ruta documentada", False,
            f"{r.url} devolvió 404. El host RESPONDE —no es la VPN—, pero esa "
            f"ruta no está publicada. "
            + (f"Sí responde 200: {acertadas[0]} (ajusta TRN239_RUTA_HEALTH)."
               if acertadas else
               "Ninguna variante habitual respondió 200; confirma la ruta con "
               "DEV."), ev)
        # Se recorta la base para que la anotación quepa y se lean las rutas,
        # que es lo que se está comparando. Antes recortaba por '/Argo/', que
        # era la base equivocada: desde que la buena es zeus-services, ese
        # rsplit no encontraba nada y salían las URL enteras.
        caso.anotar(
            "Rutas tanteadas: "
            + " · ".join(f"{(ruta.split(P.BASE_URL, 1)[-1] or '/') if ruta.startswith(P.BASE_URL) else ruta}"
                         f"→{est or 'sin respuesta'}"
                         for ruta, est in candidatos))
        caso.exigir()
        return

    # El healthcheck no es una transacción: no tiene Errorcode ni Error_text,
    # así que no se usa r.resumen() (mostraba «Errorcode=None»). Se arma un
    # detalle propio con lo que sí trae.
    caso.paso("El endpoint responde", r.estado == 200,
              f"HTTP {r.estado} · version={r.cuerpo.get('version', '?')} · "
              f"{r.ms} ms", ev)
    if r.estado != 200:
        caso.anotar("Sin respuesta del healthcheck no se puede afirmar nada "
                    "del resto de la corrida.")
        caso.exigir()
        return

    estado_svc = str(r.cuerpo.get("status", "")).upper()

    # El desglose de la BD vive bajo `details` (real) o `parts` (documentado en
    # TRN-569). Se prueban los dos: buscar solo uno era la causa del falso
    # FALLA — la API SÍ trae el estado, pero en `details`, y el caso lo daba
    # por ausente.
    contenedor_usado = ""
    bd_info = {}
    for llave in ("details", "parts"):
        cont = r.cuerpo.get(llave, {}) or {}
        if isinstance(cont, dict) and cont.get("database"):
            bd_info = cont.get("database", {}) or {}
            contenedor_usado = llave
            break

    estado_bd = str(bd_info.get("status", "")).upper()
    error_bd = bd_info.get("error", "")
    latencia_bd = bd_info.get("latencyMs")
    # La BD está sana con 'UP' (real) o 'OK' (documentado); caída con cualquier
    # otro valor no vacío.
    bd_sana = estado_bd in ("UP", "OK")
    bd_caida = bool(estado_bd) and not bd_sana

    caso.paso("El requerimiento trae `status`", bool(estado_svc),
              f"status={estado_svc or '(ausente)'}")

    # El desglose de la BD es lo que distingue este healthcheck de un ping. Sin
    # él no se puede saber si la API persiste, que es justo el escenario
    # peligroso: contestar Errorcode 0 con la base caída.
    if estado_bd:
        detalle_bd = f"database={estado_bd} (en `{contenedor_usado}`)"
        if latencia_bd is not None:
            detalle_bd += f" · latencyMs={latencia_bd}"
        if error_bd:
            detalle_bd += f" · error={error_bd}"
        caso.paso("El requerimiento desglosa el estado de la base", True, detalle_bd)
        if contenedor_usado != "parts" or estado_bd not in ("OK", "DOWN"):
            # Sana pero con nombres distintos a los del ticket: hallazgo de
            # requerimiento, no defecto. Se anota para DEV sin tumbar el caso.
            caso.anotar(
                f"Hallazgo de requerimiento (TRN-569): el healthcheck documenta "
                f"`parts.database.status` con valores OK/DOWN, pero la API "
                f"devuelve `{contenedor_usado}.database.status`={estado_bd}. "
                f"Funciona igual; conviene alinear la documentación o el "
                f"requerimiento.")
    else:
        caso.paso(
            "El requerimiento desglosa el estado de la base", None,
            f"la respuesta NO trae el estado de la BD ni en `details` ni en "
            f"`parts`. Claves recibidas: {sorted(r.cuerpo.keys()) or '(ninguna)'}. "
            f"Sin ese desglose el healthcheck no distingue «vivo» de «vivo pero "
            f"sin base de datos».")

    # ── Veredicto del servicio ──────────────────────────────────────────────
    # Estado del servicio y estado de la base son dos lecturas distintas y se
    # juzgan por separado.
    if estado_svc == "UP":
        if bd_sana:
            caso.paso("Servicio y BD operativos", True,
                      f"status=UP · database={estado_bd} · "
                      f"uptime={r.cuerpo.get('uptime')}")
        elif bd_caida:
            caso.paso("Servicio y BD operativos", False,
                      f"status=UP pero database={estado_bd} {error_bd}: la API "
                      f"se declara sana con la base caída.")
        else:
            caso.paso("Servicio y BD operativos", None,
                      f"status=UP · el estado de la base NO viene en la "
                      f"respuesta, así que no se puede afirmar que persista. "
                      f"uptime={r.cuerpo.get('uptime')}")
    elif estado_svc == "DEGRADED":
        caso.paso("Servicio DEGRADED", None,
                  f"database={estado_bd or '?'} {error_bd}. La API responde "
                  f"pero puede no persistir: los casos de integridad de esta "
                  f"corrida hay que leerlos con esto delante.")
        caso.anotar("Healthcheck DEGRADED — comprueba la VPN y el acceso a BD.")
    else:
        caso.paso("Estado reconocible", False,
                  f"status='{estado_svc or '(vacío)'}' no es UP ni DEGRADED; "
                  f"el requerimiento de TRN-569 solo documenta esos dos.")

    caso.exigir()
