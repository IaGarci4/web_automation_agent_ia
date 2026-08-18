"""
Diagnostics — captura DevTools para que desarrollo replique fallas.

Se engancha a la Page de Playwright y graba pasivamente:
  • Errores de CONSOLA (console.error, warnings)
  • Excepciones JS no atrapadas (pageerror)
  • Respuestas HTTP con error (status >= 400: 500, 404, 403...)
  • Requests fallidos (red caída, CORS, timeout)

Cuando un test falla — o cuando se invoca dump() — vuelca un "bundle de
diagnóstico": un JSON con todo lo capturado + un reporte HTML legible +
screenshot, de modo que desarrollo pueda reproducir el error exacto
(URL, payload, status, stack) sin depender de que QA lo repita a mano.

Uso (en un test o fixture):
    diag = Diagnostics(page)
    diag.attach()
    ...  # correr el flujo
    if diag.tiene_errores():
        diag.dump("src/tests/evidence/diag/cp02")
"""

import html
import json
import time
from pathlib import Path


class Diagnostics:
    def __init__(self, page, capturar_warnings: bool = False):
        self.page = page
        self.capturar_warnings = capturar_warnings
        self.consola = []     # {tipo, texto, ts}
        self.errores_js = []  # {mensaje, stack, ts}
        self.red = []         # {status, metodo, url, ts}
        self.fallidos = []    # {url, motivo, ts}
        self._attached = False

    # ── Enganche pasivo ───────────────────────────────────────────────────────

    def attach(self) -> None:
        if self._attached:
            return
        self._attached = True
        self.page.on("console", self._on_console)
        self.page.on("pageerror", self._on_pageerror)
        self.page.on("response", self._on_response)
        self.page.on("requestfailed", self._on_requestfailed)

    def _ts(self):
        return time.strftime("%H:%M:%S")

    def _on_console(self, msg):
        tipo = msg.type
        if tipo == "error" or (self.capturar_warnings and tipo == "warning"):
            self.consola.append({"tipo": tipo, "texto": msg.text[:500], "ts": self._ts()})

    def _on_pageerror(self, err):
        self.errores_js.append({
            "mensaje": str(err)[:300],
            "stack": (getattr(err, "stack", "") or "")[:1200],
            "ts": self._ts(),
        })

    async def _on_response(self, resp):
        """
        Captura respuestas con error (>=400) con TODO lo que un dev necesita para
        reproducir: status, status text, método, url, headers del request,
        payload del request, el CUERPO de la respuesta (donde el backend suele
        poner el mensaje/stack del 500) y un comando cURL listo para pegar en una
        terminal. Handler async para poder leer body/headers sin bloquear.
        """
        try:
            if resp.status < 400:
                return
            entry = {
                "status": resp.status,
                "status_text": getattr(resp, "status_text", "") or "",
                "metodo": resp.request.method,
                "url": resp.url[:300],
                "tipo": getattr(resp.request, "resource_type", "") or "",
                "ts": self._ts(),
            }
            # Payload del request (útil en 500/422 para reproducir).
            # Se guarda completo para el cURL y truncado para el reporte visual.
            pd_full = None
            try:
                pd_full = resp.request.post_data
                if pd_full:
                    entry["payload"] = pd_full[:800]
            except Exception:
                pass
            # Headers del request (incluye auth/cookies de sesión → reproducible)
            headers = {}
            try:
                headers = await resp.request.all_headers()
            except Exception:
                try:
                    headers = resp.request.headers
                except Exception:
                    headers = {}
            entry["req_headers"] = {k: v[:200] for k, v in (headers or {}).items()}
            # Cuerpo de la respuesta de error (mensaje/stack del backend)
            try:
                cuerpo = await resp.text()
                if cuerpo:
                    entry["cuerpo"] = cuerpo[:1000]
            except Exception:
                entry["cuerpo"] = ""
            # Comando cURL reproducible (url y payload COMPLETOS)
            entry["curl"] = self._build_curl(entry["metodo"], resp.url, headers, pd_full)
            self.red.append(entry)
        except Exception:
            pass

    @staticmethod
    def _build_curl(method: str, url: str, headers: dict, payload) -> str:
        """Construye un `curl` reproducible. Omite headers de transporte que
        curl calcula solo (content-length, host, connection) y escapa comillas."""
        skip = {"content-length", "host", "connection"}
        parts = [f"curl -X {method} '{url}'"]
        for k, v in (headers or {}).items():
            if k.lower() in skip or k.startswith(":"):
                continue
            v = str(v).replace("'", "'\\''")
            parts.append(f"-H '{k}: {v}'")
        if payload:
            p = str(payload).replace("'", "'\\''")
            parts.append(f"--data '{p}'")
        return " \\\n  ".join(parts)

    def _on_requestfailed(self, req):
        try:
            self.fallidos.append({
                "url": req.url[:300],
                "motivo": (req.failure or "desconocido"),
                "ts": self._ts(),
            })
        except Exception:
            pass

    # ── Consultas ─────────────────────────────────────────────────────────────

    def errores_servidor(self) -> list:
        """Respuestas 5xx — fallas del backend a reportar a desarrollo."""
        return [r for r in self.red if 500 <= r["status"] < 600]

    def tiene_errores(self) -> bool:
        return bool(self.errores_js or self.errores_servidor()
                    or self.consola or self.fallidos)

    def resumen(self) -> str:
        return (f"consola={len(self.consola)} jsError={len(self.errores_js)} "
                f"http4xx5xx={len(self.red)} reqFallidos={len(self.fallidos)}")

    # ── Volcado del bundle ────────────────────────────────────────────────────

    async def dump(self, carpeta: str, nombre: str = "diagnostico") -> dict:
        """Escribe JSON + HTML + screenshot. Retorna las rutas."""
        base = Path(carpeta)
        base.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")

        bundle = {
            "url_final": self.page.url,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "consola": self.consola,
            "errores_js": self.errores_js,
            "http_errores": self.red,
            "requests_fallidos": self.fallidos,
        }
        json_path = base / f"{nombre}_{stamp}.json"
        json_path.write_text(json.dumps(bundle, indent=2, ensure_ascii=False), encoding="utf-8")

        html_path = base / f"{nombre}_{stamp}.html"
        html_path.write_text(self._render_html(bundle), encoding="utf-8")

        png_path = base / f"{nombre}_{stamp}.png"
        try:
            await self.page.screenshot(path=str(png_path), full_page=True)
        except Exception:
            png_path = None

        return {"json": str(json_path), "html": str(html_path),
                "screenshot": str(png_path) if png_path else None}

    def _render_html(self, b: dict) -> str:
        def tabla(titulo, filas, cols, color, why):
            if not filas:
                return ""
            head = "".join(f"<th>{c}</th>" for c in cols)
            body = "".join("<tr>" + "".join(f"<td>{html.escape(str(f.get(c.lower().replace(' ', '_'), f.get(c, ''))))}</td>" for c in cols) + "</tr>" for f in filas)
            return (f'<div class="sec" style="border-color:{color}"><h2>{titulo} ({len(filas)})</h2>'
                    f'<p class="why">{why}</p>'
                    f'<table><tr>{head}</tr>{body}</table></div>')

        def curls(errores):
            bloques = []
            for r in errores:
                if not r.get("curl"):
                    continue
                bloques.append(
                    f'<div class="curl"><div class="curlhead">'
                    f'{r.get("status","")} {html.escape(str(r.get("metodo","")))} '
                    f'{html.escape(str(r.get("url","")))}</div>'
                    f'<pre>{html.escape(str(r["curl"]))}</pre></div>'
                )
            if not bloques:
                return ""
            return ('<div class="sec" style="border-color:#7CE0D3">'
                    '<h2>Comandos cURL para reproducir</h2>'
                    '<p class="why">Copia y pega en una terminal para reproducir el '
                    'request exacto: método, headers de sesión (auth/cookies) y payload.</p>'
                    + "".join(bloques) + '</div>')

        srv = self.errores_servidor()
        return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Diagnóstico de error — {html.escape(b.get('portal', 'portal'))}</title>
<style>
 body{{font-family:Segoe UI,Calibri,sans-serif;background:#0E1B33;color:#E8EEF7;margin:0;padding:32px}}
 h1{{color:#E84855;font-size:24px;margin:0 0 4px}} .sub{{color:#9FB2D0;margin:0 0 20px;font-size:13px}}
 .sec{{background:#16284A;border-left:4px solid #888;border-radius:8px;padding:14px 18px;margin:0 0 18px}}
 .sec h2{{margin:0 0 6px;font-size:16px;color:#fff}} .why{{color:#9FB2D0;font-size:12.5px;margin:0 0 10px}}
 table{{width:100%;border-collapse:collapse;font-size:12px}} th{{text-align:left;color:#7CE0D3;border-bottom:1px solid #2A3D63;padding:5px}}
 td{{padding:5px;border-bottom:1px solid #1d2f52;color:#CBD8EE;word-break:break-all}}
 .curl{{margin:10px 0}} .curlhead{{color:#F0A202;font-size:12px;margin:0 0 4px}}
 pre{{background:#0A1428;border:1px solid #2A3D63;border-radius:6px;padding:10px;font-size:11.5px;
      color:#B9E7DE;white-space:pre-wrap;word-break:break-all;margin:0}}
 .ok{{color:#2BB673}}
</style></head><body>
<h1>Diagnóstico para desarrollo</h1>
<p class="sub">URL final: <b>{html.escape(b['url_final'])}</b> · {b['timestamp']}<br>
Comparte este reporte: contiene status, URL, método, headers, payload, respuesta y cURL para reproducir el error sin repetir la prueba manual.</p>
{tabla("Errores de servidor (5xx)", srv, ["status", "metodo", "url", "payload", "cuerpo", "ts"], "#E84855", "Fallas del backend. Prioridad alta. 'cuerpo' = respuesta del servidor (mensaje/stack); 'payload' = datos enviados — con esto se reproduce el 500.")}
{tabla("Otros errores HTTP (4xx)", [r for r in b['http_errores'] if r not in srv], ["status", "metodo", "url", "payload", "cuerpo", "ts"], "#F0A202", "Permisos, rutas o validaciones. 'cuerpo' y 'payload' ayudan a identificar la causa.")}
{curls(b['http_errores'])}
{tabla("Excepciones JavaScript", b['errores_js'], ["mensaje", "stack", "ts"], "#E84855", "Errores no atrapados en el front. El stack indica el archivo y línea.")}
{tabla("Requests fallidos (red)", b['requests_fallidos'], ["url", "motivo", "ts"], "#F0A202", "Conexiones que nunca completaron: timeout, CORS o red caída.")}
{tabla("Consola", b['consola'], ["tipo", "texto", "ts"], "#888", "Mensajes de consola capturados durante la ejecución.")}
{'<p class="ok">Sin errores capturados ✓</p>' if not (srv or b['http_errores'] or b['errores_js'] or b['requests_fallidos'] or b['consola']) else ''}
</body></html>"""
