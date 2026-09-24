"""
Parámetros compartidos por los casos de la etiqueta KRA-1527.

Un solo sitio para los datos de entrada de los flujos, todos sobreescribibles
por variable de entorno: la etiqueta se corre en máquinas distintas (con otra
impresora, otro pagador, otro ambiente) y no se debería tocar código para eso.

Los NOMBRES de los casos también viven aquí, porque son la clave con la que se
nombran las carpetas de evidencia y las entradas del reporte — y tienen que
coincidir con QMetry.
"""

import os
from pathlib import Path

from config import settings

# ── Identificadores de los casos ────────────────────────────────────────────
# Formato CP0X-NombreDelCaso: es el nombre de la carpeta de evidencias y la
# clave del reporte HTML.
#
# ⚠️ La numeración se ha corrido DOS veces. Si QMetry conserva una versión
# anterior, esta es la equivalencia acumulada:
#
#   1er corrimiento — se descartó la captura de firma digital (era el CP04 y
#     no existe en la aplicación):        CP05→CP04, CP06→CP05, CP07→CP06,
#                                         CP08→CP07
#   2º corrimiento — se eliminó la Inspección Consolidada (ver abajo):
#                                         CP07→CP06, CP08→CP07, CP09→CP08
#   3er corrimiento — el Control Negativo dejó de ser un caso y pasó a ser
#     una compuerta del preflight:        CP07→CP06, CP08→CP07
#
# Ahora TODOS los CP son flujos reales de la aplicación. Nada de lo que hay
# aquí prueba la herramienta: todo prueba el producto.
#
# Por qué desapareció la Inspección Consolidada: leía el reporte acumulado
# para «consolidar» los volcados de los demás casos, pero se leía también a
# SÍ MISMO, así que cada corrida registraba de nuevo lo ya registrado y el
# recuento crecía sin límite (2 → 4 → 6…). Aparecía además en el resumen como
# un caso «con token en claro» sin haber tocado la aplicación: un hallazgo
# fantasma en el reporte del ticket. Sus dos funciones ya estaban cubiertas:
# cada caso inspecciona su propio volcado con vector y vigencia —más
# información de la que daba la pasada consolidada— y el borrado de los .DMP
# está desactivado a propósito desde que la carpeta ES la evidencia.
#
# Por qué se fue el Control Negativo: no validaba el criterio del ticket
# —probaba el inspector, no el producto—, no figura en `qmetry_mapeo.json`, y
# su fallo no detenía nada (sin `-x`, los demás casos corrían igual y podían
# reportar PASS). Vive en `control_negativo.py` y lo ejecuta el preflight,
# donde sí puede abortar la corrida. Ver ese módulo.
CP01 = "CP01-EnvioMoneyTransfer"
CP02 = "CP02-FichaDeposito"
CP03 = "CP03-EscaneoCheque"
CP04 = "CP04-FichaDepositoRedLenta"
CP05 = "CP05-ReimpresionRecibo"
CP06 = "CP06-ImprimirBalanceCajero"      # cobertura adicional
CP07 = "CP07-ImprimirMoneyOrder"         # cobertura adicional

INSPECTOR = Path(settings.PROJECT_ROOT) / "tools" / "dump_token_inspector.py"

# ── Datos de los flujos ─────────────────────────────────────────────────────
# ELEKTRA a propósito: es el envío más sencillo y el más probado del proyecto.
# SORIANA disparaba el modal de Información de Cumplimiento, que añade un
# formulario entero al caso — ruido para una prueba cuyo objeto es el volcado
# de memoria, no el compliance.
MT_PAYER = os.getenv("KRA1527_PAYER", "ELEKTRA")
MT_MONTO = int(os.getenv("KRA1527_AMOUNT", "20"))
DS_MONTO = os.getenv("KRA1527_DEPOSITO", "333")
CHEQUE_MONTO = os.getenv("KRA1527_CHEQUE", "5.00")
MO_MONTO = os.getenv("KRA1527_MO_AMOUNT", "3000")       # $3,000 → 3 money orders
MO_ESPERADOS = int(os.getenv("KRA1527_MO_COUNT", "3"))
MO_ANULAR = os.getenv("KRA1527_MO_VOID", "1").strip().lower() in (
    "1", "true", "si", "yes")

# Cancelar lo que la etiqueta crea. Encendido por defecto: cada caso hace
# transacciones REALES en TEST para que la app invoque al agente, y dejarlas
# vivas ensucia los reportes del ambiente y descuadra los balances.
# Apagarlo solo para depurar un flujo concreto y ver el registro en la app.
CANCELAR = os.getenv("KRA1527_CANCELAR", "1").strip().lower() in (
    "1", "true", "si", "yes")

# CP03: el cheque NO se cancela desde Hermes.
#
# El menú kebab del reporte de transacciones no ofrece 'Cancel' para el tipo
# CHECKS — comprobado: el menú abre, la opción no está, y el cheque queda vivo
# en TEST. La baja se hace en Chronos rechazándolo por el emisor:
#   Other Products > Search Other Products > Check > buscar > Issuer >
#   Edited Checks Hold > Reason > Reject
CHEQUE_MOTIVO_RECHAZO = os.getenv("KRA1527_CHEQUE_MOTIVO", "Other")
CHEQUE_AGENCIA = os.getenv("KRA1527_CHEQUE_AGENCIA", settings.AGENCY_CODE)

# CP05: cuánto se ralentiza la red para ampliar la vida del proxy efímero.
PROXY_KBPS = int(os.getenv("KRA1527_PROXY_KBPS", "50"))
PROXY_LATENCIA = int(os.getenv("KRA1527_PROXY_LATENCIA_MS", "500"))

# Resolución/idioma con los que se corre la etiqueta.
PANTALLA = [("English", 1366, 768)]


def pdf_impresion(caso: str) -> Path:
    """Ruta donde se guarda el PDF que produce «Guardar impresión como».

    Va dentro de la carpeta de evidencia del caso, junto a sus capturas, y no
    en el Escritorio —que es donde abre el diálogo por defecto—. El sello de
    tiempo evita que dos corridas se pisen y que Windows interponga el aviso
    de sobrescritura, que dejaría el diálogo abierto esperando otra
    confirmación que nadie va a dar.
    """
    from datetime import datetime
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    destino = settings.EVIDENCE_DIR / "KRA-1527" / caso
    return destino / f"impresion_{caso}_{sello}.pdf"


def cargar_payer(code: str = None):
    """Pagador del catálogo por código (con el primero como respaldo)."""
    from .flujos import mt as F
    payers, ciudades = F.cargar_catalogo(modulo="mexico")
    objetivo = (code or MT_PAYER).upper()
    for p in payers:
        if p["code"].upper() == objetivo:
            return dict(p), ciudades
    return dict(payers[0]), ciudades
