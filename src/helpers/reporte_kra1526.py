"""
Reporte HTML consolidado de KRA-1526 — Autorización IDOR (IdUser / IdAgent).

Mismo molde que `reporte_trn239`: es EL entregable de la etiqueta. Cuenta, por
caso, qué se envió (con qué IdUser/IdAgent), qué contestó el API (HTTP + si trajo
datos) y el veredicto. El acumulado (`resultados.json`) NO se borra entre
corridas; para la corrida que se entrega, primero `kra1526.ps1` (que resetea).

Regla de la prueba (alcance: SOLO mono-agente, confirmada por DEV):
    Mono-agente → se validan IdUser Y IdAgent. Cambiar cualquiera ⇒ 403.
"""

from __future__ import annotations

import html
import json
from datetime import datetime

from config.logger import get_logger

logger = get_logger("KRA-1526.reporte")

# Dos estados en el reporte: PASS o FAIL. Sin tercer color tibio: lo que no se
# pudo comprobar (p. ej. un endpoint que no respondió) se marca FAIL con el
# motivo, porque una prueba de seguridad que no pudo ejecutarse no aprueba.
ESTILOS = {
    "PASS": ("#059669", "#ecfdf5", "OK"),
    "FAIL": ("#dc2626", "#fef2f2", "FALLA"),
}


def _bin(veredicto: str) -> str:
    return "FAIL" if veredicto == "FAIL" else "PASS"


def peor(veredictos) -> str:
    """FAIL si hay algún FAIL; si no, PASS. Una sola escala para caso y reporte."""
    return "FAIL" if any(_bin(v) == "FAIL" for v in veredictos) else "PASS"


def _ruta(P):
    P.EVIDENCIA_BASE.mkdir(parents=True, exist_ok=True)
    return P.RESULTADOS


def leer(P) -> list:
    try:
        return json.loads(_ruta(P).read_text(encoding="utf-8"))
    except Exception:
        return []


def limpiar(P) -> None:
    try:
        _ruta(P).unlink(missing_ok=True)
    except Exception:
        pass


def registrar(P, caso: str, titulo: str, veredicto: str, *,
              subticket: str = "", pasos=None, notas: str = "") -> None:
    """Agrega o reemplaza el resultado de un caso en el acumulado."""
    datos = [d for d in leer(P) if d.get("caso") != caso]
    datos.append({
        "caso": caso,
        "titulo": titulo,
        "veredicto": veredicto,
        "subticket": subticket,
        "pasos": pasos or [],
        "notas": notas,
        "momento": datetime.now().isoformat(timespec="seconds"),
    })
    datos.sort(key=lambda d: d.get("caso", ""))
    try:
        _ruta(P).write_text(
            json.dumps(datos, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8")
    except Exception as e:
        logger.warning("[Reporte] No se pudo guardar: %s", str(e)[:90])
    logger.info("[Reporte] %s registrado → %s", caso, veredicto)


def _e(x) -> str:
    return html.escape(str(x if x is not None else ""))


def _chip(veredicto: str) -> str:
    color, fondo, texto = ESTILOS[_bin(veredicto)]
    return (f'<span style="background:{fondo};color:{color};padding:2px 9px;'
            f'border-radius:11px;font-size:11.5px;font-weight:700;'
            f'white-space:nowrap">{texto}</span>')


def _tabla_pasos(pasos) -> str:
    if not pasos:
        return ""
    filas = []
    for p in pasos:
        ev = p.get("evidencia") or ""
        enlace = (f'<a href="{_e(ev)}" style="color:#60a5fa">ver</a>'
                  if ev else "")
        filas.append(
            f"<tr><td>{_e(p.get('nombre'))}</td>"
            f"<td>{_chip(p.get('veredicto', 'PASS'))}</td>"
            f"<td>{_e(p.get('detalle'))}</td>"
            f"<td>{enlace}</td></tr>")
    return (f'<table class="pasos"><thead><tr><th>Paso</th><th></th>'
            f'<th>Detalle</th><th>Evidencia</th></tr></thead>'
            f'<tbody>{"".join(filas)}</tbody></table>')


def generar(P) -> str:
    datos = leer(P)
    global_v = peor([d.get("veredicto") for d in datos]) if datos else "PASS"
    color, fondo, texto_v = ESTILOS[global_v]

    cuenta = {k: sum(1 for d in datos if _bin(d.get("veredicto")) == k)
              for k in ESTILOS}

    bloques = []
    for d in datos:
        v = _bin(d.get("veredicto"))
        abierto = " open" if v == "FAIL" else ""
        n_pasos = len(d.get("pasos") or [])
        bloques.append(f"""
        <details class="caso"{abierto}>
          <summary>
            {_chip(d.get('veredicto', 'PASS'))}
            <span class="caso-id">{_e(d.get('caso'))}</span>
            <span class="caso-tit">{_e(d.get('titulo'))}</span>
            <span class="caso-meta">{n_pasos} paso(s)</span>
          </summary>
          {f'<p class="sub">{_e(d.get("subticket"))}</p>' if d.get('subticket') else ''}
          {_tabla_pasos(d.get('pasos'))}
          {f'<p class="notas">{_e(d.get("notas"))}</p>' if d.get('notas') else ''}
        </details>""")

    resumen = " · ".join(
        f"{cuenta[k]} {ESTILOS[k][2]}" for k in ("PASS", "FAIL") if cuenta[k])

    doc = f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<title>KRA-1526 · Autorización IDOR — Reporte</title><style>
body{{font-family:'Segoe UI',system-ui,sans-serif;background:#0f172a;color:#e2e8f0;margin:0}}
.wrap{{max-width:1080px;margin:0 auto;padding:28px 20px 70px}}
h1{{font-size:22px;margin:0 0 4px}} .sub{{color:#94a3b8;font-size:12.5px;margin:2px 0}}
.hero{{text-align:center;padding:24px;border-radius:12px;margin:20px 0 26px;
background:#1e293b;border:1px solid #334155}}
.big{{font-size:40px;font-weight:800;color:{color}}}
.caso{{background:#1e293b;border:1px solid #334155;border-radius:10px;
padding:6px 18px;margin-bottom:12px}}
.caso>summary{{list-style:none;cursor:pointer;padding:12px 0;display:flex;
gap:10px;align-items:center;font-size:14px}}
.caso>summary::-webkit-details-marker{{display:none}}
.caso>summary::before{{content:'▸';color:#64748b;font-size:12px;transition:transform .15s}}
.caso[open]>summary::before{{transform:rotate(90deg)}}
.caso-id{{font-weight:700;color:#e2e8f0}}
.caso-tit{{color:#cbd5e1;font-size:13px;font-weight:400}}
.caso-meta{{color:#64748b;font-size:11.5px;margin-left:auto;white-space:nowrap}}
table.pasos{{width:100%;border-collapse:collapse;font-size:12.5px;margin:4px 0 12px}}
table.pasos td,table.pasos th{{padding:6px 9px;border-bottom:1px solid #0f172a;
text-align:left;vertical-align:top}}
table.pasos th{{color:#94a3b8;font-weight:600}}
.sub{{color:#94a3b8;font-size:12px}}
.notas{{color:#94a3b8;font-size:12px;margin:6px 0 12px;font-style:italic}}
.pie{{color:#64748b;font-size:11.5px;margin-top:26px;line-height:1.6}}
code{{color:#fbbf24}}
</style></head><body><div class="wrap">
<h1>KRA-1526 · Autorización IDOR (IdUser / IdAgent) — Reporte de pruebas</h1>
<p class="sub">Búsqueda global y endpoints relacionados · perfil: {_e(getattr(P, 'MODO', 'mono-agente'))}</p>
<p class="sub">{_e(P.BASE_URL)} · generado {datetime.now():%Y-%m-%d %H:%M:%S}</p>
<div class="hero"><div class="big">{texto_v}</div><div>{_e(resumen)}</div></div>
{''.join(bloques) or '<p class="sub">Sin casos ejecutados todavía.</p>'}
<p class="pie">
<b>La regla (confirmada por DEV):</b> en <b>mono-agente</b> el middleware valida
<i>IdUser</i> Y <i>IdAgent</i> → cambiar cualquiera ⇒ <b>403</b> sin datos. En
<b>multi-agente</b> valida <i>IdUser</i> (ajeno ⇒ 403) pero <b>NO</b> el
<i>IdAgent</i> (cambiarlo ⇒ 200 por diseño). El multi-agente corre <b>aparte</b>
(agencia 0040, <code>KRA1526_MULTI=1</code>, reporte propio).<br>
<b>Veredicto por IDENTIDAD (no solo por código):</b> la propiedad de seguridad
es que manipular un id <i>no exponga datos de otra identidad</i>. Salen <b>OK</b>:
un bloqueo (HTTP 403/401), o un 200 que devuelve <i>solo los datos propios</i>
(el servidor ignoró el id ajeno — común en multi-agente, que resuelve el usuario
del token), o un 200 vacío. Sale <b>FALLA</b> solo una <b>fuga real</b>: 200 con
datos de <i>otra</i> identidad (otro cliente / otra agencia) al enviar el id
ajeno. Un endpoint que no respondió (404/timeout) también es FALLA: no se pudo
comprobar.<br>
<b>Regresión:</b> tras un 403, restaurar los IDs propios debe volver a
devolver las coincidencias (mismo <code>totalRecords</code> y todos con el
IdAgent propio). Si no vuelven, el bloqueo dejó daño colateral.<br>
<b>Solo hay OK o FALLA.</b> Si un endpoint no respondió (404/timeout) el caso
sale FALLA con el motivo: una prueba de seguridad que no se pudo ejecutar no se
da por buena. El par petición/respuesta exacto de cada llamada está en el
enlace «ver» de cada paso (los IDs alterados van marcados con <code>_MODIFICADO</code>).<br>
<b>Sin intervención manual:</b> el token y los IdUser/IdAgent propios se
capturan en vivo de la sesión (búsqueda real del teléfono de prueba); no se
pega ningún curl. El token de Hermes dura ~20 min y se toma fresco en cada corrida.
</p></div></body></html>"""

    P.EVIDENCIA_BASE.mkdir(parents=True, exist_ok=True)
    P.REPORTE.write_text(doc, encoding="utf-8")
    logger.info("[Reporte] KRA-1526 generado → %s (%d caso(s), veredicto %s)",
                P.REPORTE, len(datos), global_v)
    return str(P.REPORTE)
