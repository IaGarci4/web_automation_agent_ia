"""
Flujo de Money Transfer REUTILIZABLE (data-driven) — motor compartido por
TODOS los países del módulo de pagadores.

Un solo flujo ESTABLE (HmTransferelektraPage, la pantalla real de Transfers de
Hermes2) se parametriza con lo que cambia entre pagadores: país destino,
ciudad del pagador, búsqueda, fila del modal y sucursal. Cada país vive en su
propia carpeta bajo `src/pagadores/<pais>/payers.json` — agregar un pagador NO
requiere grabar nada: se llena su entrada en ese JSON y se pone
"activo": true. Agregar un país nuevo: crear `src/pagadores/<pais>/payers.json`
con el mismo esquema (ver src/pagadores/mexico/payers.json como referencia) y
`cargar_catalogo()` lo descubre automáticamente.

Lo usan los tests generados en src/tests/test_envio_normal_<pais>.py.
"""

import json
import re
from pathlib import Path

_PAGADORES_DIR = Path(__file__).parent

_ELEKTRA_FALLBACK = {
    "code": "ELEKTRA", "country": "MEXICo", "search": "ELEKTRa", "row": "ELEKTRA DIRECTO",
    "needs_branch": True, "branch": "DAZ JAL SAN JOAQUIN GUAD", "payer_city": "GUADALAJARa",
    "id_payment_type": 1, "id_country_currency": 10,
    "is_enabled_scale_rounding": False, "id_scale_rounding": None, "_modulo": "mexico",
}


def _modulos_disponibles() -> list[str]:
    """Nombres de subcarpetas de país que tienen un payers.json (mexico, brasil, ...)."""
    return sorted(
        p.parent.name for p in _PAGADORES_DIR.glob("*/payers.json")
    )


def cargar_catalogo(modulo: str = None):
    """
    Devuelve (payers_activos, ciudades_estado_por_pais).

    Sin `modulo`: agrega los payers ACTIVOS de TODOS los países disponibles
    (cada payer queda anotado con "_modulo": "<pais>" para saber a qué
    test_envio_normal_<pais>.py enrutarlo). Con `modulo` (ej. "mexico"):
    solo ese país.
    """
    ciudades: dict = {}
    payers: list = []
    modulos = [modulo] if modulo else _modulos_disponibles()
    for mod in modulos:
        cfg_path = _PAGADORES_DIR / mod / "payers.json"
        if not cfg_path.exists():
            continue
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for p in data.get("payers", []):
            if p.get("activo"):
                p = dict(p)
                p["_modulo"] = mod
                payers.append(p)
        for pais, pool in (data.get("ciudades_estado_por_pais") or {}).items():
            ciudades.setdefault(pais, pool)
    if not payers:
        payers = [dict(_ELEKTRA_FALLBACK)]
        ciudades.setdefault("MEXICo", [["GUADALAJARA", "JALISCO"]])
    return payers, ciudades


def elegir_payer(payers, rng, forzado: str = "") -> dict:
    if forzado:
        for p in payers:
            if p["code"].upper() == forzado.upper():
                return p
    return rng.choice(payers)


def destino(cfg: dict, ciudades: dict, rng):
    """País del pagador + ciudad/estado aleatorios de ESE país."""
    pais = cfg.get("country", "MEXICo")
    pool = ciudades.get(pais) or ciudades.get("MEXICo") or [["GUADALAJARA", "JALISCO"]]
    ciudad, estado = rng.choice(pool)
    return pais, ciudad, estado


async def llenar_hasta_monto(flow, datos, cfg, pais, ciudad, estado) -> float:
    """Cliente + beneficiario (país del pagador; ciudad/estado aleatorios) + tarifa + monto."""
    await flow.navigate()
    await flow.fill_transfer_customer_cellphone_0_cellphone_input(datos.valor("phone", "phone"))
    await flow.fill_transfer_customer_name_0_input(datos.valor("customer_name", "first_name"))
    await flow.fill_transfer_customer_first_lastname_0_input(datos.valor("customer_last1", "last_name"))
    await flow.fill_transfer_customer_second_lastname_0_input(datos.valor("customer_last2", "last_name"))
    await flow.click_close_table()
    await flow.fill_transfer_customer_address_0_input(datos.valor("address", "address"))
    await flow.fill_transfer_customer_zip_code_0_input(datos.valor("us_zip", "us_zip"))
    await flow.esperar_autocomplete_cp()
    await flow.click_transfer_beneficiary_toggle_fi()
    await flow.click_transfer_beneficiary_clear_0_i()
    await flow.fill_transfer_beneficiary_country_0_dropdown_input(pais)
    await flow.click_beneficiary()
    await flow.fill_transfer_beneficiary_name_0_dropdown_input(datos.valor("beneficiary_name", "first_name"))
    await flow.fill_transfer_beneficiary_first_lastname_0_input(datos.valor("beneficiary_last1", "last_name"))
    await flow.fill_transfer_beneficiary_second_lastname_0_input(datos.valor("beneficiary_last2", "last_name"))
    await flow.fill_transfer_beneficiary_cellphone_0_cellphone_input(datos.valor("phone", "phone"))
    await flow.fill_transfer_beneficiary_address_0_input(datos.valor("address", "address"))
    await flow.fill_transfer_beneficiary_zip_code_0_input(datos.valor("zip", "zip"))
    await flow.fill_transfer_beneficiary_city_0_input(ciudad)     # ALEATORIO (del país)
    await flow.fill_transfer_beneficiary_state_0_input(estado)    # ALEATORIO (del país)
    await flow.fill_transfer_beneficiary_date_of_birth_0_input(datos.valor("date", "date"))
    await flow.fill_transfer_beneficiary_email_0_input(datos.valor("email", "email"))
    await flow.scroll_219px()
    await flow.fill_transfer_payers_money_info_city_0_cash_dropdown_input(cfg.get("payer_city", "GUADALAJARa"))
    await flow.click_mexico_regular()
    await flow.wait_for_no_blocking_overlays()
    monto = datos.monto()
    await flow.click_transfer_payers_money_info_amo(monto)
    try:
        return float(datos.valor("amount"))
    except Exception:
        return None


# ── Manejo VERIFICADO del formulario de beneficiario (port de ai_agent) ───────
# Toggle del formulario de beneficiario (data-testid estable). REGLA DE ORO: al
# llenar para enviar se EXPANDE; para revelar el panel de Totales se RETRAE.
SEL_BENEF_TOGGLE = "[data-testid='transfer-beneficiary-toggle-fields-button-0']"
# Campo que SOLO es visible cuando el beneficiario está EXPANDIDO (existe en el
# DOM aun colapsado, pero no visible). Sirve para verificar el estado REAL.
SEL_BENEF_DETALLE = "[data-testid='transfer-beneficiary-cellphone-0-cellphone-input']"


async def set_beneficiary_expandido(flow, expandir: bool) -> None:
    """Deja el formulario de beneficiario expandido (True) o retraído (False).

    Verifica por la VISIBILIDAD REAL de un campo de detalle (el celular del
    beneficiario), NO por aria-expanded —que a veces queda obsoleto y hacía
    'creer' que estaba expandido sin estarlo—. Hace clic en el toggle SOLO lo
    necesario (máx 3 intentos). Esto reemplaza el `click_transfer_beneficiary_
    toggle_fi()` a ciegas, que si el form ya estaba abierto lo CERRABA y dejaba
    los siguientes fill cayendo en elementos ocultos/equivocados."""
    estado = "visible" if expandir else "hidden"
    try:
        btn = flow.page.locator(SEL_BENEF_TOGGLE).first
        if await btn.count() == 0:
            return
        detalle = flow.page.locator(SEL_BENEF_DETALLE).first
        for _ in range(3):
            try:
                if (await detalle.is_visible()) == expandir:
                    return
            except Exception:
                pass
            try:
                await btn.scroll_into_view_if_needed(timeout=1_500)
                await btn.click(timeout=2_500)
            except Exception:
                pass
            # Esperar a que el detalle alcance el estado deseado (fin de la
            # animación 'collapse' de Bootstrap), en vez de un sleep ciego +
            # re-chequeo que puede volver a clickear y OSCILAR el estado.
            try:
                await detalle.wait_for(state=estado, timeout=2_500)
                return
            except Exception:
                continue
    except Exception:
        pass


async def llenar_formulario_completo(flow, datos, cfg, pais, ciudad, estado, monto=None, tipo="cash", benef_phone=None, colapsar_beneficiario=True) -> float:
    """Llena el formulario COMPLETO de un envío NORMAL, EMPEZANDO DESDE EL
    TELÉFONO del cliente (no desde el país). Orden: cliente (celular, nombre,
    dirección, CP) → beneficiario (país + detalle, expandido con verificación) →
    transferencia (ciudad pagador, fee type, monto). Deja el beneficiario
    COLAPSADO antes de la sección de dinero para revelar el panel de Totales y
    para que los campos de dinero no queden tapados. Devuelve el monto (float).

    Es el llenado robusto de ai_agent: usa set_beneficiary_expandido (no clics a
    ciegas) y cierra la tabla 'Global search results' que puede tapar campos."""
    await flow.navigate()
    # 1) CLIENTE — desde el celular
    await flow.fill_transfer_customer_cellphone_0_cellphone_input(datos.valor("phone", "phone"))
    await flow.fill_transfer_customer_name_0_input(datos.valor("customer_name", "first_name"))
    await flow.fill_transfer_customer_first_lastname_0_input(datos.valor("customer_last1", "last_name"))
    await flow.fill_transfer_customer_second_lastname_0_input(datos.valor("customer_last2", "last_name"))
    try:
        await flow.click_close_table()
    except Exception:
        pass
    await flow.fill_transfer_customer_address_0_input(datos.valor("address", "address"))
    await flow.fill_transfer_customer_zip_code_0_input(datos.valor("us_zip", "us_zip"))
    await flow.esperar_autocomplete_cp()
    # 2) BENEFICIARIO: país + detalle (expandido con verificación)
    await set_beneficiary_expandido(flow, True)
    await flow.click_transfer_beneficiary_clear_0_i()
    await flow.fill_transfer_beneficiary_country_0_dropdown_input(pais)
    await flow.click_beneficiary()
    await flow.fill_transfer_beneficiary_name_0_dropdown_input(datos.valor("beneficiary_name", "first_name"))
    await flow.fill_transfer_beneficiary_first_lastname_0_input(datos.valor("beneficiary_last1", "last_name"))
    await flow.fill_transfer_beneficiary_second_lastname_0_input(datos.valor("beneficiary_last2", "last_name"))
    # La tabla 'Global search results' puede aparecer al teclear nombre/celular y
    # TAPAR los campos del beneficiario. Cerrarla, re-expandir y hacer scroll.
    try:
        await flow.click_close_table()
    except Exception:
        pass
    await set_beneficiary_expandido(flow, True)
    try:
        await flow.page.locator(SEL_BENEF_DETALLE).first.scroll_into_view_if_needed(timeout=2000)
    except Exception:
        pass
    # Teléfono del beneficiario: si el país/pagador exige un prefijo (ej. '573'
    # para Uniteller Colombia — KRA-1125), se pasa en benef_phone; si no, Faker.
    await flow.fill_transfer_beneficiary_cellphone_0_cellphone_input(
        benef_phone or datos.valor("phone", "phone"))
    await flow.fill_transfer_beneficiary_address_0_input(datos.valor("address", "address"))
    await flow.fill_transfer_beneficiary_zip_code_0_input(datos.valor("zip", "zip"))
    await flow.fill_transfer_beneficiary_city_0_input(ciudad)     # ALEATORIO (del país)
    await flow.fill_transfer_beneficiary_state_0_input(estado)    # ALEATORIO (del país)
    await flow.fill_transfer_beneficiary_date_of_birth_0_input(datos.valor("date", "date"))
    await flow.fill_transfer_beneficiary_email_0_input(datos.valor("email", "email"))
    # 3) COLAPSAR (revela Totales) + elegir TIPO de envío + sección Transfer.
    #    Con colapsar_beneficiario=False el panel de info del beneficiario se DEJA
    #    ABIERTO (ej. KRA-1125: la corrección del teléfono debe quedar visible y
    #    no queremos abrir/cerrar el panel). El scroll baja a la sección de dinero.
    if colapsar_beneficiario:
        await set_beneficiary_expandido(flow, False)
    await flow.scroll_219px()
    # Seleccionar el tab del tipo (cash/deposit/home/mobile/atm). Cash = default.
    await flow.seleccionar_tipo_envio(tipo)
    monto_str = str(int(monto)) if monto is not None else datos.monto()
    if tipo == "cash":
        # Sub-formulario CASH (mapeado y estable): ciudad pagador → fee type → monto
        await flow.fill_transfer_payers_money_info_city_0_cash_dropdown_input(cfg.get("payer_city", "GUADALAJARa"))
        await flow.click_mexico_regular()
        await flow.wait_for_no_blocking_overlays()
        await flow.click_transfer_payers_money_info_amo(monto_str)
    elif tipo == "deposit":
        # Sub-formulario DEPÓSITO (testids con segmento 'deposit'): ciudad pagador
        # → TARIFA (fee-type) → monto. La tarifa es la que HABILITA el campo de
        # monto y el modal de pagador; omitirla dejaba el form inválido. El tipo
        # de cuenta y el número de cuenta los llena el caller (van junto al pagador).
        await flow.select_typeahead(
            "transfer-payers-money-info-city-0-deposit-dropdown-input",
            cfg.get("payer_city", "GUADALAJARa"))
        await flow.seleccionar_fee_type("deposit", cfg.get("fee_type", "MEXICO REGULAR"))
        await flow.wait_for_no_blocking_overlays()
        await flow.fill_monto(
            "transfer-payers-money-info-amount-0-deposit-amount-input", monto_str)
    elif tipo == "atm":
        # Sub-formulario ATM (doméstico, ej. Pin4Cash / MASTERCARD CASH PICK-UP):
        # estado del beneficiario + monto. El pagador lo elige el caller con
        # seleccionar_pagador(tipo="atm"). Testids: ...-0-atm-...
        await flow.select_typeahead(
            "transfer-payers-money-info-state-0-atm-dropdown-input", estado)
        await flow.wait_for_no_blocking_overlays()
        await flow.fill_monto(
            "transfer-payers-money-info-amount-0-atm-amount-input", monto_str)
    else:
        # home/mobile: el tab ya quedó seleccionado; sus campos siguen
        # PENDIENTES de mapear (Consulta #2).
        try:
            flow.logger.warning(
                f"[tipo={tipo}] Tab seleccionado. Sub-formulario de '{tipo}' aún "
                f"NO mapeado (faltan los data-testid de sus campos).")
        except Exception:
            pass
    try:
        return float(monto_str)
    except Exception:
        return None


SELECTOR_BRANCH_REQUIRED = (
    "transfersmoneyinfocashform p.text-danger.error-input, "
    "transfersmoneyinfocashform p[class*='error-input'], "
    ".payer-branch-button ~ p.text-danger.error-input"
)


async def _modal_sucursal_abierto(flow) -> bool:
    try:
        return await flow.page.locator("#branchesModalId, .modal.show").first.is_visible()
    except Exception:
        return False


async def _cerrar_modal_sucursal_con_x(flow):
    """Último recurso: cerrar el modal con su X (la fila ya quedó resaltada).
    NO se usa Escape porque suele CANCELAR la selección."""
    try:
        x = flow.page.locator(
            "#branchesModalId .btn-close, #branchesModalId [aria-label='Close'], "
            "#branchesModalId button.close, .modal.show .btn-close, "
            ".modal.show [aria-label='Close']").first
        if await x.is_visible():
            await x.click(timeout=1500)
    except Exception:
        pass


async def _commit_fila_sucursal(flow, fila, txt, logger=None) -> bool:
    """Confirma la fila de sucursal y verifica que el modal CIERRE."""
    async def cerrado():
        return not await _modal_sucursal_abierto(flow)

    for accion in ("click", "dblclick", "enter", "td_click", "x"):
        try:
            if accion == "click":
                await fila.click(timeout=2000)
            elif accion == "dblclick":
                await fila.dblclick(timeout=2000)
            elif accion == "enter":
                await fila.focus()
                await flow.page.keyboard.press("Enter")
            elif accion == "td_click":
                await fila.locator("td").first.click(timeout=1500)
            elif accion == "x":
                await _cerrar_modal_sucursal_con_x(flow)
        except Exception:
            pass
        for _ in range(5):
            if await cerrado():
                if logger:
                    logger.info(f"✓ sucursal '{txt[:30]}' aplicada (vía {accion}) — modal cerrado")
                return True
            await flow.page.wait_for_timeout(220)
    if logger:
        logger.warning(f"Sucursal '{txt[:30]}': no logré cerrar el modal tras varios intentos.")
    return False


async def _elegir_fila_sucursal(flow, logger=None) -> bool:
    """Dentro del modal de sucursales, elige una fila AL AZAR por ÍNDICE."""
    import random
    sel = (
        "tr[tabindex='0'], tr.p-selectable-row, [data-p-selectable-row='true'], "
        ".p-datatable-tbody tr, #branchesModalId tbody tr, .modal.show tbody tr"
    )
    try:
        await flow.page.locator(sel).first.wait_for(state="visible", timeout=9000)
    except Exception:
        pass
    filas = flow.page.locator(sel)
    visibles = []
    try:
        n = await filas.count()
        for i in range(min(n, 60)):
            f = filas.nth(i)
            try:
                if await f.is_visible() and (await f.inner_text()).strip():
                    visibles.append(i)
            except Exception:
                pass
    except Exception:
        pass
    if not visibles:
        if logger:
            logger.warning("Sucursal: no aparecieron filas en el modal — continúo.")
        return False
    idx = random.choice(visibles)
    fila = filas.nth(idx)
    try:
        txt = (await fila.inner_text()).strip()
    except Exception:
        txt = "?"
    if logger:
        logger.info(f"Sucursal: elegida al azar (índice {idx} de {len(visibles)}): '{txt[:30]}'.")
    return await _commit_fila_sucursal(flow, fila, txt, logger)


async def seleccionar_sucursal_si_aplica(flow, logger=None) -> bool:
    """Selecciona sucursal SOLO si la app la marca como requerida ('Field required')."""
    try:
        # Sondeo RÁPIDO de 'Field required': corta apenas aparece (caso que SÍ
        # requiere sucursal, ej. Uniteller depósito) en vez de esperar 700 ms
        # fijos. Si no aparece en ~600 ms, se asume que no se requiere.
        requerida = False
        for _ in range(4):
            try:
                if await flow.page.locator(SELECTOR_BRANCH_REQUIRED).first.is_visible():
                    requerida = True
                    break
            except Exception:
                pass
            await flow.page.wait_for_timeout(150)
        if not requerida:
            if logger:
                logger.info("Sucursal NO requerida (sin 'Field required') — sigo al flujo normal.")
            return False
        if logger:
            logger.info("'Field required' de sucursal detectado → eligiendo una sucursal al azar.")
        await flow.click_branch()
        return await _elegir_fila_sucursal(flow, logger)
    except Exception as e:
        if logger:
            logger.warning(f"Sucursal: no se pudo manejar ({e}) — continúo.")
        return False


async def seleccionar_pagador_atm(flow, search, logger=None):
    """Pagador ATM (doméstico): NO es un modal de búsqueda como cash/deposit — es
    un TYPEAHEAD directo en el input `...-0-atm-input`. Se teclea y se CLICKEA la
    opción desplegada (select_typeahead ya hace click en la opción). Ej.:
    'MASTERCARD CASH PICK-UP'."""
    if logger:
        logger.info("seleccionar_pagador_atm (typeahead): %s", search)
    await flow.select_typeahead("transfer-payers-money-info-payer-0-atm-input", search)
    await flow.wait_for_no_blocking_overlays()


async def seleccionar_pagador(flow, cfg, logger=None, seleccionar_sucursal=True, tipo="cash"):
    """Selección GENÉRICA de pagador (cualquiera del catálogo), para el TIPO dado
    (cash/deposit/...). Abre el campo Payer del sub-formulario correcto.

    OJO: para 'atm' el pagador es un typeahead directo — usar
    seleccionar_pagador_atm() en su lugar."""
    await flow.click_payer_field(tipo)
    await flow.buscar_pagador_rapido(cfg.get("search", cfg["code"]), cfg.get("row") or "")
    await flow.scroll_250px()
    if seleccionar_sucursal:
        await seleccionar_sucursal_si_aplica(flow, logger)
    elif logger:
        logger.info("Sucursal OMITIDA (fase solo-cálculo): no se selecciona aunque sea requerida.")
    await flow.scroll_230px()
    await flow.scroll_130px()


SEND_BUTTON_TESTID = "transfers-container-modal-summary-0-send-button"
_SUCCESS_DECLINE_TESTID = "transfers-container-modal-success-transfer-0-decline-button"

# Mensaje INFORMATIVO de compliance/OFAC que sale al dar Continue en ciertos
# envíos (ej. beneficiario OFAC): "Additional beneficiary information is required
# ... contact Compliance". NO es llenable; hay que pulsar 'Back to Transfer' y
# reintentar Continue (el envío igual procede y cae en Hold). Port del script base.
_OFAC_MSG_TESTID      = "compliance-show-messages-tab-0-message"
_BACK_TO_TRANSFER_SEL = "button.footer-btn-back"
_RE_BACK              = re.compile(r"back to transfer|regresar a env", re.I)

# Pago con Tarjeta de Débito (TDD): opción en el panel Totales + modal del POS
# (emulador de terminal bancaria) que aparece tras 'Sí, Enviar'.
TESTID_PAGO_DEBITO = "transfer-totals-pin-0"
_POS_ACCEPT_TESTID = "pos-accept-button"


async def seleccionar_pago_tarjeta_debito(flow, logger=None) -> bool:
    """Selecciona la forma de pago 'Tarjeta débito' en el panel de Totales."""
    try:
        btn = flow.page.get_by_test_id(TESTID_PAGO_DEBITO).first
        await btn.wait_for(state="visible", timeout=15_000)
        await btn.click(force=True)
        if logger:
            logger.info("Forma de pago 'Tarjeta débito' seleccionada.")
        await flow.page.wait_for_timeout(1_000)
        return True
    except Exception as e:
        if logger:
            logger.warning("No se pudo seleccionar 'Tarjeta débito': %s", str(e)[:80])
        return False


async def _mensaje_compliance_visible(flow) -> bool:
    """True si está en pantalla el mensaje informativo de compliance/OFAC."""
    try:
        if await flow.page.get_by_test_id(_OFAC_MSG_TESTID).first.is_visible():
            return True
    except Exception:
        pass
    try:
        if await flow.page.locator(_BACK_TO_TRANSFER_SEL).first.is_visible():
            return True
    except Exception:
        pass
    return False


async def _click_back_to_transfer(flow, logger=None) -> bool:
    """Pulsa 'Back to Transfer' / 'Regresar A Envío' desde la pantalla OFAC."""
    for get in (lambda: flow.page.locator(_BACK_TO_TRANSFER_SEL).first,
                lambda: flow.page.get_by_role("button", name=_RE_BACK).first):
        try:
            btn = get()
            await btn.wait_for(state="visible", timeout=6_000)
            await btn.click(timeout=5_000)
            if logger:
                logger.info("Mensaje de compliance/OFAC → 'Back to Transfer' pulsado.")
            await flow.page.wait_for_timeout(1_500)
            return True
        except Exception:
            continue
    return False


async def completar_envio(flow, completar=True, logger=None, evi=None,
                          pos_pago=False):
    """Termina la transacción: Continue → (resumen) → YES, Send → declina recibo.

    Maneja el mensaje INFORMATIVO de compliance/OFAC (beneficiario sancionado):
    si aparece, pulsa 'Back to Transfer' y reintenta Continue (hasta 6 veces),
    igual que el script base. El envío procede y cae en OFAC/KYC Hold.

    pos_pago=True (Tarjeta de Débito): tras 'Sí, Enviar' aparece el modal del POS
    (emulador de terminal); se espera y se pulsa 'Accept' antes del cierre."""
    if not completar:
        if logger:
            logger.info("Envío NO completado (configurado COMPLETAR_ENVIO=0).")
        return False
    try:
        send_btn = flow.page.get_by_test_id(SEND_BUTTON_TESTID)

        async def _esperar_mensaje_o_resumen(timeout_ms: int) -> str:
            """Tras dar Continue, espera (poll) a que aparezca ALGO: el mensaje
            informativo de compliance/OFAC O el resumen (botón 'Sí, Enviar').
            El mensaje OFAC a veces TARDA (ej. doméstico), por eso se sondea."""
            paso = 1_000
            t = 0
            while t < timeout_ms:
                if await _mensaje_compliance_visible(flow):
                    return "mensaje"
                try:
                    if await send_btn.first.is_visible():
                        return "resumen"
                except Exception:
                    pass
                await flow.page.wait_for_timeout(paso)
                t += paso
            return ""

        resumen = False
        for intento in range(1, 9):
            await flow.wait_for_no_blocking_overlays()
            try:
                await flow.click_continue()
            except Exception:
                pass

            estado = await _esperar_mensaje_o_resumen(12_000)
            if estado == "resumen":
                resumen = True
                break
            if estado == "mensaje":
                if evi is not None and intento == 1:
                    await evi.shot("mensaje_info_adicional")
                if logger:
                    logger.info("Mensaje de compliance/OFAC (intento %d) → Back to Transfer.",
                                intento)
                await _click_back_to_transfer(flow, logger)
                continue
            # Nada apareció en la ventana: reintentar Continue en la próxima vuelta.
            if logger:
                logger.info("Sin mensaje ni resumen (intento %d) — reintento Continue.", intento)

        if not resumen:
            if logger:
                logger.warning("No se abrió el resumen de envío (Continue no avanzó).")
            return False

        if evi is not None:
            await evi.shot("envio_continue")

        await flow.click_yes_send()

        # Pago con Tarjeta de Débito: tras 'Sí, Enviar' aparece el modal del POS
        # (emulador de terminal bancaria, ya preparado para recibir la petición).
        # Se espera y se acepta el cobro con tarjeta antes de continuar al éxito.
        if pos_pago:
            try:
                pos = flow.page.get_by_test_id(_POS_ACCEPT_TESTID).first
                await pos.wait_for(state="visible", timeout=30_000)
                if evi is not None:
                    await evi.shot("pos_tarjeta_debito")
                await pos.click()
                if logger:
                    logger.info("POS: 'Accept' del cobro con tarjeta de débito pulsado.")
                await flow.page.wait_for_timeout(3_000)
            except Exception as e:
                if logger:
                    logger.warning("POS: no apareció/aceptó el cobro con tarjeta: %s",
                                   str(e)[:80])

        # Dar TIEMPO al modal de éxito ("¡Transacción exitosa! / ¿desea hacer otra
        # transacción?") antes de cerrarlo con NO. Cerrarlo de inmediato daba la
        # PERCEPCIÓN de fallo. Se espera a que aparezca, se captura evidencia y se
        # deja visible una pausa (SUCCESS_PAUSE_MS, default 3500 ms) antes del NO.
        import os as _os
        pausa = int(_os.getenv("SUCCESS_PAUSE_MS", "1500"))
        try:
            decline = flow.page.get_by_test_id(_SUCCESS_DECLINE_TESTID)
            await decline.wait_for(state="visible", timeout=15_000)
            if evi is not None:
                await evi.shot("envio_exitoso", search_text="exitosa")
            if logger:
                logger.info(f"✅ ¡Transacción exitosa! — dejando el modal visible {pausa} ms "
                            f"antes de cerrar (no da percepción de fallo).")
            await flow.page.wait_for_timeout(pausa)
        except Exception:
            if logger:
                logger.info("Modal de éxito no detectado por testid — continúo al cierre.")
        try:
            await flow.click_no()
        except Exception:
            pass
        await flow.wait_for_no_blocking_overlays()
        if logger:
            logger.info("✅ Transacción COMPLETADA (enviada).")
        return True
    except Exception as e:
        if logger:
            logger.warning(f"No se pudo completar el envío: {e}")
        return False
