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


# ── Portal objetivo (genérico) ──────────────────────────────────────────────
# Nombre corto del portal — se usa para nombrar la sesión guardada y carpetas.
PORTAL_NAME = os.getenv("PORTAL_NAME", "portal")

# URL a la que se navega al iniciar (la app o su pantalla de login).
APP_URL = os.getenv("APP_URL", "https://example.com/login")

# Patrón de URL que indica que YA estás dentro (sesión válida). Si la URL final
# coincide con esto, se omite el login. Ej: "**/dashboard**".
READY_URL_PATTERN = os.getenv("READY_URL_PATTERN", "")

# ── Credenciales (por .env, nunca hardcodeadas) ─────────────────────────────
PORTAL_USER = os.getenv("PORTAL_USER", "")
PORTAL_PASS = os.getenv("PORTAL_PASS", "")

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
PORTAL_USER_MULTI   = os.getenv("PORTAL_USER_MULTI", "")
PORTAL_PASS_MULTI   = os.getenv("PORTAL_PASS_MULTI", "")
AGENCY_CODE         = os.getenv("AGENCY_CODE", "0040-OK")
STORAGE_STATE_MULTI = SESSION_DIR / f"{PORTAL_NAME}_multi_storage_state.json"