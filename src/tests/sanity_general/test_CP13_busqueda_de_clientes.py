"""
CP13 — Búsqueda de clientes (Settings > Cliente).
(Migración/mejora de `HERMES2-qa/src/sanity_general/test_CP13_Busqueda_de_clientes.py`.)

Qué mejora respecto al sanity original:
  • Usa nuestra sesión estable: la fixture `logged_page` ya entra a la app,
    reutiliza la sesión persistente, cierra notificaciones y fija idioma. Aquí NO
    se hace login ni se maneja Kerberos (deshabilitado) — solo el flujo del caso.
  • La lógica frágil (navegación, aviso de salida, espera de la tabla, dropdown
    del beneficiario) vive endurecida en `src/sanity_general/clientes.py`.
  • Evidencia numerada por paso con `Evidencia` (StepPP-*.png), lista para QMetry.

Pasos:
  1. Settings > Cliente carga.
  2. Buscar el cliente por nombre + primer apellido → aparece la tabla.
  3. Seleccionar el primer resultado → cargan los campos de beneficiario.
  4. Elegir el beneficiario del dropdown y validar que los valores coincidan.

COMO CORRER:
    pytest src/tests/sanity_general -k CP13 -v -s
"""
import pytest
from playwright.async_api import Page

from config.logger import get_logger
from src.helpers.screenshot_helper import ScreenshotHelper
from src.sanity_general import Evidencia
from src.sanity_general import clientes as C

logger = get_logger("CP13")

# Datos precreados en TEST (mismos del sanity original).
CLIENTE_NOMBRE            = "LORENXO"
CLIENTE_APELLIDO1         = "TEST"

BENEFICIARIO_NOMBRE       = "MILDRED"
BENEFICIARIO_APELLIDO1    = "FERNANDEZ"
BENEFICIARIO_APELLIDO2    = "TEST"

EVIDENCE = "CP13_busqueda_de_clientes"


@pytest.mark.sanity_general
@pytest.mark.asyncio
@pytest.mark.parametrize("language,width,height", [("English", 1366, 768)])
async def test_CP13_busqueda_de_clientes(logged_page: Page, language, width, height):
    evi = Evidencia(ScreenshotHelper(logged_page), EVIDENCE)
    logger.info("[CP13] Búsqueda de clientes en Settings > Cliente.")

    # ── Step 1: Settings > Cliente ───────────────────────────────────────────
    assert await C.abrir_settings_cliente(logged_page), \
        "No se pudo abrir Settings > Cliente."
    await evi.shot("settings_cliente_cargado", paso=1, locators=[
        logged_page.get_by_test_id(C.CUST_NOMBRE).first])

    # ── Step 2: buscar cliente ───────────────────────────────────────────────
    assert await C.buscar_cliente(logged_page, CLIENTE_NOMBRE, CLIENTE_APELLIDO1), \
        (f"No apareció la tabla de resultados para "
         f"'{CLIENTE_NOMBRE} {CLIENTE_APELLIDO1}'.")
    await evi.shot("resultados_busqueda", paso=2, locators=[
        logged_page.locator(C.TABLA_RESULTADOS).first])

    # ── Step 3: seleccionar el primer cliente ────────────────────────────────
    assert await C.seleccionar_primer_cliente(logged_page), \
        "No se cargaron los campos de beneficiario tras seleccionar el cliente."
    await evi.shot("cliente_seleccionado", paso=3, locators=[
        logged_page.get_by_test_id(C.BENEF_NOMBRE).first])

    # ── Step 4: seleccionar beneficiario y validar ───────────────────────────
    assert await C.seleccionar_beneficiario_y_validar(
        logged_page,
        BENEFICIARIO_NOMBRE, BENEFICIARIO_APELLIDO1, BENEFICIARIO_APELLIDO2), \
        (f"No se pudo seleccionar/validar el beneficiario "
         f"'{BENEFICIARIO_NOMBRE} {BENEFICIARIO_APELLIDO1} "
         f"{BENEFICIARIO_APELLIDO2}'.")
    await evi.shot("beneficiario_validado", paso=4, locators=[
        logged_page.get_by_test_id(C.BENEF_NOMBRE).first,
        logged_page.get_by_test_id(C.BENEF_APELLIDO1).first,
        logged_page.get_by_test_id(C.BENEF_APELLIDO2).first])

    logger.info("[CP13] Búsqueda de clientes OK.")
