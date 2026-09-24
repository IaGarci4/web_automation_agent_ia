"""
Reporte HTML consolidado — KRA-1527.

Junta, en un solo archivo autocontenido y compartible, lo que hoy se prueba a
mano: por cada flujo, si la comunicación con el Hardware Agent ocurrió de
verdad, qué se intercambió, y si el JWT apareció en claro — en el tráfico o en
la memoria de los procesos.

Decisión de diseño importante: el reporte **nunca** escribe un token. Si se
detecta uno, se muestran sus *claims* y su longitud, lo justo para demostrar el
hallazgo sin convertir la evidencia en una nueva filtración.

Los resultados se acumulan en un JSON (`resultados.json`) que cada test va
alimentando; al final se renderiza el HTML. Así el reporte sobrevive aunque un
caso falle a medias.
"""

import html
import json
from datetime import datetime
from pathlib import Path

from config import settings
from config.logger import get_logger

logger = get_logger("kra1527.reporte")

BASE = settings.EVIDENCE_DIR / "KRA-1527"
ACUMULADO = BASE / "resultados.json"
REPORTE = BASE / "reporte_KRA-1527.html"

# Veredictos y cómo se presentan. El orden define la gravedad.
ESTILOS = {
    "FAIL":         ("#b3261e", "#fce8e6", "TOKEN EXPUESTO"),
    "ERROR":        ("#8a4b00", "#fff0e0", "ERROR DE ANÁLISIS"),
    "WARN":         ("#8a6100", "#fff8e1", "REVISAR"),
    "SIN_TRAFICO":  ("#5f6368", "#eceff1", "SIN COMUNICACIÓN"),
    "NO_CAPTURADO": ("#5f6368", "#eceff1", "NO CAPTURADO"),
    "PENDIENTE":    ("#5f6368", "#eceff1", "CAPTURADO, SIN ANALIZAR"),
    "SIN_VOLCADO":  ("#5f6368", "#eceff1", "SIN VOLCADO"),
    "PASS":         ("#0b7a3b", "#e6f4ea", "SIN TOKEN EN CLARO"),
}
GRAVEDAD = ["PASS", "NO_CAPTURADO", "PENDIENTE", "SIN_VOLCADO", "SIN_TRAFICO",
            "WARN", "ERROR", "FAIL"]


def _peor(veredictos) -> str:
    presentes = [v for v in veredictos if v]
    if not presentes:
        return "SIN_TRAFICO"
    return max(presentes, key=lambda v: GRAVEDAD.index(v)
               if v in GRAVEDAD else 0)


# Veredictos que salen de haber ANALIZADO un volcado (no de no haberlo hecho).
_CONCLUYENTES = {"PASS", "WARN", "FAIL", "ERROR"}


def _veredicto_del_caso(auditoria: dict, volcados: list) -> str:
    """Veredicto del caso, dándole el peso que corresponde a cada evidencia.

    El criterio de aceptación del ticket es **el volcado de memoria**. La
    auditoría de tráfico es apoyo: demuestra, además, que el token tampoco viaja
    en claro.

    Antes esto era un simple «el peor de todos», y ahí estaba el ruido: un caso
    con el volcado inspeccionado y LIMPIO se etiquetaba «SIN COMUNICACIÓN»
    porque no se habían visto peticiones HTTP. El reporte gritaba en gris sobre
    un caso que había cumplido, y el veredicto global se contagiaba. Mirar un
    reporte y no poder distinguir «esto está bien» de «esto no se pudo medir» es
    exactamente lo que hace que un reporte deje de leerse.

    Ahora, cuando hay un volcado analizado, se ignora el «no se vio tráfico» —
    que es una limitación de la medición, no un resultado. Lo que **no** se
    ignora nunca es un hallazgo: si la auditoría vio un token en claro en la
    comunicación, eso manda aunque el volcado salga limpio. Silenciar una fuga
    real porque otra evidencia salió bien sería el mismo error, del revés."""
    todos = [(auditoria or {}).get("veredicto")] + \
            [v.get("veredicto") for v in (volcados or [])]
    if any(v in _CONCLUYENTES for v in (x.get("veredicto")
                                        for x in (volcados or []))):
        # Con volcado analizado, los estados «no se pudo medir» dejan de pesar.
        todos = [v for v in todos if v in _CONCLUYENTES]
    return _peor(todos)


def registrar(caso: str, titulo: str, auditoria: dict, volcados: list,
              notas: str = "") -> dict:
    """Acumula el resultado de un flujo. Devuelve la entrada guardada."""
    BASE.mkdir(parents=True, exist_ok=True)
    datos = _leer()
    entrada = {
        "caso": caso,
        "titulo": titulo,
        "cuando": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "auditoria": auditoria or {},
        "volcados": volcados or [],
        "notas": notas,
    }
    entrada["veredicto"] = _veredicto_del_caso(auditoria, volcados)
    datos = [d for d in datos if d.get("caso") != caso] + [entrada]
    ACUMULADO.write_text(json.dumps(datos, indent=2, ensure_ascii=False),
                         encoding="utf-8")
    logger.info("[Reporte] %s registrado → %s", caso, entrada["veredicto"])
    return entrada


def _leer() -> list:
    try:
        return json.loads(ACUMULADO.read_text(encoding="utf-8"))
    except Exception:
        return []


def leer() -> list:
    """Resultados acumulados de la corrida (público: lo usa el caso que
    consolida los volcados para reunir lo que ya dictaminó cada caso)."""
    return _leer()


def limpiar() -> None:
    """Borra el acumulado (para empezar una corrida nueva)."""
    try:
        ACUMULADO.unlink()
    except Exception:
        pass


# ── Render ──────────────────────────────────────────────────────────────────

def _e(t) -> str:
    return html.escape(str(t if t is not None else ""))


def _chip(veredicto: str) -> str:
    color, fondo, texto = ESTILOS.get(veredicto, ESTILOS["WARN"])
    return (f'<span class="chip" style="color:{color};background:{fondo};'
            f'border-color:{color}33">{_e(texto)}</span>')


def _prueba_por_volcado(volcados) -> str:
    """Declara la comunicación con el agente cuando el .DMP la demuestra.

    Por qué: la auditoría HTTP escucha DESDE EL NAVEGADOR. El canal con el
    agente local no siempre pasa por ahí, así que puede ver «0 llamadas» en un
    flujo donde la impresión ocurrió de verdad. El reporte decía entonces «no
    se registró ninguna llamada al Hardware Agent» — una frase falsa sobre una
    prueba correcta, que además invitaba a dudar del resultado.

    La evidencia real es el volcado: se le tomó la memoria al proceso del
    agente, y dentro están sus endpoints de trabajo. Eso es lo que se afirma
    aquí, nombrando el archivo .DMP para que el analista sepa qué abrir.
    """
    capturados = [v for v in (volcados or []) if v.get("capturado")]
    if not capturados:
        return ('<p class="vacio">No se registró ninguna llamada al Hardware '
                'Agent durante este flujo, y tampoco se capturó su memoria: '
                'este caso <b>no aporta evidencia</b> sobre el hallazgo.</p>')

    marcas = []
    for v in capturados:
        marcas.extend(v.get("actividad") or [])
    huella = ("".join(f"<li>{_e(m)}</li>" for m in dict.fromkeys(marcas))
              if marcas else "")

    archivos = "".join(
        f'<li><b class="mono">{_e(v.get("archivo") or "—")}</b> · '
        f'{v.get("tam_mb") or "—"} MB · proceso <span class="mono">'
        f'{_e(v.get("proceso"))}</span> · {_chip(v.get("veredicto", "WARN"))}'
        f'<div class="ruta mono">{_e(v.get("ruta") or "")}</div></li>'
        for v in capturados)

    if marcas:
        encabezado = (
            'Hubo comunicación con el Hardware Agent. No aparece en la tabla '
            'de tráfico porque esa auditoría observa el navegador y el canal '
            'con el agente local no pasa por ahí; la prueba está en su '
            '<b>volcado de memoria</b>, que conserva las rutas de trabajo que '
            'el agente atendió:')
    else:
        encabezado = (
            'Se capturó la memoria del Hardware Agent mientras el flujo lo '
            'ejercitaba. La tabla de tráfico sale vacía porque esa auditoría '
            'observa el navegador y el canal con el agente local no pasa por '
            'ahí; el veredicto se emite sobre el <b>volcado de memoria</b>:')

    return f"""
    <div class="prueba">
      <p>{encabezado}</p>
      {f'<ul class="huella">{huella}</ul>' if huella else ''}
      <p class="etq">Evidencia analizada — archivo <b>.DMP</b>:</p>
      <ul class="dmp">{archivos}</ul>
      <p class="pie">El .DMP es el documento que sostiene el veredicto de este
      caso. Se conserva junto a esta evidencia, en
      <span class="mono">reports/evidence/KRA-1527/VolcadoMemoriaDMP</span>,
      para revisión manual; <b>no se adjunta a QMetry</b>.</p>
    </div>"""


def _tabla_eventos(eventos, volcados=None) -> str:
    if not eventos:
        return _prueba_por_volcado(volcados)
    filas = []
    for ev in eventos[:120]:
        an = ev.get("analisis", {})
        cuerpo = ev.get("cuerpo") or ""
        detalle = ""
        if an.get("jwts"):
            claims = ", ".join(an["jwts"][0].get("claims", [])[:6])
            detalle = (f'<div class="hallazgo">JWT de autenticación · '
                       f'claims: {_e(claims)}</div>')
        elif an.get("fragmentos"):
            # Redactado a propósito en positivo: una cadena «eyJ…» que NO
            # decodifica es la señal de que el dato va protegido, no una
            # sospecha pendiente. Llamarla «posible cifrado» hacía que cada
            # evento normal pareciera merecer una revisión manual.
            detalle = (f'<div class="frag">{an["fragmentos"]} cadena(s) «eyJ…» '
                       f'que no decodifican: dato protegido, sin token legible'
                       f'</div>')
        filas.append(f"""
        <tr>
          <td class="mono">{_e(ev.get('hora'))}</td>
          <td>{_e(ev.get('tipo'))} {_e(ev.get('metodo') or '')}</td>
          <td class="url mono">{_e(ev.get('url'))}</td>
          <td>{_chip(an.get('veredicto', 'PASS'))}{detalle}</td>
          <td class="mono cuerpo">{_e(cuerpo[:300])}{'…' if len(cuerpo) > 300 else ''}</td>
        </tr>""")
    extra = ("" if len(eventos) <= 120 else
             f'<p class="vacio">… y {len(eventos) - 120} evento(s) más.</p>')
    return f"""
    <table class="ev">
      <thead><tr><th>Hora</th><th>Tipo</th><th>Destino</th>
                 <th>Análisis</th><th>Contenido (recortado)</th></tr></thead>
      <tbody>{''.join(filas)}</tbody>
    </table>{extra}"""


def _tabla_volcados(volcados) -> str:
    if not volcados:
        return ('<p class="vacio">No se realizó volcado de memoria en este '
                'flujo.</p>')
    filas = []
    for v in volcados:
        enlace = ""
        if v.get("reporte"):
            # El enlace se calcula RELATIVO a la carpeta del reporte
            # consolidado. Antes se usaba solo el nombre del archivo, y como el
            # reporte del inspector vive en la subcarpeta del caso
            # (KRA-1527/CP01-…/inspector_….html), el navegador lo buscaba en
            # KRA-1527/ y daba ERR_FILE_NOT_FOUND: el detalle estaba ahí, pero
            # no había forma de abrirlo desde el reporte.
            destino = Path(v["reporte"])
            try:
                ruta = destino.resolve().relative_to(BASE.resolve()).as_posix()
            except Exception:
                ruta = destino.name
            enlace = f'<a href="{_e(ruta)}" target="_blank">ver detalle</a>'
        motivo = "" if v.get("capturado") else (
            f'<div class="frag">{_e(v.get("salida", "")[:200])}</div>')
        filas.append(f"""
        <tr>
          <td class="mono">{_e(v.get('proceso'))}</td>
          <td class="mono">{_e(v.get('archivo') or '—')}</td>
          <td>{v.get('tam_mb') or '—'} MB</td>
          <td>{_chip(v.get('veredicto', 'WARN'))}{motivo}</td>
          <td>{enlace}</td>
        </tr>""")
    return f"""
    <table class="ev">
      <thead><tr><th>Proceso</th><th>Volcado</th><th>Tamaño</th>
                 <th>Veredicto</th><th>Inspector</th></tr></thead>
      <tbody>{''.join(filas)}</tbody>
    </table>"""


def _seccion(d: dict) -> str:
    aud = d.get("auditoria") or {}
    llamadas = aud.get("llamadas", 0)
    aviso = ""
    if aud.get("veredicto") == "SIN_TRAFICO":
        volcados_ok = [v for v in (d.get("volcados") or []) if v.get("capturado")]
        # Con el volcado capturado, el caso tiene la evidencia que pide el
        # criterio de aceptación y NO se pone ningún aviso.
        #
        # Antes había uno explicando que no se vio tráfico HTTP. Se quitó: el
        # caso pasó, el volcado está ahí, y el analista que revisa la evidencia
        # se encontraba un recuadro ámbar hablando de algo que no es el alcance
        # del ticket. Un aviso que obliga a preguntar «¿y esto por qué sale?»
        # sobre un resultado correcto no informa: distrae. El detalle técnico
        # sigue en el log de la corrida para quien lo necesite.
        if not volcados_ok:
            aviso = ('<div class="aviso">⚠ Este flujo <b>no ejercitó al Hardware '
                     'Agent</b>: ni tráfico auditado ni volcado de memoria, así '
                     'que un resultado limpio aquí <b>no demuestra nada</b>. '
                     'Revisa que el agente esté corriendo y que la impresión no '
                     'esté neutralizada.</div>')
    return f"""
    <section class="caso">
      <div class="cab">
        <h2>{_e(d.get('caso'))} · {_e(d.get('titulo'))}</h2>
        {_chip(d.get('veredicto', 'WARN'))}
      </div>
      <p class="meta">{_e(d.get('cuando'))} ·
         {llamadas} llamada(s) al agente ·
         {aud.get('descartadas', 0)} petición(es) ajenas descartadas ·
         {aud.get('duracion_s', 0)} s</p>
      {aviso}
      {f'<p class="notas">{_e(d.get("notas"))}</p>' if d.get('notas') else ''}
      <h3>Comunicación con el Hardware Agent</h3>
      {_tabla_eventos(aud.get('eventos'), d.get('volcados'))}
      <h3>Volcados de memoria</h3>
      {_tabla_volcados(d.get('volcados'))}
    </section>"""


CSS = """
:root{--tinta:#1f2328;--suave:#5f6368;--linea:#e3e6ea;--azul:#425cc7}
*{box-sizing:border-box}
body{margin:0;padding:32px;background:#f6f7f9;color:var(--tinta);
     font:15px/1.55 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1180px;margin:0 auto}
header{background:#fff;border:1px solid var(--linea);border-radius:14px;
       padding:26px 30px;margin-bottom:22px}
h1{margin:0 0 6px;font-size:23px;letter-spacing:-.2px}
.sub{color:var(--suave);margin:0}
.resumen{display:flex;gap:14px;flex-wrap:wrap;margin-top:20px}
.kpi{flex:1 1 150px;background:#fafbfc;border:1px solid var(--linea);
     border-radius:10px;padding:14px 16px}
.kpi b{display:block;font-size:26px;line-height:1.1}
.kpi span{color:var(--suave);font-size:12.5px;text-transform:uppercase;
          letter-spacing:.4px}
.caso{background:#fff;border:1px solid var(--linea);border-radius:14px;
      padding:22px 26px;margin-bottom:18px}
.cab{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
h2{font-size:17.5px;margin:0}
h3{font-size:13px;text-transform:uppercase;letter-spacing:.6px;
   color:var(--suave);margin:22px 0 8px;border-bottom:1px solid var(--linea);
   padding-bottom:6px}
.meta{color:var(--suave);font-size:13px;margin:8px 0 0}
.notas{background:#fafbfc;border-left:3px solid var(--azul);padding:9px 13px;
       margin:12px 0;font-size:14px}
.aviso{background:#fff8e1;border:1px solid #f0c36d;border-radius:9px;
       padding:11px 14px;margin:13px 0;font-size:14px}
.chip{display:inline-block;padding:3px 12px;border-radius:99px;font-size:12px;
      font-weight:700;letter-spacing:.4px;border:1px solid}
table.ev{width:100%;border-collapse:collapse;font-size:13px}
table.ev th{text-align:left;color:var(--suave);font-weight:600;font-size:11.5px;
            text-transform:uppercase;letter-spacing:.4px;padding:7px 9px;
            border-bottom:1px solid var(--linea)}
table.ev td{padding:9px;border-bottom:1px solid #f0f2f4;vertical-align:top}
table.ev tr:last-child td{border-bottom:none}
.mono{font-family:ui-monospace,Consolas,monospace;font-size:12px}
.url{max-width:330px;word-break:break-all;color:var(--azul)}
.cuerpo{max-width:300px;word-break:break-all;color:var(--suave)}
.hallazgo{color:#b3261e;font-size:12px;margin-top:4px;font-weight:600}
.frag{color:#8a6100;font-size:12px;margin-top:4px}
.vacio{color:var(--suave);font-style:italic;font-size:13.5px;margin:6px 0}
/* Bloque que declara la comunicación probada por el volcado. En verde sobrio:
   es un resultado correcto, no una advertencia — el ámbar hacía que un caso
   que pasó pareciera necesitar revisión. */
.prueba{background:#f2f9f4;border:1px solid #cfe6d6;border-left:4px solid #2e7d4f;
        border-radius:9px;padding:14px 16px;margin:8px 0 4px;font-size:13.5px}
.prueba p{margin:0 0 8px}
.prueba .etq{color:var(--suave);font-size:12px;text-transform:uppercase;
             letter-spacing:.4px;margin:12px 0 6px}
.prueba ul{margin:0;padding-left:18px}
.prueba .huella li{color:#2e7d4f;margin:2px 0}
.prueba .dmp li{margin:6px 0;list-style:none;padding:8px 10px;background:#fff;
                border:1px solid var(--linea);border-radius:7px}
.prueba .dmp{padding-left:0}
.prueba .ruta{color:var(--suave);font-size:11.5px;margin-top:3px;
              word-break:break-all}
.prueba .pie{color:var(--suave);font-size:12px;margin:10px 0 0}
footer{color:var(--suave);font-size:12.5px;text-align:center;margin-top:26px;
       line-height:1.7}
a{color:var(--azul)}
"""


def generar(destino=None) -> Path:
    """Renderiza el HTML consolidado a partir del acumulado."""
    datos = sorted(_leer(), key=lambda d: d.get("caso", ""))
    destino = Path(destino or REPORTE)
    destino.parent.mkdir(parents=True, exist_ok=True)

    total = len(datos)
    fallos = sum(1 for d in datos if d["veredicto"] == "FAIL")
    limpios = sum(1 for d in datos if d["veredicto"] == "PASS")
    # KPI honesto: cuántos volcados se llegaron a INSPECCIONAR. Es la medida de
    # cuánta prueba real hay detrás del veredicto — mucho más informativa que
    # contar los casos «sin comunicación», que sonaba a fallo cuando en realidad
    # solo decía que el tráfico HTTP no era observable desde el navegador.
    inspeccionados = sum(
        1 for d in datos for v in (d.get("volcados") or [])
        if v.get("veredicto") in _CONCLUYENTES)
    llamadas = sum((d.get("auditoria") or {}).get("llamadas", 0) for d in datos)
    global_v = _peor([d["veredicto"] for d in datos]) if datos else "SIN_TRAFICO"

    cuerpo = "".join(_seccion(d) for d in datos) or (
        '<section class="caso"><p class="vacio">Todavía no hay resultados. '
        'Ejecuta los tests de KRA-1527 para poblar este reporte.</p></section>')

    doc = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>KRA-1527 · Token del Hardware Agent</title><style>{CSS}</style></head>
<body><div class="wrap">
<header>
  <h1>KRA-1527 · El token no debe viajar ni quedar en claro</h1>
  <p class="sub">Verificación automatizada del fix: por cada flujo que hace
     hablar a Hermes 2.0 con el agente de hardware local, se audita el tráfico y
     se inspecciona la memoria de <code>{_e(settings.HW_AGENT_PROC)}</code> y
     <code>{_e(settings.HW_PROXY_PROC)}</code>.</p>
  <div class="resumen">
    <div class="kpi"><b>{total}</b><span>Flujos verificados</span></div>
    <div class="kpi"><b>{limpios}</b><span>Sin token en claro</span></div>
    <div class="kpi"><b>{fallos}</b><span>Con token expuesto</span></div>
    <div class="kpi"><b>{inspeccionados}</b><span>Volcados inspeccionados</span></div>
    <div class="kpi"><b>{llamadas}</b><span>Llamadas al agente</span></div>
    <div class="kpi"><b style="font-size:15px;padding-top:6px">
        {_chip(global_v)}</b><span>Veredicto global</span></div>
  </div>
</header>
{cuerpo}
<footer>
  Generado el {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ·
  Ambiente <b>{_e(settings.ENV)}</b> · AutomationAgent<br>
  Este reporte no contiene tokens: de cualquier hallazgo se muestran solo sus
  claims y su longitud. Los volcados <code>.DMP</code> se borran tras
  inspeccionarse.
</footer>
</div></body></html>"""
    destino.write_text(doc, encoding="utf-8")
    logger.info("[Reporte] KRA-1527 generado → %s (%d flujo(s), veredicto %s)",
                destino, total, global_v)
    return destino
