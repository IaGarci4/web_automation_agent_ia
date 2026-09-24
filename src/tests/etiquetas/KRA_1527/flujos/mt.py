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
import os
import re
from pathlib import Path

from config import settings

from . import modales as _MOD

# ⚠️ OJO AL COPIAR: en el original esto era `Path(__file__).parent`, porque el
# módulo VIVÍA en src/pagadores/ junto a los payers.json. Al copiarlo a la
# etiqueta apuntaba a esta carpeta, no encontraba ningún catálogo y
# `cargar_catalogo` devolvía el fallback de ELEKTRA en silencio — el envío se
# hacía, pero con otro pagador del que pedía el caso. Los catálogos son DATOS
# del ambiente y se comparten a propósito: si un pagador se desactiva porque
# dejó de existir en la app, la etiqueta debe enterarse.
_PAGADORES_DIR = Path(settings.PROJECT_ROOT) / "src" / "pagadores"

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
    """País del pagador + ciudad/estado ALEATORIOS de ese país.

    ⚠️ Para un happy path NO uses esto: usa `destino_del_pagador`. Aleatorizar
    la ciudad rompe el envío, porque **no todos los pagadores operan en todas
    las ciudades**. ELEKTRA tiene sucursales en Guadalajara; si el azar elige
    Mérida, el modal de sucursales sale vacío, el formulario queda inválido y
    Continue no avanza — un fallo que parece del script y es del dato.

    Se conserva para pruebas que quieran barrer destinos a propósito."""
    pais = cfg.get("country", "MEXICo")
    pool = ciudades.get(pais) or ciudades.get("MEXICo") or [["GUADALAJARA", "JALISCO"]]
    ciudad, estado = rng.choice(pool)
    return pais, ciudad, estado


def destino_del_pagador(cfg: dict, ciudades: dict, logger=None):
    """Ciudad y estado del CATÁLOGO del pagador. Determinista y probado.

    Es la pareja ciudad/pagador que el módulo de pagadores declara como buena
    (`payer_city`), la misma que usa el agente cuando le pides «haz un envío a
    Elektra». Para ELEKTRA es GUADALAJARA/JALISCO, donde sí hay sucursales.

    Lo que se aleatoriza es lo que da igual —nombres, apellidos, direcciones,
    teléfonos, correos— y lo que NO se aleatoriza es la geografía, que es la
    que decide si el pagador existe en ese destino. Esa es la diferencia entre
    un happy path repetible y una prueba que falla un día de cada tres por el
    dato que le tocó."""
    pais = cfg.get("country", "MEXICo")
    ciudad = (cfg.get("payer_city") or "").strip()
    pool = ciudades.get(pais) or ciudades.get("MEXICo") or [["GUADALAJARA", "JALISCO"]]
    for c, e in pool:
        if c.strip().upper() == ciudad.upper():
            if logger:
                logger.info("Destino del catálogo de %s: %s / %s.",
                            cfg.get("code", "?"), c, e)
            return pais, c, e
    # El catálogo trae una ciudad que no está en la tabla ciudad→estado: se usa
    # la primera pareja y se DICE, en vez de inventar un estado que no cuadre.
    ciudad_fb, estado_fb = pool[0]
    if logger:
        logger.warning("El pagador %s declara la ciudad '%s', que no está en la "
                       "tabla ciudad→estado de %s. Uso %s / %s. Revisa "
                       "src/pagadores/%s/payers.json.",
                       cfg.get("code", "?"), ciudad or "(vacía)", pais,
                       ciudad_fb, estado_fb, cfg.get("_modulo", "mexico"))
    return pais, ciudad_fb, estado_fb


STATE_BENEF = "transfer-beneficiary-state-0-input"


async def elegir_primer_estado(flow) -> str:
    """Abre el desplegable de State del beneficiario y elige la 1ª opción.

    Sirve cuando el caso no fija un estado concreto: el campo es obligatorio,
    así que dejarlo vacío bloquea el envío. Devuelve el valor que quedó."""
    page = flow.page
    try:
        campo = page.get_by_test_id(STATE_BENEF).first
        await campo.click(force=True, timeout=5_000)
        await page.wait_for_timeout(700)
        opcion = page.locator("li[role='option'], .p-dropdown-item, "
                              "[role='option']").first
        await opcion.wait_for(state="visible", timeout=6_000)
        texto = (await opcion.inner_text() or "").strip()
        await opcion.click(force=True, timeout=4_000)
        await page.wait_for_timeout(500)
        try:
            flow.logger.info("State del beneficiario (1ª opción): '%s'", texto)
        except Exception:
            pass
        return texto
    except Exception as e:
        try:
            flow.logger.warning("No se pudo elegir el State del beneficiario: %s",
                                str(e)[:90])
        except Exception:
            pass
        return ""


async def llenar_direccion_cliente(flow, datos, max_intentos: int = 10) -> bool:
    """Resuelve el validador de direcciones del CLIENTE en el ORDEN correcto:
    dirección primero → elegir una verificada → poner el ZIP de esa dirección.

    El validador exige que la dirección exista EN el zip del campo; NO ajusta el
    zip al elegir. Por eso se teclea una calle, se elige una sugerencia real (por
    teclado) y se pone SU zip. Reintenta con otras calles del catálogo si alguna
    no verifica. Devuelve True cuando una queda verificada."""
    from src.helpers.direcciones_us import candidatos
    for i, dom in enumerate(candidatos(max_intentos), 1):
        ok, elegido, _sug = await flow.resolver_direccion_cliente(
            dom["direccion"], zip_preferido=dom["zip"],
            ciudad=dom.get("ciudad", ""), estado=dom.get("estado", ""))
        if ok:
            flow.logger.info("Dirección del cliente verificada al intento %d: %s",
                             i, elegido)
            return True
        flow.logger.warning("Dirección intento %d/%d: '%s' no verificó — pruebo otra.",
                            i, max_intentos, dom["direccion"])
        try:                                   # limpiar antes del siguiente intento
            await flow.fill_transfer_customer_address_0_input("")
            await flow.fill_transfer_customer_zip_code_0_input("")
        except Exception:
            pass
    flow.logger.error("Ninguna de %d direcciones del catálogo verificó contra el "
                      "validador de Hermes — revisa direcciones_us.py.", max_intentos)
    return False


async def llenar_hasta_monto(flow, datos, cfg, pais, ciudad, estado) -> float:
    """Cliente + beneficiario (país del pagador; ciudad/estado aleatorios) + tarifa + monto."""
    await flow.navigate()
    await flow.fill_transfer_customer_cellphone_0_cellphone_input(datos.valor("phone", "phone"))
    await flow.fill_transfer_customer_name_0_input(datos.valor("customer_name", "first_name"))
    await flow.fill_transfer_customer_first_lastname_0_input(datos.valor("customer_last1", "last_name"))
    await flow.fill_transfer_customer_second_lastname_0_input(datos.valor("customer_last2", "last_name"))
    await flow.click_close_table()
    # Dirección del cliente: la resuelve el validador de direcciones reales
    # (Google) de Hermes — ZIP primero, luego elige la sugerencia que casa con
    # ese ZIP, reintentando con otras del catálogo si alguna no verifica.
    await llenar_direccion_cliente(flow, datos)
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
    # ESTADO: campo OBLIGATORIO. Si el caller no lo pasa se elige la primera
    # opción del desplegable, en vez de teclear cadena vacía — eso dejaba el
    # campo en rojo ('Required Field') y el envío no continuaba, mientras el log
    # decía "✓ typeahead ''" como si hubiera funcionado.
    if str(estado or "").strip():
        await flow.fill_transfer_beneficiary_state_0_input(estado)
    else:
        await elegir_primer_estado(flow)
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
                await btn.scroll_into_view_if_needed(timeout=1_000)
                await btn.click(timeout=1_500)
            except Exception:
                pass
            # Esperar a que el detalle alcance el estado deseado (fin de la
            # animación 'collapse' de Bootstrap), en vez de un sleep ciego +
            # re-chequeo que puede volver a clickear y OSCILAR el estado.
            try:
                await detalle.wait_for(state=estado, timeout=1_500)
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
    # Dirección del cliente: la resuelve el validador de direcciones reales
    # (Google) de Hermes — ZIP primero, luego elige la sugerencia que casa con
    # ese ZIP, reintentando con otras del catálogo si alguna no verifica.
    await llenar_direccion_cliente(flow, datos)
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
    # ESTADO: campo OBLIGATORIO. Si el caller no lo pasa se elige la primera
    # opción del desplegable, en vez de teclear cadena vacía — eso dejaba el
    # campo en rojo ('Required Field') y el envío no continuaba, mientras el log
    # decía "✓ typeahead ''" como si hubiera funcionado.
    if str(estado or "").strip():
        await flow.fill_transfer_beneficiary_state_0_input(estado)
    else:
        await elegir_primer_estado(flow)
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
    elif tipo == "home":
        # Sub-formulario HOME DELIVERY (entrega a domicilio; lo usa CP11).
        # Orden: ciudad → monto. A diferencia de depósito, aquí la TARIFA llega
        # preseleccionada y el monto se habilita solo un instante después de
        # elegir la ciudad; por eso se espera a que el campo sea editable en vez
        # de clickearlo a ciegas (daba 'Element is not visible' sobre un input
        # 'readonly disabled'). La tarifa y el pagador quedan como respaldos por
        # si algún pagador sí los exige antes del importe.
        await flow.select_typeahead(
            "transfer-payers-money-info-city-0-home-dropdown-input",
            cfg.get("payer_city") or ciudad)
        await flow.wait_for_no_blocking_overlays()
        campo_monto = "transfer-payers-money-info-amount-0-home-amount-input"
        # La TARIFA de Home suele venir preseleccionada (el dropdown llega con
        # `p-inputwrapper-filled`), así que solo se toca si el monto sigue
        # bloqueado: intentarlo siempre costaba segundos y ensuciaba el log.
        if not await esperar_campo_habilitado(flow, campo_monto, timeout_ms=4_000):
            await flow.seleccionar_fee_type("home", cfg.get("fee_type") or "")
            await flow.wait_for_no_blocking_overlays()
        if not await esperar_campo_habilitado(flow, campo_monto):
            # Puede ser el PAGADOR el que habilita el monto (en cash/deposit es
            # al revés). Se elige el pagador y se vuelve a intentar, en vez de
            # estrellarse con 'Element is not visible' sobre un input disabled.
            try:
                flow.logger.info(
                    "[home] El monto sigue deshabilitado tras la tarifa — "
                    "elijo el pagador primero.")
            except Exception:
                pass
            await seleccionar_pagador_home(
                flow, cfg.get("search", cfg.get("code", "")),
                getattr(flow, "logger", None))
            await flow.wait_for_no_blocking_overlays()
            if not await esperar_campo_habilitado(flow, campo_monto):
                raise AssertionError(
                    "El campo de monto de HOME DELIVERY sigue deshabilitado "
                    "tras elegir ciudad, tarifa y pagador. Revisa qué dato "
                    "falta en esa pantalla.")
        await flow.fill_monto(campo_monto, monto_str)
    else:
        # mobile: el tab ya quedó seleccionado; sus campos siguen PENDIENTES
        # de mapear (faltan sus data-testid).
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
    filas = flow.page.locator(sel)

    async def _visibles(limite: int = 60) -> list:
        """Índices de filas REALMENTE visibles y con texto."""
        try:
            n = min(await filas.count(), limite)
        except Exception:
            return []
        encontradas = []
        for i in range(n):
            f = filas.nth(i)
            try:
                if await f.is_visible() and (await f.inner_text()).strip():
                    encontradas.append(i)
            except Exception:
                continue
        return encontradas

    # ⚠️ Antes esto era `locator(sel).first.wait_for(state="visible", timeout=9000)`
    # y se comía 9 de los 10 segundos que tardaba el paso. El motivo es el de
    # siempre: `.first` es el primero en el DOM, no el primero VISIBLE, y el
    # selector incluye `tr[tabindex='0']` sin acotar al modal — así que cazaba
    # una fila de un modal anterior que Angular deja en el DOM ya oculto.
    # Esperar a que ESA se vuelva visible es esperar para siempre.
    #
    # Ahora se sondea por lo que de verdad hace falta —que haya al menos una
    # fila visible y con texto— y se sale en cuanto la hay.
    visibles = []
    espera = 0
    while espera <= 6_000:
        visibles = await _visibles()
        if visibles:
            break
        await flow.page.wait_for_timeout(200)
        espera += 200
    if visibles and logger:
        logger.info("Sucursal: %d fila(s) listas en %.1f s.", len(visibles),
                    espera / 1000)

    # Si el modal no pintó filas, REINTENTAR abriéndolo: dejarlo sin sucursal
    # cuando la app la exige deja el formulario INVÁLIDO y Continue no avanza
    # (se veía como 'Sin mensaje ni resumen' en bucle).
    if not visibles:
        for _ in range(2):
            try:
                await flow.click_branch()
            except Exception:
                pass
            espera = 0
            while espera <= 4_000:
                visibles = await _visibles()
                if visibles:
                    break
                await flow.page.wait_for_timeout(200)
                espera += 200
            if visibles:
                break
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


async def esperar_campo_habilitado(flow, testid: str, timeout_ms: int = 10_000) -> bool:
    """Espera a que un input deje de estar `disabled`/`readonly`.

    Los sub-formularios de Hermes habilitan sus campos en cascada (la tarifa
    habilita el monto, el monto habilita el pagador…). Sin esta espera el error
    que sale es 'Element is not visible', que apunta al sitio equivocado."""
    campo = flow.page.get_by_test_id(testid).first
    espera = 0
    while espera <= timeout_ms:
        try:
            if await campo.is_editable():
                return True
        except Exception:
            pass
        await flow.page.wait_for_timeout(250)
        espera += 250
    return False


async def esperar_pagador_autoseleccionado(flow, testid: str,
                                           timeout_ms: int = 10_000) -> str:
    """Espera a que Hermes AUTOSELECCIONE el pagador; devuelve su valor o ''.

    En Home Delivery el pagador se asigna solo unos segundos después de escribir
    el monto. Leerlo de inmediato lo encontraba vacío y disparaba la apertura de
    un modal que no correspondía — y ahí se perdían dos minutos de reintentos."""
    campo = flow.page.get_by_test_id(testid).first
    espera = 0
    while espera <= timeout_ms:
        try:
            valor = (await campo.input_value() or "").strip()
            if valor:
                return valor
        except Exception:
            pass
        await flow.page.wait_for_timeout(400)
        espera += 400
    return ""


async def seleccionar_pagador_home(flow, search, logger=None,
                                   branch_code: str = None):
    """Pagador de HOME DELIVERY (lo usa CP11).

    Particularidad de esta pantalla: al escribir el monto, Hermes suele
    AUTOSELECCIONAR el pagador. Por eso primero se LEE el campo: si ya trae
    valor no se toca nada (abrir el modal encima lo borraba). Si está vacío, se
    abre el modal de búsqueda y se elige la fila por texto.

    `branch_code`: se escribe solo si la pantalla reclama 'Bank Branch Code'."""
    campo = "transfer-payers-money-info-payer-0-home-input"
    actual = await esperar_pagador_autoseleccionado(flow, campo)
    if actual:
        if logger:
            logger.info("Pagador HOME autoseleccionado: '%s' — no se toca.", actual)
    else:
        if logger:
            logger.info("seleccionar_pagador_home (modal): %s", search)
        await flow.click_payer_field("home")
        # Confirmar que el modal ABRIÓ antes de teclear: si no, los reintentos
        # de buscar_pagador_rapido tardan ~2 min en rendirse contra una pantalla
        # donde el buscador ni existe.
        buscador = flow.page.get_by_test_id(
            "transfers-money-info-modal-search-payer-0-input-search-input").first
        try:
            await buscador.wait_for(state="visible", timeout=8_000)
        except Exception:
            raise AssertionError(
                "El modal de pagador de HOME DELIVERY no abrió y el campo "
                f"quedó vacío (esperaba '{search}'). Puede que este pagador se "
                "asigne solo y la pantalla necesite otro dato antes.")
        await flow.buscar_pagador_rapido(search, "")
        await flow.wait_for_no_blocking_overlays()
    if branch_code:
        await escribir_branch_code_si_aplica(flow, branch_code, logger)
    await flow.scroll_230px()


# Tooltip que reclama el código de sucursal (bilingüe).
_TOOLTIP_BRANCH = ("div#tooltip:has-text('Bank Branch Code field is required'), "
                   "div#tooltip:has-text('Código de sucursal')")
_BRANCH_INPUT = "transfer-payers-money-info-branch-code-0-deposit-input"


async def escribir_branch_code_si_aplica(flow, branch_code: str, logger=None) -> bool:
    """Escribe el Bank Branch Code SOLO si la pantalla lo está reclamando.

    Se decide por el tooltip de validación, no a ciegas: en la mayoría de los
    pagadores el campo no existe y escribir en él rompería el formulario."""
    try:
        tooltip = flow.page.locator(_TOOLTIP_BRANCH).first
        if not await tooltip.is_visible():
            if logger:
                logger.info("No se requiere Bank Branch Code.")
            return False
    except Exception:
        return False
    try:
        campo = flow.page.get_by_test_id(_BRANCH_INPUT).first
        await campo.click()
        await campo.fill("")
        await campo.type(str(branch_code), delay=100)
        if logger:
            logger.info("Bank Branch Code '%s' escrito.", branch_code)
        return True
    except Exception as e:
        if logger:
            logger.warning("No se pudo escribir el Branch Code: %s", str(e)[:80])
        return False


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

# Datos por defecto para la INFORMACIÓN ADICIONAL cuando el flujo la exige
# (regla del proyecto: si el campo/ficha se requiere, se llena; si no, se sigue).
# Configurables por entorno para no tocar código.
_IA_PAIS    = os.getenv("IA_PAIS",    "MEXICO")
_IA_TIPO_ID = os.getenv("IA_TIPO_ID", "PASSPORT")
_IA_NUM_ID  = os.getenv("IA_NUM_ID",  "A1234567")
_IA_EXP     = os.getenv("IA_EXP",     "12/31/2032")
_IA_DOB     = os.getenv("IA_DOB",     "05/21/1983")


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


_RE_REQUERIDO = re.compile(r"required field|campo requerido|campo obligatorio", re.I)


async def campos_requeridos_visibles(flow, limite: int = 6) -> list:
    """Etiquetas de los campos marcados como obligatorios sin llenar.

    Hermes pinta 'Required Field' bajo el campo en rojo. Detectarlo permite
    cortar el bucle de Continue con un diagnóstico útil, en vez de reintentar
    hasta agotar los intentos."""
    try:
        avisos = flow.page.get_by_text(_RE_REQUERIDO)
        total = min(await avisos.count(), limite)
    except Exception:
        return []
    etiquetas = []
    for i in range(total):
        aviso = avisos.nth(i)
        try:
            if not await aviso.is_visible():
                continue
            # El nombre del campo suele estar en el contenedor del aviso.
            texto = await aviso.evaluate(
                "(el) => { const c = el.closest('div'); "
                " return c ? (c.innerText || '').trim() : ''; }")
            etiquetas.append(" ".join((texto or "requerido").split())[:60])
        except Exception:
            continue
    return etiquetas


# Botón AFIRMATIVO del modal de éxito ("¿desea imprimir el recibo?"). El único
# testid mapeado del modal es el de declinar, así que el afirmativo se busca por
# variantes de testid y, si no, por texto bilingüe. Se confirma con dom_audit.
_SUCCESS_ACCEPT_TESTIDS = (
    "transfers-container-modal-success-transfer-0-accept-button",
    "transfers-container-modal-success-transfer-0-confirm-button",
    "transfers-container-modal-success-transfer-0-approve-button",
    "modal-confirmation-confirm-button",
)
_RE_IMPRIMIR = re.compile(r"^\s*(yes|s[ií])\b|print|imprimir", re.I)


async def aceptar_impresion_recibo(flow, logger=None, evi=None) -> bool:
    """⚠️ OBSOLETA — NO USAR. Se conserva solo para no romper llamadas viejas.

    Partía de una premisa equivocada: que el modal de éxito preguntaba si se
    quería imprimir el recibo. No lo pregunta. Dice «Transaction Successful!
    Please give the receipt to the customer» y a continuación **«Do you want to
    make another transaction?»**, así que su botón afirmativo abre OTRO envío.

    La impresión del recibo es automática al completarse la transacción, siempre
    que haya una impresora seleccionada en Configuración > Dispositivos (ver
    `flujos/impresora.py`). Para cerrar el modal: `cerrar_modal_exito`."""
    if logger:
        logger.warning("[Recibo] `aceptar_impresion_recibo` está obsoleta: ese "
                       "botón inicia otra transacción, no imprime. Usa "
                       "`cerrar_modal_exito` y configura la impresora.")
    page = flow.page
    decline = _SUCCESS_DECLINE_TESTID
    for tid in _SUCCESS_ACCEPT_TESTIDS:
        try:
            btn = page.get_by_test_id(tid).first
            if await btn.is_visible():
                await btn.click(force=True, timeout=5_000)
                if logger:
                    logger.info("[Recibo] Impresión ACEPTADA (testid %s).", tid)
                await page.wait_for_timeout(2_500)
                return True
        except Exception:
            continue
    # Respaldo por texto, excluyendo explícitamente el botón de declinar.
    try:
        candidatos = page.locator("div.modal-content button, .modal button")
        total = min(await candidatos.count(), 10)
        for i in range(total):
            b = candidatos.nth(i)
            try:
                if not await b.is_visible():
                    continue
                if (await b.get_attribute("data-testid") or "") == decline:
                    continue
                texto = (await b.inner_text() or "").strip()
                if _RE_IMPRIMIR.search(texto):
                    await b.click(force=True, timeout=5_000)
                    if logger:
                        logger.info("[Recibo] Impresión ACEPTADA por texto ('%s').",
                                    texto)
                    await page.wait_for_timeout(2_500)
                    return True
            except Exception:
                continue
    except Exception:
        pass
    if logger:
        logger.warning("[Recibo] No encontré el botón para ACEPTAR la impresión "
                       "— el Hardware Agent no será invocado. Confirma el testid "
                       "del botón afirmativo con dom_audit.")
    return False


async def cerrar_modal_exito(flow, logger=None, timeout_ms: int = 8_000) -> bool:
    """Cierra el modal de éxito con **NO** («¿desea hacer otra transacción?»).

    Se sondea el botón esperando a que esté HABILITADO y se pulsa en cuanto lo
    está, cada 150 ms. La versión anterior tardaba varios segundos en cerrarlo
    y a veces acababa pulsando el YES de al lado — un clic en el botón
    equivocado deja la app arrancando otro envío y el caso siguiente empieza
    en una pantalla que no esperaba."""
    page = flow.page
    # Si quedó el diálogo de recibo digital encima, el modal de éxito ni
    # siquiera ha montado: sondearlo sería agotar el timeout contra un modal
    # que no puede aparecer.
    await _MOD.descartar_recibo_digital(flow, logger)
    espera = 0
    while espera <= timeout_ms:
        try:
            btn = page.get_by_test_id(_SUCCESS_DECLINE_TESTID)
            for i in range(min(await btn.count(), 4)):
                el = btn.nth(i)
                if await el.is_visible() and await el.is_enabled():
                    try:
                        await el.click(timeout=3_000)
                    except Exception:
                        await el.click(force=True, timeout=3_000)
                    if logger:
                        logger.info("[Éxito] Cerrado con NO (%.1f s).",
                                    espera / 1000)
                    await page.wait_for_timeout(500)
                    return True
        except Exception:
            pass
        await page.wait_for_timeout(150)
        espera += 150
    # Respaldo: la ruta del page object (smart_click), más lenta pero robusta.
    try:
        await flow.click_no()
        return True
    except Exception:
        if logger:
            logger.warning("[Éxito] No pude cerrar el modal con NO.")
        return False


async def completar_envio(flow, completar=True, logger=None, evi=None,
                          pos_pago=False, tipo_envio="cash",
                          imprimir_recibo=False):
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
    # Import perezoso (evita ciclo pagadores↔sanity_general al cargar el módulo).
    from . import info_adicional as _IA
    try:
        send_btn = flow.page.get_by_test_id(SEND_BUTTON_TESTID)

        async def _esperar_mensaje_o_resumen(timeout_ms: int) -> str:
            """Tras dar Continue, espera (poll) a que aparezca ALGO: el mensaje
            informativo de compliance/OFAC, la INFO ADICIONAL requerida, o el
            resumen (botón 'Sí, Enviar'). El mensaje OFAC a veces TARDA (ej.
            doméstico), por eso se sondea."""
            # 400 ms y no 1 s: este sondeo se recorre en cada intento de
            # Continue, así que su granularidad se paga multiplicada.
            paso = 400
            t = 0
            atendidos = 0
            while t < timeout_ms:
                # ── PRIMERO el diálogo del recibo digital ────────────────────
                # Sale justo AQUÍ, entre Continue y el resumen — no después de
                # «Sí, Enviar», como supuse la primera vez. Al no ser ninguno
                # de los tres estados que este sondeo conocía, agotaba los
                # 12 s y devolvía "" ocho veces: más de minuto y medio de
                # reintentos contra un modal que solo había que cerrar.
                #
                # Y al cerrarlo se DEVUELVE el control: tras «NO, Print» la app
                # vuelve al formulario y hay que pulsar Continue OTRA VEZ. Si
                # nos quedáramos aquí esperando el resumen, esperaríamos 12 s
                # por algo que no puede llegar sin ese segundo clic.
                if atendidos < 3 and await _MOD.descartar_recibo_digital(
                        flow, logger):
                    atendidos += 1
                    return "recibo_digital"
                if await _mensaje_compliance_visible(flow):
                    return "mensaje"
                try:
                    if await send_btn.first.is_visible():
                        return "resumen"
                except Exception:
                    pass
                # ¿Se completó ya el envío sin pasar por el resumen? Puede
                # ocurrir si la app decide mandar la transacción al cerrar el
                # diálogo del recibo. No lo doy por supuesto en ninguno de los
                # dos sentidos: si el modal de éxito está en pantalla, el envío
                # está hecho y buscar el resumen sería esperar algo que ya pasó.
                try:
                    if await flow.page.get_by_test_id(
                            _SUCCESS_DECLINE_TESTID).first.is_visible():
                        return "enviado"
                except Exception:
                    pass
                # REGLA DEL PROYECTO: si el flujo PIDE Información Adicional, se
                # llena; si no la pide, se continúa. Sin esto, Continue no avanza
                # (el form queda inválido) y el loop reintentaba en vano.
                try:
                    if await _IA._requiere_info(flow, timeout=800):
                        return "info_adicional"
                except Exception:
                    pass
                await flow.page.wait_for_timeout(paso)
                t += paso
            return ""

        resumen = False
        ya_enviado = False       # el envío se completó sin pasar por el resumen
        # 12 y no 8: ahora hay vueltas que NO son reintentos fallidos — atender
        # el diálogo del recibo consume una, y llenar la Información Adicional
        # otra. Ampliar el margen es barato (esas vueltas duran milisegundos);
        # quedarse corto costaría el envío entero.
        for intento in range(1, 13):
            # ORDEN: primero se quita el diálogo, después se esperan overlays.
            # El del recibo digital ES un overlay bloqueante, así que esperar a
            # que «se vaya solo» agotaba los 3 s de timeout en cada intento —
            # 24 s regalados en el peor caso, además de los reintentos.
            await _MOD.descartar_recibo_digital(flow, logger)
            await flow.wait_for_no_blocking_overlays()
            try:
                await flow.click_continue()
            except Exception:
                pass

            estado = await _esperar_mensaje_o_resumen(12_000)
            if estado == "resumen":
                resumen = True
                break
            if estado == "recibo_digital":
                # Ya se pulsó «NO, Print»; la app quedó de vuelta en el
                # formulario esperando Continue. Se vuelve al principio del
                # bucle SIN esperar nada más.
                if evi is not None and intento == 1:
                    await evi.shot("recibo_digital_no_print")
                if logger:
                    logger.info("Recibo digital atendido (intento %d) → "
                                "Continue de nuevo.", intento)
                continue
            if estado == "enviado":
                # Ya está enviada: el modal de éxito está en pantalla. Volver a
                # pulsar Continue o buscar el resumen sería trabajar contra una
                # transacción que ya ocurrió.
                resumen, ya_enviado = True, True
                if logger:
                    logger.info("El envío se completó sin pasar por el resumen "
                                "(intento %d) — sigo al cierre del modal de "
                                "éxito.", intento)
                break
            if estado == "mensaje":
                if evi is not None and intento == 1:
                    await evi.shot("mensaje_info_adicional")
                if logger:
                    logger.info("Mensaje de compliance/OFAC (intento %d) → Back to Transfer.",
                                intento)
                await _click_back_to_transfer(flow, logger)
                continue
            if estado == "info_adicional":
                # El flujo EXIGE Información Adicional → se llena y se acepta;
                # luego se reintenta Continue. Si no se pudiera llenar, se sigue
                # intentando en la próxima vuelta (no se aborta el envío).
                if logger:
                    logger.info("Información Adicional REQUERIDA (intento %d) → llenando…",
                                intento)
                if evi is not None and intento == 1:
                    await evi.shot("info_adicional_requerida")
                try:
                    await _IA.llenar_si_requerida(
                        flow, pais=_IA_PAIS, tipo_id=_IA_TIPO_ID, num_id=_IA_NUM_ID,
                        exp=_IA_EXP, dob=_IA_DOB, tipo=tipo_envio, timeout=3_000)
                except Exception as e:
                    if logger:
                        logger.warning("Info Adicional: no se pudo llenar (%s).", str(e)[:90])
                continue
            # Nada apareció en la ventana: reintentar Continue en la próxima vuelta.
            if logger:
                logger.info("Sin mensaje ni resumen (intento %d) — reintento Continue.", intento)
            # Si el formulario tiene un campo marcado como obligatorio, insistir
            # es tiempo perdido: Continue nunca va a avanzar. Se corta y se dice
            # QUÉ falta, en vez de scrollear ocho veces contra el mismo error.
            faltantes = await campos_requeridos_visibles(flow)
            if faltantes:
                if logger:
                    logger.error("El formulario tiene campos obligatorios sin "
                                 "llenar: %s — Continue no puede avanzar.",
                                 ", ".join(faltantes))
                return False

        if not resumen:
            if logger:
                logger.warning("No se abrió el resumen de envío (Continue no avanzó).")
            return False

        if evi is not None:
            await evi.shot("envio_continue")

        if not ya_enviado:
            await flow.click_yes_send()

        # ── Recibo digital, segunda oportunidad ─────────────────────────────
        # El diálogo se atiende sobre todo tras Continue (ver el sondeo de
        # arriba, que es donde de verdad aparece). Se vuelve a mirar aquí por
        # si en algún flujo saliera después de «Sí, Enviar»: preguntar cuesta
        # milisegundos y no preguntar costó minuto y medio.
        #
        # La espera es CORTA (2 s, y cero si el envío ya está hecho): sondear
        # 12 s «por si acaso» aquí sería reintroducir la misma espera inútil que
        # acabamos de quitar, solo que en otro sitio.
        #
        # Se pulsa «NO, Print» a propósito: «YES, Send» envía el recibo por
        # SMS/correo y NO invoca al Hardware Agent — el caso pasaría sin haber
        # probado el fix.
        if await _MOD.descartar_recibo_digital(
                flow, logger, timeout_ms=0 if ya_enviado else 2_000):
            if evi is not None:
                await evi.shot("recibo_digital_no_print")

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
        # ⚠️ CORRECCIÓN IMPORTANTE (KRA-1527): este modal NO pregunta si se
        # quiere imprimir. Dice «Transaction Successful! Please give the receipt
        # to the customer» y pregunta **«Do you want to make another
        # transaction?»** — o sea que su botón afirmativo abre OTRO envío, no
        # imprime nada.
        #
        # Pulsarlo (lo que hacía `imprimir_recibo=True`) tenía dos efectos, los
        # dos malos: dejaba la app arrancando una transacción nueva, y no
        # generaba ninguna impresión. La impresión del recibo es AUTOMÁTICA al
        # completarse el envío — siempre que haya una impresora seleccionada en
        # Configuración > Dispositivos (ver `flujos/impresora.py`).
        #
        # Así que aquí SIEMPRE se cierra con NO, igual que el sanity. Lo que
        # distingue a la etiqueta no es este clic: es que no se neutraliza
        # `window.print` y que la impresora está configurada.
        await cerrar_modal_exito(flow, logger=logger)
        await flow.wait_for_no_blocking_overlays()
        if logger:
            logger.info("✅ Transacción COMPLETADA (enviada).")
        return True
    except Exception as e:
        if logger:
            logger.warning(f"No se pudo completar el envío: {e}")
        return False
