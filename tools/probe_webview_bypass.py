"""
Probe de bypass del interstitial 'Continúe en la aplicación de Maxi' (handoff al
Hermes2Agent) para el PARALELO WEB en equipos CON el HA instalado.

PROBLEMA
--------
En una máquina con el Hermes2Agent (HA) instalado, la web app de Hermes 2, al
cargar /transfers en un navegador NORMAL, muestra el interstitial y dispara el
protocolo `hermes2agent://` — AUNQUE la sesión SSO sea válida. Eso lanza el
diálogo nativo de Chrome "¿Abrir Hermes2Agent?" que Playwright no puede cerrar,
y bloquea el paralelo. El WebView2 del propio HA NO ve el interstitial porque el
app detecta que corre dentro del shell nativo.

HIPÓTESIS
---------
El app decide "estoy dentro del agente" por alguna huella del WebView2 — casi
siempre `window.chrome.webview` (que WebView2 inyecta) y/o el User-Agent. Si la
falsificamos en un Chromium aislado, el app cargaría /transfers directo, sin
interstitial ni diálogo — permitiendo N navegadores en paralelo, sin HA.

QUÉ HACE ESTE SCRIPT
--------------------
  PARTE A · Huella del HA (si el puerto CDP responde):
     se engancha al WebView2 del HA y saca navigator.userAgent, si existe
     window.chrome.webview, las claves de window.chrome, window.external, y
     cualquier global sospechoso. Esa es la "verdad" a imitar.

  PARTE B · Prueba candidatos de bypass en Chromium AISLADO (contexto propio,
     sin caché compartida) usando la sesión guardada gw0:
       1. baseline           — nada (para reproducir el interstitial)
       2. webview-shim        — inyecta window.chrome.webview + bloquea hermes2agent://
       3. agent-UA            — copia el User-Agent del HA
       4. shim + agent-UA     — ambos
     Para cada uno reporta: ¿llegó a la app (READY_SELECTOR)? ¿interstitial?
     ¿formulario de login? y la URL final.

USO
---
    # 1) Asegúrate de tener la sesión gw0 guardada (warm-up):
    #    python -m pytest -m cookies -v -s   (o -n 4)
    # 2) (opcional pero ideal) deja el HA corriendo con CDP para la PARTE A:
    #    Ejecutar_Hermes2Agent.bat  y entra a la app
    # 3) Corre el probe (headed para VER qué pasa):
    python tools/probe_webview_bypass.py
    #    headless:
    python tools/probe_webview_bypass.py --headless

Al final imprime una RECOMENDACIÓN con el candidato ganador. Pásamela y lo
horneo en _nuevo_contexto (conftest) para todo el paralelo.
"""
import argparse
import asyncio
import sys
from pathlib import Path

# Permite importar config.* al correr desde la raíz del repo.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import settings  # noqa: E402
from playwright.async_api import async_playwright  # noqa: E402


# ── Init scripts de bypass ───────────────────────────────────────────────────

# Shim de WebView2: crea window.chrome.webview ANTES de que corra el JS del app,
# imitando el canal que inyecta el WebView2 real. Además neutraliza cualquier
# intento de navegar al protocolo hermes2agent:// (por si el app lo dispara).
WEBVIEW_SHIM = r"""
(() => {
  try {
    if (!window.chrome) { window.chrome = {}; }
    if (!window.chrome.webview) {
      const _l = {};
      window.chrome.webview = {
        postMessage: function (m) { /* swallow */ },
        addEventListener: function (t, cb) { (_l[t] || (_l[t] = [])).push(cb); },
        removeEventListener: function (t, cb) {
          if (_l[t]) _l[t] = _l[t].filter(f => f !== cb);
        },
        dispatchEvent: function () { return true; },
        hostObjects: { sync: {}, options: { defaultSyncProxy: true } },
      };
    }
  } catch (e) { /* no-op */ }

  // Bloquear el handoff al escritorio: cualquier href/redirect a hermes2agent://
  try {
    document.addEventListener('click', function (e) {
      const a = e.target && e.target.closest && e.target.closest('a[href^="hermes2agent:"]');
      if (a) { e.preventDefault(); e.stopPropagation(); }
    }, true);
  } catch (e) { /* no-op */ }
})();
"""


async def _fingerprint_page(page):
    """Extrae la huella JS relevante de una página."""
    js = r"""
    () => {
      const chromeKeys = window.chrome ? Object.keys(window.chrome) : null;
      let webviewKeys = null;
      try {
        webviewKeys = (window.chrome && window.chrome.webview)
          ? Object.keys(window.chrome.webview) : null;
      } catch (e) { webviewKeys = 'err:' + e.message; }
      const sospechosos = Object.keys(window).filter(k =>
        /maxi|hermes|agent|webview|native|desktop|electron|wpf/i.test(k));
      return {
        userAgent: navigator.userAgent,
        hasChrome: !!window.chrome,
        chromeKeys: chromeKeys,
        hasWebview: !!(window.chrome && window.chrome.webview),
        webviewKeys: webviewKeys,
        hasExternal: typeof window.external !== 'undefined',
        externalKeys: (typeof window.external !== 'undefined')
          ? (function(){ try { return Object.keys(window.external); } catch(e){ return 'err'; } })() : null,
        globalsSospechosos: sospechosos,
        href: location.href,
      };
    }
    """
    try:
        return await page.evaluate(js)
    except Exception as e:
        return {"error": str(e)[:200]}


async def parte_a_huella_del_agente():
    print("\n" + "=" * 78)
    print("PARTE A · Huella del Hermes2Agent (WebView2) por CDP")
    print("=" * 78)
    cdp = settings.AGENT_CDP_URL
    import re as _re
    async with async_playwright() as pw:
        try:
            navegador = await pw.chromium.connect_over_cdp(cdp, timeout=5000)
        except Exception as e:
            print(f"  [!] No se pudo conectar al CDP del HA en {cdp}: {str(e)[:120]}")
            print("      (Deja el HA corriendo con Ejecutar_Hermes2Agent.bat y entra "
                  "a la app para tener esta huella. La PARTE B corre igual.)")
            return None
        try:
            ctx = navegador.contexts[0] if navegador.contexts else None
            if not ctx or not ctx.pages:
                print("  [!] El HA está corriendo pero no tiene páginas abiertas.")
                return None
            patron = _re.compile(settings.AGENT_PAGE_URL_RE, _re.I)
            page = next((p for p in ctx.pages if patron.search(p.url or "")), ctx.pages[0])
            fp = await _fingerprint_page(page)
            print(f"  URL del agente        : {fp.get('href')}")
            print(f"  User-Agent            : {fp.get('userAgent')}")
            print(f"  window.chrome.webview : {fp.get('hasWebview')}  keys={fp.get('webviewKeys')}")
            print(f"  window.chrome keys    : {fp.get('chromeKeys')}")
            print(f"  window.external       : {fp.get('hasExternal')}  keys={fp.get('externalKeys')}")
            print(f"  globals sospechosos   : {fp.get('globalsSospechosos')}")
            return fp
        finally:
            try:
                await navegador.close()   # cierra SOLO la conexión CDP, no el HA
            except Exception:
                pass


async def _evaluar_estado(page):
    """Devuelve (estado, url) — estado ∈ {app, interstitial, login, desconocido}."""
    import re as _re
    url = page.url
    # ¿App cargada?
    try:
        if settings.READY_SELECTOR:
            r = page.locator(settings.READY_SELECTOR).first
            if await r.count() and await r.is_visible():
                return "app", url
    except Exception:
        pass
    # ¿Interstitial?
    try:
        rx = _re.compile(r"contin[uú]e en la aplicaci|continue in the maxi|"
                         r"ser redirigido a la aplicaci|abrir maxi", _re.I)
        loc = page.get_by_text(rx).first
        if await loc.count() and await loc.is_visible():
            return "interstitial", url
    except Exception:
        pass
    # ¿Login?
    try:
        if settings.LOGIN_USER_TESTID:
            u = page.get_by_test_id(settings.LOGIN_USER_TESTID).first
        else:
            u = page.locator(settings.LOGIN_USER_SELECTOR).first
        if await u.count() and await u.is_visible():
            return "login", url
    except Exception:
        pass
    return "desconocido", url


async def _probar_candidato(pw, nombre, headless, storage, init_script=None,
                            user_agent=None):
    print(f"\n  ── Candidato: {nombre} " + "-" * (56 - len(nombre)))
    args = [
        "--ignore-certificate-errors",
        "--allow-insecure-localhost",
        "--disable-web-security",
        "--allow-running-insecure-content",
    ]
    navegador = await pw.chromium.launch(headless=headless, args=args)
    ctx_kwargs = {
        "viewport": {"width": 1366, "height": 768},
        "ignore_https_errors": True,
    }
    if storage and Path(storage).exists():
        ctx_kwargs["storage_state"] = str(storage)
    else:
        print(f"     [!] No existe la sesión {storage} — corre primero el warm-up "
              f"(python -m pytest -m cookies). El candidato correrá SIN sesión.")
    if user_agent:
        ctx_kwargs["user_agent"] = user_agent
    contexto = await navegador.new_context(**ctx_kwargs)
    if init_script:
        await contexto.add_init_script(init_script)
    page = await contexto.new_page()
    estado = "desconocido"
    url = ""
    try:
        await page.goto(settings.APP_URL, wait_until="domcontentloaded",
                        timeout=settings.TIMEOUT_NAVIGATION)
        # Dar tiempo a la SPA para montar / redirigir al interstitial.
        for _ in range(12):
            await page.wait_for_timeout(1000)
            estado, url = await _evaluar_estado(page)
            if estado in ("app", "interstitial", "login"):
                break
    except Exception as e:
        print(f"     [!] Error navegando: {str(e)[:140]}")
    icono = {"app": "✅ ENTRÓ A LA APP", "interstitial": "⛔ interstitial (handoff)",
             "login": "🔑 pidió login", "desconocido": "❓ desconocido"}[estado]
    print(f"     Resultado: {icono}")
    print(f"     URL final: {url}")
    try:
        await contexto.close()
        await navegador.close()
    except Exception:
        pass
    return nombre, estado


async def parte_b_probar_bypass(headless, agent_ua):
    print("\n" + "=" * 78)
    print("PARTE B · Candidatos de bypass en Chromium AISLADO (sesión gw0)")
    print("=" * 78)
    storage = settings.storage_state_por_worker("gw0")
    print(f"  APP_URL        : {settings.APP_URL}")
    print(f"  READY_SELECTOR : {settings.READY_SELECTOR}")
    print(f"  Sesión gw0     : {storage}  (existe={Path(storage).exists()})")

    candidatos = [
        ("baseline", None, None),
        ("webview-shim", WEBVIEW_SHIM, None),
    ]
    if agent_ua:
        candidatos.append(("agent-UA", None, agent_ua))
        candidatos.append(("shim + agent-UA", WEBVIEW_SHIM, agent_ua))
    else:
        print("  (Sin huella del HA → no se prueban candidatos de User-Agent; "
              "deja el HA corriendo para incluirlos.)")

    resultados = []
    async with async_playwright() as pw:
        for nombre, script, ua in candidatos:
            r = await _probar_candidato(pw, nombre, headless, storage,
                                        init_script=script, user_agent=ua)
            resultados.append(r)
    return resultados


async def main():
    ap = argparse.ArgumentParser(description="Probe de bypass del interstitial (HA).")
    ap.add_argument("--headless", action="store_true",
                    help="Corre headless (por defecto headed, para VER el resultado).")
    args = ap.parse_args()

    print("PROBE DE BYPASS · Hermes 2 (paralelo web con HA instalado)")
    print(f"  HERMES_ENV = {'PROD' if settings._ES_PROD else 'TEST'}")

    fp = await parte_a_huella_del_agente()
    agent_ua = fp.get("userAgent") if fp else None

    resultados = await parte_b_probar_bypass(args.headless, agent_ua)

    print("\n" + "=" * 78)
    print("RESUMEN / RECOMENDACIÓN")
    print("=" * 78)
    for nombre, estado in resultados:
        print(f"  {nombre:<18} → {estado}")
    ganadores = [n for n, e in resultados if e == "app"]
    if ganadores:
        # Preferir el más simple que funcione.
        orden = ["webview-shim", "shim + agent-UA", "agent-UA", "baseline"]
        ganador = min(ganadores, key=lambda n: orden.index(n) if n in orden else 99)
        print(f"\n  ✅ BYPASS ENCONTRADO: '{ganador}' entró a /transfers sin interstitial.")
        print("     Pásame este resultado y lo horneo en _nuevo_contexto (conftest)")
        print("     para que TODOS los workers del paralelo lo usen. Luego:")
        print("       python -m pytest -m sanity_general -n 3 --html=report.html --self-contained-html")
    else:
        if fp and fp.get("hasWebview") is False:
            print("\n  ⚠ El HA tampoco expone window.chrome.webview → la detección NO es")
            print("     por ese canal. Revisa la huella de PARTE A (UA/externals/globals)")
            print("     y probamos el siguiente candidato (UA, window.external, etc.).")
        else:
            print("\n  ⚠ Ningún candidato entró. Con la huella de PARTE A ajustamos el shim")
            print("     (o pasamos al plan de instancias aisladas del HA).")
    print()


if __name__ == "__main__":
    asyncio.run(main())
