"""
Cambio de estatus de una transferencia vía BD (SP `Soporte.sp_ChangeStatusTransaction`).

## Por qué

En **TEST**, el servicio que avanza el estatus de los pagadores de Asia está
apagado (ese cambio se hace manual). Para que las pruebas de Chronos puedan
ejercitar la cancelación desde 'Payment Ready', se le da la vuelta poniendo la
transferencia en ese estatus directamente en BD, usando el mismo SP que soporte
usa a mano. En **PRODUCCIÓN esto NO se usa**: el servicio real avanza el estatus.

Adaptado de `statusChange.py` (Documentos): aquí NO lee un .txt ni imprime —
recibe el/los claimcode(s) por parámetro, reutiliza `sql_helper` (credenciales
del `.env`, las mismas del token de soporte) y registra en el log.

Flujo típico (lo usa CP14):
    from src.helpers import status_change as SC
    claim, ok = SC.preparar_payment_ready(agentcode="50280-CA", folio="215")

Pasos internos:
  1. IdAgent desde AgentCode:  SELECT IdAgent FROM Agent WHERE AgentCode = ?
  2. Transfer por IdAgent+Folio (NOLOCK) → ClaimCode.
  3. EXEC Soporte.sp_ChangeStatusTransaction @claimcode, @notas, 23, 1  (PaymentReady + commit).
"""

from __future__ import annotations

from config.logger import get_logger
from src.helpers import sql_helper as SQL

logger = get_logger("status-change")

# IdStatus objetivo (según el SP de soporte). 23 = Payment Ready.
ID_STATUS_PAYMENT_READY = 23
SP = "EXEC Soporte.sp_ChangeStatusTransaction ?, ?, ?, ?"
NOTAS_DEFAULT = "Automatizacion CP14 - PaymentReady (test)"


def _claimcode_de_fila(fila: dict) -> str:
    """Extrae el ClaimCode de una fila de Transfer, tolerando el nombre exacto
    de la columna (ClaimCode / Claimcode / CLAIM_CODE…)."""
    if not fila:
        return ""
    for k, v in fila.items():
        if str(k).replace("_", "").lower() == "claimcode":
            return str(v or "").strip()
    return ""


def obtener_idagent(agentcode: str) -> int | None:
    """IdAgent a partir del AgentCode (ej. '50280-CA'). None si no se encuentra."""
    if not agentcode:
        return None
    cn = SQL.conectar()
    if cn is None:
        return None
    try:
        filas = SQL.consultar(
            cn, "SELECT IdAgent FROM Agent WHERE AgentCode = ?", (agentcode,))
    finally:
        try:
            cn.close()
        except Exception:
            pass
    if not filas:
        logger.warning("[StatusChange] No se encontró IdAgent para AgentCode '%s'.",
                       agentcode)
        return None
    try:
        idagent = int(filas[0].get("IdAgent"))
        logger.info("[StatusChange] AgentCode '%s' → IdAgent %s.", agentcode, idagent)
        return idagent
    except Exception:
        logger.warning("[StatusChange] IdAgent ilegible para '%s': %s",
                       agentcode, filas[0])
        return None


def obtener_transfer(idagent: int, folio) -> dict | None:
    """Fila de Transfer (NOLOCK) por IdAgent + Folio. None si no existe."""
    if not idagent or not folio:
        return None
    cn = SQL.conectar()
    if cn is None:
        return None
    try:
        filas = SQL.consultar(
            cn,
            "SELECT * FROM Transfer WITH (NOLOCK) WHERE IdAgent = ? AND Folio = ?",
            (idagent, str(folio)))
    finally:
        try:
            cn.close()
        except Exception:
            pass
    if not filas:
        logger.warning("[StatusChange] No hay Transfer con IdAgent=%s y Folio=%s.",
                       idagent, folio)
        return None
    return filas[0]


def cambiar_status(claimcode: str, id_status: int = ID_STATUS_PAYMENT_READY,
                   notas: str = NOTAS_DEFAULT) -> bool:
    """Ejecuta el SP de cambio de estatus para un claimcode (con commit).
    Devuelve True si se ejecutó sin error."""
    if not claimcode:
        logger.warning("[StatusChange] claimcode vacío — no se ejecuta el SP.")
        return False
    cn = SQL.conectar()
    if cn is None:
        return False
    try:
        # param4 = 1 → commit en BD (como el script de soporte).
        ok = SQL.ejecutar(cn, SP, (claimcode, notas, int(id_status), 1), commit=True)
        if ok:
            logger.info("[StatusChange] Estatus cambiado: claimcode=%s → IdStatus=%s.",
                        claimcode, id_status)
        return ok
    finally:
        try:
            cn.close()
        except Exception:
            pass


def preparar_payment_ready(agentcode: str, folio,
                           notas: str = NOTAS_DEFAULT) -> tuple[str, bool]:
    """Deja la transferencia (agentcode+folio) en 'Payment Ready' vía BD.

    Devuelve (claimcode, ok). Si no encuentra IdAgent/Transfer/ClaimCode, devuelve
    ('', False) sin lanzar — el llamador decide si continúa o cae al fallback."""
    idagent = obtener_idagent(agentcode)
    if not idagent:
        return "", False
    fila = obtener_transfer(idagent, folio)
    claim = _claimcode_de_fila(fila)
    if not claim:
        logger.warning("[StatusChange] La transferencia no trae ClaimCode "
                       "(IdAgent=%s, Folio=%s).", idagent, folio)
        return "", False
    logger.info("[StatusChange] ClaimCode de la transferencia: %s", claim)
    ok = cambiar_status(claim, ID_STATUS_PAYMENT_READY, notas)
    return claim, ok
