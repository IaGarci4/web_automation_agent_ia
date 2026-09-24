"""
Chronos — Collection > Digital Deposit Receipt (CP10, cierre del caso).

Tras enviar la Ficha de Depósitos desde Hermes, el recibo aparece aquí y el
caso lo ELIMINA para no dejar basura en el ambiente.

Flujo: Menu → Collection → Digital Deposit Receipt → seleccionar el registro de
la agencia → Delete → Yes → esperar la confirmación → Close.

El registro se elige por el CÓDIGO DE AGENCIA (0040-OK en test, 0020-TX en
producción), no por posición: en producción hay recibos de muchas agencias y
tomar "el primero" borraría el de alguien más.
"""

import re

from config import settings
from config.logger import get_logger
from src.sanity_general import chronos as CR
from src.sanity_general.chronos_cobranza import (
    COLLECTION_OPTION, limpiar_modales, _visible, _click_js)

logger = get_logger("sanity.chronos.recibo")

TIMEOUT = 120_000

SUBMENU = "//div[normalize-space()='Digital Deposit Receipt']"
RE_DELETE = re.compile(r"^\s*delete\s*$|^\s*eliminar\s*$", re.I)
RE_YES = re.compile(r"^\s*(yes|s[ií])\s*$", re.I)
RE_CLOSE = re.compile(r"close|cerrar", re.I)
RE_BORRADO = re.compile(r"deleted|successfully|process|eliminad", re.I)
TEXTO_MODAL = "p, p.modal-text, div.modal-body"


async def ir_a_recibo_digital(page) -> bool:
    """Menu → Collection → Digital Deposit Receipt."""
    try:
        await limpiar_modales(page)
        await CR._click_listo(page, page.locator(CR.TOOLBAR_MENU).first,
                              "Menu abierto", timeout=TIMEOUT)
        await page.wait_for_timeout(800)
        await CR._click_listo(page, page.locator(COLLECTION_OPTION).first,
                              "Collection", timeout=TIMEOUT)
        await page.wait_for_timeout(800)
        await CR._click_listo(page, page.locator(SUBMENU).first,
                              "Digital Deposit Receipt", timeout=TIMEOUT)
        await page.wait_for_timeout(2_500)
        return True
    except Exception as e:
        logger.warning("[Recibo] No se pudo abrir Digital Deposit Receipt: %s",
                       str(e)[:110])
        return False


async def seleccionar_registro(page, agency_code: str = None) -> bool:
    """Selecciona el recibo de la agencia y baja al pie de la pantalla."""
    codigo = agency_code or settings.AGENCY_CODE
    try:
        fila = page.get_by_text(codigo, exact=True).first
        await fila.wait_for(state="visible", timeout=TIMEOUT)
        await CR._click_listo(page, fila, f"Recibo de {codigo} seleccionado",
                              timeout=TIMEOUT)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1_200)
        return True
    except Exception as e:
        logger.warning("[Recibo] No apareció un recibo de %s: %s",
                       codigo, str(e)[:100])
        return False


async def eliminar(page) -> bool:
    """Delete → Yes → confirmación → Close.

    Igual que en Agent Monitor, los botones se buscan entre TODAS las
    coincidencias visibles: Chronos deja los modales previos en el DOM y
    quedarse con `.first` apunta a uno oculto."""
    borrar = await _visible(page, "button", RE_DELETE)
    if borrar is None:
        logger.warning("[Recibo] No se encontró el botón 'Delete'.")
        return False
    await _click_js(borrar)
    await page.wait_for_timeout(1_000)

    si = await _visible(page, "button", RE_YES)
    if si is None:
        logger.warning("[Recibo] No apareció la confirmación 'Yes'.")
        return False
    await _click_js(si)
    logger.info("[Recibo] Eliminación confirmada (Yes).")

    # Confirmación del borrado (el backend tarda; hasta 80 s como el original).
    espera = 0
    confirmado = False
    while espera <= 80_000:
        if await _visible(page, TEXTO_MODAL, RE_BORRADO) is not None:
            confirmado = True
            break
        await page.wait_for_timeout(500)
        espera += 500
    if confirmado:
        logger.info("[Recibo] ✓ Recibo eliminado (%.0f s).", espera / 1000)
    else:
        logger.warning("[Recibo] No llegó la confirmación de borrado en 80 s.")

    cerrar = await _visible(page, "button", RE_CLOSE)
    if cerrar is not None:
        await _click_js(cerrar)
    await page.wait_for_timeout(800)
    await limpiar_modales(page)
    return confirmado
