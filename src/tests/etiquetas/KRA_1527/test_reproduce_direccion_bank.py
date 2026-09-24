"""
Reproductor/validador del BANCO de direcciones (segundo flujo).

A diferencia de test_valida_direccion_loop.py (que cosecha del validador EN
VIVO), este script toma las direcciones YA guardadas en
`src/helpers/direcciones_us_validadas.json` y las REPRODUCE en el formulario del
cliente para confirmar que cada una sigue siendo real y VÁLIDA (que el endpoint
de Hermes NO muestre el error de dirección → deja continuar).

Regla de auto-limpieza: si una dirección del banco YA NO valida (no la devuelve
el validador, o el campo queda en error), se DESCARTA del JSON. Así el banco se
depura solo y no arrastra direcciones muertas.

Flujo por dirección:
  1. (sesión/idioma los da logged_page)
  2. Llena identidad del cliente (ficticia)
  3. Teclea la CALLE del banco → busca ESA sugerencia (misma calle + su zip) →
     la elige (↓+Enter) → pone su zip → verifica que NO haya error
  4. Limpia (transfer-customer-clear-0-icon-svg) y sigue con la siguiente
  5. Al final: guarda el banco depurado (sin las que fallaron)

Ejecutar:
    $env:KRA1527_REPRO_DIR="1"
    pytest src/tests/etiquetas/KRA_1527/test_reproduce_direccion_bank.py -s
Opcionales:
    $env:KRA1527_REPRO_MAX="200"     # probar solo N direcciones (default: todas)
    $env:KRA1527_REPRO_MIN_PCT="95"  # % mínimo para que el test pase (default 95)
    $env:KRA1527_REPRO_PURGAR="0"    # 1=descarta las fallidas (default 1)
"""

import json
import os
import random
import re
from pathlib import Path

import pytest
from faker import Faker

from config import settings
from config.logger import get_logger
from .flujos.transferencia_page import HmTransferelektraPage

logger = get_logger("KRA-1527.repro-dir")

BANK = Path(settings.PROJECT_ROOT) / "src" / "helpers" / "direcciones_us_validadas.json"
CLEAR_TESTID = "transfer-customer-clear-0-icon-svg"
ADDR_TESTID = "transfer-customer-address-0-input"
ZIP_TESTID = "transfer-customer-zip-code-0-input"


def _cargar():
    if not BANK.is_file():
        return {}
    try:
        return json.loads(BANK.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("[Repro] no se pudo leer el banco: %s", str(e)[:120])
        return {}


def _guardar(crudo):
    orden = {zp: {"city": crudo[zp].get("city", ""),
                  "state": crudo[zp].get("state", ""),
                  "streets": sorted(crudo[zp].get("streets", []))}
             for zp in sorted(crudo) if crudo[zp].get("streets")}
    BANK.write_text(json.dumps(orden, ensure_ascii=False, indent=1), encoding="utf-8")


@pytest.mark.repro_dir
@pytest.mark.asyncio
async def test_reproduce_direccion_bank(logged_page):
    if os.getenv("KRA1527_REPRO_DIR", "0").strip().lower() not in (
            "1", "true", "si", "sí", "yes"):
        pytest.skip("Reproductor desactivado. Actívalo con KRA1527_REPRO_DIR=1.")

    banco = _cargar()
    if not banco:
        pytest.skip(f"El banco {BANK} no existe o está vacío. Corre primero la "
                    "cosecha (test_valida_direccion_loop.py).")

    purgar = os.getenv("KRA1527_REPRO_PURGAR", "1").strip() in ("1", "true", "si", "sí", "yes")
    min_pct = float(os.getenv("KRA1527_REPRO_MIN_PCT", "95") or "95")

    # Aplanar el banco a (zip, city, state, street), barajado.
    filas = []
    for zp, info in banco.items():
        for st in info.get("streets", []):
            filas.append((zp, info.get("city", ""), info.get("state", ""), st))
    random.shuffle(filas)
    tope = os.getenv("KRA1527_REPRO_MAX", "").strip()
    if tope.isdigit():
        filas = filas[:int(tope)]

    flow = HmTransferelektraPage(logged_page)
    page = logged_page
    fake = Faker("en_US")

    async def _valor(testid):
        try:
            return (await page.get_by_test_id(testid).first.input_value(timeout=1_200)) or ""
        except Exception:
            return ""

    logger.info("[Repro] %d direcciones del banco a reproducir (purgar=%s).",
                len(filas), purgar)

    ok = 0
    a_descartar = []          # (zip, street) que ya no validan
    total = len(filas)
    for i, (zp, city, state, street) in enumerate(filas, 1):
        await flow.navigate()
        await flow.fill_transfer_customer_cellphone_0_cellphone_input(fake.numerify("210555####"))
        await flow.fill_transfer_customer_name_0_input(fake.first_name())
        await flow.fill_transfer_customer_first_lastname_0_input(fake.last_name())
        await flow.fill_transfer_customer_second_lastname_0_input(fake.last_name())
        try:
            await flow.click_close_table()
        except Exception:
            pass

        # Teclear la CALLE del banco y buscar ESA sugerencia (misma calle + zip).
        data = await flow.sugerencias_direccion_por_red(street)
        objetivo_idx = None
        escr = flow._tokens_calle(street)
        for k, it in enumerate(data):
            sec = (it.get("secondaryText") or "")
            mt = it.get("mainText") or ""
            if not mt[:1].isdigit():
                continue
            if zp in sec and flow._tokens_calle(mt) == escr:
                objetivo_idx = k
                break
        # Respaldo: misma calle aunque el zip venga en otra (Hermes pondrá el zip real).
        if objetivo_idx is None:
            for k, it in enumerate(data):
                mt = it.get("mainText") or ""
                if mt[:1].isdigit() and flow._tokens_calle(mt) == escr:
                    objetivo_idx = k
                    break

        valido = False
        if objetivo_idx is not None:
            it = data[objetivo_idx]
            sec = " ".join((it.get("secondaryText") or "").split())
            m = re.search(r"\b(\d{5})\b", sec)
            zsel = m.group(1) if m else zp
            try:
                for _ in range(objetivo_idx + 1):
                    await page.keyboard.press("ArrowDown")
                    await page.wait_for_timeout(120)
                await page.keyboard.press("Enter")
            except Exception:
                try:
                    await page.get_by_text(it.get("mainText"), exact=False).first.click(timeout=4_000)
                except Exception:
                    pass
            await page.wait_for_timeout(400)
            if zsel:
                await flow.fill_transfer_customer_zip_code_0_input(zsel)
                await flow.esperar_autocomplete_cp()
            for _ in range(8):
                if not await flow._direccion_en_error():
                    valido = True
                    break
                await page.wait_for_timeout(400)

        if valido:
            ok += 1
            logger.info("[%d/%d] ✓ %s [%s %s]", i, total, street, city, zp)
        else:
            a_descartar.append((zp, street))
            logger.warning("[%d/%d] ✗ NO validó → se descartará: %s [%s %s]",
                           i, total, street, city, zp)

        for intento in (False, True):
            try:
                await page.get_by_test_id(CLEAR_TESTID).first.click(force=intento, timeout=4_000)
                break
            except Exception:
                continue
        await page.wait_for_timeout(500)

    # Auto-limpieza: quitar del banco las que ya no validan.
    if purgar and a_descartar:
        for zp, street in a_descartar:
            if zp in banco and street in banco[zp].get("streets", []):
                banco[zp]["streets"] = [s for s in banco[zp]["streets"] if s != street]
        banco = {zp: v for zp, v in banco.items() if v.get("streets")}
        _guardar(banco)
        logger.info("[Repro] Banco depurado: se quitaron %d direcciones muertas.",
                    len(a_descartar))

    pct = 100.0 * ok / total if total else 0
    logger.info("═" * 60)
    logger.info("[Repro] %d/%d válidas (%.1f%%) · %d descartadas · banco: %s",
                ok, total, pct, len(a_descartar), BANK)
    logger.info("═" * 60)

    assert pct >= min_pct, (f"Solo {pct:.1f}% del banco validó (< {min_pct:.0f}%). "
                            f"{len(a_descartar)} descartadas. Revisa el log.")
