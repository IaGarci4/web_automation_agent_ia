"""
Pagos en Línea (Online Payments) — CP09, lado Hermes.

Flujo: navbar 'Online Payments' → (opcional) revisar 'Add New Account' y sus
Términos y Condiciones → volver → elegir la cuenta por ALIAS → monto → Pay Now
→ confirmar (Yes) → aceptar.

Detalles del original que aquí se respetan:
  • Pay Now / Yes / Accept se disparan por JS (`document.querySelector(...).click()`):
    los overlays del modal interceptan el click normal de Playwright.
  • 'Yes' y 'Accept' comparten el MISMO data-testid
    (modal-confirmation-confirm-button); son modales distintos en momentos
    distintos, así que se desambigua por TEXTO (bilingüe).
"""

import re

from config.logger import get_logger

logger = get_logger("sanity.pagos_linea")

TIMEOUT = 180_000

# ── Navegación ──────────────────────────────────────────────────────────────
NAVBAR_LINK_SEL = "dropdown-navbar-item a.nav-link"
RE_ONLINE_PAY = re.compile(r"online\s*payments|pagos\s*en\s*l[ií]nea", re.I)
DENY_BTN = 'button[data-testid="modal-confirmation-deny-button"]'
RE_YES_LEAVE = re.compile(r"yes.*leave|s[ií].*salir", re.I)

# ── Cuenta / monto / pago ───────────────────────────────────────────────────
AMOUNT_SEL = ('inputamountfield[formcontrolname="amountToPayControl"] '
              'input[data-testid="input-field-input"]')
PAY_NOW_SEL = "button#pay-now"
CONFIRM_SEL = 'button[data-testid="modal-confirmation-confirm-button"]'
RE_PAY = re.compile(r"pay|pagar", re.I)
RE_ACCEPT = re.compile(r"accept|aceptar", re.I)
RE_ADD_ACCOUNT = re.compile(r"add\s*new\s*account|agregar\s*cuenta", re.I)
RE_TERMS = re.compile(r"terms\s*and\s*conditions|t[eé]rminos", re.I)
RE_GO_BACK = re.compile(r"go\s*back|regresar|volver", re.I)


def _fila_alias(alias: str) -> str:
    """Fila de la tabla de cuentas cuyo alias coincide."""
    return (f'//tbody[contains(@class,"p-datatable-tbody")]//tr'
            f'[td[contains(@class,"td-alias") and normalize-space()="{alias}"]]')


async def _click_tolerante(locator, timeout: int = 10_000) -> bool:
    try:
        await locator.click(timeout=timeout)
        return True
    except Exception:
        try:
            await locator.click(force=True, timeout=timeout)
            return True
        except Exception:
            return False


async def _click_js(page, selector: str, desc: str) -> bool:
    """Click por JS (los modales de Hermes interceptan el click normal)."""
    try:
        await page.evaluate(
            """(sel) => { const b = document.querySelector(sel);
                          if (!b) throw new Error('no encontrado'); b.click(); }""",
            selector)
        logger.info("[Pagos] %s", desc)
        return True
    except Exception as e:
        logger.warning("[Pagos] No se pudo pulsar %s: %s", desc, str(e)[:80])
        return False


async def abrir_pagos_en_linea(flow) -> bool:
    """Navbar 'Online Payments' / 'Pagos en Línea' (+ modal de salida si aparece)."""
    page = flow.page
    logger.info("[Pagos] Abriendo Pagos en Línea…")
    try:
        link = page.locator(NAVBAR_LINK_SEL).filter(has_text=RE_ONLINE_PAY).first
        await link.wait_for(state="visible", timeout=TIMEOUT)
        await _click_tolerante(link)
    except Exception as e:
        logger.warning("[Pagos] No se encontró el menú de pagos: %s", str(e)[:90])
        return False
    # Modal 'YES, Leave' al salir de otra pantalla (opcional)
    try:
        deny = page.locator(DENY_BTN).filter(has_text=RE_YES_LEAVE).first
        if await deny.is_visible(timeout=5_000):
            await _click_tolerante(deny)
            logger.info("[Pagos] Modal de salida cerrado (YES, Leave).")
    except Exception:
        pass
    await page.wait_for_timeout(1_500)
    return True


async def revisar_terminos_nueva_cuenta(flow, evi=None) -> bool:
    """Entra a 'Add New Account', comprueba los Términos y Condiciones y vuelve.

    Es el paso de revisión del caso original; si la pantalla no aparece, se
    omite sin romper el flujo."""
    page = flow.page
    try:
        add = page.get_by_role("button", name=RE_ADD_ACCOUNT).first
        if await add.count() == 0:
            logger.info("[Pagos] 'Add New Account' no disponible — se omite.")
            return False
        await _click_tolerante(add)
        terms = page.get_by_text(RE_TERMS).first
        await terms.wait_for(state="visible", timeout=15_000)
        logger.info("[Pagos] Términos y Condiciones visibles ✓")
        if evi:
            await evi.shot("terminos_y_condiciones")
        volver = page.get_by_role("button", name=RE_GO_BACK).first
        await _click_tolerante(volver)
        await page.wait_for_timeout(1_200)
        return True
    except Exception as e:
        logger.info("[Pagos] Revisión de términos omitida (%s).", str(e)[:70])
        try:                     # intentar regresar de todos modos
            volver = page.get_by_role("button", name=RE_GO_BACK).first
            if await volver.count():
                await _click_tolerante(volver)
        except Exception:
            pass
        return False


async def elegir_cuenta(flow, alias: str) -> bool:
    """Selecciona la cuenta por su ALIAS en la tabla."""
    page = flow.page
    try:
        fila = page.locator(_fila_alias(alias)).first
        await fila.wait_for(state="visible", timeout=TIMEOUT)
        try:
            await fila.scroll_into_view_if_needed(timeout=5_000)
        except Exception:
            pass
        ok = await _click_tolerante(fila)
        logger.info("[Pagos] Cuenta '%s' seleccionada (%s).", alias, "ok" if ok else "falló")
        return ok
    except Exception as e:
        logger.warning("[Pagos] No se encontró la cuenta '%s': %s", alias, str(e)[:90])
        return False


async def pagar(flow, monto: str = "1", evi=None) -> bool:
    """Escribe el monto y completa el pago (Pay Now → Yes → Accept)."""
    page = flow.page
    # Monto
    try:
        amount = page.locator(AMOUNT_SEL).first
        await amount.wait_for(state="visible", timeout=TIMEOUT)
        await amount.click()
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Backspace")
        await amount.type(str(monto), delay=90)
        logger.info("[Pagos] Monto a pagar: %s", monto)
    except Exception as e:
        logger.warning("[Pagos] No se pudo escribir el monto: %s", str(e)[:90])
        return False
    if evi:
        await evi.shot("monto_a_pagar")

    # Pay Now (por JS: el botón queda bajo el overlay del panel)
    try:
        btn = page.locator(PAY_NOW_SEL).first
        await btn.wait_for(state="visible", timeout=TIMEOUT)
    except Exception:
        logger.warning("[Pagos] El botón 'Pay Now' no apareció.")
        return False
    if not await _click_js(page, PAY_NOW_SEL, "'Pay Now' pulsado"):
        return False
    await page.wait_for_timeout(1_500)

    # Confirmación 'Yes, Pay' y luego 'Accept' — MISMO testid, distinto momento:
    # se espera cada uno por su TEXTO antes de disparar el click por JS.
    for regex, desc in ((RE_PAY, "'Yes, Pay' confirmado"),
                        (RE_ACCEPT, "'Accept' confirmado")):
        try:
            modal_btn = page.locator(CONFIRM_SEL).filter(has_text=regex).first
            await modal_btn.wait_for(state="visible", timeout=60_000)
            if evi:
                await evi.shot("confirmacion_pago" if regex is RE_PAY else "pago_aceptado")
            await _click_js(page, CONFIRM_SEL, desc)
            await page.wait_for_timeout(2_000)
        except Exception as e:
            logger.warning("[Pagos] No apareció el paso %s: %s", desc, str(e)[:80])
    logger.info("[Pagos] Pago en línea completado.")
    return True
