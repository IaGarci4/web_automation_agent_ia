"""
Módulo Bill Payment (Pago de Bill) — dominio propio, sin relación con Money
Transfer. Replica los métodos del repo base (BillPaymentPage + Summary) como
funciones que operan sobre `flow` (HmTransferelektraPage: .page, .logger,
smart_click, cancelar_transaccion, click_reports/transactions).

Locators verificados contra `HERMES2-qa/.../bill_payment_locators.py`.

Flujo típico (CP05/CP06):
  navigate_to_bill_payment → search_customer_by_phone → get_customer_name →
  select_national_tab → fill_national_payment → click_continue →
  summary_pagar → cancelar_bill_payment
"""

import random
import re

from config.logger import get_logger

logger = get_logger("sanity.bill_payment")

# ── Locators (data-testid / selectores del repo base) ───────────────────────
SERVICES_NAVBAR       = "services-navbar-item"
BILLPAY_DROPDOWN      = "services-0-navbar-dropdown-item"
MODAL_DENY_BTN        = "modal-confirmation-deny-button"

PHONE_INPUT           = "customer-billpay-form-phone-input"
NAME_CONTAINER        = "customer-billpay-form-name"
CUST_SEARCH_FIRST_ROW = "//tr[@data-testid='customer-search-table-0-tr']/td[1]"
CUST_SEARCH_ALL_ROWS  = "tr[data-testid*='customer-search-table-']"
CUST_SEARCH_CLOSE     = "customer-search-table-close-table"

NATIONAL_TAB          = "bill-payment-tab-tab-title-0"
CLEAR_PAYMENT_BTN     = "bill-payment-tab-clear-button-icon-svg"
SERVICE_DROPDOWN      = 'span[role="combobox"][aria-haspopup="listbox"]'

BILLER_COMPANY_INPUT  = 'input[type="text"][maxlength="150"]'
BILLER_ZIP_CONTAINER  = "customer-billpay-form-billerZipCode"
ACCOUNT_CONTAINER     = "customer-billpay-form-accountNumber"
ACCOUNT_CONFIRM_CONT  = "customer-billpay-form-accountNumberConfirm"

CONTINUE_BTN          = "totals-bill-payment-send-button"

# Summary modal
SUMMARY_PAY_BTN       = "bill-modal-summary-pay-button"
CONFIRM_ACCEPT_BTN    = "confirmation-modal-accept-button-button"

# Reportes > Transacciones (búsqueda bill payment)
START_DATE_INPUT      = "report-range-dates-start-date-input"
SEARCH_INPUT_FIELD    = '[data-testid="input-field-input"]'
SEARCH_BUTTON         = '[data-testid="test-id-button"]'

_RE_TXTYPE_MT   = re.compile(r"money transfer|env[ií]o de dinero", re.I)
_RE_OPT_BILLPAY = re.compile(r"bill payment|pago de bill", re.I)
_RE_OPT_CELL    = re.compile(r"cell phone|celular", re.I)
# Confirmación del 'Warning: Are you sure…?' → 'YES, Cancel' / 'SÍ, Cancelar'.
_RE_YES_CANCEL  = re.compile(r"yes,?\s*cancel|s[ií],?\s*cancelar", re.I)


def generate_random_amount(min_exclusive: float = 1.00, max_inclusive: float = 2.00) -> str:
    """Monto aleatorio > min y <= max, 2 decimales (ej. '1.47')."""
    amount = round(random.uniform(min_exclusive + 0.01, max_inclusive), 2)
    logger.info("Monto aleatorio bill payment: %.2f", amount)
    return f"{amount:.2f}"


# ── Navegación + cliente ────────────────────────────────────────────────────

async def navigate_to_bill_payment(flow) -> None:
    """Servicios > Pago de Bill. Cierra el modal de confirmación si aparece."""
    page = flow.page
    logger.info("Navegando a Servicios > Pago de Bill...")
    await page.get_by_test_id(SERVICES_NAVBAR).click()
    await page.wait_for_timeout(1000)
    await page.get_by_test_id(BILLPAY_DROPDOWN).click()
    await page.wait_for_timeout(2000)
    try:
        deny = page.get_by_test_id(MODAL_DENY_BTN).first
        if await deny.is_visible():
            await deny.click(force=True)
            await page.wait_for_timeout(2000)
    except Exception:
        pass


async def search_customer_by_phone(flow, phone: str) -> None:
    """Teclea el teléfono y selecciona el primer cliente del modal de búsqueda."""
    page = flow.page
    logger.info("Buscando cliente por teléfono: %s", phone)
    inp = page.get_by_test_id(PHONE_INPUT).first
    await inp.click(force=True)
    await inp.fill(phone)
    await page.wait_for_timeout(10000)

    fila = page.locator(CUST_SEARCH_FIRST_ROW).first
    await fila.wait_for(state="visible", timeout=10000)
    await fila.click(force=True)
    # Esperar a que el nombre se poblé
    name_inp = page.get_by_test_id(NAME_CONTAINER).locator("input").first
    try:
        await name_inp.wait_for(state="visible", timeout=10000)
        for _ in range(20):
            if (await name_inp.input_value()).strip():
                break
            await page.wait_for_timeout(500)
    except Exception:
        pass
    await page.wait_for_timeout(500)
    logger.info("Cliente seleccionado del modal.")


async def get_customer_name(flow) -> str:
    """Nombre del cliente cargado (campo Name)."""
    try:
        return (await flow.page.get_by_test_id(NAME_CONTAINER).locator("input").first.input_value()).strip()
    except Exception:
        return ""


async def close_customer_search_table(flow) -> None:
    """Cierra la tabla flotante de búsqueda de cliente si quedó visible (tapa los
    campos del formulario). Best-effort."""
    try:
        x = flow.page.get_by_test_id(CUST_SEARCH_CLOSE).first
        if await x.is_visible():
            await x.click()
            await flow.page.wait_for_timeout(500)
            logger.info("Tabla flotante de búsqueda cerrada.")
    except Exception:
        pass


# ── Formulario nacional ─────────────────────────────────────────────────────

async def select_national_tab(flow) -> None:
    """Tab 'Nacional' del formulario de bill payment."""
    logger.info("Seleccionando tab Nacional...")
    await flow.page.get_by_test_id(NATIONAL_TAB).click(force=True)
    await flow.page.wait_for_timeout(1000)


async def _fill_biller_company(flow, company: str) -> None:
    page = flow.page
    inp = page.locator(BILLER_COMPANY_INPUT).first
    await inp.wait_for(state="visible", timeout=10000)
    await inp.click(force=True)
    await inp.type(company, delay=100)
    await page.wait_for_timeout(2000)
    await inp.press("ArrowDown")
    await page.wait_for_timeout(300)
    await inp.press("Enter")
    await page.wait_for_timeout(1000)
    logger.info("Biller company: %s", company)


async def _fill_account(flow, account: str) -> None:
    page = flow.page
    a = page.get_by_test_id(ACCOUNT_CONTAINER).locator("input").first
    await a.click(force=True)
    await a.fill(account)
    await page.wait_for_timeout(500)
    ac = page.get_by_test_id(ACCOUNT_CONFIRM_CONT).locator("input").first
    await ac.click(force=True)
    await ac.fill(account)
    await page.wait_for_timeout(500)
    logger.info("Número de cuenta: %s", account)


async def _fill_biller_zip(flow, zip_code: str) -> None:
    page = flow.page
    z = page.get_by_test_id(BILLER_ZIP_CONTAINER).locator("input").first
    await z.click(force=True)
    await z.fill(zip_code)
    await page.wait_for_timeout(500)
    logger.info("Biller ZIP: %s", zip_code)


async def _fill_amount(flow, amount: str) -> None:
    page = flow.page
    amt = page.get_by_role("textbox", name="Amount").or_(
        page.get_by_role("textbox", name="Monto")).first
    try:
        await amt.wait_for(state="visible", timeout=15000)
    except Exception:
        pass
    await amt.click(force=True)
    await amt.type(amount, delay=100)
    await amt.press("Tab")
    await page.wait_for_timeout(500)
    logger.info("Monto: %s", amount)


async def fill_national_payment(flow, biller_company: str, account_number: str,
                                amount: str, biller_zip_code: str = None) -> None:
    """Llena el formulario nacional (Fidelity Express / Fiserv usan los mismos
    campos: biller, cuenta, [zip], monto). Limpia el form antes."""
    page = flow.page
    logger.info("Llenando formulario nacional de bill payment...")
    try:
        await page.get_by_test_id(CLEAR_PAYMENT_BTN).click(force=True)
        await page.wait_for_timeout(1500)
    except Exception:
        pass
    await _fill_biller_company(flow, biller_company)
    await _fill_account(flow, account_number)
    if biller_zip_code:
        await _fill_biller_zip(flow, biller_zip_code)
    await _fill_amount(flow, amount)
    await page.wait_for_timeout(5000)


async def is_continue_enabled(flow) -> bool:
    try:
        return await flow.page.get_by_test_id(CONTINUE_BTN).first.is_enabled()
    except Exception:
        return False


async def click_continue(flow) -> None:
    page = flow.page
    logger.info("Bill payment: click Continuar...")
    btn = page.get_by_test_id(CONTINUE_BTN).first
    try:
        await btn.wait_for(state="visible", timeout=10000)
    except Exception:
        pass
    await btn.click(force=True)
    await page.wait_for_timeout(2000)


# ── Summary modal (pagar) ───────────────────────────────────────────────────

RE_CANCEL = re.compile(r"^\s*(cancel|cancelar)\s*$", re.I)


async def _error_impresora_visible(flow) -> bool:
    """True si el modal 'The printer is not connected' / error está en pantalla."""
    try:
        if await flow.page.get_by_test_id(MODAL_DENY_BTN).first.is_visible():
            return True
    except Exception:
        pass
    return False


async def _cancelar_error_impresora(flow, timeout: int = 12_000) -> bool:
    """Da clic en 'Cancel'/'Cancelar' del modal de error de impresora (por testid
    o por texto EN/ES). Espera a que aparezca (hasta timeout) y a que cierre."""
    page = flow.page
    candidatos = [
        page.get_by_test_id(MODAL_DENY_BTN),
        page.get_by_role("button", name=RE_CANCEL),
    ]
    for cand in candidatos:
        try:
            btn = cand.first
            await btn.wait_for(state="visible", timeout=timeout)
            await btn.click(force=True)
            try:
                await btn.wait_for(state="hidden", timeout=8_000)
            except Exception:
                pass
            logger.info("Error de impresora cancelado.")
            return True
        except Exception:
            continue
    return False


async def summary_pagar(flow) -> None:
    """Paga desde el resumen manejando el error de impresora ('printer not
    connected') que aparece tras Continue y/o tras Pay: se le da CANCEL (EN/ES)
    para que la transacción continúe."""
    page = flow.page
    logger.info("Bill payment: resumen y pago (manejando error de impresora)...")
    pay = page.get_by_test_id(SUMMARY_PAY_BTN).first

    # Fase 1: esperar el botón Pay del resumen, cancelando el error de impresora
    # cada vez que aparezca (puede salir ANTES del resumen, tras Continue).
    t = 0
    while t < 30_000:
        if await _error_impresora_visible(flow):
            await _cancelar_error_impresora(flow, timeout=6_000)
            await page.wait_for_timeout(500)
            continue
        try:
            if await pay.is_visible():
                break
        except Exception:
            pass
        await page.wait_for_timeout(1_000)
        t += 1_000

    # Click Pay
    try:
        await pay.wait_for(state="visible", timeout=10_000)
        await pay.click(force=True)
        logger.info("Bill payment: 'Pay' pulsado.")
    except Exception as e:
        logger.warning("No apareció/pulsó el botón Pay del resumen: %s", str(e)[:80])

    # Fase 2 (post-Pay): el SEGUNDO error de impresora aparece TARDE (al finalizar
    # el pago, ~10-20s). Se sondea hasta 45s: si sale el error → Cancel; si sale
    # la confirmación de pago → Aceptar. Se termina cuando el resumen cierra y ya
    # no hay más modales (con una última ventana por el error tardío).
    import time as _t
    fin = _t.monotonic() + 45
    confirmado = False
    while _t.monotonic() < fin:
        # 1) Error de impresora (tardío) → Cancel
        if await _error_impresora_visible(flow):
            await _cancelar_error_impresora(flow, timeout=6_000)
            await page.wait_for_timeout(600)
            continue
        # 2) Confirmación de pago de Bill → Aceptar
        try:
            acc = page.get_by_test_id(CONFIRM_ACCEPT_BTN).first
            if await acc.is_visible():
                await acc.click(force=True)
                confirmado = True
                logger.info("Confirmación de pago aceptada.")
                await page.wait_for_timeout(800)
                continue
        except Exception:
            pass
        # 3) ¿El resumen ya cerró? → dar una última ventana por el error tardío
        resumen_cerrado = True
        try:
            resumen_cerrado = not await pay.is_visible()
        except Exception:
            pass
        if resumen_cerrado:
            if await _cancelar_error_impresora(flow, timeout=6_000):
                continue  # apareció tarde y lo cancelamos → seguir vigilando
            break         # resumen cerrado y sin error → pago finalizado
        await page.wait_for_timeout(1_000)

    logger.info("Bill payment: pago enviado%s.", " (confirmado)" if confirmado else "")


# ── Cancelación (Reportes > Transacciones, tipo BILL PAYMENT, por teléfono) ──

async def _buscar_bill_payment_por_telefono(flow, phone: str) -> None:
    """En Reportes > Transacciones: tipo BILL PAYMENT + Search by CELL PHONE +
    fecha inicial ayer + teléfono → Buscar. Compatible EN/ES."""
    page = flow.page
    logger.info("Filtrando reportes por BILL PAYMENT + teléfono: %s", phone)
    # Tipo de transacción: MONEY TRANSFER → BILL PAYMENT
    try:
        tx = page.get_by_role("combobox", name=_RE_TXTYPE_MT).first
        await tx.click()
        await page.wait_for_timeout(500)
        await page.get_by_role("option", name=_RE_OPT_BILLPAY).first.click()
        await page.wait_for_timeout(600)
    except Exception as e:
        logger.warning("No se pudo cambiar tipo a BILL PAYMENT: %s", str(e)[:80])
    # Fecha inicial = ayer
    try:
        from datetime import datetime, timedelta
        ayer = (datetime.now() - timedelta(days=1)).strftime("%m/%d/%Y")
        d = page.get_by_test_id(START_DATE_INPUT).first
        await d.wait_for(state="visible", timeout=10000)
        await d.click()
        await d.fill(ayer)
        await page.wait_for_timeout(500)
    except Exception:
        pass
    # Search by → CELL PHONE (segundo p-dropdown)
    try:
        await page.locator("//p-dropdown/div/span").nth(1).click()
        await page.wait_for_timeout(400)
        await page.get_by_role("option", name=_RE_OPT_CELL).first.click()
        await page.wait_for_timeout(500)
    except Exception as e:
        logger.warning("No se pudo elegir 'CELL PHONE': %s", str(e)[:80])
    # Teléfono + Buscar
    await page.locator(SEARCH_INPUT_FIELD).first.fill(phone)
    await page.locator(SEARCH_BUTTON).first.click(force=True)
    await page.wait_for_timeout(4000)


_RE_CANCEL_MENU = re.compile(r"^\s*(cancel|cancelar)\s*$", re.I)


async def _cancelar_desde_menu_billpay(flow, row_index: int = 0) -> bool:
    """Cancelación de BILL PAYMENT desde la tabla de reportes: abre el kebab y da
    'Cancel'. A diferencia del Money Transfer, NO lleva el modal de 'notas', así
    que se considera hecha al pulsar Cancel (+ confirmación simple si aparece)."""
    page = flow.page
    # Esperar a que rendericen las filas/kebab del resultado
    try:
        await page.locator(
            "tr.report-transactions-result-row, button.report-transaction-menu-toggle, "
            "[data-testid*='menu-toggle'], .td-options .icon"
        ).first.wait_for(state="visible", timeout=12_000)
        await page.wait_for_timeout(500)
    except Exception:
        logger.warning("[BillPay] No aparecieron filas de resultado tras Buscar.")

    # Abrir el menú kebab de la fila
    kebab = [
        "button.report-transaction-menu-toggle",
        "[data-testid*='menu-toggle']",
        "[data-testid*='menu-icon']",
        ".td-options .icon", ".td-options button",
        "tr.report-transactions-result-row .icon",
    ]
    abierto = False
    for sel in kebab:
        try:
            loc = page.locator(sel)
            await loc.first.wait_for(state="visible", timeout=2_500)
            cnt = await loc.count()
            target = loc.nth(row_index) if cnt > row_index else loc.first
            await target.scroll_into_view_if_needed(timeout=2_000)
            await target.click(force=True, timeout=3_000)
            abierto = True
            logger.info("[BillPay] Menú kebab abierto (%s).", sel)
            break
        except Exception:
            continue
    if not abierto:
        logger.warning("[BillPay] No abrí el menú kebab.")
        return False
    await page.wait_for_timeout(400)

    # Click 'Cancel' del menú (testid conocido; luego por texto EN/ES)
    clicked = False
    for tid in ("reports-transaction-menu-cancel-paragraph-semi-bold",
                "reports-transaction-menu--cancel-paragraph-semi-bold"):
        try:
            item = page.get_by_test_id(tid)
            if await item.count() == 0:
                continue
            await item.first.click(force=True, timeout=4_000)
            clicked = True
            break
        except Exception:
            continue
    if not clicked:
        try:
            await page.locator(".dropdown-menu, [role='menu'], .p-menu, .report-transaction-menu") \
                .get_by_text(_RE_CANCEL_MENU).first.click(force=True, timeout=4_000)
            clicked = True
        except Exception:
            pass
    if not clicked:
        logger.warning("[BillPay] No encontré la opción 'Cancel' del menú.")
        return False

    await page.wait_for_timeout(1_000)

    # Confirmación 'Warning: Are you sure you want to cancel this Bill Payment?'
    # → botón 'YES, Cancel' / 'SÍ, Cancelar'. Aparece un instante DESPUÉS, por eso
    # se ESPERA (no is_visible instantáneo). EN/ES por testid o por texto.
    confirmado = False
    candidatos = [
        page.get_by_test_id("modal-confirmation-confirm-button"),
        page.get_by_role("button", name=_RE_YES_CANCEL),
        page.get_by_test_id("confirmation-modal-accept-button-button"),
    ]
    for cand in candidatos:
        try:
            b = cand.first
            await b.wait_for(state="visible", timeout=8_000)
            await b.click(force=True)
            confirmado = True
            logger.info("[BillPay] Confirmación 'YES, Cancel' pulsada.")
            break
        except Exception:
            continue
    if not confirmado:
        logger.warning("[BillPay] No apareció/pulsó la confirmación 'YES, Cancel'.")

    await page.wait_for_timeout(1_000)
    logger.info("[BillPay] 'Cancel' ejecutado (bill payment no lleva modal de notas).")
    return confirmado


async def cancelar_bill_payment(flow, phone: str, *, logger=logger, evi=None,
                                notes: str = "TEST", reason_index: int = 0) -> bool:
    """Cancela el bill payment desde Reportes: navega, filtra por BILL PAYMENT +
    teléfono, y cancela vía el kebab (SIN el modal de notas del Money Transfer).
    `evi` (Evidencia) numera automáticamente la fila y el resultado."""
    logger.info("[BillPay] Cancelando pago por teléfono: %s", phone)
    _sel = "tbody tr, tr.report-transactions-result-row"
    await flow.click_reports()
    await flow.wait_for_no_blocking_overlays()
    await flow.click_transactions()
    await flow.wait_for_no_blocking_overlays()
    try:
        await flow.click_yes_leave()
    except Exception:
        pass
    await flow.wait_for_no_blocking_overlays()

    await _buscar_bill_payment_por_telefono(flow, phone)

    # El teléfono NO es columna de la tabla; la fila a cancelar es la más reciente
    # (arriba). Captura simple del listado antes de cancelar.
    if evi is not None:
        await evi.shot("cancelacion_encontrada")

    ok = await _cancelar_desde_menu_billpay(flow, row_index=0)
    await flow.wait_for_no_blocking_overlays()

    if ok:
        # Pausa GENEROSA para que la tabla refresque el estatus a
        # 'Cancelled'/'Cancelado' y se alcance a visualizar/capturar. Doble del
        # anterior. Configurable con CANCEL_PAUSE_MS.
        import os as _os
        pausa = int(_os.getenv("CANCEL_PAUSE_MS", "10000"))
        logger.info("[BillPay] Esperando %d ms para que el estatus cambie a Cancelled...", pausa)
        await flow.page.wait_for_timeout(pausa)

    # Evidencia final: RESALTAR el registro cancelado (estilo CP01). El estatus
    # 'Cancelled'/'Cancelado' contiene 'cancel' → search_text language-agnostic.
    if evi is not None:
        if ok:
            await evi.shot("cancelacion_exitosa", search_text="Cancel", selector=_sel)
        else:
            await evi.shot("cancelacion_fallo")

    if ok:
        logger.info("[BillPay] Pago cancelado.")
    return ok
