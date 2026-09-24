"""
KRA-1526 · Parámetros de la etiqueta — Autorización IDOR (IdUser / IdAgent).

Todo lo configurable en un solo sitio; los casos no leen `os.getenv`.

## Qué prueba esta etiqueta (alcance: SOLO mono-agente)

El bug IDOR original: la búsqueda global (y varios endpoints que llevan IdUser /
IdAgent) devolvía datos de clientes de OTRO usuario/agencia al cambiar esos IDs
en el request. La corrección: el middleware valida en servidor.

Regla confirmada por DEV (Eduardo López), para mono-agente:
    · IdUser ajeno   → 403 (y sin datos)
    · IdAgent ajeno  → 403 (y sin datos)
    · IDs propios    → 200 (con datos)
El caso multi-agente (IdAgent no se valida) quedó fuera de alcance.

## Sin intervención manual

No se pega ningún curl. La corrida:
  1. Inicia sesión en Hermes 2 TEST sola (fixture de sesión persistente).
  2. Teclea el teléfono de prueba y CAPTURA en vivo el request real de
     `/customer/search` — de ahí salen el token (Authorization), el IdUser y el
     IdAgent PROPIOS y el body 200 de baseline.
  3. Reproduce las variantes (IdUser/IdAgent ajenos, regresión) y valida.
  4. Escribe el reporte HTML.

El token de Hermes dura ~20 min; por eso se toma fresco al inicio de cada corrida.
"""

import os
from pathlib import Path

from config import settings

# ── Identificadores de los casos (CP0X-Nombre: carpeta de evidencia y clave) ──
CP01 = "CP01-BusquedaGlobalPropios"
CP02 = "CP02-IdUserAjeno"
CP03 = "CP03-IdAgentAjeno"
CP04 = "CP04-RegresionRestaurar"
CP05 = "CP05-BalancePorCajero"
CP06 = "CP06-ReporteTransacciones"
CP07 = "CP07-RegresionProduccion"
# Multi-agente (opcional, KRA1526_MULTI=1) — se ejecutan en la agencia 0040.
CP08 = "CP08-MultiIdUserAjeno"
CP09 = "CP09-MultiIdAgentDiseno"

SUBTICKETS = {
    CP01: "KRA-1526 (búsqueda global — baseline propios)",
    CP02: "KRA-1526 (IDOR: IdUser ajeno rechazado)",
    CP03: "KRA-1526 (IDOR: IdAgent ajeno rechazado — mono-agente)",
    CP04: "KRA-1526 (regresión: restaurar IDs devuelve coincidencias)",
    CP05: "KRA-1526 (cobertura endpoint Balance por Cajero — IdUser+IdAgent)",
    CP06: "KRA-1526 (cobertura Reporte de transacciones — body + isMonoAgent)",
    CP07: "KRA-1526 (regresión en PRODUCCIÓN — opcional, KRA1526_PROD=1)",
    CP08: "KRA-1526 (multi-agente: IdUser ajeno rechazado — sí se valida)",
    CP09: "KRA-1526 (multi-agente: IdAgent distinto → 200 por diseño — no se valida)",
}

# ── API (TEST) ────────────────────────────────────────────────────────────────
# El host REAL se toma del request capturado; este es el default/documental que
# aparece en el reporte y el fallback si la captura no trae host.
BASE_URL = os.getenv(
    "KRA1526_BASE_URL",
    "https://test-hermes-api-containers.maxilabs.net").rstrip("/")

# Rutas de los endpoints que llevan IdUser / IdAgent (del análisis del 8-sep).
# La búsqueda global se CAPTURA (no se hardcodea su ruta); estas dos son para la
# cobertura extra y se construyen sobre el host capturado.
RUTA_BUSQUEDA = os.getenv("KRA1526_RUTA_BUSQUEDA", "/api/bff/customer/search")
# El balance por cajero vive en el host de LAMBDAS (no en api-containers) y su
# header de auth se llama `authorizer` (JWT sin 'Bearer'). Confirmado con el
# request real capturado en DevTools.
BALANCE_HOST = os.getenv("KRA1526_BALANCE_HOST",
                         "https://test-hermes-api-lambdas.maxilabs.net").rstrip("/")
RUTA_BALANCE_CAJERO = os.getenv("KRA1526_RUTA_BALANCE",
                                "/api/reports/balance_by_cashier")
# URL COMPLETA real del balance por cajero (host + path + query con IdUser e
# IdAgent PROPIOS), si se quiere fijar en vez de capturarla/inferirla. Se
# configura UNA vez (p. ej. en .env) y CP05 queda 100% automático en cada
# corrida. El endpoint real vive en el host de lambdas, no en api-containers.
BALANCE_URL = os.getenv("KRA1526_BALANCE_URL", "").strip()
RUTA_MONEY_TRANSFERS = os.getenv("KRA1526_RUTA_MT",
                                 "/api/transactions/reports/money_transfers")

# ── PRODUCCIÓN (CP07, opcional) ───────────────────────────────────────────────
# Por seguridad NO se ejecuta contra PROD salvo que se pida explícitamente. En
# PROD la búsqueda es de solo lectura (GET), pero se deja bajo bandera para no
# tocar producción sin querer. Requiere una sesión PROD válida.
PROD = os.getenv("KRA1526_PROD", "0").strip().lower() in ("1", "true", "si", "sí", "yes")
PROD_BASE_URL = os.getenv("KRA1526_PROD_BASE_URL",
                          "https://hermes2-api.maxiagentes.net").rstrip("/")

# ── MULTI-AGENTE (CP08/CP09, opcional y SEPARADO del run mono) ────────────────
# Se activa con KRA1526_MULTI=1 y corre en la AGENCIA 0040. Requiere las
# credenciales multiagente (PORTAL_USER_MULTI / MAXI_USER_M en el entorno).
# Reporte y resultados APARTE del mono para no mezclarlos.
MULTI = os.getenv("KRA1526_MULTI", "0").strip().lower() in ("1", "true", "si", "sí", "yes")
AGENCY_MULTI = os.getenv("KRA1526_AGENCY", "0040")
# IdAgent DISTINTO para el caso de diseño (CP09): un agente real diferente al de
# la agencia 0040. Por diseño el multi-agente NO valida el IdAgent → 200.
ID_AGENT_DISTINTO = os.getenv("KRA1526_IDAGENT_DISTINTO", "1242")

MODO = f"multi-agente (agencia {AGENCY_MULTI})" if MULTI else "mono-agente"

# ── Datos de negocio de la prueba ─────────────────────────────────────────────
# Teléfono de prueba del ticket. Con IDs propios devuelve varios clientes, todos
# con el IdAgent propio. El conteo REAL se toma del baseline capturado; 11 es la
# referencia observada el 8-sep (IdAgent 1242).
TELEFONO_PRUEBA = os.getenv("KRA1526_TELEFONO", "8118615244")
REGRESION_TOTAL_REF = int(os.getenv("KRA1526_TOTAL_REF", "11"))
REGRESION_IDAGENT_REF = os.getenv("KRA1526_IDAGENT_REF", "1242")

# Valores AJENOS a probar. Bien formados (numéricos) pero de otro usuario/agencia:
# el objetivo es un 403, no un 400 por formato.
ID_USER_AJENO = os.getenv("KRA1526_IDUSER_AJENO", "99999")
ID_AGENT_AJENO = os.getenv("KRA1526_IDAGENT_AJENO", "9999")

# Un bloqueo correcto responde con uno de estos (el catálogo exacto puede variar;
# 403 es el esperado). 401 = token vencido (no es bloqueo IDOR, es entorno).
CODIGOS_BLOQUEO = (401, 403)
# Códigos que significan «no hay nadie que rechace» (endpoint ausente/caído):
# no prueban nada → el caso sale FALLA con el motivo.
SIN_ENDPOINT = (0, 404, 405, 501, 502, 503, 504)

TIMEOUT = int(os.getenv("KRA1526_TIMEOUT", "30"))

# ── Evidencia ─────────────────────────────────────────────────────────────────
EVIDENCIA_BASE = settings.EVIDENCE_DIR / "KRA-1526"
# Reporte y acumulado SEPARADOS por perfil, para que el run mono y el multi no
# se pisen: cada runner escribe el suyo.
if MULTI:
    REPORTE = EVIDENCIA_BASE / "reporte_KRA-1526-multi.html"
    RESULTADOS = EVIDENCIA_BASE / "resultados_multi.json"
else:
    REPORTE = EVIDENCIA_BASE / "reporte_KRA-1526.html"
    RESULTADOS = EVIDENCIA_BASE / "resultados.json"
