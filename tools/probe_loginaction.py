"""
Prueba del BYPASS del autenticador 'kerberoswebviewprotection' de Keycloak.

DESCUBRIMIENTO
--------------
El interstitial es un autenticador custom de Keycloak (<kerberoswebviewprotection>)
cuyo único fin es empujar al escritorio cuando NO detecta el WebView del HA. La
página expone en un <script> la variable:

    loginAction = 'https://sso.maxilabs.net/auth/realms/Agents/login-actions/
                    authenticate?session_code=...&execution=...&client_id=...&tab_id=...'

Ese es el endpoint que CONTINÚA el flow OIDC. El WebView del HA lo llama solo; el
botón 'Abrir Maxisend' en cambio dispara hermes2agent:// (handoff al escritorio).

ESTE SCRIPT prueba, en una sesión aislada con la sesión gw0, distintas formas de
CONTINUAR el flow por navegador (sin escritorio) y reporta cuál llega a /transfers:

    A) GET  navegando a loginAction
    B) POST a loginAction (form submit vacío)
    C) Click en 'Abrir Maxisend' y ver si la MISMA pestaña avanza (bloqueando el
       protocolo hermes2agent://)

Cada intento parte de una carga FRESCA de /transfers (loginAction es de un solo
uso: session_code/execution/tab_id cambian por intento).

USO
---
    python tools/probe_loginaction.py            # headed
    python tools/probe_loginaction.py --headless
"""
import argparse
import asyncio
import html as _html
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

LAUNCH_ARGS = [
    "--ignore-certificate-errors", "--allow-insecure-localhost",
    "--disable-web-security", "--allow-running-insecure-content",
]


async def _es_app(page) -> bool:
    try:
        if settings.READY_SELECTOR:
            r = page.locator(settings.READY_SELECTOR).first
            return bool(await r.count()) and await r.is_visible()
    except Exception:
        pass
    return False


async def _es_handoff(page) -> bool:
    try:
        loc = page.get_by_text(_RE_INTER).first
        return bool(await loc.count()) and await loc.is_visible()
    except Exception:
        return False


async def _ir_al_handoff(page):
    """Carga /transfers y espera a caer en el handoff. Devuelve estado."""
    await page.goto(settings.APP_URL, wait_until="domcontentloaded",
                    timeout=settings.TIMEOUT_NAVIGATION)
    for _ in range(15):
        await page.wait_for_timeout(1000)
        if await _es_app(page):
            return "app"
        if await _es_handoff(page):
            return "handoff"
    return "desconocido"


async def _leer_login_action(page) -> str | None:
    try:
        val = await page.evaluate(
            "() => (typeof loginAction !== 'undefined') ? loginAction : null")
        if val:
            return _html.unescape(val)
    except Exception:
        pass
    # Fallback: el <span id=kcLoginUrl> también lo tiene.
    try:
        txt = await page.locator("#kcLoginUrl").first.text_content(timeout=2000)
        if txt:
            return _html.unescape(txt.strip())
    except Exception:
        pass
    return None


async def _estado_final(page, etiqueta):
    for _ in range(12):
        await page.wait_for_timeout(1000)
        if await _es_app(page):
            print(f"     [{etiqueta}] ✅ ENTRÓ A LA APP · URL={page.url[:90]}")
            return "app"
        u = page.url
        if re.search(r"[?&]code=", u):
            print(f"     [{etiqueta}] ✅ redirect con code= (login OK) · URL={u[:110]}")
            return "code"
        if await _es_handoff(page):
            print(f"     [{etiqueta}] ⛔ sigue en el handoff · URL={u[:90]}")
            return "handoff"
    print(f"     [{etiqueta}] ❓ estado desconocido · URL={page.url[:90]}")
    return "desconocido"


async def intento_A_get(ctx):
    print("\n  ── A) GET navegando a loginAction " + "-" * 40)
    page = await ctx.new_page()
    try:
        est = await _ir_al_handoff(page)
        if est == "app":
            print("     (Entró directo — sin handoff.)")
            return "app"
        la = await _leer_login_action(page)
        print(f"     loginAction={la[:110] if la else None}...")
        if not la:
            print("     [A] No se pudo leer loginAction.")
            return "sin_action"
        await page.goto(la, wait_until="domcontentloaded",
                        timeout=settings.TIMEOUT_NAVIGATION)
        return await _estado_final(page, "A")
    finally:
        await page.close()


async def intento_B_post(ctx):
    print("\n  ── B) POST a loginAction (form vacío) " + "-" * 36)
    page = await ctx.new_page()
    try:
        est = await _ir_al_handoff(page)
        if est == "app":
            print("     (Entró directo — sin handoff.)")
            return "app"
        la = await _leer_login_action(page)
        if not la:
            print("     [B] No se pudo leer loginAction.")
            return "sin_action"
        # Enviar un POST desde la misma página (mismo origen/cookies) con fetch y,
        # si responde con redirect/HTML de la app, navegar a la URL final.
        res = await page.evaluate(
            """async (url) => {
                try {
                  const r = await fetch(url, {method:'POST', headers:{
                    'Content-Type':'application/x-www-form-urlencoded'},
                    body:'', redirect:'follow', credentials:'include'});
                  return {ok:r.ok, status:r.status, url:r.url};
                } catch(e){ return {error:String(e)}; }
            }""", la)
        print(f"     POST → {res}")
        if isinstance(res, dict) and res.get("url"):
            await page.goto(res["url"], wait_until="domcontentloaded",
                            timeout=settings.TIMEOUT_NAVIGATION)
        return await _estado_final(page, "B")
    finally:
        await page.close()


async def intento_C_click(ctx):
    print("\n  ── C) Click 'Abrir Maxisend' (bloqueando el protocolo) " + "-" * 18)
    page = await ctx.new_page()
    # Bloquear la navegación al protocolo hermes2agent:// para que no cuelgue.
    await page.add_init_script("""
      document.addEventListener('click', function(e){
        const a = e.target && e.target.closest && e.target.closest('a[href^="hermes2agent:"]');
        if (a){ e.preventDefault(); e.stopPropagation(); }
      }, true);
    """)
    try:
        est = await _ir_al_handoff(page)
        if est == "app":
            print("     (Entró directo — sin handoff.)")
            return "app"
        try:
            btn = page.get_by_role(
                "button", name=re.compile(r"abrir\s*maxi|open\s*maxi", re.I)).first
            await btn.click(timeout=4000)
        except Exception as e:
            print(f"     [C] No se pudo clickear: {str(e)[:80]}")
        return await _estado_final(page, "C")
    finally:
        await page.close()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--headless", action="store_true")
    args = ap.parse_args()

    storage = settings.storage_state_por_worker("gw0")
    print(f"Sesión gw0: {storage} (existe={Path(storage).exists()})")
    if not Path(storage).exists():
        print("[!] Falta la sesión gw0 — corre: python -m pytest -m cookies -v -s")
        return
    print(f"APP_URL={settings.APP_URL}  READY_SELECTOR={settings.READY_SELECTOR}")

    resultados = {}
    async with async_playwright() as pw:
        for etq, fn in (("A-GET", intento_A_get),
                        ("B-POST", intento_B_post),
                        ("C-CLICK", intento_C_click)):
            navegador = await pw.chromium.launch(headless=args.headless, args=LAUNCH_ARGS)
            ctx = await navegador.new_context(
                viewport={"width": 1366, "height": 768},
                ignore_https_errors=True, storage_state=str(storage))
            try:
                resultados[etq] = await fn(ctx)
            except Exception as e:
                resultados[etq] = f"error:{str(e)[:80]}"
            finally:
                await ctx.close()
                await navegador.close()

    print("\n" + "=" * 78)
    print("RESUMEN")
    print("=" * 78)
    for k, v in resultados.items():
        print(f"  {k:<9} → {v}")
    ganador = next((k for k, v in resultados.items() if v in ("app", "code")), None)
    if ganador:
        print(f"\n  ✅ BYPASS: '{ganador}' completó el login por navegador (sin escritorio).")
        print("     Lo horneo en el helper de sesión para que cada worker lo use tras")
        print("     el goto(/transfers). Luego: pytest -m sanity_general -n 3 ...")
    else:
        print("\n  ⚠ Ninguno entró. Pásame la salida y ajusto (quizá loginAction")
        print("     necesita params extra del WebView, o vemos plan de instancias HA).")


if __name__ == "__main__":
    asyncio.run(main())
