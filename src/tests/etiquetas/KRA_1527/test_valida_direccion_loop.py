"""
Prueba en BUCLE del validador de direcciones + COSECHA de direcciones válidas.

Repite N veces el ciclo:
  1-3. Sesión + notificaciones + idioma  (fixture logged_page)
  4.   Llena el formulario del cliente (teléfono, nombre, apellidos)
  5.   ORDEN CORRECTO: teclea una calle → elige una sugerencia verificada
       (teclado ↓+Enter) → pone el ZIP de ESA dirección → verifica sin error
  6.   Guarda la dirección validada en el concentrado y pulsa «Limpiar»

Doble propósito:
  · Estabilidad: mide cuántas de N vuelven válidas (%).
  · Banco de datos: acumula las direcciones REALES confirmadas por Hermes en
    `src/helpers/direcciones_us_validadas.json` (dedup, agrupado por zip; se
    salva cada 25 vueltas y al terminar/interrumpir). Formato reutilizable —
    mismo esquema que direcciones_us_bank.json.

Ejecutar por ITERACIONES:
    $env:KRA1527_VALIDA_DIR="1"; $env:KRA1527_DIR_ITER="10000"
    pytest src/tests/etiquetas/KRA_1527/test_valida_direccion_loop.py -s
Ejecutar por TIEMPO (minutos; manda sobre las iteraciones):
    $env:KRA1527_VALIDA_DIR="1"; $env:KRA1527_DIR_MINUTES="120"
    pytest src/tests/etiquetas/KRA_1527/test_valida_direccion_loop.py -s

COSECHA RÁPIDA para ENGORDAR el banco (solo teclea semillas variadas y recolecta
las sugerencias reales de PostGrid; sin validar/intercept/envío → mucho más rápido):
    $env:KRA1527_VALIDA_DIR="1"; $env:KRA1527_DIR_COSECHA="1"; $env:KRA1527_DIR_MINUTES="120"
    pytest src/tests/etiquetas/KRA_1527/test_valida_direccion_loop.py -s
Opcionales:
    $env:KRA1527_DIR_MIN_PCT="90"   # % mínimo para que el test pase (default 90)

Solo cosecha calles BIEN FORMADAS que devuelve PostGrid (real); al arrancar
depura del banco las malformadas heredadas (respaldo en direcciones_us_validadas.bak.json).
El banco resultante lo usan en random los demás scripts de Money Transfer
(vía src/helpers/direcciones_us.py).
"""

import json
import os
import random as _rnd
from pathlib import Path

import pytest
from faker import Faker

from config import settings
from config.logger import get_logger
from src.helpers.direcciones_us import candidatos
from .flujos.transferencia_page import HmTransferelektraPage

logger = get_logger("KRA-1527.valida-dir")

CLEAR_TESTID = "transfer-customer-clear-0-icon-svg"
CITY_TESTID = "transfer-customer-city-0-input"
STATE_TESTID = "transfer-customer-state-0-input"
ADDR_TESTID = "transfer-customer-address-0-input"
ZIP_TESTID = "transfer-customer-zip-code-0-input"

BANK = Path(settings.PROJECT_ROOT) / "src" / "helpers" / "direcciones_us_validadas.json"
GUARDAR_CADA = 25

# ── Validación de calle bien formada (para cosechar solo direcciones limpias) ─
_DIRS = {"N", "S", "E", "W", "NE", "NW", "SE", "SW"}
_SUF = {"ST", "STREET", "AVE", "AVENUE", "BLVD", "BOULEVARD", "RD", "ROAD",
        "DR", "DRIVE", "LN", "LANE", "CT", "COURT", "PL", "PLACE", "SQ",
        "SQUARE", "PKWY", "PARKWAY", "HWY", "HIGHWAY", "LOOP", "WAY", "TER",
        "TERRACE", "CIR", "CIRCLE", "TRL", "TRAIL"}


def _calle_ok(street: str) -> bool:
    """True si la calle está BIEN FORMADA como la devuelve PostGrid.

    Rechaza las corruptas de la cosecha vieja donde el direccional quedó ANTES
    del sufijo ('125 MAIN N ST', '1315 10TH NW ST', '401 2ND NW ST'). Un postdir
    real va DESPUÉS del sufijo ('601 LAKESIDE AVE E'), no antes."""
    t = (street or "").upper().split()
    if len(t) < 2 or not t[0][:1].isdigit():
        return False
    for i in range(1, len(t) - 1):
        if t[i] in _DIRS and t[i + 1] in _SUF:   # DIR justo antes del sufijo → corrupto
            return False
    return True


# ── Generador de semillas VARIADAS (para que PostGrid devuelva calles nuevas) ─
_NOMBRES = [
    "OAK", "ELM", "MAPLE", "PINE", "CEDAR", "PARK", "MAIN", "WASHINGTON",
    "LINCOLN", "JEFFERSON", "MADISON", "FRANKLIN", "JACKSON", "ADAMS", "LAKE",
    "HILL", "RIVER", "CENTER", "CHURCH", "MARKET", "BROAD", "HIGH", "UNION",
    "SPRING", "SUNSET", "HIGHLAND", "RIDGE", "MEADOW", "FOREST", "VALLEY",
    "WILLOW", "CHERRY", "WALNUT", "CHESTNUT", "JOHNSON", "WILSON", "MILLER",
    "DAVIS", "CLARK", "MONROE", "COLLEGE", "SCHOOL", "MILL", "WATER", "STATE",
    "COURT", "PROSPECT", "GRAND", "CANAL", "DEPOT", "HARRISON", "GRANT",
]
_ORD = [f"{n}{'TH' if 11 <= n % 100 <= 13 else {1: 'ST', 2: 'ND', 3: 'RD'}.get(n % 10, 'TH')}"
        for n in range(1, 41)]
_SUF_GEN = ["ST", "AVE", "DR", "RD", "BLVD", "LN", "CT", "PL", "WAY"]
_PRE_GEN = ["", "", "N", "S", "E", "W"]   # a veces sin direccional


def _semilla_variada() -> str:
    """Una calle plausible al azar ('<num> [DIR] NOMBRE SUF') para provocar que el
    autocomplete de PostGrid devuelva direcciones reales NUEVAS."""
    num = _rnd.choice([_rnd.randint(1, 299),
                       _rnd.choice([100, 200, 300, 400, 500, 700, 900, 1200, 1500, 2000])])
    nombre = _rnd.choice(_NOMBRES + _ORD)
    pre = _rnd.choice(_PRE_GEN)
    suf = _rnd.choice(_SUF_GEN)
    return " ".join(x for x in [str(num), pre, nombre, suf] if x)


def _proxima_semilla() -> str:
    """80% semilla variada (calles frescas) · 20% del banco (para homónimos)."""
    if _rnd.random() < 0.80:
        return _semilla_variada()
    try:
        c = candidatos(1)
        return c[0]["direccion"] if c else _semilla_variada()
    except Exception:
        return _semilla_variada()


def _cargar():
    """{zip: {'city','state','streets': set()}}"""
    banco = {}
    try:
        if BANK.is_file():
            for zp, info in json.loads(BANK.read_text(encoding="utf-8")).items():
                banco[zp] = {"city": info.get("city", ""),
                             "state": info.get("state", ""),
                             "streets": set(info.get("streets", []))}
    except Exception as e:
        logger.warning("[Valida-Dir] no se pudo cargar el concentrado: %s", str(e)[:120])
    return banco


def _guardar(banco):
    crudo = {zp: {"city": v["city"], "state": v["state"],
                  "streets": sorted(v["streets"])}
             for zp, v in sorted(banco.items())}
    BANK.write_text(json.dumps(crudo, ensure_ascii=False, indent=1), encoding="utf-8")


@pytest.mark.valida_dir
@pytest.mark.asyncio
async def test_valida_direccion_loop(logged_page):
    if os.getenv("KRA1527_VALIDA_DIR", "0").strip().lower() not in (
            "1", "true", "si", "sí", "yes"):
        pytest.skip("Prueba de bucle desactivada. Actívala con KRA1527_VALIDA_DIR=1.")

    import time as _t
    n = int(os.getenv("KRA1527_DIR_ITER", "10") or "10")
    minutos = float(os.getenv("KRA1527_DIR_MINUTES", "0") or "0")
    deadline = (_t.monotonic() + minutos * 60) if minutos > 0 else None
    if deadline:
        n = 10 ** 9                       # tope alto; manda el tiempo
    meta = f"{minutos:g}min" if deadline else str(n)
    min_pct = float(os.getenv("KRA1527_DIR_MIN_PCT", "90") or "90")
    flow = HmTransferelektraPage(logged_page)
    page = logged_page
    fake = Faker("en_US")
    doms = candidatos(max(min(n, 200), 10))

    async def _valor(testid):
        try:
            return (await page.get_by_test_id(testid).first.input_value(timeout=1_200)) or ""
        except Exception:
            return ""

    banco = _cargar()

    # Auto-limpieza: respaldo (una vez) + purga de calles malformadas heredadas,
    # para que la cosecha quede limpia y el flujo real vuelva a ser la norma.
    quitadas = 0
    for zp in list(banco):
        limpias = {s for s in banco[zp]["streets"] if _calle_ok(s)}
        quitadas += len(banco[zp]["streets"]) - len(limpias)
        if limpias:
            banco[zp]["streets"] = limpias
        else:
            del banco[zp]
    if quitadas:
        bak = BANK.with_suffix(".bak.json")
        if not bak.exists():
            try:
                bak.write_text(BANK.read_text(encoding="utf-8"), encoding="utf-8")
                logger.info("[Valida-Dir] Respaldo del banco → %s", bak)
            except Exception:
                pass
        _guardar(banco)
        logger.info("[Valida-Dir] Banco depurado: %d calles malformadas retiradas.", quitadas)

    nuevas = [0]

    def _agregar(zp, city, state, street):
        if not (zp and street) or not _calle_ok(street):   # solo calles limpias
            return
        e = banco.setdefault(zp, {"city": city, "state": state, "streets": set()})
        e["city"] = e["city"] or city
        e["state"] = e["state"] or state
        if street not in e["streets"]:
            e["streets"].add(street)
            nuevas[0] += 1

    def _cosechar(data):
        """Guarda todas las sugerencias reales número+calle de una consulta."""
        antes = nuevas[0]
        for it in (data or []):
            if it.get("id") == "auto-0":            # ignora el mock del intercept
                continue
            mt = " ".join((it.get("mainText") or "").split()).upper()
            if not mt or not mt[:1].isdigit():
                continue
            sec = " ".join((it.get("secondaryText") or "").split())
            mz = next((t for t in sec.split() if len(t) == 5 and t.isdigit()), None)
            if not mz:
                continue
            ciu = sec.replace(mz, "").strip(" ,").upper()
            _agregar(mz, ciu, "", mt)
        return nuevas[0] - antes

    # ── MODO COSECHA RÁPIDA: solo teclea semillas variadas y recolecta las
    #    sugerencias reales de PostGrid (sin validar, sin intercept, sin envío).
    #    Es la forma más rápida de engordar el banco. Actívalo con KRA1527_DIR_COSECHA=1.
    if os.getenv("KRA1527_DIR_COSECHA", "0").strip().lower() in (
            "1", "true", "si", "sí", "yes"):
        await flow.navigate()
        proc = 0
        try:
            for i in range(1, n + 1):
                if deadline and _t.monotonic() >= deadline:
                    break
                proc += 1
                seed = _proxima_semilla()
                try:
                    data = await flow.sugerencias_direccion_por_red(seed, espera_ms=1_200)
                except Exception as e:
                    logger.warning("[Cosecha %d] %s", i, str(e)[:100])
                    data = []
                nuevas_i = _cosechar(data)
                if nuevas_i or i % 10 == 0:
                    tot = sum(len(v["streets"]) for v in banco.values())
                    logger.info("[Cosecha %d/%s] '%s' → +%d · banco %d dir / %d zip (+%d nuevas)",
                                i, meta, seed, nuevas_i, tot, len(banco), nuevas[0])
                if i % GUARDAR_CADA == 0:
                    _guardar(banco)
        finally:
            _guardar(banco)
        tot = sum(len(v["streets"]) for v in banco.values())
        logger.info("═" * 60)
        logger.info("[Cosecha] %d consultas · banco %d dir / %d zip (+%d nuevas) · %s",
                    proc, tot, len(banco), nuevas[0], BANK)
        logger.info("═" * 60)
        return

    ok = 0
    fallas = []
    modos = {"real": 0, "intercept": 0, "otro": 0}   # cómo se resolvió cada dirección
    try:
        for i in range(1, n + 1):
            if deadline and _t.monotonic() >= deadline:
                break
            if i > 1 and (i - 1) % len(doms) == 0:
                doms = candidatos(200)     # nueva tanda barajada → más variedad
            dom = doms[(i - 1) % len(doms)]
            await flow.navigate()
            await flow.fill_transfer_customer_cellphone_0_cellphone_input(fake.numerify("210555####"))
            await flow.fill_transfer_customer_name_0_input(fake.first_name())
            await flow.fill_transfer_customer_first_lastname_0_input(fake.last_name())
            await flow.fill_transfer_customer_second_lastname_0_input(fake.last_name())
            try:
                await flow.click_close_table()
            except Exception:
                pass

            # ORDEN CORRECTO: dirección primero → elegir verificada → su zip.
            elegido, sugerencias = {}, []
            try:
                _okd, elegido, sugerencias = await flow.resolver_direccion_cliente(
                    dom["direccion"], zip_preferido=dom["zip"])
            except Exception as e:
                logger.warning("[%d/%d] excepción al resolver: %s", i, n, str(e)[:120])

            # COSECHAR TODAS las sugerencias reales de esta consulta (no solo la
            # elegida). Cada una es una dirección real con su propio zip; el set
            # por zip descarta duplicados automáticamente.
            cosechadas = 0
            for it in sugerencias:
                mt = " ".join((it.get("mainText") or "").split()).upper()
                if not mt or not mt[:1].isdigit():      # Hermes exige número+calle
                    continue
                sec = " ".join((it.get("secondaryText") or "").split())
                mz = None
                for tok in sec.split():
                    if len(tok) == 5 and tok.isdigit():
                        mz = tok
                        break
                if not mz:
                    continue
                ciu = sec.replace(mz, "").strip(" ,").upper()
                antes = nuevas[0]
                _agregar(mz, ciu, "", mt)
                cosechadas += (nuevas[0] - antes)

            modo = (elegido or {}).get("modo") or "otro"
            modos[modo if modo in modos else "otro"] += 1

            en_error = await flow._direccion_en_error()
            addr = (await _valor(ADDR_TESTID)).strip()
            zip_f = (await _valor(ZIP_TESTID)).strip()
            city_f = (await _valor(CITY_TESTID)).strip()
            state_f = (await _valor(STATE_TESTID)).strip()
            # Efectividad real: dirección SIN error, con calle Y con ZIP poblado
            # (el ZIP es requerido; era justo lo que faltaba antes).
            valido = (not en_error) and bool(addr) and bool(zip_f)

            # CONFIRMACIÓN de que la validación pasó: avanzar al SIGUIENTE
            # formulario (Beneficiario) seleccionando País = MÉXICO, esperar 3-5 s
            # y comprobar que la alerta roja de dirección NO reaparezca.
            confirmado = False
            if valido:
                try:
                    await flow.fill_transfer_beneficiary_country_0_dropdown_input("MEXICO")
                except Exception:
                    try:   # respaldo: clic al combo de nombre del beneficiario
                        await page.get_by_test_id(
                            "transfer-beneficiary-name-0-dropdown-input").first.click(timeout=3_000)
                    except Exception:
                        pass
                await page.wait_for_timeout(4_000)      # 3-5 s de garantía
                confirmado = not await flow._direccion_en_error()

            exito = valido and confirmado
            if exito:
                ok += 1
                logger.info("[%d/%s] ✓ ÉXITO (%s) — %s · ZIP=%s · %s %s | ÉXITOS=%d FALLAS=%d",
                            i, meta, modo, elegido.get("direccion") or addr, zip_f,
                            city_f, state_f, ok, len(fallas))
            else:
                fallas.append({"i": i, "zip": dom["zip"], "dir": dom["direccion"],
                               "modo": modo, "en_error": en_error,
                               "confirmado": confirmado, "addr": addr, "zip_f": zip_f})
                logger.warning("[%d/%s] ✗ FALLA (%s) — zip=%s dir='%s' en_error=%s "
                               "confirmado=%s addr='%s' zip_lleno='%s' | ÉXITOS=%d FALLAS=%d",
                               i, meta, modo, dom["zip"], dom["direccion"], en_error,
                               confirmado, addr, zip_f, ok, len(fallas))

            # Limpiar (botón que indicó el usuario) y repetir.
            for intento in (False, True):
                try:
                    await page.get_by_test_id(CLEAR_TESTID).first.click(
                        force=intento, timeout=4_000)
                    break
                except Exception:
                    continue
            await page.wait_for_timeout(500)

            if i % GUARDAR_CADA == 0:
                _guardar(banco)
                total = sum(len(v["streets"]) for v in banco.values())
                logger.info("[Valida-Dir] progreso %d/%s · válidas %d · banco %d dir / %d zip (+%d nuevas)",
                            i, meta, ok, total, len(banco), nuevas[0])
    finally:
        _guardar(banco)   # persistir aunque se interrumpa (Ctrl+C)

    total = sum(len(v["streets"]) for v in banco.values())
    proc = ok + len(fallas)                      # vueltas realmente ejecutadas
    pct = 100.0 * ok / proc if proc else 0
    logger.info("═" * 60)
    logger.info("[Valida-Dir] %d/%d válidas (%.1f%%) · resueltas: real=%d intercept=%d otro=%d",
                ok, proc, pct, modos["real"], modos["intercept"], modos["otro"])
    logger.info("[Valida-Dir] banco: %d dir / %d zip (+%d nuevas) · %s",
                total, len(banco), nuevas[0], BANK)
    for f in fallas[:30]:
        logger.warning("[Valida-Dir] FALLA #%d zip=%s dir='%s' en_error=%s addr='%s'",
                       f["i"], f["zip"], f["dir"], f["en_error"], f["addr"])
    logger.info("═" * 60)

    assert pct >= min_pct, (f"Estabilidad {pct:.1f}% < mínimo {min_pct:.0f}% "
                            f"({len(fallas)}/{proc} fallas). Banco guardado en {BANK}.")
