"""
Volcado de la pantalla de handoff de Keycloak ('Continúe en la aplicación de
Maxi' / 'Abrir Maxisend') para descubrir cómo pasar al /transfers en el navegador.

CONTEXTO
--------
El probe anterior demostró que el interstitial lo sirve el SSO (Keycloak) en
    sso.maxilabs.net/auth/realms/Agents/protocol/openid-connect/auth?...
tras autenticar con la sesión guardada. En vez de devolver el `code` de OAuth a
https://test-hermes.maxilabs.net/transfers/?code=..., Keycloak muestra el handoff
y dispara el deep link `hermes2agent://...`.

HIPÓTESIS: ese deep link (o algún enlace/campo de la página) contiene el mismo
`code`+`state`. Si lo extraemos y navegamos el NAVEGADOR a
    https://test-hermes.maxilabs.net/transfers/?code=<code>&state=<state>
completamos el login OIDC en el navegador — sin escritorio, sin diálogo de Chrome.

QUÉ HACE
--------
  1. Lanza Chromium aislado con la sesión gw0.
  2. Navega a /transfers; espera la pantalla de handoff en el SSO.
  3. Vuelca TODO lo útil de esa página:
       - todos los <a href> (marca los hermes2agent:// y los que lleven code=)
       - todos los <button> (texto + onclick)
       - <form action> y sus inputs (name=value ocultos, p. ej. code/state)
       - <meta http-equiv=refresh>
       - <script> inline que mencione hermes2agent / code / redirect / location
       - texto visible de la página
  4. Guarda el HTML completo en reports/interstitial_dump.html para inspección.

USO
---
    python tools/probe_interstitial_dump.py            # headed
    python tools/probe_interstitial_dump.py --headless
"""
import argparse
import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import settings  # noqa: E402
from playwright.async_api import async_playwright  # noqa: E402

_RE_INTER = re.compile(
    r"contin[uú]e en la aplicaci|continue in the maxi|"
    r"ser redirigido a la aplicaci|abrir maxi", re.I)


async def _es_handoff(page) -> bool:
    try:
        loc = page.get_by_text(_RE_INTER).first
        return bool(await loc.count()) and await loc.is_visible()
    except Exception:
        return False


async def _es_app(page) -> bool:
    try:
        if settings.READY_SELECTOR:
            r = page.locator(settings.READY_SELECTOR).first
            return bool(await r.count()) and await r.is_visible()
    except Exception:
        pass
    return False


async def volcar(page):
    print("\n" + "=" * 78)
    print("VOLCADO DE LA PANTALLA DE HANDOFF")
    print("=" * 78)
    print(f"  URL: {page.url}")

    data = await page.evaluate(r"""
    () => {
      const abs = (h) => { try { return new URL(h, location.href).href; } catch(e){ return h; } };
      const links = [...document.querySelectorAll('a[href]')].map(a => ({
        href: a.getAttribute('href'), abs: abs(a.getAttribute('href')),
        text: (a.innerText || '').trim().slice(0, 60)
      }));
      const buttons = [...document.querySelectorAll('button, input[type=button], input[type=submit]')].map(b => ({
        text: (b.innerText || b.value || '').trim().slice(0, 60),
        onclick: b.getAttribute('onclick') || null,
        formaction: b.getAttribute('formaction') || null
      }));
      const forms = [...document.querySelectorAll('form')].map(f => ({
        action: f.getAttribute('action'),
        method: f.getAttribute('method'),
        inputs: [...f.querySelectorAll('input')].map(i => ({
          name: i.getAttribute('name'), type: i.getAttribute('type'),
          value: (i.getAttribute('value') || '').slice(0, 80)
        }))
      }));
      const metas = [...document.querySelectorAll('meta[http-equiv]')].map(m => ({
        httpEquiv: m.getAttribute('http-equiv'), content: m.getAttribute('content')
      }));
      const scripts = [...document.querySelectorAll('script:not([src])')]
        .map(s => s.textContent || '')
        .filter(t => /hermes2agent|code=|redirect|location\.|window\.open|\.href/i.test(t))
        .map(t => t.slice(0, 800));
      return { links, buttons, forms, metas, scripts,
               text: (document.body.innerText || '').slice(0, 1500),
               html_len: document.documentElement.outerHTML.length };
    }
    """)

    def _mark(s):
        s = s or ""
        tag = ""
        if "hermes2agent" in s.lower():
            tag += "  <<< DEEP LINK"
        if re.search(r"[?&]code=", s):
            tag += "  <<< TIENE code="
        if "test-hermes" in s.lower():
            tag += "  <<< WEB redirect"
        return tag

    print("\n  ── <a href> ─────────────────────────────────────────")
    for l in data["links"]:
        print(f"    text={l['text']!r}")
        print(f"      href={l['href']}{_mark(l['href'])}")
        if l["abs"] != l["href"]:
            print(f"      abs ={l['abs']}{_mark(l['abs'])}")

    print("\n  ── <button> / inputs ────────────────────────────────")
    for b in data["buttons"]:
        print(f"    text={b['text']!r} onclick={b['onclick']} formaction={b['formaction']}{_mark(b['onclick'])}{_mark(b['formaction'])}")

    print("\n  ── <form> ───────────────────────────────────────────")
    for f in data["forms"]:
        print(f"    action={f['action']} method={f['method']}{_mark(f['action'])}")
        for i in f["inputs"]:
            print(f"      input name={i['name']} type={i['type']} value={i['value']!r}{_mark(i['value'])}")

    print("\n  ── <meta refresh> ───────────────────────────────────")
    for m in data["metas"]:
        print(f"    {m['httpEquiv']} = {m['content']}{_mark(m['content'])}")

    print("\n  ── <script> inline relevantes ───────────────────────")
    for i, s in enumerate(data["scripts"]):
        print(f"    [script {i}] {s}{_mark(s)}")
        print("    " + "-" * 40)

    print("\n  ── texto visible ────────────────────────────────────")
    print("    " + data["text"].replace("\n", "\n    "))

    # Guardar HTML completo para inspección offline.
    try:
        html = await page.content()
        out = ROOT / "reports" / "interstitial_dump.html"
        out.parent.mkdir(exist_ok=True)
        out.write_text(html, encoding="utf-8")
        print(f"\n  HTML completo guardado en: {out}  ({data['html_len']} chars)")
    except Exception as e:
        print(f"\n  [!] No se pudo guardar el HTML: {str(e)[:120]}")

    # Buscar code/state en toda la página (URLs, hrefs, scripts).
    blob = str(data)
    codes = re.findall(r"[?&]code=([A-Za-z0-9._\-]+)", blob)
    states = re.findall(r"[?&]state=([A-Za-z0-9._\-]+)", blob)
    print("\n  ── code/state detectados en la página ───────────────")
    print(f"    code : {codes[:2] if codes else 'NINGUNO'}")
    print(f"    state: {states[:2] if states else 'NINGUNO'}")
    if codes:
        print("\n  ✅ La página EXPONE el code de OAuth → se puede completar el login")
        print("     navegando el navegador a /transfers/?code=...&state=... (sin escritorio).")
    else:
        print("\n  ⚠ No se ve el code en el DOM; puede venir por navegación a")
        print("     hermes2agent:// o generarse al pulsar el botón. Mira el HTML guardado")
        print("     y los <a>/<form> de arriba.")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--headless", action="store_true")
    args = ap.parse_args()

    storage = settings.storage_state_por_worker("gw0")
    print(f"Sesión gw0: {storage} (existe={Path(storage).exists()})")
    if not Path(storage).exists():
        print("[!] Falta la sesión gw0 — corre: python -m pytest -m cookies -v -s")
        return

    launch_args = [
        "--ignore-certificate-errors", "--allow-insecure-localhost",
        "--disable-web-security", "--allow-running-insecure-content",
    ]
    async with async_playwright() as pw:
        navegador = await pw.chromium.launch(headless=args.headless, args=launch_args)
        contexto = await navegador.new_context(
            viewport={"width": 1366, "height": 768},
            ignore_https_errors=True, storage_state=str(storage))
        page = await contexto.new_page()
        await page.goto(settings.APP_URL, wait_until="domcontentloaded",
                        timeout=settings.TIMEOUT_NAVIGATION)

        estado = "?"
        for _ in range(15):
            await page.wait_for_timeout(1000)
            if await _es_app(page):
                estado = "app"
                break
            if await _es_handoff(page):
                estado = "handoff"
                break
        print(f"\nEstado alcanzado: {estado} — URL: {page.url}")

        if estado == "app":
            print("  (Entró directo a la app — no hay handoff que volcar.)")
        else:
            await volcar(page)

        try:
            await contexto.close()
            await navegador.close()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
