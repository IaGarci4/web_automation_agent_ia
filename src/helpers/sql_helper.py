"""
Conexión a SQL Server para las validaciones de integridad de datos.

## Por qué existe

Hasta ahora la suite solo miraba la interfaz: si la pantalla decía «enviado»,
el caso pasaba. Para una **migración de riesgo** como TRN-239 eso no basta —
lo que hay que demostrar es que *lo que se envió es lo que quedó guardado*, y
eso solo lo sabe la base de datos.

## Configuración (`.env`)

    SERVIDOR_SQL=192.168.5.10
    NAME_BD=MaxiTest
    AUTENTICATION="Autenticacion de SQL Server"   # o "Windows"
    USER_SQL=...
    PASSWORD_SQL=...

`AUTENTICATION` decide el modo: si contiene «windows» se usa
`Trusted_Connection` (la cuenta de Windows que corre la prueba) y no hacen
falta usuario ni contraseña. Cualquier otro valor se entiende como
autenticación de SQL Server, que sí los exige.

## Nunca revienta

Todo devuelve `None` o una lista vacía si algo falta, con un aviso que dice
QUÉ falta. Un caso que no puede validar contra BD debe poder decirlo —«no
verificado»— en vez de tumbar una corrida de veinte minutos por un driver
ausente. La diferencia entre «verificado y correcto» y «no verificado» la
marca quien llama, no este módulo.
"""

from __future__ import annotations

import os

# `settings` es quien llama a `load_dotenv`. Importarlo ANTES de leer nada del
# entorno no es decorativo: si este módulo se importara primero, todas las
# variables saldrían vacías y el diagnóstico diría «falta SERVIDOR_SQL en el
# .env» con el .env perfectamente rellenado — un mensaje que manda a buscar
# donde no es.
from config import settings                                   # noqa: F401
from config.logger import get_logger

logger = get_logger("sql")

SERVIDOR = os.getenv("SERVIDOR_SQL", "").strip()
BASE_DATOS = os.getenv("NAME_BD", "").strip()
AUTENTICACION = os.getenv("AUTENTICATION", "").strip().strip('"').strip("'")
USUARIO = os.getenv("USER_SQL", "").strip()
CONTRASENA = os.getenv("PASSWORD_SQL", "").strip()

# Cadena completa, si alguien prefiere darla hecha. Gana sobre lo de arriba.
CONN_DIRECTA = os.getenv("SQL_CONN", "").strip()

# Drivers ODBC en orden de preferencia. Se prueba cuál está instalado en vez
# de fijar uno: la máquina de QA tiene el 17 y la de integración puede tener
# el 18, y un nombre clavado convierte eso en un fallo incomprensible.
DRIVERS = (
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "ODBC Driver 13 for SQL Server",
    "SQL Server Native Client 11.0",
    "SQL Server",
)


def usa_windows_auth() -> bool:
    return "windows" in AUTENTICACION.lower()


def driver_disponible() -> str:
    """Primer driver ODBC de la lista que esté instalado. '' si ninguno."""
    try:
        import pyodbc
    except ImportError:
        return ""
    try:
        instalados = {d.strip() for d in pyodbc.drivers()}
    except Exception:
        return ""
    for d in DRIVERS:
        if d in instalados:
            return d
    return ""


def cadena_conexion() -> str:
    """Cadena ODBC armada desde el `.env`. '' si falta algo esencial."""
    if CONN_DIRECTA:
        return CONN_DIRECTA
    driver = driver_disponible()
    if not (driver and SERVIDOR and BASE_DATOS):
        return ""
    partes = [f"DRIVER={{{driver}}}", f"SERVER={SERVIDOR}",
              f"DATABASE={BASE_DATOS}"]
    if usa_windows_auth():
        partes.append("Trusted_Connection=yes")
    else:
        if not (USUARIO and CONTRASENA):
            return ""
        partes += [f"UID={USUARIO}", f"PWD={CONTRASENA}"]
    # El driver 18 exige cifrado y certificado válido por defecto; en una IP
    # privada con certificado autofirmado eso falla con un error de TLS que no
    # se parece en nada a «el certificado no es de confianza».
    partes.append("TrustServerCertificate=yes")
    return ";".join(partes) + ";"


def motivo_sin_conexion() -> str:
    """Explica POR QUÉ no se puede conectar. '' si sí se puede."""
    try:
        import pyodbc                                        # noqa: F401
    except ImportError:
        return "falta el paquete `pyodbc` (pip install pyodbc)"
    if CONN_DIRECTA:
        return ""
    if not driver_disponible():
        return ("no hay driver ODBC de SQL Server instalado. Descarga "
                "«ODBC Driver 18 for SQL Server» de Microsoft")
    if not SERVIDOR:
        return "falta SERVIDOR_SQL en el .env"
    if not BASE_DATOS:
        return "falta NAME_BD en el .env"
    if not usa_windows_auth() and not (USUARIO and CONTRASENA):
        return (f"AUTENTICATION='{AUTENTICACION}' exige usuario y contraseña, "
                f"y USER_SQL o PASSWORD_SQL están vacíos en el .env")
    return ""


def conectar(timeout: int = 10):
    """Conexión a SQL Server, o `None` con el motivo en el log."""
    motivo = motivo_sin_conexion()
    if motivo:
        logger.warning("[SQL] Sin validación en BD: %s.", motivo)
        return None
    try:
        import pyodbc
        cn = pyodbc.connect(cadena_conexion(), timeout=timeout)
        modo = "Windows" if usa_windows_auth() else f"SQL ({USUARIO})"
        logger.info("[SQL] Conectado a %s/%s · autenticación %s.",
                    SERVIDOR, BASE_DATOS, modo)
        return cn
    except Exception as e:
        # El mensaje de pyodbc trae la cadena completa, y la cadena lleva la
        # CONTRASEÑA. Se recorta y se censura antes de que llegue al log o,
        # peor, al reporte que se adjunta al ticket.
        detalle = str(e)
        if CONTRASENA:
            detalle = detalle.replace(CONTRASENA, "***")
        logger.warning("[SQL] No se pudo conectar a %s/%s: %s",
                       SERVIDOR, BASE_DATOS, detalle[:220])
        return None


def consultar(cn, sql: str, params: tuple = ()) -> list:
    """Ejecuta una SELECT y devuelve una lista de dicts. [] si falla."""
    if cn is None:
        return []
    try:
        cur = cn.cursor()
        cur.execute(sql, params) if params else cur.execute(sql)
        columnas = [d[0] for d in cur.description]
        return [dict(zip(columnas, fila)) for fila in cur.fetchall()]
    except Exception as e:
        logger.warning("[SQL] Consulta fallida: %s", str(e)[:200])
        return []


def describir() -> str:
    """Una línea para el log del preflight."""
    motivo = motivo_sin_conexion()
    if motivo:
        return f"NO disponible ({motivo})"
    modo = "Windows" if usa_windows_auth() else f"SQL/{USUARIO}"
    return f"{SERVIDOR}/{BASE_DATOS} · {modo} · {driver_disponible()}"
