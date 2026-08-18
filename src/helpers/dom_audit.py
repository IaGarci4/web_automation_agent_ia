"""
DomAudit — auditor de estructura HTML en tiempo de ejecución.

Recorre TODO el DOM de la página actual y detecta problemas de
localización/estructura que hacen frágiles las pruebas:

  • data-testid DUPLICADOS    → el mismo testid en N elementos (strict mode)
  • data-testid GENÉRICOS     → test-id-button, typography, id-button... reusados
  • data-testid DINÁMICOS     → con índices/GUIDs que cambian entre corridas
  • IDs HTML DUPLICADOS        → rompen los selectores #id (HTML inválido)
  • interactivos SIN testid    → no hay forma estable de ubicarlos
  • TEXTOS repetidos           → varios botones/links con el mismo texto (ambiguo)
  • inputs SIN etiqueta        → sin testid/label/aria/placeholder (no localizable)
  • divs SOBRECARGADOS         → demasiados hijos directos (acoplamiento)
  • anidación PROFUNDA          → árboles muy profundos, IGNORANDO el interior de
                                 los SVG (íconos) que no es estructura real
  • idioma MEZCLADO            → términos en el idioma contrario al esperado

Cada hallazgo trae el PORQUÉ está mal, la SOLUCIÓN y DÓNDE está (ruta/ancestro
estable), para que desarrollo lo corrija rápido.

Uso en un test / fixture:
    from src.helpers.dom_audit import DomAudit
    audit = DomAudit(page)
    await audit.scan(etiqueta="reportes_agent_balance")
    audit.save_html("reports/audit/reportes.html")
"""

import html
import json
import time
from pathlib import Path

# Testids/ids que la app reutiliza en muchos elementos — no identifican nada
GENERICOS = {
    "test-id-button", "typography", "id-button", "id-input", "id-label",
    "test-id-paragraph-medium-bold", "test-id-paragraph-semi-bold",
}

# Umbrales de estructura
MAX_HIJOS_DIRECTOS = 15   # un div con más hijos directos está sobrecargado
MAX_PROFUNDIDAD    = 25   # profundidad de anidación excesiva (sin contar SVG)

# ── Detección de idioma mezclado ────────────────────────────────────────────
ES_HINTS = {
    "enviar", "envío", "envio", "dinero", "buscar", "salir", "cliente",
    "beneficiario", "cuenta", "saldo", "reportes", "transacciones", "cerrar",
    "sesión", "sesion", "continuar", "regresar", "cancelar", "guardar",
    "nombre", "apellido", "dirección", "direccion", "ciudad", "estado",
    "monto", "tarifa", "impuesto", "descuento", "comisión", "comision",
    "ayuda", "notificaciones", "importantes", "cheques", "servicios", "pagos",
}
EN_HINTS = {
    "send", "money", "search", "logout", "customer", "beneficiary",
    "account", "balance", "reports", "transactions", "close", "session",
    "continue", "back", "cancel", "save", "name", "last", "address",
    "city", "state", "amount", "fee", "tax", "discount", "fees", "help",
    "notifications", "important", "checks", "services", "payments", "transfers",
}

_SCAN_JS = r"""
() => {
    const generic = %GENERICOS%;
    const MAXH = %MAXH%, MAXD = %MAXD%;

    // Tags internos de SVG: su anidación es decorativa, NO estructura de la app.
    const SVG = new Set(['SVG','PATH','G','DEFS','USE','SYMBOL','CLIPPATH',
        'LINEARGRADIENT','RADIALGRADIENT','STOP','MASK','PATTERN','POLYGON',
        'POLYLINE','RECT','CIRCLE','ELLIPSE','LINE','TEXT','TSPAN','FILTER',
        'FEGAUSSIANBLUR','FEOFFSET','FEMERGE','FEMERGENODE','FECOLORMATRIX',
        'FEFLOOD','FECOMPOSITE','FOREIGNOBJECT','MARKER','SWITCH','DESC','TITLE']);

    // ── 1. data-testid: contar ocurrencias ──────────────────────────────
    const conteo = {};
    document.querySelectorAll('[data-testid]').forEach(el => {
        const t = el.getAttribute('data-testid');
        conteo[t] = (conteo[t] || 0) + 1;
    });
    const duplicados = Object.entries(conteo)
        .filter(([t, n]) => n > 1)
        .map(([t, n]) => ({ testid: t, veces: n }))
        .sort((a, b) => b.veces - a.veces);

    const genericos = Object.entries(conteo)
        .filter(([t]) => generic.includes(t))
        .map(([t, n]) => ({ testid: t, veces: n }));

    // testids DINÁMICOS: índice numérico (-0-, _3) o GUID/hash → inestables
    const reIndice = /(^|[-_])\d+([-_]|$)/;
    const reGuid   = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}/i;
    const reHash   = /[-_][0-9a-f]{12,}([-_]|$)/i;
    const dinamicos = Object.keys(conteo)
        .filter(t => !generic.includes(t) &&
                     (reIndice.test(t) || reGuid.test(t) || reHash.test(t)))
        .map(t => ({ testid: t, veces: conteo[t] }))
        .sort((a, b) => b.veces - a.veces)
        .slice(0, 30);

    // ── 2. IDs HTML duplicados (rompen selectores #id) ──────────────────
    const idCount = {};
    document.querySelectorAll('[id]').forEach(el => {
        const i = el.id; if (i) idCount[i] = (idCount[i] || 0) + 1;
    });
    const idsDuplicados = Object.entries(idCount)
        .filter(([i, n]) => n > 1)
        .map(([i, n]) => ({ id: i, veces: n }))
        .sort((a, b) => b.veces - a.veces)
        .slice(0, 30);

    // Helpers de localización
    function loc(el) {
        if (!el || !el.tagName) return '';
        const tid = el.getAttribute && el.getAttribute('data-testid');
        if (tid) return '[data-testid="' + tid + '"]';
        if (el.id) return '#' + el.id;
        let s = el.tagName.toLowerCase();
        const cls = (typeof el.className === 'string' ? el.className : '')
            .trim().split(/\s+/).filter(c => c && !c.startsWith('ng-')).slice(0, 2);
        if (cls.length) s += '.' + cls.join('.');
        return s;
    }
    function ancestroTestid(el) {
        const a = el.closest && el.closest('[data-testid]');
        return a ? a.getAttribute('data-testid') : '';
    }
    // Cadena desde el ancestro estable (testid/id) hasta el nodo — DÓNDE está.
    function cadena(el, maxLen) {
        const stack = []; let cur = el, guard = 0;
        while (cur && cur.tagName && cur.tagName !== 'BODY' && guard < (maxLen || 40)) {
            stack.unshift(loc(cur));
            if (cur.getAttribute && cur.getAttribute('data-testid')) break;
            if (cur.id) break;
            cur = cur.parentElement; guard++;
        }
        return stack.join(' > ');
    }
    // Cuenta wrappers <div> sin testid encadenados encima del nodo (redundantes)
    function wrappersDiv(el) {
        let cur = el, n = 0, guard = 0;
        while (cur && cur.tagName && cur.tagName !== 'BODY' && guard < 40) {
            if (cur.tagName === 'DIV' && !(cur.getAttribute && cur.getAttribute('data-testid')))
                n++;
            if (cur.getAttribute && cur.getAttribute('data-testid')) break;
            if (cur.id) break;
            cur = cur.parentElement; guard++;
        }
        return n;
    }

    // ── 3. interactivos visibles sin data-testid ────────────────────────
    const sinTestid = [];
    document.querySelectorAll('button, a, input, select, textarea, [role="button"], [role="option"]')
        .forEach(el => {
            if (el.hasAttribute('data-testid')) return;
            const r = el.getBoundingClientRect();
            if (r.width === 0 || r.height === 0) return;  // oculto
            const txt = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 40);
            sinTestid.push({
                tag: el.tagName.toLowerCase(),
                texto: txt,
                id: el.id || '',
                ruta: cadena(el, 8),
            });
        });

    // ── 4. textos repetidos entre interactivos (ambigüedad por texto) ────
    const txtCount = {};
    document.querySelectorAll('button, a, [role="button"]').forEach(el => {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return;
        const t = (el.innerText || '').trim();
        if (!t || t.length > 40) return;
        txtCount[t] = (txtCount[t] || 0) + 1;
    });
    const textosDup = Object.entries(txtCount)
        .filter(([t, n]) => n > 1)
        .map(([t, n]) => ({ texto: t, veces: n }))
        .sort((a, b) => b.veces - a.veces)
        .slice(0, 20);

    // ── 5. inputs sin etiqueta accesible (ni testid/label/aria/placeholder) ─
    const inputsSinLabel = [];
    document.querySelectorAll('input, select, textarea').forEach(el => {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return;
        if ((el.type || '').toLowerCase() === 'hidden') return;
        const hasTestid = el.hasAttribute('data-testid');
        const aria = el.getAttribute('aria-label');
        const ph = el.getAttribute('placeholder');
        let lbl = false;
        try { if (el.id) lbl = !!document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); }
        catch (e) {}
        if (!hasTestid && !aria && !ph && !lbl) {
            inputsSinLabel.push({
                tag: el.tagName.toLowerCase(),
                tipo: (el.type || ''),
                id: el.id || '',
                ruta: cadena(el, 8),
            });
        }
    });

    // ── 6. divs sobrecargados + profundidad (IGNORANDO interior de SVG) ──
    let sobrecargados = [];
    let maxProf = 0, deepEl = null;
    function recorrer(el, prof) {
        if (SVG.has(el.tagName)) return;  // no descender en SVG (íconos)
        if (prof > maxProf) { maxProf = prof; deepEl = el; }
        const hijos = el.children ? el.children.length : 0;
        if (el.tagName === 'DIV' && hijos > MAXH) {
            sobrecargados.push({
                hijos,
                ruta: cadena(el, 8),
                ancestro_testid: ancestroTestid(el),
            });
        }
        for (const c of el.children) recorrer(c, prof + 1);
    }
    recorrer(document.body, 0);
    sobrecargados = sobrecargados.sort((a, b) => b.hijos - a.hijos).slice(0, 15);

    const prof = {
        maxima: maxProf,
        umbral: MAXD,
        // nodo real más profundo (ya nunca es un <path> de SVG)
        nodo: deepEl ? loc(deepEl) : '',
        ruta: deepEl ? cadena(deepEl, 40) : '',
        ancestro_testid: deepEl ? ancestroTestid(deepEl) : '',
        wrappers_div: deepEl ? wrappersDiv(deepEl) : 0,
    };

    // ── 7. texto visible para análisis de idioma ────────────────────────
    const texto = (document.body.innerText || '').slice(0, 20000);

    return {
        url: location.href,
        total_testids: Object.keys(conteo).length,
        duplicados, genericos, dinamicos, idsDuplicados,
        sinTestid: sinTestid.slice(0, 40),
        textosDup, inputsSinLabel: inputsSinLabel.slice(0, 30),
        sobrecargados,
        profundidad: prof,
        texto_visible: texto,
    };
}
"""


class DomAudit:
    def __init__(self, page, flujo: str = ""):
        self.page = page
        self.flujo = flujo            # nombre del flujo (ej. "Agent Balance")
        self.hallazgos = []           # lista de scans acumulados

    async def scan(self, etiqueta: str = "", idioma: str = "English") -> dict:
        """
        Audita el DOM actual y acumula el resultado.
        `idioma` = idioma esperado de la UI ('English' o 'Spanish').
        """
        js = (_SCAN_JS
              .replace("%GENERICOS%", json.dumps(sorted(GENERICOS)))
              .replace("%MAXH%", str(MAX_HIJOS_DIRECTOS))
              .replace("%MAXD%", str(MAX_PROFUNDIDAD)))
        data = await self.page.evaluate(js)
        data["etiqueta"] = etiqueta or data.get("url", "")
        data["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
        data["idioma_esperado"] = idioma
        data["idioma"] = self._detectar_idioma(data.pop("texto_visible", ""), idioma)
        self.hallazgos.append(data)
        return data

    @staticmethod
    def _detectar_idioma(texto: str, esperado: str) -> dict:
        """Detecta palabras del idioma CONTRARIO al esperado."""
        import re as _re
        tokens = set(_re.findall(r"[a-záéíóúñü]+", texto.lower()))
        es_mode = esperado.lower().startswith(("es", "sp"))  # Spanish/Español
        intrusas = sorted((tokens & ES_HINTS) if not es_mode else (tokens & EN_HINTS))
        return {
            "esperado": "Español" if es_mode else "English",
            "intruso": "English" if es_mode else "Español",
            "palabras": intrusas,
        }

    # ── Reporte HTML ──────────────────────────────────────────────────────────

    def save_html(self, ruta: str) -> str:
        p = Path(ruta)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self._render_html(), encoding="utf-8")
        return str(p)

    def _render_html(self) -> str:
        secciones = "".join(self._render_scan(h) for h in self.hallazgos)
        titulo = f"Auditoría de estructura — {self.flujo}" if self.flujo else "Auditoría de estructura HTML — HERMES2"
        titulo = html.escape(titulo)
        return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>{titulo}</title>
<style>
 body{{font-family:Segoe UI,Calibri,sans-serif;background:#0E1B33;color:#E8EEF7;margin:0;padding:32px}}
 h1{{color:#1FB6A6;font-size:26px;margin:0 0 4px}}
 .sub{{color:#9FB2D0;margin:0 0 24px}}
 .scan{{background:#16284A;border-radius:10px;padding:20px 24px;margin:0 0 24px}}
 .scan h2{{color:#fff;font-size:18px;margin:0 0 12px;border-bottom:1px solid #2A3D63;padding-bottom:8px}}
 .issue{{background:#0E1B33;border-left:4px solid #F0A202;border-radius:6px;padding:12px 16px;margin:10px 0}}
 .issue.crit{{border-color:#E84855}} .issue.ok{{border-color:#2BB673}}
 .issue h3{{margin:0 0 6px;font-size:15px;color:#fff}}
 .why{{color:#9FB2D0;font-size:13px;margin:4px 0}}
 .fix{{color:#7CE0D3;font-size:13px;margin:4px 0}}
 code{{background:#23365c;padding:2px 6px;border-radius:4px;color:#FFD479;font-size:12px;word-break:break-all}}
 .count{{display:inline-block;background:#E84855;color:#fff;border-radius:10px;padding:1px 9px;font-size:12px;margin-left:6px}}
 ul{{margin:6px 0 0 18px;padding:0}} li{{font-size:12.5px;color:#CBD8EE;margin:3px 0}}
 .loc{{color:#7CE0D3}}
</style></head><body>
<h1>{titulo}</h1>
<p class="sub">Hallazgos por pantalla recorrida. Cada uno explica el porqué, la solución y DÓNDE está (ruta/ancestro estable).</p>
{secciones}
</body></html>"""

    def _render_scan(self, h: dict) -> str:
        bloques = []

        # Duplicados (crítico)
        if h.get("duplicados"):
            items = "".join(
                f"<li><code>{html.escape(d['testid'])}</code> <span class='count'>{d['veces']}×</span></li>"
                for d in h["duplicados"])
            bloques.append(f"""<div class="issue crit"><h3>data-testid duplicados ({len(h['duplicados'])})</h3>
            <p class="why">Por qué está mal: un mismo testid en varios elementos provoca <b>strict mode violation</b> en Playwright — el localizador no es único y el test falla o clickea el elemento equivocado.</p>
            <p class="fix">Solución: hacer único cada testid (sufijo por contexto: <code>report-options-button</code> vs <code>search-button</code>) o desambiguar por texto/ancestro.</p>
            <ul>{items}</ul></div>""")

        # IDs HTML duplicados (crítico — rompen #id)
        if h.get("idsDuplicados"):
            items = "".join(
                f"<li><code>#{html.escape(d['id'])}</code> <span class='count'>{d['veces']}×</span></li>"
                for d in h["idsDuplicados"])
            bloques.append(f"""<div class="issue crit"><h3>IDs HTML duplicados ({len(h['idsDuplicados'])})</h3>
            <p class="why">Por qué está mal: el atributo <code>id</code> debe ser único en todo el documento. Repetido, es HTML inválido y los selectores <code>#id</code> apuntan solo al primero — el test puede operar sobre el elemento equivocado.</p>
            <p class="fix">Solución: garantizar IDs únicos (o migrar a <code>data-testid</code> semánticos).</p>
            <ul>{items}</ul></div>""")

        # Genéricos
        if h.get("genericos"):
            items = "".join(
                f"<li><code>{html.escape(g['testid'])}</code> <span class='count'>{g['veces']}×</span></li>"
                for g in h["genericos"])
            bloques.append(f"""<div class="issue"><h3>data-testid genéricos ({len(h['genericos'])})</h3>
            <p class="why">Por qué está mal: testids como <code>test-id-button</code> o <code>typography</code> se reutilizan en decenas de elementos; no identifican nada en concreto y obligan a adivinar por texto (que cambia con el idioma).</p>
            <p class="fix">Solución: asignar un testid semántico por elemento (<code>agent-balance-search-button</code>).</p>
            <ul>{items}</ul></div>""")

        # testids dinámicos / inestables
        if h.get("dinamicos"):
            items = "".join(
                f"<li><code>{html.escape(d['testid'])}</code>"
                + (f" <span class='count'>{d['veces']}×</span>" if d['veces'] > 1 else "") + "</li>"
                for d in h["dinamicos"])
            bloques.append(f"""<div class="issue"><h3>data-testid dinámicos / inestables ({len(h['dinamicos'])})</h3>
            <p class="why">Por qué está mal: testids con índices (<code>-0-</code>, <code>_3</code>) o GUIDs/hashes cambian al reordenar filas o entre sesiones; un selector que hoy funciona, mañana apunta a otra cosa.</p>
            <p class="fix">Solución: usar un identificador estable e independiente de la posición (por dato, no por índice). Si el índice es inevitable, localizar por el dato visible dentro de la fila.</p>
            <ul>{items}</ul></div>""")

        # Sin testid
        if h.get("sinTestid"):
            items = "".join(
                f"<li>&lt;{html.escape(s['tag'])}&gt; \"{html.escape(s['texto'])}\""
                + (f" · id=<code>{html.escape(s['id'])}</code>" if s['id'] else "")
                + (f"<br><span class='loc'>ubicación:</span> <code>{html.escape(s.get('ruta',''))}</code>" if s.get('ruta') else "")
                + "</li>"
                for s in h["sinTestid"][:25])
            bloques.append(f"""<div class="issue"><h3>Interactivos sin data-testid ({len(h['sinTestid'])})</h3>
            <p class="why">Por qué está mal: botones/inputs/links visibles sin testid solo se pueden ubicar por texto o CSS frágil; cualquier cambio de copy o estilo rompe la prueba.</p>
            <p class="fix">Solución: agregar <code>data-testid</code> a cada elemento interactivo del flujo.</p>
            <ul>{items}</ul></div>""")

        # Textos repetidos entre interactivos
        if h.get("textosDup"):
            items = "".join(
                f"<li>\"{html.escape(t['texto'])}\" <span class='count'>{t['veces']}×</span></li>"
                for t in h["textosDup"])
            bloques.append(f"""<div class="issue"><h3>Textos repetidos en interactivos ({len(h['textosDup'])})</h3>
            <p class="why">Por qué está mal: si varios botones/links muestran el mismo texto, localizar por texto es ambiguo (strict mode) y el test puede pulsar el equivocado.</p>
            <p class="fix">Solución: dar a cada uno un <code>data-testid</code> único, o desambiguar por contenedor/ancestro estable.</p>
            <ul>{items}</ul></div>""")

        # Inputs sin etiqueta accesible
        if h.get("inputsSinLabel"):
            items = "".join(
                f"<li>&lt;{html.escape(s['tag'])}&gt;"
                + (f" type=<code>{html.escape(s['tipo'])}</code>" if s['tipo'] else "")
                + (f" · id=<code>{html.escape(s['id'])}</code>" if s['id'] else "")
                + (f"<br><span class='loc'>ubicación:</span> <code>{html.escape(s.get('ruta',''))}</code>" if s.get('ruta') else "")
                + "</li>"
                for s in h["inputsSinLabel"][:20])
            bloques.append(f"""<div class="issue"><h3>Inputs sin etiqueta accesible ({len(h['inputsSinLabel'])})</h3>
            <p class="why">Por qué está mal: un campo sin <code>data-testid</code>, <code>label</code>, <code>aria-label</code> ni <code>placeholder</code> no tiene forma estable ni accesible de localizarse — y es un problema de accesibilidad (a11y).</p>
            <p class="fix">Solución: añadir <code>data-testid</code> y una etiqueta accesible (<code>label for</code> o <code>aria-label</code>).</p>
            <ul>{items}</ul></div>""")

        # Sobrecargados — con RUTA para localizar cada uno
        if h.get("sobrecargados"):
            def _fila_sobre(s):
                anc = s.get("ancestro_testid", "")
                ref = (f" · dentro de <code>[data-testid=&quot;{html.escape(anc)}&quot;]</code>"
                       if anc else "")
                ruta = html.escape(s.get("ruta", "") or "(raíz)")
                return (f"<li><b>{s['hijos']} hijos directos</b>{ref}<br>"
                        f"<span class='loc'>ubicación:</span> <code>{ruta}</code></li>")
            items = "".join(_fila_sobre(s) for s in h["sobrecargados"])
            bloques.append(f"""<div class="issue"><h3>Contenedores sobrecargados ({len(h['sobrecargados'])})</h3>
            <p class="why">Por qué está mal: un div con &gt;{MAX_HIJOS_DIRECTOS} hijos directos suele indicar falta de componentización; dificulta localizar y vuelve lento el render.</p>
            <p class="fix">Solución: dividir en subcomponentes con su propio testid. Usa la <b>ubicación</b> para encontrarlo en el código.</p>
            <ul>{items}</ul></div>""")

        # Profundidad — nodo REAL (sin SVG) + cadena + wrappers + ancla estable
        prof = h.get("profundidad", {})
        if prof.get("maxima", 0) > prof.get("umbral", MAX_PROFUNDIDAD):
            anc = prof.get("ancestro_testid", "")
            ref = (f"<p class=\"why\">Ancla estable más cercana: "
                   f"<code>[data-testid=&quot;{html.escape(anc)}&quot;]</code> — "
                   f"localiza desde aquí en vez de una ruta CSS larga.</p>" if anc else "")
            wrappers = prof.get("wrappers_div", 0)
            wrap_txt = (f"<p class=\"why\">Hay <b>{wrappers} &lt;div&gt; sin testid</b> "
                        f"encadenados sobre el nodo — candidatos a eliminar/aplanar.</p>"
                        if wrappers else "")
            nodo = html.escape(prof.get("nodo", "") or "?")
            ruta = html.escape(prof.get("ruta", "") or "(sin ruta)")
            bloques.append(f"""<div class="issue"><h3>Anidación profunda ({prof['maxima']} niveles reales)</h3>
            <p class="why">Por qué está mal: árboles muy profundos (&gt;{prof['umbral']}) son frágiles ante refactors y encarecen los selectores CSS. <i>(Se ignora el interior de los SVG/íconos, que no es estructura real.)</i></p>
            <p class="fix">Solución: aplanar la estructura; preferir localización por testid sobre rutas CSS largas.</p>
            <p class="why"><span class="loc">nodo más profundo:</span> <code>{nodo}</code></p>
            <p class="why"><span class="loc">cadena desde el ancestro estable:</span><br><code>{ruta}</code></p>
            {wrap_txt}{ref}</div>""")

        if not bloques:
            bloques.append('<div class="issue ok"><h3>Sin problemas estructurales detectados ✓</h3></div>')

        # ── Módulo de idioma (siempre al final de cada scan) ──────────────────
        idi = h.get("idioma", {})
        palabras = idi.get("palabras", [])
        if palabras:
            chips = "".join(f"<code>{html.escape(p)}</code> " for p in palabras)
            bloques.append(f"""<div class="issue" style="border-color:#8E7CC3">
            <h3>Idioma mezclado — {len(palabras)} palabra(s) en {idi.get('intruso','?')}</h3>
            <p class="why">Por qué está mal: la UI debería estar 100% en
            <b>{idi.get('esperado','?')}</b>, pero se detectaron términos en
            <b>{idi.get('intruso','?')}</b>. Una interfaz con idioma mezclado
            confunde al usuario y suele indicar cadenas sin traducir (i18n incompleto).</p>
            <p class="fix">Solución: revisar las claves de traducción de esas
            palabras y asegurar que existan en ambos idiomas.</p>
            <p style="margin-top:8px">{chips}</p></div>""")
        elif idi:
            bloques.append(f'<div class="issue ok"><h3>Idioma consistente ✓ '
                           f'<span style="font-weight:400;color:#9FB2D0">(esperado: {idi.get("esperado","?")})</span></h3></div>')

        return (f'<div class="scan"><h2>{html.escape(h["etiqueta"])} '
                f'<span style="color:#7CE0D3;font-size:13px;font-weight:400">· {h["total_testids"]} testids · {h["timestamp"]}</span></h2>'
                + "".join(bloques) + "</div>")
# fin dom_audit
