"""
TRN-239 · Limpieza de TEST: cancela las altas SUCCESS que dejó la corrida.

La suite da de alta en muchos casos pero solo el CP03 cancela, así que cada
corrida deja ~11 transacciones SUCCESS vivas en `lunex.TransferLN` (TEST). Este
script las cancela vía la API —la misma CancelTransaction que se está probando—
para dejar la tabla como estaba.

    python src\tests\etiquetas\TRN_239\trn239_limpiar.py            # cancela
    python src\tests\etiquetas\TRN_239\trn239_limpiar.py --dry-run  # solo lista
    python src\tests\etiquetas\TRN_239\trn239_limpiar.py --desde 2026-09-01

## Qué cancela, y por qué es seguro

El filtro es deliberadamente estrecho: SOLO toca filas que cumplen TODO esto
a la vez, que es la huella exacta de lo que este arnés inserta:

    EnterByIdUser = tu usuario (13491 por defecto)
    Login = 'Lun3xProdUser'   Entity = 'MX01D3643A'
    ExternalID = 'M120312738S13491'   CID = el del script
    LNStatus = 'SUCCESS'   AND   DateOfCancel IS NULL   (no canceladas ya)
    DateOfCreation >= @desde   (hoy por defecto)

No toca FAILT, no toca lo ya cancelado (VOID), no toca nada de otro usuario ni
de otra entidad. Es imposible que alcance tráfico real de TEST de otra persona
salvo que compartan las cinco señales de identidad, cosa que no ocurre.
"""

import argparse
import sys
from datetime import date
from pathlib import Path


def _raiz_del_repo() -> Path:
    for d in [Path(__file__).resolve(), *Path(__file__).resolve().parents]:
        if (d / "pytest.ini").is_file() and (d / "config").is_dir():
            return d
    return Path(__file__).resolve().parents[1]


sys.path.insert(0, str(_raiz_del_repo()))

from config.logger import get_logger                             # noqa: E402
from src.helpers import sql_helper                               # noqa: E402
from src.tests.etiquetas.TRN_239 import parametros as P          # noqa: E402
from src.tests.etiquetas.TRN_239.flujos import bd as BD          # noqa: E402
from src.tests.etiquetas.TRN_239.flujos import bodies as B       # noqa: E402
from src.tests.etiquetas.TRN_239.flujos import lunex_api as API  # noqa: E402

logger = get_logger("TRN-239.limpiar")


def pendientes(cn, id_user: int, desde: str) -> list:
    """Filas sin cancelar que dejó el arnés. `[]` si no hay o no hay BD.

    «Sin cancelar» = `DateOfCancel IS NULL` y `LNStatus <> 'VOID'`. Antes el
    filtro pedía `LNStatus = 'SUCCESS'` y por eso dejaba fuera las **FAILT**
    (una recarga fallida notificada). Se incluyen ahora: si la API no deja
    cancelar una FAILT, lo dirá con su Errorcode y la fila se queda, pero al
    menos se intenta y no se acumula en silencio.
    """
    if cn is None:
        return []
    sql = (
        f"SELECT TransactionID, SKU, SKUType, Amount, LNStatus, DateOfCreation "
        f"FROM {P.TABLA_TRANSFER} "
        f"WHERE EnterByIdUser = ? "
        f"  AND Login = ? AND Entity = ? AND ExternalID = ? AND CID = ? "
        f"  AND DateOfCancel IS NULL AND LNStatus <> 'VOID' "
        f"  AND DateOfCreation >= ? "
        f"ORDER BY DateOfCreation")
    return sql_helper.consultar(
        cn, sql, (id_user, P.LOGIN, P.ENTITY, B.external_id(), P.CID, desde)) or []


def main() -> int:
    ap = argparse.ArgumentParser(description="TRN-239 · limpieza de TEST")
    ap.add_argument("--id-user", type=int, default=P.ID_USER,
                    help="EnterByIdUser a limpiar (por defecto el IdUser del script)")
    ap.add_argument("--desde", default=str(date.today()),
                    help="fecha mínima YYYY-MM-DD (por defecto hoy)")
    ap.add_argument("--dry-run", action="store_true",
                    help="solo lista lo que cancelaría, sin tocar nada")
    args = ap.parse_args()

    cn = BD.conectar()
    if cn is None:
        print("Sin conexión a la base de datos: no puedo saber qué cancelar.")
        print("Revisa la VPN y el .env (o TRN239_VALIDAR_BD=1).")
        return 2

    filas = pendientes(cn, args.id_user, args.desde)
    print()
    print("═" * 74)
    print(f"  TRN-239 · Limpieza — EnterByIdUser={args.id_user} · desde {args.desde}")
    print("═" * 74)
    if not filas:
        print("  No hay transacciones sin cancelar. Nada que hacer.")
        return 0

    print(f"  {len(filas)} transacción(es) sin cancelar:")
    for f in filas:
        print(f"    · {f['TransactionID']}  SKU {f['SKU']:<6} {f['SKUType']:<4} "
              f"{f['LNStatus']:<8} {f['Amount']}  ({f['DateOfCreation']})")
    print("─" * 74)

    if args.dry_run:
        print("  --dry-run: no se canceló nada.")
        return 0

    cnt = B.Contadores()
    ok, err = 0, 0
    for f in filas:
        cuerpo = B.cancelacion(cnt, str(f["TransactionID"]),
                               str(f["SKU"]), str(f["SKUType"]))
        r = API.cancelar(cuerpo)
        if r.ok:
            ok += 1
            print(f"    cancelada {f['TransactionID']} · {r.resumen()}")
        else:
            err += 1
            print(f"    ** NO cancelada {f['TransactionID']} · {r.resumen()}")
    print("─" * 74)
    print(f"  Canceladas: {ok} · Con error: {err}")
    print("═" * 74)
    return 0 if err == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
