"""
TRN-239 · Happy path: registrar una transacción y cancelarla.

Una ejecución, dos peticiones, un reporte. Sin casos negativos.

Es un **script**, no un test: se ejecuta con `python`, no con `pytest`
(con pytest recolecta 0 items y parece que falló cuando ni siquiera corrió).

    python src\tests\etiquetas\TRN_239\trn239_happy_path.py
    python src\tests\etiquetas\TRN_239\trn239_happy_path.py --sku 8456
    python src\tests\etiquetas\TRN_239\trn239_happy_path.py --monto 20
    python src\tests\etiquetas\TRN_239\trn239_happy_path.py --sin-cancelar

## Qué hace, en orden

    1. Elige un producto AL AZAR del catálogo vivo (`lunex.Product`)
    2. POST Payments/RegisterTransaction   → espera Errorcode 0
    3. Consulta `lunex.TransferLN`         → ¿quedó registrada?
    4. POST Payments/CancelTransaction     → espera Errorcode 0
    5. Consulta de nuevo                   → ¿cambió el Status?
    6. Escribe un HTML con las dos peticiones, las dos respuestas y las
       dos lecturas de base de datos, una al lado de otra

## Sobre el `Margin` — hipótesis descartada

Una versión anterior mandaba el `Margin` de `lunex.Product` como
`CommissionPercentage`, buscando ahí el origen del `Errorcode 15`. No era eso:
el 15 venía de un `IdAgent` equivocado (1242 en vez de 8918), y los datos de
producción cerraron la pregunta por otro lado —`Commission = D1Discount` en
los 4 659 662 registros ITU—. La comisión viaja en `D1Discount`;
`CommissionPercentage` ni siquiera tiene columna donde caer.

El `Margin` se sigue leyendo y se imprime en el reporte como referencia del
catálogo. Se muestra, no se envía.

## Productos excluidos del azar

El catálogo mezcla recargas telefónicas con cosas que no lo son: tarjetas de
transporte (`UTA-*`, `OMNY-*`), activaciones y algún producto de prueba. Una
recarga de 25 USD a una tarjeta del metro de Nueva York no es un happy path
—es un caso raro disfrazado— y ensucia el diagnóstico. Se quedan fuera; con
`--sku` se puede forzar cualquiera.
"""

import argparse
import html
import json
import random
import sys
from datetime import datetime
from pathlib import Path


def _raiz_del_repo() -> Path:
    """Sube hasta encontrar la raíz del proyecto.

    Antes era `parents[1]`, que solo acierta si el archivo vive en `tools/`.
    Al moverlo a `src/tests/etiquetas/TRN_239/` esa cuenta apuntaba a
    `etiquetas` y los imports de `src.helpers` dejaban de resolverse.

    Contar carpetas hacia arriba es frágil por definición: se rompe en cuanto
    alguien mueve el archivo, que es exactamente lo que pasó. Se busca una
    señal —`pytest.ini` junto a `config/`— y así da igual dónde esté.
    """
    for d in [Path(__file__).resolve(), *Path(__file__).resolve().parents]:
        if (d / "pytest.ini").is_file() and (d / "config").is_dir():
            return d
    # Respaldo: el comportamiento viejo, por si el repo cambia de forma.
    return Path(__file__).resolve().parents[1]


sys.path.insert(0, str(_raiz_del_repo()))

from src.helpers import sql_helper                              # noqa: E402
from src.tests.etiquetas.TRN_239 import parametros as P         # noqa: E402
from src.tests.etiquetas.TRN_239.flujos import bd as BD         # noqa: E402
from src.tests.etiquetas.TRN_239.flujos import bodies as B      # noqa: E402
from src.tests.etiquetas.TRN_239.flujos import lunex_api as API  # noqa: E402

SALIDA = P.EVIDENCIA_BASE / "happy_path_TRN-239.html"

# Fragmentos que sacan un producto del sorteo: no son recargas telefónicas.
EXCLUIR = ("uta-", "omny", "activation", "activacion", "guatellama",
           "telemedia", "reduced fare")

# Respaldo si no hay base de datos. SKU y nombres tomados de la Query 1 sobre
# producción, no de memoria: la versión anterior traía «9760 Tracfone» (el
# real es 9762) y «Honduras - PaqueTigo» (el real es «Honduras - Paquetigo
# Super Recargas»). Un SKU inventado convierte cualquier error de la API en
# ruido, y este catálogo solo entra en juego sin BD — justo cuando menos
# herramientas hay para darse cuenta.
CATALOGO_FALLBACK = [
    ("8456", "Guatemala - Tigo Paqueton", 11.00),
    ("8510", "Mexico - Telcel Amigo Sin Limite", 35.00),
    ("8485", "Honduras - Paquetigo Super Recargas", 10.00),
    ("7802", "Guatemala - Tigo", 11.00),
    ("7831", "Honduras - Tigo", 10.00),
    ("7962", "Mexico - Telcel", 42.00),
    ("8498", "Honduras - Claro Super Pack", 11.00),
    ("8520", "Mexico - Telcel Amigo Sin Limite 3", 35.00),
    ("9851", "USA - Metro PCS - RTR (fee based)", 6.00),
    ("9511", "USA - Cricket - RTR (fee based)", 5.00),
    ("9451", "USA - AT-T - RTR", 10.00),
]


def catalogo(cn) -> list:
    """`[(SKU, Product, Margin)]` del catálogo vivo, ya filtrado."""
    if cn is None:
        return CATALOGO_FALLBACK
    filas = sql_helper.consultar(
        cn, f"SELECT SKU, Product, Margin FROM {P.TABLA_PRODUCTO} "
            f"WHERE IdGenericstatus = 1")
    limpio = []
    for f in filas:
        nombre = str(f.get("Product") or "").strip()
        if not nombre or any(x in nombre.lower() for x in EXCLUIR):
            continue
        try:
            margen = float(f.get("Margin") or 0)
        except (TypeError, ValueError):
            margen = 0.0
        limpio.append((str(f["SKU"]).strip(), nombre, margen))
    return limpio or CATALOGO_FALLBACK


def _col(fila: dict, *nombres):
    """Primer valor presente entre varios nombres de columna posibles."""
    for n in nombres:
        for k in fila:
            if k.lower() == n.lower() and fila[k] not in (None, ""):
                return fila[k]
    return None


def identidad_real(cn) -> dict:
    """Entity, ExternalID y CID de una transacción REAL de la tabla.

    ## Por qué esto y no seguir adivinando

    `Entity=MX01D3643A`, `IdAgent=1242` e `IdUser=13491` vienen del runner
    viejo y nadie los confirmó nunca. Son datos de identidad: pasan la
    validación de formato —por eso no dan `Errorcode 5`— y si la API no
    encuentra ese agente en su catálogo, lo que sale es justo un error
    interno.

    En vez de inventar combinaciones, se copia la identidad de una
    transacción que la API YA procesó bien alguna vez. Si con esos valores
    el alta pasa, el 15 era nuestro; si sigue fallando, es del servidor.
    """
    if cn is None:
        return {}
    filas = sql_helper.consultar(
        cn, f"SELECT TOP 1 * FROM {P.TABLA_TRANSFER} ORDER BY 1 DESC")
    if not filas:
        return {}
    f = filas[0]
    return {
        "Entity": _col(f, "Entity", "AgentEntity", "Entidad"),
        "ExternalID": _col(f, "ExternalID", "ExternalId", "IdExterno"),
        "CID": _col(f, "CID", "Cid"),
        "SKU": _col(f, "SKU", "Sku"),
        "Amount": _col(f, "Amount", "Monto", "MontoUSD"),
        "_columnas": sorted(f.keys()),
    }


def cuerpo_alta(cnt, sku, nombre, margen, monto):
    """El cuerpo del alta, tal como lo arma la etiqueta.

    **Aquí había un experimento que los datos desmintieron.** Se metía el
    `Margin` del catálogo en `CommissionPercentage` y se ponía `D1Discount` en
    0, buscando que el `Errorcode 15` viniera de una comisión mal calculada.
    No era eso —el 15 era el `IdAgent` equivocado— y además la producción dice
    lo contrario:

        Commission = D1Discount   en 4 659 662 de 4 659 662 filas ITU

    O sea que la comisión **es** el `D1Discount` que manda el cliente, y
    ponerlo en 0 era mandar una comisión de cero. `CommissionPercentage` ni
    siquiera tiene columna en `lunex.TransferLN`. El `Margin` reparte entre
    agente y corporativo, que es otra cosa (pregunta abierta A).

    El `margen` se sigue recibiendo y se sigue imprimiendo en el reporte como
    dato del catálogo: sirve para leer el resultado, no para construirlo.

    El **tipo se deduce**, no se fuerza. Antes iba `"ITU"` fijo, y eso pasó a
    ser un error cuando el cuerpo empezó a depender del tipo: un 9xxx —que es
    DTU— salía con moneda y tipo de cambio donde producción tiene NULL, con
    `TopupPhone` distinto de `Phone` donde producción los tiene iguales, y con
    `SKUType=ITU` declarando ser algo que no es.
    """
    tipo = BD.tipo_por_sku(sku, nombre)
    return B.alta(cnt, (sku, nombre, tipo), monto=monto)


# ── Reporte ─────────────────────────────────────────────────────────────────
def _e(x):
    return html.escape(str(x if x is not None else ""))


def _bloque(titulo, peticion, respuesta, extra="", abierto=False):
    """Un bloque DESPLEGABLE por transacción: el título con su chip queda
    visible y, al expandir, se ven petición y respuesta lado a lado."""
    def pre(obj):
        try:
            txt = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
        except Exception:
            txt = str(obj)
        return f"<pre>{_e(txt)}</pre>"
    return f"""<details class="b"{' open' if abierto else ''}>
      <summary><span class="bt">{_e(titulo)}</span>{extra}</summary>
      <div class="par"><div><h3>Petición (cópiala para reproducir)</h3>{pre(peticion)}</div>
      <div><h3>Respuesta</h3>{pre(respuesta)}</div></div></details>"""


def _chip(ok, texto):
    c = "#059669" if ok else "#dc2626"
    f = "#ecfdf5" if ok else "#fef2f2"
    return (f'<span style="background:{f};color:{c};padding:2px 10px;'
            f'border-radius:11px;font-size:12px;font-weight:700">{_e(texto)}'
            f'</span>')


def escribir(bloques, resumen, veredicto):
    color = "#059669" if veredicto == "OK" else "#dc2626"
    doc = f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<title>TRN-239 · Happy path</title><style>
body{{font-family:'Segoe UI',system-ui,sans-serif;background:#0f172a;
color:#e2e8f0;margin:0}} .w{{max-width:1150px;margin:0 auto;padding:26px 20px 60px}}
h1{{font-size:21px;margin:0 0 4px}} .s{{color:#94a3b8;font-size:12.5px;margin:2px 0}}
.hero{{text-align:center;padding:22px;border-radius:12px;margin:18px 0 24px;
background:#1e293b;border:1px solid #334155}}
.big{{font-size:36px;font-weight:800;color:{color}}}
.b{{background:#1e293b;border:1px solid #334155;border-radius:10px;
padding:6px 16px;margin-bottom:10px}}
.b>summary{{list-style:none;cursor:pointer;display:flex;gap:10px;
align-items:center;padding:10px 0;font-size:14px}}
.b>summary::-webkit-details-marker{{display:none}}
.b>summary::before{{content:'▸';color:#64748b;font-size:12px;transition:transform .15s}}
.b[open]>summary::before{{transform:rotate(90deg)}}
.bt{{font-weight:700;color:#e2e8f0}}
.b h2{{font-size:14px;margin:10px 0 8px}}
.b h3{{font-size:12px;color:#94a3b8;margin:0 0 4px;font-weight:600}}
.par{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
pre{{background:#0f172a;border:1px solid #334155;border-radius:6px;padding:9px;
font-size:11px;overflow:auto;max-height:340px;margin:0;white-space:pre-wrap;
word-break:break-word}}
table{{width:100%;border-collapse:collapse;font-size:12.5px}}
td,th{{padding:6px 9px;border-bottom:1px solid #0f172a;text-align:left}}
th{{color:#94a3b8}} .pie{{color:#64748b;font-size:11.5px;margin-top:22px;line-height:1.6}}
</style></head><body><div class="w">
<h1>TRN-239 · Happy path — alta y cancelación</h1>
<p class="s">{_e(P.BASE_URL)}</p>
<p class="s">{datetime.now():%Y-%m-%d %H:%M:%S}</p>
<div class="hero"><div class="big">{_e(veredicto)}</div></div>
<section class="b"><h2>Resumen</h2><table>{resumen}</table></section>
{''.join(bloques)}
<p class="pie">Una llamada es correcta si <b>HTTP 200</b> y <b>Errorcode = 0</b>
y <b>Error_text</b> contiene «Success» — las tres cosas.
La comisión viaja en <b>D1Discount</b>: en producción <code>Commission =
D1Discount</code> en los 4 659 662 registros ITU. El <b>Margin</b> del catálogo
se muestra como referencia, no se envía.
Las lecturas de base de datos son de <code>{_e(P.TABLA_TRANSFER)}</code>.</p>
</div></body></html>"""
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(doc, encoding="utf-8")


# ── Main ────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="TRN-239 happy path")
    ap.add_argument("--sku", help="forzar un SKU concreto")
    ap.add_argument("--monto", type=float, default=None)
    ap.add_argument("--altas", type=int, default=1,
                    help="cuántos RegisterTransaction mandar (cada uno un "
                         "bloque desplegable en el reporte). Por defecto 1.")
    ap.add_argument("--sin-cancelar", action="store_true")
    ap.add_argument("--desde-bd", action="store_true",
                    help="copiar Entity/ExternalID/CID de una transacción "
                         "REAL de lunex.TransferLN en vez de usar los "
                         "valores heredados sin confirmar")
    args = ap.parse_args()

    cn = BD.conectar()
    productos = catalogo(cn)

    # ── Identidad: la heredada o la real ────────────────────────────────────
    real = identidad_real(cn) if args.desde_bd else {}
    if args.desde_bd:
        if not real:
            print("  [!] No hay filas en lunex.TransferLN de donde copiar la "
                  "identidad. Se sigue con los valores heredados.")
        else:
            print("  Identidad tomada de una transacción REAL de la tabla:")
            for clave in ("Entity", "ExternalID", "CID"):
                print(f"    {clave:<12} BD='{real.get(clave)}'  "
                      f"vs heredado='{getattr(P, clave.upper(), '')}'")
            print(f"    Columnas de la tabla: "
                  f"{', '.join(real.get('_columnas', [])[:14])}…")

    if args.sku:
        elegido = next((p for p in productos if p[0] == args.sku), None)
        if elegido is None:
            elegido = (args.sku, f"SKU {args.sku}", 16.00)
            print(f"  [!] {args.sku} no está en el catálogo; se usa margen 16.")
    else:
        elegido = random.choice(productos)
    sku, nombre, margen = elegido
    monto = args.monto if args.monto is not None else float(P.MONTO)

    print()
    print("═" * 74)
    print("  TRN-239 · Happy path")
    print("═" * 74)
    print(f"  {P.BASE_URL}")
    print(f"  Producto : {sku} · {nombre}")
    print(f"  Margin   : {margen} %   (referencia del catálogo, no se envía)")
    print(f"  Monto    : {monto}")
    print(f"  Catálogo : {len(productos)} producto(s) "
          f"{'de BD' if cn is not None else '(respaldo, sin BD)'}")
    print("─" * 74)

    cnt = B.Contadores()
    bloques, filas_resumen = [], []
    veredicto_ok = True

    # ── Altas ────────────────────────────────────────────────────────────────
    # Se puede mandar más de un registro con --altas N. Cada uno es un bloque
    # DESPLEGABLE con su petición y su respuesta (título con el TransactionID);
    # el resumen de arriba lleva el veredicto de cada uno. Se cancela el último.
    alta, r1, fila_alta = None, None, {}
    for i in range(1, args.altas + 1):
        alta = cuerpo_alta(cnt, sku, nombre, margen, monto)
        # Con `--desde-bd`, la identidad se copia de una transacción que la API
        # ya procesó (solo los campos que existan).
        for clave in ("Entity", "ExternalID", "CID"):
            if real.get(clave):
                alta[clave] = real[clave]
        r1 = API.registrar(alta)
        print(f"  {i}. RegisterTransaction  tran={alta['TransactionID']} "
              f"→ {r1.resumen()}")
        bloques.append(_bloque(
            f"{i} · RegisterTransaction: {alta['TransactionID']}", alta,
            r1.cuerpo or r1.texto[:900],
            _chip(r1.ok, "OK" if r1.ok else "FALLA"),
            abierto=(args.altas == 1)))
        filas_resumen.append(
            f"<tr><td>Alta {i}</td>"
            f"<td>{_chip(r1.ok, 'OK' if r1.ok else 'FALLA')}</td>"
            f"<td>tran={_e(alta['TransactionID'])} · {_e(r1.resumen())}</td></tr>")
        veredicto_ok &= r1.ok

        fila_alta = {}
        if cn is not None and r1.ok:
            fila_alta = BD.buscar_transaccion(cn, alta["TransactionID"])
            hallada = bool(fila_alta)
            comp = BD.comparar(fila_alta, alta) if hallada else {}
            detalle = ("coinciden: " + ", ".join(comp.get("coinciden", []))
                       if hallada and not comp.get("difieren")
                       else "; ".join(comp.get("difieren", []))
                       if hallada else "la API dijo Success y no persistió")
            filas_resumen.append(
                f"<tr><td>Persistida {i}</td>"
                f"<td>{_chip(hallada, 'OK' if hallada else 'FALLA')}</td>"
                f"<td>{_e(detalle)}</td></tr>")
            veredicto_ok &= hallada
            if hallada:
                fallos = BD.coherencia_produccion(fila_alta)
                coherente = not fallos
                filas_resumen.append(
                    f"<tr><td>Coherencia {i}</td>"
                    f"<td>{_chip(coherente, 'OK' if coherente else 'FALLA')}</td>"
                    f"<td>{_e('reglas de producción OK' if coherente else '; '.join(fallos))}</td></tr>")
                veredicto_ok &= coherente
        elif cn is None:
            filas_resumen.append(
                f"<tr><td>Persistida {i}</td><td>—</td>"
                f"<td>sin conexión a base de datos</td></tr>")

    # ── 3. Cancelación (del último registro) ────────────────────────────────
    if r1 and r1.ok and not args.sin_cancelar:
        cancel = B.cancelacion(cnt, alta["TransactionID"], sku, "ITU")
        r2 = API.cancelar(cancel)
        print(f"  CancelTransaction       → {r2.resumen()}")
        bloques.append(_bloque(
            f"CancelTransaction: {alta['TransactionID']}", cancel,
            r2.cuerpo or r2.texto[:900],
            _chip(r2.ok, "OK" if r2.ok else "FALLA")))
        filas_resumen.append(
            f"<tr><td>Cancelación</td>"
            f"<td>{_chip(r2.ok, 'OK' if r2.ok else 'FALLA')}</td>"
            f"<td>Status enviado={_e(P.ESTADO_CANCELACION)} · "
            f"{_e(r2.resumen())}</td></tr>")
        veredicto_ok &= r2.ok

        # ── 4. ¿Cambió el estado? ───────────────────────────────────────────
        if cn is not None and r2.ok:
            fila_cancel = BD.buscar_transaccion(cn, alta["TransactionID"])
            cancelada, detalle_cancel = BD.cancelacion_confirmada(fila_cancel)
            estado = BD.estado_persistido(cn, alta["TransactionID"])
            print(f"  4. Cancelada en BD      → {'SÍ' if cancelada else 'NO'} "
                  f"({detalle_cancel})")
            bloques.append(_bloque(
                "4 · Lectura tras la cancelación",
                {"TransactionID": alta["TransactionID"]},
                fila_cancel or "(no encontrada)",
                _chip(cancelada,
                      f"Cancelada = {'SÍ' if cancelada else 'NO'} · {estado or '?'}")))
            filas_resumen.append(
                f"<tr><td>Estado tras cancelar</td>"
                f"<td>{_chip(cancelada, 'OK' if cancelada else 'FALLA')}</td>"
                f"<td>{_e(detalle_cancel)}</td></tr>")
            veredicto_ok &= cancelada
    elif args.sin_cancelar:
        print("  3. CancelTransaction    → omitida (--sin-cancelar)")

    veredicto = "OK" if veredicto_ok else "FALLA"
    escribir(bloques, "".join(filas_resumen), veredicto)

    print("─" * 74)
    print(f"  VEREDICTO: {veredicto}")
    print(f"  Reporte  : {SALIDA}")
    print("═" * 74)
    print()
    if cn is not None:
        try:
            cn.close()
        except Exception:
            pass
    return 0 if veredicto_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
