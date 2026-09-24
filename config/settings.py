"""
Configuración GENÉRICA para automatizar CUALQUIER portal web.

A diferencia de la versión Hermes, aquí nada está fijo: el portal, la URL de
login y los selectores de usuario/contraseña/botón se definen por variables de
entorno (o un .env). Así el mismo motor sirve para Zeus, un CRM, un panel admin,
lo que sea.

Copia .env.example a .env y rellena los valores de tu portal.
"""

import os
import shutil
import tempfile
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
# ── Login de Chronos: CAMBIA POR AMBIENTE ───────────────────────────────────
#   TEST → formulario propio de Keycloak: usuario + contraseña (sin 2FA).
#   PROD → SSO de Google: correo Maxi + contraseña de Gmail + 2FA en el celular.
# El modo se detecta solo mirando la pantalla; se puede forzar con
# CHRONOS_LOGIN_MODE = auto | password | google.
CHRONOS_LOGIN_MODE = os.getenv("CHRONOS_LOGIN_MODE", "auto").strip().lower()

# Credenciales por ambiente (como en Hermes: PROD_* para producción).
CHRONOS_USER = (os.getenv("CHRONOS_USER_FORCE")
                or por_ambiente(os.getenv("CHRONOS_USER", ""),
                                os.getenv("PROD_CHRONOS_USER",
                                          os.getenv("CHRONOS_USER", ""))))
CHRONOS_PASS = (os.getenv("CHRONOS_PASS_FORCE")
                or por_ambiente(os.getenv("CHRONOS_PASS", ""),
                                os.getenv("PROD_CHRONOS_PASS",
                                          os.getenv("GMAIL_PASS",
                                                    os.getenv("CHRONOS_PASS", "")))))

# Agencia por ambiente (la usan CP04, CP07 y los flujos multiagencia).
AGENCY_CODE_ENV = os.getenv("AGENCY_CODE") or por_ambiente("0040-OK", "0020-TX")

# Fax configurado en la ficha de la agencia (lo valida el CP11).
AGENCY_FAX = os.getenv("AGENCY_FAX") or por_ambiente(
    "(469) 729-3817", "(866) 367-6295")

# ── KRA-1527 · Hardware Agent y volcados de memoria ─────────────────────────
# El agente de escritorio de Hermes y el proxy efímero que ejecuta el request.
HW_AGENT_PROC = os.getenv("HW_AGENT_PROC", "Hermes2Agent.exe")
HW_PROXY_PROC = os.getenv("HW_PROXY_PROC",
                          "Maxi.RulesOffice.Security.HttpProxy.exe")
# procdump (Sysinternals). Si no está, los tests auditan el tráfico igual y
# reportan el volcado como 'no disponible' en vez de fallar.
#
# Se BUSCA en varios sitios en vez de exigir una ruta exacta. Motivo práctico:
# la alternativa sin instalar nada es `rundll32 comsvcs.dll MiniDump`, que es
# la misma técnica que usa el malware de robo de credenciales — y sus volcados
# nos salen ilegibles de forma consistente. procdump está firmado por
# Microsoft y no despierta esa sospecha, así que conviene que baste con
# descomprimirlo en cualquier sitio razonable para que el proyecto lo encuentre.
def _buscar_procdump() -> Path:
    explicito = os.getenv("PROCDUMP_PATH")
    candidatas = [Path(os.path.expandvars(explicito))] if explicito else []
    candidatas += [
        PROJECT_ROOT / "tools" / "procdump.exe",
        PROJECT_ROOT / "tools" / "procdump64.exe",
        Path(r"C:\Tools\Sysinternals\procdump.exe"),
        Path(r"C:\Tools\procdump.exe"),
        Path.home() / "Downloads" / "procdump.exe",
        Path.home() / "Downloads" / "Procdump" / "procdump.exe",
    ]
    ruta_path = shutil.which("procdump") or shutil.which("procdump64")
    if ruta_path:
        candidatas.insert(0 if explicito else 0, Path(ruta_path))
    for c in candidatas:
        try:
            if c.is_file():
                return c
        except Exception:
            continue
    # Ninguna: se devuelve la preferida para que el mensaje de «no está» diga
    # una ruta concreta en la que el usuario pueda dejarlo.
    return candidatas[0] if candidatas else Path("procdump.exe")


PROCDUMP_PATH = _buscar_procdump()
# Dónde se escriben los volcados.
#
# HISTORIA, para no repetirla: primero apuntaban a %TEMP%; el inspector falló
# con «Permission denied» y lo atribuí al antivirus escaneando el archivo
# nuevo, así que los moví a una carpeta del proyecto. Empeoró — en el repo los
# .DMP quedaron RETENIDOS de forma permanente: ni se podían leer ni borrar
# (`WinError 5` sobre volcados de horas antes). Una carpeta de código está
# vigilada por el editor, el indexador y las reglas de protección de Defender;
# es el peor sitio posible para un archivo de 500 MB.
#
# Lección: el problema nunca fue «qué carpeta elijo yo», sino que yo elegía a
# ciegas. Ahora `memdump_helper` PRUEBA las candidatas (escribe, lee y borra un
# archivo pequeño) y usa la primera que funcione de verdad. Esto es solo la
# preferida; si no sirve, se cae a las siguientes sin que nadie intervenga.
#
# El volcado se escribe DIRECTAMENTE donde se queda como evidencia. Antes
# pasaba por %TEMP% y luego se movía; el paso intermedio no aportaba nada y sí
# podía fallar — si el movimiento no salía, el archivo desaparecía de un sitio
# sin llegar al otro. Escribir en el destino elimina ese modo de fallo entero.
#
# Va junto al resto de la evidencia (`reports/evidence/KRA-1527/`), no en el
# árbol de código: el .DMP es un artefacto de la corrida, igual que las
# capturas y el reporte HTML, y ahí es donde el analista ya sabe buscar.
# Se escribe literal en vez de reusar EVIDENCE_DIR porque esa constante se
# define más abajo en este mismo archivo.
KRA1527_RESPALDO_DIR = (PROJECT_ROOT / "reports" / "evidence" / "KRA-1527" /
                        "VolcadoMemoriaDMP")
DUMP_OUT_DIR = Path(os.path.expandvars(
    os.getenv("DUMP_OUT_DIR", str(KRA1527_RESPALDO_DIR))))
# Candidatas por orden de preferencia para el sondeo de `memdump_helper`, por
# si la carpeta de evidencia no fuera escribible en alguna máquina. %TEMP%
# queda solo como último recurso: allí el volcado no sirve de respaldo porque
# el sistema puede limpiarlo cuando quiera.
_TEMP_DUMPS = Path(tempfile.gettempdir()) / "kra1527_dumps"
DUMP_DIRS_CANDIDATAS = list(dict.fromkeys([
    DUMP_OUT_DIR,
    KRA1527_RESPALDO_DIR,
    PROJECT_ROOT / "reports" / "dumps",
    _TEMP_DUMPS,
]))
# Qué URLs se consideran "llamada al Hardware Agent".
# El agente escucha en local, pero NO siempre en un host que se llame
# 'localhost': es práctica común publicar un dominio propio que resuelve a
# 127.0.0.1 para poder usar un certificado TLS válido. Por eso el patrón
# incluye también los dominios del agente de Maxi. Si en tu máquina aparece
# otro, la auditoría lo lista como candidato al fallar y basta con ponerlo aquí.
HW_AGENT_URL_PATTERN = os.getenv(
    "HW_AGENT_URL_PATTERN",
    r"localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0|"
    r"maxiagentes|hermes-agent|agent2hermes|hermes2agent")
# Volcar memoria (requiere procdump). La auditoría de tráfico corre siempre.
KRA1527_DUMP = os.getenv("KRA1527_DUMP", "1").strip().lower() in (
    "1", "true", "si", "yes")
# Segundos a esperar a que un .DMP TERMINE de escribirse antes de analizarlo.
#
# Esto costó un ERROR que parecía del antivirus y no lo era: el inspector leyó
# un volcado de 487 MB y falló con «Permission denied»; al cerrar la corrida el
# MISMO archivo pesaba 511 MB. No estaba bloqueado, estaba a medio escribir.
# Un volcado *full* de medio giga tarda más de lo que parece, y quien lo está
# escribiendo lo tiene abierto en exclusiva, así que cualquier lectura rebota.
KRA1527_ESPERA_VOLCADO = int(os.getenv("KRA1527_ESPERA_VOLCADO", "300"))
# Conservar los .DMP tras la corrida (para depurar). Por defecto se borran al
# final: pesan cientos de MB y contienen datos sensibles.
KRA1527_CONSERVAR_DMP = os.getenv("KRA1527_CONSERVAR_DMP", "0").strip().lower() in (
    "1", "true", "si", "yes")
# Qué hacer si el proceso del Hardware Agent NO está corriendo en la máquina:
#   "omitir" (por defecto) → los casos se saltan con el motivo, sin gastar
#                            dos minutos de flujo para fallar al final.
#   "fallar"               → se ejecutan igual y fallan en exigir_comunicacion.
KRA1527_SIN_AGENTE = os.getenv("KRA1527_SIN_AGENTE", "omitir").strip().lower()
# Qué hacer si el volcado se CAPTURA pero no se puede LEER (lo tiene retenido
# el antivirus, típicamente).
#   0 (por defecto) → el caso FALLA. Es lo honesto: sin poder leer el volcado no
#                     se verificó el criterio del ticket, y un PASSED junto a un
#                     reporte en ERROR es exactamente el ruido que hace que los
#                     reportes dejen de leerse.
#   1               → el caso pasa con un aviso muy visible. Útil cuando lo que
#                     se está estabilizando es el FLUJO (que los nueve casos
#                     naveguen bien) y no se quiere que el problema del archivo
#                     tape los problemas de la interfaz.
KRA1527_TOLERAR_ERROR_VOLCADO = os.getenv(
    "KRA1527_TOLERAR_ERROR_VOLCADO", "0").strip().lower() in (
        "1", "true", "si", "yes")
# Empezar el reporte de cero. Por defecto el acumulado se conserva, para poder
# estabilizar un caso a la vez sin perder los resultados de los otros.
KRA1527_RESET = os.getenv("KRA1527_RESET", "0").strip().lower() in (
    "1", "true", "si", "yes")

# ── QMetry (Test Management for Jira Cloud) ─────────────────────────────────
# Para subir las EVIDENCIAS del sanity al Test Cycle correspondiente.
# La API autentica con la API Key de QMetry (header 'apiKey'); algunos endpoints
# piden además el Basic auth de Jira (correo + API token de Atlassian).
QMETRY_API_KEY   = os.getenv("QMETRY_API_KEY", "")
QMETRY_BASE_URL  = os.getenv("QMETRY_BASE_URL", "https://qtmcloud.qmetry.com")
QMETRY_PROJECT_ID = os.getenv("QMETRY_PROJECT_ID", "10030")     # BM
QMETRY_PROJECT_KEY = os.getenv("QMETRY_PROJECT_KEY", "BM")
# Basic auth de Jira (opcional; solo si la API lo exige)
QMETRY_JIRA_EMAIL = os.getenv("QMETRY_JIRA_EMAIL", "")
QMETRY_JIRA_TOKEN = os.getenv("QMETRY_JIRA_TOKEN", "")
# Test Cycle por ambiente (test / producción)
QMETRY_TEST_CYCLE = os.getenv("QMETRY_TEST_CYCLE") or por_ambiente(
    "BM-TR-1370", "BM-TR-1412")          # 'Sanity General TEST' / '... PROD'
# ── SWITCH MAESTRO de la integración con QMetry ─────────────────────────────
# APAGADO por defecto: la lógica está integrada en TODOS los casos del sanity,
# pero no se sube nada hasta que se encienda a propósito. Para encenderlo:
#     $env:QMETRY_UPLOAD="1"      (una corrida)
#     QMETRY_UPLOAD=1  en el .env (permanente)
#     o la casilla del módulo 'Sanity General' en la GUI.
# Nada se sube si el caso FALLA, aunque esté encendido (ver conftest.py).
QMETRY_UPLOAD = os.getenv("QMETRY_UPLOAD", "0").strip().lower() in ("1", "true", "si", "yes")
# Además de las evidencias, ESCRIBIR el resultado (Pass/Fail) de los pasos y de
# la ejecución en el ciclo. Es el veredicto REAL de pytest, no "tiene imagen".
QMETRY_RESULTADO = os.getenv("QMETRY_RESULTADO", "0").strip().lower() in ("1", "true", "si", "yes")


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

# ── Modo AGENTE / WebView2 (CDP) ────────────────────────────────────────────
# El Hermes2Agent es WPF .NET6 + WebView2 (Chromium embebido) que carga la MISMA
# web app. Cuando este modo está activo, la automatización NO lanza su propio
# navegador: se ENGANCHA por CDP al WebView2 ya autenticado (Kerberos) y reutiliza
# la página existente y el POM sin cambios. La captura de pantalla del agente está
# bloqueada (sale negra), así que en este modo la evidencia es solo DOM.
#
# Activar (una corrida):  $env:HERMES_AGENT_CDP="1"
# URL del endpoint CDP (debe coincidir con el puerto del .bat):
AGENT_CDP_URL = os.getenv("HERMES_AGENT_CDP_URL", "http://127.0.0.1:9222")
# "1"/"true" → usa la URL default; también se acepta pasar la URL directa en
# HERMES_AGENT_CDP (ej. "http://127.0.0.1:9333").
_agent_cdp_raw = os.getenv("HERMES_AGENT_CDP", "").strip()
AGENT_CDP = bool(_agent_cdp_raw) and _agent_cdp_raw.lower() not in ("0", "false", "no")
if _agent_cdp_raw.lower().startswith("http"):
    AGENT_CDP_URL = _agent_cdp_raw
# Patrón de la página objetivo dentro del WebView2 (la web app real).
AGENT_PAGE_URL_RE = os.getenv(
    "HERMES_AGENT_PAGE_RE", r"test-hermes\.maxilabs\.net|/transfers")

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