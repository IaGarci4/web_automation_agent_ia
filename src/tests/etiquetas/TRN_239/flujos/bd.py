"""
Validación de integridad contra `lunex.TransferLN`.

Es el corazón de TRN-239. La API puede contestar `Errorcode: 0` y aun así
haber guardado el monto en la columna equivocada, truncado el teléfono o
aplicado dos veces la conversión horaria. Una migración de riesgo no se
valida con el código de respuesta: se valida comparando **lo enviado contra
lo persistido**.

## Los nombres de columna no están confirmados

El mapeo campo→columna es la pregunta 1 del brief y sigue sin responder. Por
eso cada comparación acepta **varios nombres candidatos** y, si no encuentra
ninguno, lo reporta como *no verificado* en vez de inventarse un fallo. Un
«no pude comprobarlo» es un resultado honesto; un FAIL por haber adivinado
mal el nombre de una columna es ruido que quema la confianza en la suite.

Cuando DEV conteste el mapeo, se ajusta `CANDIDATOS` y las comparaciones se
vuelven exactas sin tocar los casos.
"""

from __future__ import annotations

from config.logger import get_logger
from src.helpers import sql_helper

from .. import parametros as P

logger = get_logger("TRN-239.bd")

# Nombres posibles de cada campo en la tabla. El primero que exista gana.
# `Status` se persiste en **LNStatus** (confirmado en el volcado real): va
# primero, por eso `estado_persistido` devolvía '' y el reporte mostraba
# «Status = ?» — buscaba una columna `Status` que no existe.
CANDIDATOS = {
    "TransactionID": ("TransactionID", "TransaccionID", "IdTransaccion"),
    "SKU": ("SKU", "Sku", "ProductSKU"),
    "Amount": ("Amount", "Monto", "MontoUSD"),
    "Phone": ("Phone", "Telefono", "PhoneNumber"),
    "TopupPhone": ("TopupPhone", "TelefonoRecarga"),
    "Entity": ("Entity", "AgentEntity", "Entidad"),
    "Status": ("LNStatus", "Status", "Estatus", "Estado"),
    "IdStatus": ("IdStatus", "StatusId", "IdEstado"),
    "DateOfCancel": ("DateOfCancel", "FechaCancelacion", "DateCancel"),
    "ExternalID": ("ExternalID", "ExternalId", "IdExterno"),
    "SKUType": ("SKUType", "SkuType", "TipoSKU"),
    "TransactionDate": ("TransactionDate", "FechaTransaccion", "Fecha"),
    "Commission": ("Commission", "Comision"),
    "AgentCommission": ("AgentCommission", "ComisionAgente"),
    "CorpCommission": ("CorpCommission", "ComisionCorp", "CorporateCommission"),
    "D1Discount": ("D1Discount", "D1"),
    "ExRate": ("ExRate", "TipoCambio"),
    "AmountInMN": ("AmountInMN", "MontoMN"),
    "CommissionPercentage": ("CommissionPercentage", "PorcentajeComision"),
    "Fee": ("Fee", "Cargo"),
}

# 22 = Cancelada/VOID en `IdStatus` (confirmado por el volcado). 30 = éxito.
ID_STATUS_CANCELADA = 22


def conectar():
    """Conexión, o None. Respeta el interruptor `TRN239_VALIDAR_BD`."""
    if not P.VALIDAR_BD:
        logger.info("[BD] Validación desactivada (TRN239_VALIDAR_BD=0).")
        return None
    return sql_helper.conectar()


def buscar_transaccion(cn, transaction_id: str, reintentos: int = 4,
                       espera_s: float = 1.0) -> dict:
    """La fila de `lunex.TransferLN` de esa transacción, o {}.

    Reintenta antes de rendirse. La API responde `Errorcode 0` **antes** de que
    la fila sea visible en la tabla (persistencia asíncrona): una lectura
    inmediata la pierde. Eso hacía que CP03 y CP07 reportaran «no se encontró»
    filas que sí existían —se veían segundos después en el volcado manual—,
    mientras CP08 acertaba solo porque el reenvío intermedio le daba tiempo.

    Con 4 intentos y 1 s entre ellos se cubre ese desfase sin colgar el caso.
    Si de verdad no está tras el último intento, entonces sí es un hallazgo:
    la API dijo Success y no persistió.
    """
    import time
    if cn is None:
        return {}
    for intento in range(1, reintentos + 1):
        for columna in CANDIDATOS["TransactionID"]:
            filas = sql_helper.consultar(
                cn, f"SELECT TOP 1 * FROM {P.TABLA_TRANSFER} WHERE {columna} = ?",
                (str(transaction_id),))
            if filas:
                if intento > 1:
                    logger.info("[BD] %s visible al intento %d (persistencia "
                                "asíncrona ~%.0f s).", transaction_id, intento,
                                (intento - 1) * espera_s)
                return filas[0]
        if intento < reintentos:
            time.sleep(espera_s)
    logger.warning("[BD] %s no apareció en %s tras %d intentos (%.0f s).",
                   transaction_id, P.TABLA_TRANSFER, reintentos,
                   reintentos * espera_s)
    return {}


def _valor(fila: dict, campo: str):
    """Valor de `campo` en la fila, probando los nombres candidatos.

    Devuelve `(nombre_columna, valor)` o `(None, None)` si ninguno existe —
    que es distinto de «existe y vale NULL», y por eso no se colapsan.
    """
    for nombre in CANDIDATOS.get(campo, (campo,)):
        if nombre in fila:
            return nombre, fila[nombre]
    return None, None


def _igual(enviado, guardado) -> bool:
    """Comparación tolerante al formato, estricta en el valor.

    `25.0` y `25.00` son el mismo monto; `'8510'` y `8510`, el mismo SKU. Lo
    que NO se tolera es una diferencia real — para eso se comparan como
    números cuando ambos lo son, y como texto normalizado si no.
    """
    if enviado is None and guardado is None:
        return True
    try:
        return abs(float(enviado) - float(guardado)) < 0.005
    except (TypeError, ValueError):
        pass
    return str(enviado).strip().casefold() == str(guardado).strip().casefold()


def comparar(fila: dict, enviado: dict, campos=None) -> dict:
    """Compara lo enviado contra lo persistido.

    Devuelve `{'coinciden': [...], 'difieren': [...], 'sin_columna': [...]}`.
    Las tres listas importan: `sin_columna` es lo que NO se pudo verificar, y
    confundirlo con «coincide» sería exactamente el falso negativo que esta
    etiqueta existe para evitar.
    """
    campos = campos or ("SKU", "Amount", "Phone", "Entity", "ExternalID",
                        "SKUType")
    coinciden, difieren, sin_columna = [], [], []
    for campo in campos:
        if campo not in enviado:
            continue
        columna, guardado = _valor(fila, campo)
        if columna is None:
            sin_columna.append(campo)
        elif _igual(enviado[campo], guardado):
            # Solo se muestra la columna cuando su nombre difiere del campo;
            # «Amount(Amount)» era ruido. «Status(LNStatus)» sí informa.
            coinciden.append(campo if columna == campo
                             else f"{campo}→{columna}")
        else:
            difieren.append(
                f"{campo}: enviado='{enviado[campo]}' vs BD.{columna}='{guardado}'")
    return {"coinciden": coinciden, "difieren": difieren,
            "sin_columna": sin_columna}


def estado_persistido(cn, transaction_id: str) -> str:
    """El `Status` que quedó en BD. '' si no se pudo leer.

    Lo usa el caso de cancelación para resolver la duda VOID-vs-Cancelled del
    brief: lo que importa no es qué aceptó la API, sino qué quedó guardado.
    """
    fila = buscar_transaccion(cn, transaction_id)
    if not fila:
        return ""
    _, valor = _valor(fila, "Status")
    return "" if valor is None else str(valor).strip()


def _num(v):
    """Convierte a float, o None si no se puede."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def cancelacion_confirmada(fila: dict) -> tuple:
    """¿La fila quedó cancelada? `(bool, detalle)`.

    No basta con que la API dijera Success: se lee la BD, que es lo que importa.
    Se cruzan **dos señales**, como pediste:

      1. `DateOfCancel` con fecha (no NULL) → se canceló, y cuándo.
      2. `IdStatus = 22` → el estado de cancelación (22 == VOID).

    Y de paso el texto `LNStatus`. Se considera cancelada si CUALQUIERA de las
    dos señales duras lo dice; si se contradicen, se marca la incoherencia.
    """
    _, fecha_cancel = _valor(fila, "DateOfCancel")
    _, id_status = _valor(fila, "IdStatus")
    _, ln_status = _valor(fila, "Status")

    tiene_fecha = fecha_cancel not in (None, "")
    es_22 = str(id_status).strip() == str(ID_STATUS_CANCELADA)
    es_void = str(ln_status).strip().upper() == "VOID"

    cancelada = tiene_fecha or es_22 or es_void
    detalle = (f"DateOfCancel={'sí (' + str(fecha_cancel) + ')' if tiene_fecha else 'NULL'}"
               f" · IdStatus={id_status} ({'cancelada' if es_22 else 'no-22'})"
               f" · LNStatus={ln_status}")

    # Señales que no concuerdan: p. ej. IdStatus=22 pero sin DateOfCancel, o
    # LNStatus=VOID con IdStatus distinto de 22. Es justo el tipo de
    # incoherencia que la migración no debe heredar (Query 4 lo mostró en prod).
    if cancelada and not (tiene_fecha and es_22 and es_void):
        detalle += " · ⚠ señales no del todo consistentes entre sí"
    return cancelada, detalle


def coherencia_produccion(fila: dict) -> list:
    """Valida una fila persistida contra las reglas duras de PRODUCCIÓN.

    Devuelve una lista de inconsistencias (vacía = coherente). Son las reglas
    que se cumplen al 100 % en los 7 M de filas de producción, así que una
    violación en TEST es un campo que la migración cambió y no debía:

      · ITU: `Commission == D1Discount`      (4 659 662/4 659 662 filas)
      · no-DTU: `Commission == Agent + Corp`  (100 % salvo DTU fee-based)
      · con ExRate: `AmountInMN == Amount × ExRate`  (al centavo)

    No se valida Phone≠Topup por fila: en producción hay un 0.06 % de ITU con
    ambos iguales, así que una sola fila no basta para llamarlo defecto.
    """
    fallos = []
    _, tipo = _valor(fila, "SKUType")
    tipo = str(tipo or "").upper()

    com = _num(_valor(fila, "Commission")[1])
    d1 = _num(_valor(fila, "D1Discount")[1])
    agente = _num(_valor(fila, "AgentCommission")[1])
    corp = _num(_valor(fila, "CorpCommission")[1])
    monto = _num(_valor(fila, "Amount")[1])
    exrate = _num(_valor(fila, "ExRate")[1])
    en_mn = _num(_valor(fila, "AmountInMN")[1])

    if tipo == "ITU" and com is not None and d1 is not None:
        if abs(com - d1) >= 0.01:
            fallos.append(f"ITU pero Commission={com} ≠ D1Discount={d1} "
                          f"(en producción son iguales siempre)")

    if tipo != "DTU" and None not in (com, agente, corp):
        if abs(com - (agente + corp)) >= 0.01:
            fallos.append(f"Commission={com} ≠ Agent({agente})+Corp({corp})="
                          f"{round(agente + corp, 4)}")

    if None not in (monto, exrate, en_mn):
        if abs(en_mn - (monto * exrate)) >= 0.01:
            fallos.append(f"AmountInMN={en_mn} ≠ Amount({monto})×ExRate({exrate})="
                          f"{round(monto * exrate, 4)}")

    return fallos


def contar_transacciones(cn, transaction_id: str) -> int:
    """Cuántas filas hay con ese TransactionID. -1 si no se pudo contar.

    Para la idempotencia: dos filas con el mismo TransactionID significan que
    un reenvío duplicó el dato, que en un sistema de pagos es el peor
    resultado posible.
    """
    if cn is None:
        return -1
    for columna in CANDIDATOS["TransactionID"]:
        filas = sql_helper.consultar(
            cn, f"SELECT COUNT(*) AS n FROM {P.TABLA_TRANSFER} "
                f"WHERE {columna} = ?", (str(transaction_id),))
        if filas:
            return int(filas[0].get("n", 0))
    return -1


def productos_activos(cn) -> list:
    """Catálogo real desde `lunex.Product`; el de parámetros como respaldo.

    Randomizar contra el catálogo vivo hace la prueba más honesta: si DEV da
    de alta un producto nuevo, entra en la rotación sin tocar el código.
    """
    if cn is None:
        return P.PRODUCTOS
    filas = sql_helper.consultar(
        cn, f"SELECT SKU, Product FROM {P.TABLA_PRODUCTO} "
            f"WHERE IdGenericstatus = 1")
    if not filas:
        return P.PRODUCTOS
    # SKUType: se toma el REAL de producción (lo que Lunex realmente envió por
    # ese SKU en lunex.TransferLN). NO se deriva del país: se comprobó que
    # `lunex.Product.IdCountry` NO corresponde al país real (0 de 407 productos
    # coinciden; los de EE.UU. apuntan a Kirguistán). El prefijo del SKU (9xxx=
    # DTU) queda solo como respaldo para SKUs sin ventas históricas.
    reales = _skutype_real_por_sku(cn)
    tipos_local = {sku: tipo for sku, _, tipo in P.PRODUCTOS}
    salida = []
    for f in filas:
        sku = str(f["SKU"])
        nombre = str(f.get("Product", ""))
        tipo = reales.get(sku) or tipos_local.get(sku) or tipo_por_sku(sku, nombre)
        salida.append((sku, nombre, tipo))
    logger.info("[BD] Catálogo vivo: %d producto(s); %d con SKUType real de "
                "TransferLN.", len(salida), len(reales))
    return salida or P.PRODUCTOS


def _skutype_real_por_sku(cn) -> dict:
    """`{SKU: SKUType}` — el SKUType más usado por cada SKU en `lunex.TransferLN`.

    Es el dato de verdad: lo que producción realmente notificó. Evita adivinar
    y elimina la única excepción del prefijo (9881 «Telcel America», que en
    producción sale ITU aunque empiece por 9). `{}` si la consulta falla.
    """
    sql = ("SELECT SKU, SKUType FROM ("
           " SELECT SKU, SKUType,"
           " ROW_NUMBER() OVER (PARTITION BY SKU ORDER BY COUNT(*) DESC) rn"
           f" FROM {P.TABLA_TRANSFER} WHERE SKUType IS NOT NULL"
           " GROUP BY SKU, SKUType) x WHERE rn = 1")
    filas = sql_helper.consultar(cn, sql)
    return {str(f["SKU"]): str(f["SKUType"]) for f in (filas or [])}


def tipo_por_sku(sku, nombre: str = "") -> str:
    """RESPALDO: deduce el `SKUType` de un SKU **sin ventas históricas**.

    El camino principal es `_skutype_real_por_sku` (el dato real de
    `lunex.TransferLN`). Esto solo entra si un SKU nunca se ha usado.

    Regla validada contra los **407 productos activos** (hoja del análisis):
    los **54 SKUType=DTU son TODOS 9xxx** (carriers de EE. UU.), sin una sola
    excepción; ITU son 7xxx/8xxx. La única rareza es 9881 «Telcel America»,
    que en producción sale ITU pese a empezar por 9 — pero ese ya se resuelve
    por el dato real, no aquí.

        1xxx  →  Pinless
        9xxx  →  DTU   (doméstico EE. UU.)
        resto →  ITU   (internacional)

    El país NO sirve para esto: `lunex.Product.IdCountry` no corresponde al
    país real del producto (0 de 407 coinciden). Por eso se deduce por SKU.
    """
    s = str(sku).strip()
    if s.startswith("9") or str(nombre).upper().startswith("USA"):
        return "DTU"
    if s.startswith("1"):
        return "Pinless"
    return "ITU"
