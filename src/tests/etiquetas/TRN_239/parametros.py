"""
TRN-239 · Parámetros de la etiqueta — API Lunex (migración BE Urano → FastAPI).

Todo lo configurable en un solo sitio. Los casos no leen `os.getenv`.

## La URL: zeus-services, confirmada contra el entorno

    https://zeus-services.maxilabs.net/api/v1/lunex/
        Payments/RegisterTransaction
        Payments/CancelTransaction

### Cómo se llegó aquí, para que no se repita

Había dos candidatas y se eligió mal:

  · `docs/TRN-239_Postman_Guia_y_Casos.md` afirmaba
    `https://test-apps.maxilabs.net/Argo/` y lo daba por **«verificado en
    campo: Argo/Payments/RegisterTransaction responde»**.
  · La colección Postman y el runner apuntaban a `zeus-services`.

Se creyó al documento por la palabra «verificado», y estaba mal. Argo
devuelve **404 en todas las rutas** de Payments —comprobado: el host
contesta, luego no es la VPN—. Lo que «respondía» era el servidor diciendo
que ahí no hay nada.

La lección es del tipo que ya nos mordió con la ACL y con `Get-Printer`:
**una afirmación escrita no es una comprobación.** La colección tenía razón
porque salía del entorno; el documento se equivocaba porque salía de la
memoria de alguien. Cuando dos fuentes se contradigan, gana la que se pueda
ejecutar.

Argo sí es el gateway del back end de Hermes —ahí viven `Argo/auth` y
`Argo/api/MoneyTransfer/*`— pero la API Lunex no está montada bajo él.

El legacy .NET sigue en `https://test-uranus.maxilabs.net/Payments/LunexService.svc`
y aparece en la cabecera SOAP `a:To` de la colección original. **No es la API
migrada**; queda como referencia para el comparativo de paridad.

## Los 8 casos

Los 14 de la guía se consolidaron en 8 agrupando lo que comparte evidencia. La
trazabilidad a los subtickets se conserva en `SUBTICKETS`.
"""

import os
from pathlib import Path

from config import settings

# ── Identificadores de los casos ────────────────────────────────────────────
# Formato CP0X-NombreDelCaso: nombre de la carpeta de evidencias y clave del
# reporte, igual que en KRA-1527.
CP01 = "CP01-Healthcheck"
CP02 = "CP02-AltaRegisterTransaction"
CP03 = "CP03-CancelacionTransaccion"
CP04 = "CP04-NegativoAutenticacion"
CP05 = "CP05-NegativosValidacion"
CP06 = "CP06-ComisionesDtuItu"
CP07 = "CP07-StatusFailt"
CP08 = "CP08-IntegridadDatos"
CP09 = "CP09-CatalogoErrores"

# De qué subticket sale cada caso. Va al reporte para que quien lo lea pueda
# saltar al ticket sin preguntar.
SUBTICKETS = {
    CP01: "TRN-569 (healthcheck)",
    CP02: "TRN-239 (alta SOAP/JSON y paridad)",
    CP03: "TRN-239 (cancelación)",
    CP04: "TRN-293 (auth inválida sin stack trace)",
    CP05: "TRN-294 (validación) · TRN-300 (error controlado al cancelar)",
    CP06: "TRN-295 / TRN-296 (comisiones DTU e ITU)",
    CP07: "TRN-239 (rechazo de Status inválido; real: SUCCESS/VOID)",
    CP08: "TRN-239 (integridad de datos e idempotencia)",
    CP09: "TRN-239 (catálogo de Errorcodes del requerimiento)",
}

# ── API ─────────────────────────────────────────────────────────────────────
BASE_URL = os.getenv(
    "TRN239_BASE_URL",
    "https://zeus-services.maxilabs.net/api/v1/lunex/").rstrip("/") + "/"

RUTA_REGISTER = os.getenv("TRN239_RUTA_REGISTER", "Payments/RegisterTransaction")
RUTA_CANCEL = os.getenv("TRN239_RUTA_CANCEL", "Payments/CancelTransaction")
# En la primera corrida esta ruta devolvió 404 con el host respondiendo. Queda
# parametrizada porque el preflight tantea variantes y te dice cuál contesta.
RUTA_HEALTH = os.getenv("TRN239_RUTA_HEALTH", "healthcheck")

# Legacy .NET, solo para el comparativo de paridad. NO es la API migrada.
URL_LEGACY = os.getenv("TRN239_URL_LEGACY",
                       "https://test-uranus.maxilabs.net/Payments/LunexService.svc")

TIMEOUT = int(os.getenv("TRN239_TIMEOUT", "30"))

# ── Credenciales ────────────────────────────────────────────────────────────
# Md5 = MD5(Login + Password + Key), hex en minúsculas, UTF-8.
LOGIN = os.getenv("TRN239_LOGIN", "Lun3xProdUser")
PASSWORD = os.getenv("TRN239_PASSWORD", "MaxiLun3x1520")
ENTITY = os.getenv("TRN239_ENTITY", "MX01D3643A")
# ⚠ `ID_AGENT` era 1242 y ESE era el Errorcode 15.
#
# `ExternalID` se calcula como `M{IdAgent × IdUser}S{IdUser}`. Con 1242 salía
# `M16755822S13491`, que apunta a un agente que no existe. La API lo busca,
# no lo encuentra, y devuelve un error interno — pasa la validación de
# formato (por eso nunca dio Errorcode 5) y falla al resolverlo.
#
# El valor bueno se dedujo de una transacción REAL en lunex.TransferLN, una
# SUCCESS del 10-sep:
#
#     ExternalID = M120312738S13491   →   120312738 ÷ 13491 = 8918
#
# El 1242 sí existe, pero en filas de 2023 emparejado con OTRAS entidades
# (MX01D4829B, MX01D2100A). La combinación 1242 + 13491 no corresponde a
# ningún agente: era una mezcla de valores heredados de dos sitios distintos.
ID_AGENT = int(os.getenv("TRN239_ID_AGENT", "8918"))
ID_USER = int(os.getenv("TRN239_ID_USER", "13491"))
CID = os.getenv("TRN239_CID", "797dd3a85456df7f014efd19320eefdw")

# ── Estados del requerimiento ────────────────────────────────────────────────────
# La Integration Guide (Confluence, ago-2026) es explícita sobre los estados:
#
#   RegisterTransaction · Status: "SUCCESS or VOID — Other values are rejected"
#   CancelTransaction   · Status: "Cancelled"
#
# Por eso:
ESTADO_ALTA = "SUCCESS"

# Los ÚNICOS estados reales son:
#     SUCCESS  → la transacción se aceptó
#     VOID     → la transacción falló / se canceló
# `FAILT` NO es un estado real: es un string inventado (la API acepta cualquier
# string, así que hay que probar que RECHACE los inválidos). Se conserva SOLO
# como entrada inválida para el CP07 —una validación negativa—: se manda FAILT
# esperando el rechazo (Errorcode 9). Si la API lo acepta, esa validación es la
# que nos avisa del defecto (D1). Por eso NO se elimina el caso; lo que se
# corrige es el nombre: no es «el estado de fallo» (ese es VOID), es un valor
# inválido de prueba.
STATUS_INVALIDO_PRUEBA = os.getenv("TRN239_STATUS_INVALIDO", "FAILT")

# CancelTransaction envía **'Cancelled'** según el requerimiento, y eso es lo que
# mandará Lunex en producción. Antes enviábamos 'VOID' (una conjetura que
# funcionó), pero para replicar producción hay que mandar lo que el requerimiento
# dice. Lo persistido queda como VOID / IdStatus 22 (eso se valida aparte, con
# `bd.cancelacion_confirmada`).
#
# ⚠ Si al enviar 'Cancelled' la cancelación empieza a fallar, ESO es un
# hallazgo grande (la API no acepta lo que su propio requerimiento define). Para
# volver al valor anterior sin tocar código:  $env:TRN239_CANCEL_STATUS="VOID"
ESTADO_CANCELACION = os.getenv("TRN239_CANCEL_STATUS", "VOID")

# ── Catálogo de productos para randomizar ───────────────────────────────────
# (SKU, nombre, tipo). ITU y DTU calculan la comisión distinto, y esa
# diferencia es justo lo que mide el CP06: por eso el catálogo lleva los dos.
#
# Los SKU y los nombres salen de la Query 1 sobre PRODUCCIÓN, no de memoria.
# La versión anterior tenía cuatro que no existen con ese número (9600 "Net 10"
# es 9601/9923; 9760 "Tracfone" es 9762) y nombres que no coinciden con el
# catálogo real. Mandar un SKU inventado convierte cualquier error de la API en
# ruido: no se sabe si falló la migración o si el producto simplemente no está.
PRODUCTOS = [
    ("8510", "Mexico - Telcel Amigo Sin Limite", "ITU"),
    ("8456", "Guatemala - Tigo Paqueton", "ITU"),
    ("8485", "Honduras - Paquetigo Super Recargas", "ITU"),
    ("8520", "Mexico - Telcel Amigo Sin Limite 3", "ITU"),
    ("7802", "Guatemala - Tigo", "ITU"),
    ("7962", "Mexico - Telcel", "ITU"),
    ("7831", "Honduras - Tigo", "ITU"),
    ("8498", "Honduras - Claro Super Pack", "ITU"),
    ("9851", "USA - Metro PCS - RTR (fee based)", "DTU"),
    ("9511", "USA - Cricket - RTR (fee based)", "DTU"),
    ("9451", "USA - AT-T - RTR", "DTU"),
    ("9491", "USA - Boost Mobile - RTR (fee based)", "DTU"),
    ("9781", "USA - Verizon - RTR", "DTU"),
    ("9730", "USA - T-Mobile - RTR", "DTU"),
    ("9701", "USA - Simple Mobile - RTR", "DTU"),
]

PRODUCTOS_ITU = [p for p in PRODUCTOS if p[2] == "ITU"]
PRODUCTOS_DTU = [p for p in PRODUCTOS if p[2] == "DTU"]

# ── Perfil monetario por SKU ────────────────────────────────────────────────
# `moneda`, `exrate` y el rango de monto, medidos sobre las filas reales de
# producción (Query 1 para el rango, Query 10 para moneda y tipo de cambio).
#
# Importa porque `AmountInMN = Amount × ExRate` se cumple al centavo en todas
# las filas observadas, y porque en DTU las tres columnas van **NULL**. Antes
# se mandaba `ExRate 21.0025 / AmountInMN 252.03 / HNL` fijo para todo, con lo
# que el monto en moneda nacional no correspondía al monto enviado en ningún
# caso. Un caso de integridad que compara esos campos no puede pasar nunca.
PERFIL_SKU = {
    "8510": {"moneda": "MXN", "exrate": 10.00, "min": 2.00, "max": 50.00},
    "8456": {"moneda": "GTQ", "exrate": 7.201, "min": 7.00, "max": 25.00},
    "8485": {"moneda": "HNL", "exrate": 24.60, "min": 7.00, "max": 25.00},
    "8520": {"moneda": "MXN", "exrate": 10.00, "min": 1.80, "max": 33.00},
    "7802": {"moneda": "GTQ", "exrate": 7.20, "min": 7.00, "max": 30.00},
    "7962": {"moneda": "MXN", "exrate": 10.00, "min": 2.00, "max": 50.00},
    "7831": {"moneda": "HNL", "exrate": 24.60, "min": 3.00, "max": 50.00},
    "8498": {"moneda": "USD", "exrate": 1.00, "min": 7.00, "max": 40.00},
    "9851": {"moneda": None, "exrate": None, "min": 3.50, "max": 300.00},
    "9511": {"moneda": None, "exrate": None, "min": 5.00, "max": 250.00},
    "9451": {"moneda": None, "exrate": None, "min": 10.00, "max": 194.41},
    "9491": {"moneda": None, "exrate": None, "min": 5.00, "max": 206.00},
    "9781": {"moneda": None, "exrate": None, "min": 5.00, "max": 150.00},
    "9730": {"moneda": None, "exrate": None, "min": 10.00, "max": 189.11},
    "9701": {"moneda": None, "exrate": None, "min": 20.00, "max": 150.00},
}

# Para un SKU que no esté en la tabla (el catálogo vivo de `lunex.Product`
# trae cientos). ITU siempre lleva moneda y tipo de cambio; DTU nunca.
PERFIL_POR_DEFECTO = {
    "ITU": {"moneda": "USD", "exrate": 1.00, "min": 5.00, "max": 30.00},
    "DTU": {"moneda": None, "exrate": None, "min": 10.00, "max": 100.00},
}


def perfil(sku: str, tipo: str) -> dict:
    return PERFIL_SKU.get(str(sku)) or PERFIL_POR_DEFECTO.get(
        tipo, PERFIL_POR_DEFECTO["ITU"])

MONTO = float(os.getenv("TRN239_MONTO", "25.0"))

# ── Cuántas altas por corrida ───────────────────────────────────────────────
# Cada alta exitosa ESCRIBE en lunex.TransferLN: es un dato real en TEST. Se
# mantiene bajo a propósito; súbelo solo cuando quieras volumen.
ALTAS = int(os.getenv("TRN239_ALTAS", "2"))

# ── Base de datos ───────────────────────────────────────────────────────────
TABLA_TRANSFER = os.getenv("TRN239_TABLA", "lunex.TransferLN")
TABLA_PRODUCTO = os.getenv("TRN239_TABLA_PRODUCTO", "lunex.Product")

# Validar contra BD. Si no hay conexión, los casos lo dicen como «no
# verificado» en vez de fallar: ver `src/helpers/sql_helper.py`.
VALIDAR_BD = os.getenv("TRN239_VALIDAR_BD", "1").strip().lower() in (
    "1", "true", "si", "sí", "yes")

# ── Evidencia ───────────────────────────────────────────────────────────────
EVIDENCIA_BASE = settings.EVIDENCE_DIR / "TRN-239"
REPORTE = EVIDENCIA_BASE / "reporte_TRN-239.html"
RESULTADOS = EVIDENCIA_BASE / "resultados.json"

# Contadores incrementales entre corridas (Key y TransactionID no se pueden
# reutilizar: el requerimiento dice que Key es único e irrepetible).
CONTADORES = Path(settings.PROJECT_ROOT) / "reports" / "trn239_contadores.json"
