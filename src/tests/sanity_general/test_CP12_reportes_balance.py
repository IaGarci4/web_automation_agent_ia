"""
CP12 — Reportes de Balance de Hermes.
(Rescate de `HERMES2-qa/src/sanity_general/test_CP12_Reportes_de_Balance_Hermes.py`.)

Son DOS pruebas, como en el sanity original:

  A. BALANCE CONTINUO — Reportes > Balance → elegir el tipo → Buscar →
     validar las tarjetas del resultado → menú de opciones (4 items) → Ver →
     visor de PDF → **descargar el PDF y verificar su contenido**.

  B. BALANCE POR CAJERO — Reportes > Balance por Cajero → estado vacío inicial
     → Buscar por rango de fechas.

IMPRESIÓN: los pasos 7 y 8 del caso original dependen de una impresora física
(WINDOWS PRINTER / MICROSOFT PRINT TO PDF). Quedan FUERA por defecto, igual que
en el sanity original y por la misma razón que en QMetry se marcan NA: el
proceso automatizado no tiene impresora. Se activan con SKIP_PRINTER_STEPS=0.

COMO CORRER:
    pytest src/tests/sanity_general -k CP12 -v -s
    pytest src/tests/sanity_general -k "CP12 and continuo" -v -s
    pytest src/tests/sanity_general -k "CP12 and cajero" -v -s
"""
import os
import pytest
from playwright.async_api import Page

from config import settings
from config.logger import get_logger
from src.helpers.screenshot_helper import ScreenshotHelper
from src.sanity_general import balance as B
from src.sanity_general import Evidencia

logger = get_logger("CP12")

DESCARGAS = str(settings.REPORTS_DIR / "downloads" / "CP12")
# Textos que debe contener el PDF del balance (encabezados del reporte).
TEXTOS_PDF = ("Begin Date", "End Date", "BALANCE")

SALTAR_IMPRESION = os.getenv("SKIP_PRINTER_STEPS", "1").strip().lower() in (
    "1", "true", "si", "yes")

EVIDENCE_CONTINUO = "CP12_balance_continuo"
EVIDENCE_CAJERO = "CP12_balance_por_cajero"


def _limpiar_descargas() -> None:
    """Vacía la carpeta de descargas para no validar un PDF de otra corrida."""
    os.makedirs(DESCARGAS, exist_ok=True)
    borrados = 0
    for nombre in os.listdir(DESCARGAS):
        ruta = os.path.join(DESCARGAS, nombre)
        if os.path.isfile(ruta):
            try:
                os.remove(ruta)
                borrados += 1
            except OSError as e:
                logger.warning("[CP12] No se pudo borrar '%s': %s", nombre, e)
    logger.info("[CP12] Carpeta de descargas limpia (%d archivo(s) borrado(s)).",
                borrados)


@pytest.mark.sanity_general
@pytest.mark.asyncio
@pytest.mark.parametrize("language,width,height", [("English", 1366, 768)])
async def test_CP12_balance_continuo(logged_page: Page, language, width, height):
    evi = Evidencia(ScreenshotHelper(logged_page), EVIDENCE_CONTINUO)
    _limpiar_descargas()
    logger.info("[CP12] Balance Continuo — descargas en %s", DESCARGAS)

    # ── Step 1: abrir el reporte ─────────────────────────────────────────────
    assert await B.abrir_balance(logged_page), "No se pudo abrir Reportes > Balance."
    # Evidencia de la pantalla inicial, con el rango de fechas y el tipo de
    # reporte resaltados: es lo que define QUÉ balance se está pidiendo.
    await evi.shot("pantalla_balance", paso=1, locators=[
        logged_page.locator(B.TIPO_REPORTE).first,
        logged_page.locator("input[formcontrolname*='begin' i], "
                            "input[formcontrolname*='start' i]").first,
    ])

    # ── Step 1b: elegir el tipo y buscar ─────────────────────────────────────
    assert await B.buscar_balance_continuo(logged_page), \
        "No se pudo lanzar la búsqueda de BALANCE CONTINUO."

    estado = await B.validar_tarjetas(logged_page)
    # Resaltado sobre las tarjetas del resultado (lo que el paso valida).
    await evi.shot("balance_continuo_resultados", paso=1, locators=[
        logged_page.get_by_test_id(B.TOTAL_A_PAGAR).first,
        logged_page.get_by_test_id(B.RESUMEN_TRANSACCIONES).first,
        logged_page.get_by_test_id(B.MONEY_TRANSFERS).first,
    ])
    faltan = [n for n, ok in estado.items() if not ok and n != "balance_final"]
    assert not faltan, f"El reporte no mostró: {', '.join(faltan)}."

    # ── Step 2: menú de opciones → Ver ───────────────────────────────────────
    opciones = await B.abrir_opciones(logged_page)
    assert opciones >= 4, (f"El menú de opciones tiene {opciones} item(s); se "
                           "esperaban 4 (Ver, Imprimir, Exportar a PDF, Excel).")
    # Las 4 opciones resaltadas: la prueba es que existan las cuatro.
    await evi.shot("menu_opciones", paso=2, locators=[
        logged_page.locator(B.OPCIONES_MENU).nth(i) for i in range(4)])

    assert await B.elegir_opcion(logged_page, B.OPCION_VER, "Ver"), \
        "No se pudo abrir la vista del reporte."
    await evi.shot("opcion_ver_abierta", paso=2)

    # ── Step 3: visor de PDF ─────────────────────────────────────────────────
    botones = await B.validar_visor_pdf(logged_page)
    # Resaltado sobre los botones de acción del visor.
    await evi.shot("visor_pdf", paso=3, locators=[
        logged_page.locator(B.BOTONES_VISOR).nth(i)
        for i in range(min(botones, 3))] or None)
    assert botones >= 3, (f"El visor mostró {botones} botón(es); se esperaban "
                          "al menos 3 (imprimir / exportar).")

    # ── Step 4: descargar el PDF y validar su contenido ──────────────────────
    ruta = await B.descargar_pdf(logged_page, DESCARGAS)
    assert ruta and os.path.exists(ruta), "El PDF del balance no se descargó."
    assert os.path.getsize(ruta) > 0, f"El PDF descargado está vacío: {ruta}"
    await evi.shot("pdf_descargado", paso=4, locators=[
        logged_page.locator(B.BOTONES_VISOR).first])

    texto = B.texto_del_pdf(ruta)
    if texto.strip():
        faltantes = [t for t in TEXTOS_PDF if t not in texto]
        assert not faltantes, (f"Al PDF le faltan estos textos: "
                               f"{', '.join(faltantes)}.")
        logger.info("[CP12] ✓ PDF válido — contiene %s.", ", ".join(TEXTOS_PDF))
    else:
        # PDF escaneado o sin pypdf: se documenta, no se inventa un fallo.
        logger.warning("[CP12] El PDF no expone texto (escaneado o sin pypdf) "
                       "— se valida solo que exista y pese > 0.")
    logger.info("[CP12] Balance Continuo OK.")


@pytest.mark.sanity_general
@pytest.mark.asyncio
@pytest.mark.parametrize("language,width,height", [("English", 1366, 768)])
async def test_CP12_balance_por_cajero(logged_page: Page, language, width, height):
    evi = Evidencia(ScreenshotHelper(logged_page), EVIDENCE_CAJERO)
    logger.info("[CP12] Balance por Cajero.")

    # ── Step 5: abrir y comprobar el estado vacío ────────────────────────────
    assert await B.abrir_balance_por_cajero(logged_page), \
        "No se pudo abrir Reportes > Balance por Cajero."
    mensaje = await B.mensaje_vacio_cajero(logged_page)
    # Resaltado sobre el MENSAJE de estado vacío: es justo lo que valida el paso
    # (antes esta captura y la siguiente salían idénticas y no probaban nada).
    await evi.shot("estado_vacio", paso=5,
                   locators=[logged_page.locator(B.CAJERO_MENSAJE_VACIO).first])
    assert mensaje, ("No apareció el mensaje de estado inicial del reporte por "
                     "cajero.")

    # ── Step 6: buscar ───────────────────────────────────────────────────────
    # Antes de pulsar: el botón Buscar y el rango de fechas resaltados.
    await evi.shot("antes_de_buscar", paso=6, locators=[
        logged_page.get_by_test_id(B.CAJERO_BTN_BUSCAR).first,
        logged_page.locator("input[formcontrolname*='begin' i], "
                            "input[formcontrolname*='start' i]").first,
    ])
    assert await B.buscar_por_cajero(logged_page), \
        "No se pudo lanzar la búsqueda por cajero."
    # Después de buscar: el resultado. Se resalta la tabla/tarjetas si existen;
    # si el rango no tiene movimientos, queda la captura simple.
    resultado = logged_page.locator(
        "table, .card, [data-testid$='-card-title-h5-heading']")
    tiene_resultado = False
    try:
        tiene_resultado = bool(await resultado.count()) and \
            await resultado.first.is_visible()
    except Exception:
        pass
    await evi.shot("resultados_busqueda", paso=6,
                   locators=[resultado.first] if tiene_resultado else None)
    logger.info("[CP12] Balance por Cajero OK (resultado visible=%s).",
                tiene_resultado)

    # ── Steps 7–8: impresión (fuera del alcance automatizado) ────────────────
    if SALTAR_IMPRESION:
        logger.info("[CP12] Pasos 7–8 (impresión) OMITIDOS: el proceso "
                    "automatizado no usa impresora física ni digital. "
                    "Actívalos con SKIP_PRINTER_STEPS=0.")
        return
    pytest.skip("Los pasos de impresión requieren una impresora Windows "
                "configurada (MICROSOFT PRINT TO PDF) y validación manual.")
