"""
Comprobaciones de entorno de TRN-239, una vez por corrida.

Dos preguntas, y las dos se contestan en segundos:

  1. **¿Responde la API?** Si el gateway no contesta, los ocho casos van a
     fallar por lo mismo y ninguno de esos fallos dice nada del ticket. Se
     omiten con el motivo, igual que la etiqueta KRA-1527 hace cuando el
     Hardware Agent no está corriendo.
  2. **¿Hay base de datos?** Aquí NO se omite nada: sin BD los casos siguen
     corriendo y validan lo que la API contesta; lo que no pueden es afirmar
     integridad, y eso queda como *no verificado* en el reporte.

La distinción es deliberada. «No pude probarlo» y «lo probé y falla» son
resultados distintos, y colapsarlos es la forma más fácil de entregar un
informe que miente.
"""

from __future__ import annotations

from config.logger import get_logger
from src.helpers import sql_helper

from . import parametros as P
from .flujos import lunex_api as API

logger = get_logger("TRN-239.preflight")

_cache = None


def estado() -> dict:
    global _cache
    if _cache is not None:
        return _cache

    salud = API.healthcheck()
    st = {
        "base_url": P.BASE_URL,
        # ── Dos preguntas distintas, y confundirlas cuesta caro ─────────────
        # `hubo_respuesta`: ¿el host contestó ALGO? Un 404 es una respuesta:
        #   el DNS resolvió, la conexión se abrió y el servidor dijo «esa ruta
        #   no existe». Eso NO es la API caída ni la VPN abajo — con la VPN
        #   abajo no hay respuesta, hay timeout (estado 0).
        # `healthcheck_ok`: ¿existe además el endpoint de salud?
        #
        # La primera versión colapsaba las dos en `estado == 200` y omitía los
        # ocho casos por un 404 del healthcheck, culpando a la VPN. Los otros
        # siete casos usan endpoints DISTINTOS y podían haber corrido.
        "hubo_respuesta": salud.estado > 0,
        "healthcheck_ok": salud.estado == 200,
        "api_detalle": salud.resumen(),
        "salud": salud.cuerpo,
        # 'UP' | 'DEGRADED' | '' — el requerimiento de TRN-569.
        "salud_estado": str(salud.cuerpo.get("status", "")).upper(),
        "salud_bd": str(
            (salud.cuerpo.get("parts", {}) or {}).get("database", {})
            .get("status", "")).upper(),
        "bd_descripcion": sql_helper.describir(),
        "bd_motivo": sql_helper.motivo_sin_conexion(),
        "validar_bd": P.VALIDAR_BD,
    }
    # Las rutas que de verdad usan los casos. El healthcheck es informativo;
    # esto es lo que decide si hay algo que probar.
    st["endpoints"] = endpoints_publicados() if st["hubo_respuesta"] else {}

    logger.info("─" * 66)
    logger.info("[Preflight] API Lunex: %s", P.BASE_URL)
    logger.info("[Preflight] Healthcheck: %s", st["api_detalle"])
    for ruta, (estado_r, existe) in (st["endpoints"] or {}).items():
        logger.info("[Preflight] %-32s → HTTP %s · %s", ruta, estado_r,
                    "publicado" if existe else "NO publicado")
    if st["salud_estado"]:
        logger.info("[Preflight] status=%s · database=%s",
                    st["salud_estado"], st["salud_bd"] or "?")
    logger.info("[Preflight] Validación en BD: %s",
                st["bd_descripcion"] if P.VALIDAR_BD
                else "DESACTIVADA (TRN239_VALIDAR_BD=0)")
    logger.info("─" * 66)

    if not st["hubo_respuesta"]:
        logger.error(
            "[Preflight] No hubo NINGUNA respuesta de %s (%s). El host no "
            "resolvió o la conexión no se abrió: revisa la VPN. Para apuntar "
            "a otra base: $env:TRN239_BASE_URL=\"...\"",
            P.BASE_URL, salud.error or "sin detalle")
    elif not st["healthcheck_ok"]:
        # El servidor contestó, así que hay red y hay host. Lo que falta es
        # la RUTA. Se prueban las variantes habituales para dar un diagnóstico
        # concreto en vez de mandar a mirar la VPN, que es lo único que
        # seguro NO es.
        st["health_candidatos"] = _probar_rutas_salud()
        acertadas = [r for r, e in st["health_candidatos"] if e == 200]
        logger.warning(
            "[Preflight] El host RESPONDE pero %s devolvió HTTP %s. No es la "
            "VPN: con la VPN caída no habría respuesta. Falta la ruta.",
            P.BASE_URL + P.RUTA_HEALTH, salud.estado)
        for ruta, estado_r in st["health_candidatos"]:
            logger.info("[Preflight]   %-46s → %s", ruta, estado_r or "sin respuesta")
        if acertadas:
            logger.warning(
                "[Preflight] Esta SÍ responde 200: %s. Ajusta TRN239_RUTA_HEALTH "
                "o confirma con DEV cuál es la buena.", acertadas[0])
        else:
            logger.warning(
                "[Preflight] Ninguna variante respondió 200. Confirma con DEV "
                "la ruta del healthcheck de TRN-569; el resto de casos usan "
                "endpoints distintos y se intentan igual.")
    elif st["salud_estado"] == "DEGRADED":
        logger.warning(
            "[Preflight] El servicio responde pero está DEGRADED "
            "(database=%s). Las altas pueden aceptarse y no persistir: "
            "cualquier caso de integridad hay que leerlo con eso en mente.",
            st["salud_bd"] or "?")
    if P.VALIDAR_BD and st["bd_motivo"]:
        logger.warning("[Preflight] Sin validación de integridad: %s.",
                       st["bd_motivo"])

    _cache = st
    return st


def _probar_rutas_salud() -> list:
    """Prueba las rutas donde suele vivir un healthcheck. [(ruta, estado)].

    Existe para que el fallo diga DÓNDE mirar. Un 404 sin más deja a quien lo
    lee eligiendo entre la VPN, el host, el puerto y la ruta; esta lista
    descarta tres de las cuatro en dos segundos.
    """
    from urllib.parse import urljoin
    raiz = P.BASE_URL
    candidatas = [
        raiz + "healthcheck",
        raiz + "health",
        raiz + "api/healthcheck",
        raiz + "api/v1/healthcheck",
        raiz + "Payments/healthcheck",
        urljoin(raiz, "/healthcheck"),
    ]
    fuera = []
    for ruta in dict.fromkeys(candidatas):
        r = API.get(ruta)
        fuera.append((ruta, r.estado))
    return fuera


def endpoints_publicados() -> dict:
    """¿Existen las rutas de Payments? `{ruta: (estado, existe)}`.

    Se sondea con **GET**, no con POST, y eso es deliberado: un POST a
    RegisterTransaction daría de alta una transacción real en TEST solo por
    averiguar si la ruta existe. El GET no escribe nada y responde igual de
    claro:

        405 Method Not Allowed  →  la ruta EXISTE (solo que no acepta GET)
        404 Not Found           →  la ruta NO está publicada

    Ese 405 es la prueba positiva que faltaba. Sin él, la etiqueta no podía
    distinguir «la API rechazó mi petición» de «no hay API», y esa confusión
    fue la que hizo pasar los casos negativos en la primera corrida.
    """
    fuera = {}
    for ruta in (P.RUTA_REGISTER, P.RUTA_CANCEL):
        r = API.get(P.BASE_URL + ruta)
        # 405 cuenta como publicado: el método no vale, la ruta sí.
        existe = r.estado == 405 or (r.estado not in (0, 404, 501, 502, 503, 504))
        fuera[ruta] = (r.estado, existe)
    return fuera


def motivo_omision() -> str:
    """Por qué omitir los casos. '' si hay algo que probar de verdad.

    Se omite en dos situaciones, y las dos significan «aquí no hay API»:

      1. **Ni una respuesta** — host que no resuelve, conexión que no abre.
      2. **Las rutas de Payments no están publicadas.** Este es el caso que
         costó la primera corrida: con todo en 404, seis casos fallaron por
         la misma causa y dos *aprobaron* comprobando que un servidor
         ausente «rechaza» peticiones. Omitir es lo honesto — un rojo o un
         verde sobre un endpoint que no existe dicen lo mismo: nada.

    El healthcheck en 404 NO omite: es un hallazgo del CP01 sobre el
    requerimiento de TRN-569, y el resto de casos usa rutas distintas.
    """
    st = estado()
    if not st["hubo_respuesta"]:
        return (f"no hubo respuesta de {P.BASE_URL} ({st['api_detalle']}). "
                f"El host no resolvió o la conexión no se abrió: comprueba la "
                f"VPN y el host con DEV.")

    publicados = st.get("endpoints") or {}
    ausentes = [ruta for ruta, (_, existe) in publicados.items() if not existe]
    if ausentes and len(ausentes) == len(publicados):
        detalle = " · ".join(f"{ruta}→{est}"
                             for ruta, (est, _) in publicados.items())
        return (
            f"la API Lunex NO está publicada en {P.BASE_URL}. Ninguna ruta de "
            f"Payments existe ({detalle}), y el host contesta, así que no es "
            f"la VPN.\n"
            f"    Probablemente el despliegue (OR-960) todavía no está en "
            f"TEST, o la base es otra.\n"
            f"    Confirma la base con DEV y apúntala con:\n"
            f"        $env:TRN239_BASE_URL=\"https://host/ruta/\"\n"
            f"    Se OMITE en vez de fallar porque sobre un endpoint ausente "
            f"ningún veredicto significa nada — ni el rojo ni el verde.")
    return ""


def _resumen_consola() -> int:
    """`python -m src.tests.etiquetas.TRN_239.preflight`

    Corre las comprobaciones y las imprime. Vale la pena tenerlo suelto: son
    dos segundos, y saber si hay API antes de lanzar los ocho casos cambia
    cómo se lee todo lo que venga después.

    Devuelve 0 si hay algo que probar, 1 si no.
    """
    st = estado()
    motivo = motivo_omision()

    def marca(ok):
        return "OK " if ok else "-- "

    print()
    print("═" * 74)
    print("  TRN-239 · Preflight")
    print("═" * 74)
    print(f"  API          : {P.BASE_URL}")
    print(f"  {marca(st['hubo_respuesta'])}Respuesta   : {st['api_detalle']}")
    print(f"  {marca(st['healthcheck_ok'])}Healthcheck : "
          f"{'200' if st['healthcheck_ok'] else 'no responde 200'}"
          + (f" · status={st['salud_estado']}" if st["salud_estado"] else ""))
    for ruta, (est, existe) in (st.get("endpoints") or {}).items():
        print(f"  {marca(existe)}{ruta:<34} HTTP {est}")
    print(f"  {marca(not st['bd_motivo'] and st['validar_bd'])}"
          f"Base de datos: "
          + (st["bd_descripcion"] if st["validar_bd"]
             else "DESACTIVADA (TRN239_VALIDAR_BD=0)")
          + (f" · {st['bd_motivo']}" if st["bd_motivo"] else ""))
    print("─" * 74)
    if motivo:
        print("  SE OMITEN LOS CASOS:")
        print("  " + motivo.replace("\n", "\n  "))
        print("═" * 74)
        return 1
    print("  Hay API. Los casos pueden correr.")
    print("═" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(_resumen_consola())
