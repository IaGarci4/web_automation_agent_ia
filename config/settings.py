"""
Configuración GENÉRICA para automatizar CUALQUIER portal web.

A diferencia de la versión Hermes, aquí nada está fijo: el portal, la URL de
login y los selectores de usuario/contraseña/botón se definen por variables de
entorno (o un .env). Así el mismo motor sirve para Zeus, un CRM, un panel admin,
lo que sea.

Copia .env.example a .env y rellena los valores de tu portal.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

# Cargar .env si existe (opcional)
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:
    pass


# ── Ambiente (test / producción) ────────────────────────────────────────────
# Muchos casos (bill payment, recargas, etc.) usan DATOS distintos según el
# ambiente. ENV lo controla (default 'test'). Cambia con:  $env:HERMES_ENV="prod"
ENV = os.getenv("HERMES_ENV", os.getenv("ENV", "test")).strip().lower()
_ES_PROD = ENV in ("prod", "production", "produccion", "producción")


def por_ambiente(valor_test, valor_prod):
    """Devuelve `valor_test` si ENV=test (default) o `valor_prod` si ENV=prod.

    Uso en un test:
        from config import settings
        BILLER = settings.por_ambiente("Comcast XFINITY SameDay",
                                       "Comcast XFINITY Cable Todas las Cuentas")
    """
    return valor_prod if _ES_PROD else valor_test


# ═════════════════════════════════════════════════════════════════════════════
#  URLs POR AMBIENTE (equivalente a settings_test.py / settings_prod.py del
#  repo QA viejo, pero en UN solo lugar: se resuelve solo según HERMES_ENV).
#  Cualquiera se puede sobreescribir con su variable de entorno.
# ═════════════════════════════════════════════════════════════════════════════

# ── Hermes 2 ────────────────────────────────────────────────────────────────
HERMES_URL = por_ambiente(
    "https://test-hermes.maxilabs.net/transfers",
    "https://hermes.maxiagentes.net/transfers/")
HERMES_BASE_URL = os.getenv("HERMES_BASE_URL") or por_ambiente(
    "https://test-hermes.maxilabs.net/",
    "https://hermes.maxiagentes.net/")
HERMES_TRANSACTIONS_URL = os.getenv("HERMES_TRANSACTIONS_URL") or por_ambiente(
    "https://test-hermes.maxilabs.net/reports/Transactions",
    "https://hermes.maxiagentes.net/reports/Transactions")

# ── Chronos (back office) ───────────────────────────────────────────────────
CHRONOS_URL = os.getenv("CHRONOS_URL") or por_ambiente(
    "https://test-apps.maxilabs.net/Chronos/Frontend/home",
    "https://corporateapp.maxiagentes.net/application/home")
# Patrón de URL que confirma que Chronos cargó (para wait_for_url tras el login).
CHRONOS_READY_URL = os.getenv("CHRONOS_READY_URL") or por_ambiente(
    "**/Chronos/Frontend/home*", "**/application/home*")
# Chronos entra por SSO de Google: correo Maxi + contraseña de Gmail.
CHRONOS_USER = os.getenv("CHRONOS_USER", "")
CHRONOS_PASS = os.getenv("CHRONOS_PASS", os.getenv("GMAIL_PASS", ""))

# Agencia por ambiente (la usan CP04, CP07 y los flujos multiagencia).
AGENCY_CODE_ENV = os.getenv("AGENCY_CODE") or por_ambiente("0040-OK", "0020-TX")

# ── Portal objetivo (genérico) ──────────────────────────────────────────────
# Nombre corto del portal — se usa para nombrar la sesión guardada y carpetas.
PORTAL_NAME = os.getenv("PORTAL_NAME", "portal")

# URL a la que se navega al iniciar. Se DERIVA del ambiente (HERMES_ENV) para
# que cambiar test↔prod no dependa de editar el .env. Para apuntar a otro portal
# (motor genérico) usar APP_URL_FORCE.
APP_URL = os.getenv("APP_URL_FORCE") or HERMES_URL

# Patrón de URL que indica que YA estás dentro (sesión válida). Si la URL final
# coincide con esto, se omite el login. Ej: "**/dashboard**".
READY_URL_PATTERN = os.getenv("READY_URL_PATTERN", "")

# ── Credenciales (por .env, nunca hardcodeadas) ─────────────────────────────
# Se resuelven POR AMBIENTE, como en el repo QA viejo pero sin duplicar código:
#   TEST → MAXI_USER / MAXI_PSWD        · multi: MAXI_USER_M
#   PROD → PROD_MAXI_USER / PROD_MAXI_PSWD · multi: PROD_MAXI_USER_M
# PORTAL_USER/PORTAL_PASS siguen funcionando y tienen PRIORIDAD (compatibilidad).
PORTAL_USER = (os.getenv("PORTAL_USER")
               or por_ambiente(os.getenv("MAXI_USER", ""),
                               os.getenv("PROD_MAXI_USER", "")))
PORTAL_PASS = (os.getenv("PORTAL_PASS")
               or por_ambiente(os.getenv("MAXI_PSWD", ""),
                               os.getenv("PROD_MAXI_PSWD", "")))

# ── Selectores de login (configurables por portal) ──────────────────────────
LOGIN_USER_SELECTOR   = os.getenv("LOGIN_USER_SELECTOR", "input[name='username'], #username, input[type='email']")
LOGIN_PASS_SELECTOR   = os.getenv("LOGIN_PASS_SELECTOR", "input[name='password'], #password, input[type='password']")
LOGIN_SUBMIT_SELECTOR = os.getenv("LOGIN_SUBMIT_SELECTOR", "button[type='submit'], #login, button:has-text('Login'), button:has-text('Iniciar')")

# data-testid opcionales (tienen prioridad si se definen)
LOGIN_USER_TESTID   = os.getenv("LOGIN_USER_TESTID", "")
LOGIN_PASS_TESTID   = os.getenv("LOGIN_PASS_TESTID", "")
LOGIN_SUBMIT_TESTID = os.getenv("LOGIN_SUBMIT_TESTID", "")

# Selector que confirma que la app cargó tras el login (opcional). Ej: "nav".
READY_SELECTOR = os.getenv("READY_SELECTOR", "")

# ── Timeouts (ms) — Playwright actúa en cuanto el elemento existe ────────────
TIMEOUT_NAVIGATION = int(os.getenv("TIMEOUT_NAVIGATION", "60000"))
TIMEOUT_ELEMENT    = int(os.getenv("TIMEOUT_ELEMENT", "30000"))
TIMEOUT_SHORT      = int(os.getenv("TIMEOUT_SHORT", "5000"))
TIMEOUT_MODAL      = int(os.getenv("TIMEOUT_MODAL", "30000"))
TIMEOUT_READY      = int(os.getenv("TIMEOUT_READY", "10000"))
TIMEOUT_2FA        = int(os.getenv("TIMEOUT_2FA", "180000"))  # 2FA manual la 1ª vez

# ── Playwright ──────────────────────────────────────────────────────────────
PW_HEADLESS = os.getenv("PW_HEADLESS", "false").lower() == "true"
PW_SLOW_MO  = int(os.getenv("PW_SLOW_MO", "0"))
PW_VIDEO    = os.getenv("PW_VIDEO", "false").lower() == "true"

# ── Rutas de salida ─────────────────────────────────────────────────────────
REPORTS_DIR  = PROJECT_ROOT / "reports"
EVIDENCE_DIR = REPORTS_DIR / "evidence"
AUDIT_DIR    = REPORTS_DIR / "audit"    # auditoría de estructura del DOM
DIAG_DIR     = REPORTS_DIR / "diag"     # reportes de error (consola/HTTP/cURL)

# ── Sesión persistente (login guardado, reutilizado por logged_page) ────────
# Un archivo de storage_state por portal (PORTAL_NAME), para no pisar la
# sesión de un portal con la de otro si se prueban varios desde el mismo repo.
SESSION_DIR   = PROJECT_ROOT / "session_state"
STORAGE_STATE = SESSION_DIR / f"{PORTAL_NAME}_storage_state.json"

# ── Multi-agente (usuario que opera VARIAS agencias) ────────────────────────
# Usuario/clave del perfil multiagente (para CPs como CP04). Sesión guardada en
# archivo APARTE para no pisar la sesión mono. AGENCY_CODE = agencia a operar.
PORTAL_USER_MULTI = (os.getenv("PORTAL_USER_MULTI")
                     or por_ambiente(os.getenv("MAXI_USER_M", ""),
                                     os.getenv("PROD_MAXI_USER_M", "")))
PORTAL_PASS_MULTI = (os.getenv("PORTAL_PASS_MULTI")
                     or por_ambiente(os.getenv("MAXI_PSWD", ""),
                                     os.getenv("PROD_MAXI_PSWD", "")))
AGENCY_CODE         = AGENCY_CODE_ENV     # 0040-OK (test) · 0020-TX (prod)
# Cookies/sesión de Chronos (archivos APARTE de los de Hermes).
# Chronos entra por SSO de Google, que LIMITA los intentos de login: la sesión se
# guarda y se reutiliza para NO volver a autenticarse en cada corrida.
STORAGE_STATE_CHRONOS = SESSION_DIR / "chronos_storage_state.json"
CHRONOS_COOKIES = SESSION_DIR / "chronos_cookies.json"
STORAGE_STATE_MULTI = SESSION_DIR / f"{PORTAL_NAME}_multi_storage_state.json"