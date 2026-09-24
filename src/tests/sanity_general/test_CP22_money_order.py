"""
CP22 — Generar Money Order con Información Adicional, imprimirlo y anularlo.
(Rescate de `HERMES2-qa/src/sanity_general/test_CP22_generar_money_order_info_adicional.py`.)

Flujo:
  1. Configuración → registrar y seleccionar la impresora de Money Orders.
  2. Services > Money Order.
  3. Datos del comprador.
  4. Alta del MO por $3,000 — el sistema lo DIVIDE en 3 money orders de $1,000.
  5. Compliance exige Información Adicional → se llena (incluye FOTO del ID).
  6. Imprimir el MO.  ← aquí es donde Hermes habla con el Hardware Agent
  7. Reportes > Transacciones (tipo MONEY ORDER) → ANULAR los 3 creados.

El paso 7 no es decorativo: un MO que se queda en Open ensucia el ambiente y
descuadra las corridas siguientes. El caso limpia lo que crea.

CÁMARA: la foto del ID usa la webcam. El conftest levanta Chromium con una
cámara simulada, así que corre en máquinas sin cámara.

REUTILIZACIÓN: el módulo `src/sanity_general/money_order.py` es el mismo que usa
la etiqueta **KRA-1527** para auditar la comunicación con el agente durante la
impresión. Un flujo, dos usos.

COMO CORRER:
    pytest src/tests/sanity_general -k CP22 -v -s
    $env:CP22_ANULAR="0"; pytest src/tests/sanity_general -k CP22 -v -s  # sin limpiar
"""
import os
import pytest
from faker import Faker
from playwright.async_api import Page

from config.logger import get_logger
from src.helpers.screenshot_helper import ScreenshotHelper
from src.sanity_general import Evidencia
from src.sanity_general import money_order as MO

logger = get_logger("CP22")
fake = Faker()

MONTO = os.getenv("CP22_AMOUNT", "3000")
ESPERADOS = int(os.getenv("CP22_ESPERADOS", "3"))     # $3,000 → 3 MO de $1,000
ANULAR = os.getenv("CP22_ANULAR", "1").strip().lower() in ("1", "true", "si", "yes")
PREPARAR_IMPRESORA = os.getenv("CP22_IMPRESORA", "1").strip().lower() in (
    "1", "true", "si", "yes")

EVIDENCE = "CP22_money_order"


def datos_comprador() -> dict:
    nombre = fake.first_name().upper()
    ap1 = fake.last_name().upper()
    ap2 = fake.last_name().upper()
    return {
        "telefono": fake.numerify("555010####"),
        "nombre": nombre,
        "apellido1": ap1,
        "apellido2": ap2,
        "pay_to": f"{nombre} {ap1}",
        "num_id": fake.numerify("#########"),
        "tax_id": fake.numerify("478######"),
        "direccion": fake.street_address().upper(),
        "razon": fake.sentence(nb_words=4),
    }


@pytest.mark.sanity_general
@pytest.mark.asyncio
@pytest.mark.parametrize("language,width,height", [("English", 1366, 768)])
async def test_CP22_money_order(logged_page: Page, language, width, height):
    evi = Evidencia(ScreenshotHelper(logged_page), EVIDENCE)
    cliente = datos_comprador()
    logger.info("[CP22] Comprador %s %s · $%s (se esperan %d money orders)",
                cliente["nombre"], cliente["apellido1"], MONTO, ESPERADOS)

    # ── Paso 1: impresora de Money Orders ────────────────────────────────────
    if PREPARAR_IMPRESORA:
        assert await MO.preparar_impresora(logged_page), (
            "No se pudo registrar/seleccionar la impresora de Money Orders. "
            "Sin ella el MO no se puede imprimir.")
        await evi.shot("impresora_configurada", paso=1)
    else:
        logger.info("[CP22] CP22_IMPRESORA=0 — se asume la impresora ya lista.")

    # ── Pasos 2-3: módulo y comprador ────────────────────────────────────────
    assert await MO.abrir_money_order(logged_page), \
        "No se pudo abrir Services > Money Order."
    assert await MO.llenar_comprador(
        logged_page, cliente["telefono"], cliente["nombre"],
        cliente["apellido1"], cliente["apellido2"]), \
        "No se pudo llenar el formulario del comprador."
    await evi.shot("comprador", paso=2, locators=[
        logged_page.get_by_test_id(MO.MO_NOMBRE).first,
        logged_page.get_by_test_id(MO.MO_TELEFONO).first,
    ])

    # ── Paso 4: alta del Money Order ─────────────────────────────────────────
    assert await MO.agregar_money_order(logged_page, cliente["pay_to"], MONTO), \
        "No se pudo agregar el Money Order."
    await evi.shot("money_order_agregado", paso=3)

    # ── Paso 5: Información Adicional ────────────────────────────────────────
    assert await MO.abrir_additional_info(logged_page), (
        "No apareció el modal de compliance pidiendo Información Adicional. "
        f"Con ${MONTO} debería exigirla.")
    assert await MO.llenar_additional_info(
        logged_page, cliente["num_id"], cliente["tax_id"],
        cliente["direccion"], cliente["razon"], evi=evi), \
        "No se pudo completar la Información Adicional."
    await evi.shot("additional_info_aceptada", paso=4)

    # ── Paso 6: impresión ────────────────────────────────────────────────────
    serie = await MO.numero_de_serie(logged_page)
    assert serie, "No se pudo leer el número de serie del Money Order."
    await evi.shot("serie_capturada", paso=5)

    assert await MO.imprimir(logged_page, serie, evi=evi), \
        f"No se pudo imprimir el Money Order #{serie}."
    await evi.shot("impresion_terminada", paso=6)

    # ── Paso 7: anulación (el caso limpia lo que creó) ───────────────────────
    if not ANULAR:
        logger.info("[CP22] CP22_ANULAR=0 — los Money Orders quedan en Open.")
        return

    assert await MO.ir_a_reportes_money_order(logged_page), \
        "No se pudo abrir el reporte de Money Orders."
    await MO.buscar(logged_page)
    await evi.shot("reporte_money_orders", paso=7)

    anulados = await MO.anular_money_orders(
        logged_page, cliente["apellido1"], maximo=ESPERADOS, evi=evi)
    await evi.shot("money_orders_anulados", paso=7)
    assert anulados == ESPERADOS, (
        f"Se anularon {anulados} de {ESPERADOS} money orders. Los que queden en "
        f"Open ensucian el ambiente: revísalos a mano en Reportes filtrando por "
        f"'{cliente['apellido1']}'.")
    logger.info("[CP22] ✓ Money Order completo — %d anulado(s).", anulados)
