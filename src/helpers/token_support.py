"""
Token de Soporte Remoto — se consulta en BD y se aplica en el Hermes2Agent.

El token vive en `corp.TokenSupport` y **caduca cada día a medianoche**
(`ExpirationDate`). Este helper:
  1. Lo consulta en BD (reusa `sql_helper`, credenciales del `.env`).
  2. Elige el vigente (no expirado y con `ExpirationDate` futura; el más reciente).
  3. Lo **cachea temporalmente** en `reports/token_support.json` con su expiración,
     para no golpear la BD en cada corrida; si el cache sigue vigente lo reusa.
  4. Lo devuelve como string listo para teclear en el input (maxlength 10).

Uso:
    from src.helpers.token_support import obtener_token
    tok = obtener_token()            # usa cache si sigue vigente
    tok = obtener_token(forzar=True) # ignora cache y re-consulta BD

CLI rápida:  python -m src.helpers.token_support
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from config import settings
from config.logger import get_logger
from src.helpers import sql_helper as SQL

logger = get_logger("token-support")

CONSULTA = "SELECT * FROM corp.TokenSupport"
CACHE = Path(settings.PROJECT_ROOT) / "reports" / "token_support.json"


def _ahora() -> _dt.datetime:
    return _dt.datetime.now()


def _parse_fecha(v):
    if isinstance(v, _dt.datetime):
        return v
    if not v:
        return None
    s = str(v).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return _dt.datetime.strptime(s[:26], fmt)
        except Exception:
            continue
    return None


def _no_expirado(fila) -> bool:
    """True si la fila NO está marcada expirada y su ExpirationDate es futura."""
    exp_flag = fila.get("Expired")
    if exp_flag in (1, True, "1", "true", "True"):
        return False
    fexp = _parse_fecha(fila.get("ExpirationDate"))
    if fexp is not None and fexp <= _ahora():
        return False
    return True


def _leer_cache():
    try:
        d = json.loads(CACHE.read_text(encoding="utf-8"))
        exp = _parse_fecha(d.get("expiration"))
        if d.get("token") and (exp is None or exp > _ahora()):
            return str(d["token"]), exp
    except Exception:
        pass
    return None, None


def _guardar_cache(token: str, expiration) -> None:
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(
            {"token": token,
             "expiration": expiration.isoformat() if expiration else None,
             "guardado": _ahora().isoformat(timespec="seconds")},
            ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("[Token] No se pudo cachear: %s", str(e)[:100])


def obtener_token(forzar: bool = False) -> str:
    """Token de soporte vigente. '' si no se pudo obtener (BD no disponible o sin
    fila vigente); el llamador decide si omitir el caso."""
    if not forzar:
        tok, exp = _leer_cache()
        if tok:
            logger.info("[Token] Usando token en cache (vigente%s).",
                        f" hasta {exp}" if exp else "")
            return tok

    cn = SQL.conectar()
    if cn is None:
        logger.warning("[Token] Sin conexión a BD (%s). No se pudo consultar el token.",
                       SQL.motivo_sin_conexion() or "motivo desconocido")
        return ""
    try:
        filas = SQL.consultar(cn, CONSULTA)
    finally:
        try:
            cn.close()
        except Exception:
            pass

    if not filas:
        logger.warning("[Token] La consulta '%s' no devolvió filas.", CONSULTA)
        return ""

    # Vigentes primero; dentro de ellos, el de ExpirationDate más lejana.
    vigentes = [f for f in filas if _no_expirado(f)]
    elegido = None
    if vigentes:
        elegido = max(vigentes, key=lambda f: (_parse_fecha(f.get("ExpirationDate"))
                                               or _dt.datetime.min))
    else:
        # Ninguna vigente: tomamos la de ExpirationDate más reciente y avisamos.
        elegido = max(filas, key=lambda f: (_parse_fecha(f.get("ExpirationDate"))
                                            or _dt.datetime.min))
        logger.warning("[Token] Ninguna fila vigente; uso la más reciente (¿caducó "
                       "a medianoche?). Verifica corp.TokenSupport.")

    token = str(elegido.get("Token") or "").strip()
    exp = _parse_fecha(elegido.get("ExpirationDate"))
    if not token:
        logger.warning("[Token] La fila elegida no trae 'Token'. Columnas: %s",
                       list(elegido.keys()))
        return ""
    logger.info("[Token] Token de soporte obtenido de BD (expira %s).", exp or "s/f")
    _guardar_cache(token, exp)
    return token


if __name__ == "__main__":
    t = obtener_token(forzar=True)
    print(f"Token de soporte: {t!r}" if t else "No se pudo obtener el token (ver log).")
