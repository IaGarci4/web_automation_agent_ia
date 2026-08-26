"""
Login MANUAL de Chronos (SSO de Google) → guarda la sesión para los tests.

Por qué existe: el SSO de Google LIMITA los intentos de login. Con esta
herramienta entras UNA vez a mano (con calma, 2FA incluido) y la sesión queda
guardada en `session_state/chronos_cookies.json`. A partir de ahí los tests
(CP07 y los demás con Chronos) reutilizan esa sesión y NO intentan autenticarse.

Uso:
    python tools/login_chronos.py                 # ambiente del .env (HERMES_ENV)
    python tools/login_chronos.py --prod          # forzar producción
    python tools/login_chronos.py --minutos 10    # más tiempo para el 2FA
    python tools/login_chronos.py --verificar     # solo comprobar si la sesión vive

Qué hace:
  1. Abre un Chrome visible en la URL de Chronos del ambiente activo.
  2. Si ya hay cookies guardadas, las reutiliza (quizá ni tengas que loguearte).
  3. Espera a que ENTRES tú (detecta el botón 'Menu' del home de Chronos).
  4. Guarda las cookies de Chronos + SSO y cierra.
"""

import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# El ambiente debe fijarse ANTES de importar settings.
if "--prod" in sys.argv:
    os.environ["HERMES_ENV"] = "prod"
elif "--test" in sys.argv:
    os.environ["HERMES_ENV"] = "test"

from playwright.async_api import async_playwright        # noqa: E402
from config import settings                              # noqa: E402
from src.sanity_general import chronos as CR             # noqa: E402


def _arg(nombre: str, defecto):
    if nombre in sys.argv:
        try:
            return sys.argv[sys.argv.index(nombre) + 1]
        except IndexError:
            pass
    return defecto


async def main() -> int:
    minutos = int(_arg("--minutos", "3"))
    solo_verificar = "--verificar" in sys.argv
    solo_manual = "--manual" in sys.argv     # no teclear credenciales, todo a mano

    print("─" * 70)
    print(f"  Chronos · ambiente {settings.ENV.upper()}")
    print(f"  URL      : {settings.CHRONOS_URL}")
    print(f"  Sesión   : {settings.CHRONOS_COOKIES}")
    print("─" * 70)

    async with async_playwright() as pw:
        navegador = await pw.chromium.launch(headless=False, slow_mo=0)
        contexto = await navegador.new_context(
            viewport={"width": 1366, "height": 768})
        pagina = await contexto.new_page()
        try:
            # 1) Reutilizar lo que ya haya guardado
            await CR.cargar_cookies(contexto)
            await pagina.goto(settings.CHRONOS_URL, wait_until="domcontentloaded",
                              timeout=settings.TIMEOUT_NAVIGATION)

            if await CR.sesion_activa(pagina):
                print("\n✓ La sesión guardada SIGUE VIVA — no hace falta loguearse.")
                await CR.guardar_cookies(contexto)       # refresca expiración
                return 0

            if solo_verificar:
                print("\n✖ La sesión NO está activa. Corre sin --verificar para "
                      "iniciarla a mano.")
                return 1

            # 2) Login AUTOMÁTICO: el bot teclea las credenciales; tú solo
            #    apruebas el acceso en el celular (2FA).
            if not solo_manual:
                if not settings.CHRONOS_USER or not settings.CHRONOS_PASS:
                    print("\n⚠  Faltan CHRONOS_USER / CHRONOS_PASS en el .env — "
                          "tendrás que loguearte a mano.")
                else:
                    print(f"\n🤖 Ingresando tus credenciales ({settings.CHRONOS_USER})…")
                    print("📱 Cuando te llegue la notificación, APRUEBA el acceso "
                          "en tu celular (hay hasta "
                          f"{CR.TIMEOUT_2FA // 60000} min).\n")
                    if await CR.login_google(pagina):
                        await CR.guardar_cookies(contexto)
                        print("\n✅ Listo. Los tests de Chronos ya NO harán login.")
                        print("   Vuelve a correr esta herramienta cuando la sesión expire.")
                        return 0
                    print("\n⚠  El login automático no se confirmó — te dejo "
                          "terminar a mano en la ventana abierta.")

            # 3) Respaldo manual: el usuario completa lo que falte
            print(f"\n👉 Termina el inicio de sesión en la ventana que se abrió "
                  f"(tienes {minutos} min).")
            print("   Cuando veas el home de Chronos, esto lo detecta solo.\n")
            # Tiempo REAL (monotonic): antes se sumaban 3 s por vuelta pero cada
            # chequeo de sesión podía tardar 10 s más → la espera real era ~4x la
            # declarada y parecía que nunca terminaba.
            limite = minutos * 60
            inicio = time.monotonic()
            ultimo_aviso = 0
            while True:
                transcurrido = time.monotonic() - inicio
                if transcurrido >= limite:
                    break
                # Chequeo RÁPIDO (1.5 s) para no inflar el tiempo de espera.
                try:
                    if await pagina.locator(CR.TOOLBAR_MENU).first.is_visible(timeout=1_500):
                        print("✓ Sesión detectada.")
                        await CR.guardar_cookies(contexto)
                        print("\n✅ Listo. Los tests de Chronos ya NO harán login.")
                        print("   Vuelve a correr esta herramienta cuando la sesión expire.")
                        return 0
                except Exception:
                    pass
                await pagina.wait_for_timeout(2_000)
                if transcurrido - ultimo_aviso >= 30:
                    ultimo_aviso = transcurrido
                    restante = int(limite - transcurrido)
                    print(f"   … esperando ({int(transcurrido)}s transcurridos, "
                          f"{restante // 60}m {restante % 60}s restantes) "
                          f"— Ctrl+C para cancelar")
            print("\n✖ Se agotó el tiempo sin detectar la sesión.")
            print("   Vuelve a intentar con más margen: --minutos 15")
            return 1
        finally:
            try:
                await contexto.close()
                await navegador.close()
            except Exception:
                pass


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\n👋 Cancelado.")
        sys.exit(130)
