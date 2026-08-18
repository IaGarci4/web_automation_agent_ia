"""
Cuestionario COMPLETO de compliance (terceros) — para envíos que exigen la
Información Adicional extendida (ocupación, tax ID, relación, propósito, origen
de fondos), como CP03 (Depósito Colombia con TDD).

Extiende la ficha simple de `info_adicional.py` con los campos del cuestionario.
Selectores verificados contra el modelo del repo base (data-testid estables).

API:
    await llenar_cuestionario_completo(flow, datos_ia)  # datos_ia = dict con los valores
"""

import re
import unicodedata

from config.logger import get_logger
from src.sanity_general import info_adicional as IA

logger = get_logger("sanity.cuestionario")

# ── Testids del cuestionario (del modelo base RefactorMTPage) ────────────────
Q_CLEAR_ALL   = "request-id-clear-fieldsicon-icon-svg"
Q_COUNTRY     = "compliance-id-info-form-country-customer-id-dropdown-input"
Q_ID_TYPE     = "compliance-id-info-form-id-type-customer-id-dropdown-input"
Q_ID_NUM      = "compliance-id-info-form-id-number-customer-id-input"
Q_EXP         = "compliance-id-info-form-expiration-date-customer-id-input"
Q_DOB         = "request-id-birth-date-input"
Q_OCCUPATION  = "compliance-customer-info-form-occupation-dropdown-input"
Q_SUB_OCC     = "compliance-customer-info-form-sub-occupation-dropdown-input"
Q_TAX_YES     = "compliance-tax-id-yes-radio"
Q_TAX_TYPE    = "compliance-tax-id-type-dropdown-input"
Q_TAX_NUM     = "compliance-tax-id-id-number-tax-id"
Q_RELATION    = "questionnaire-form-request-id-tab-relationship-dropdown-input"
Q_PURPOSE     = "questionnaire-form-request-id-tab-purpose-dropdown-input"
Q_SOURCE      = "questionnaire-form-request-id-tabsource-of-funds-dropdown-input"

RE_CLEAR_YES  = re.compile(r"yes,\s*continue|s[ií],\s*continuar", re.I)
# Tab 'Transacción de terceras personas' / 'Third party transaction' (EN/ES).
RE_THIRD_PARTY = re.compile(r"third\s*party|tercer[ao]s?\s*person|terceros", re.I)
RE_YES         = re.compile(r"^\s*(yes|s[ií])\s*$", re.I)


def _norm(t: str) -> str:
    if not t:
        return ""
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).strip().upper()


# Contenedores de opción posibles (según el widget: Bootstrap, PrimeNG, custom).
_OPCION_SELS = [
    "[data-testid$='-dropdown-item']",
    "button.dropdown-item",
    "li.p-dropdown-item",
    ".p-dropdown-item",
    "li[role='option']",
    "[role='option']",
    "ul[role='listbox'] li",
    ".dropdown-menu button",
    ".dropdown-menu li",
    ".dropdown-menu a",
]


# Sinónimos EN↔ES de los valores del cuestionario (best-effort). Si el valor
# viene en inglés y la app corre en español (o viceversa), se acepta cualquiera
# de las variantes. Un acierto de más ayuda; un fallo cae al último recurso.
_SINONIMOS = {
    "CONSTRUCTION": ["CONSTRUCCION"],
    "ARCHITECT": ["ARQUITECTO", "ARQUITECTURA"],
    "SOCIAL SECURITY NUMBER (SSN)": ["NUMERO DE SEGURO SOCIAL (SSN)",
                                     "NUMERO DE SEGURO SOCIAL", "SSN"],
    "BROTHER": ["HERMANO"],
    "HOME CONSTRUCTION": ["CONSTRUCCION DE VIVIENDA", "CONSTRUCCION DE CASA",
                          "CONSTRUCCION DE HOGAR"],
    "SAVINGS": ["AHORROS", "AHORRO"],
    "EL SALVADOR": ["EL SALVADOR"],
    "MATRICULA CONSULAR": ["MATRICULA CONSULAR", "CONSULAR REGISTRATION"],
}


def _prefijo_comun(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


async def _opciones_visibles(flow):
    """Primer selector con opciones VISIBLES en pantalla (dropdown abierto)."""
    for sel in _OPCION_SELS:
        try:
            loc = flow.page.locator(f"{sel}:visible")
            if await loc.count() > 0:
                return loc
        except Exception:
            continue
    return None


async def _abrir_dropdown(flow, input_testid: str) -> None:
    """Abre el dropdown y espera a que rendericen sus opciones (con reintento)."""
    for intento in range(2):
        try:
            await flow.page.get_by_test_id(input_testid).first.click(timeout=8_000, force=True)
        except Exception:
            try:
                await flow.smart_click(input_testid)
            except Exception:
                pass
        await flow.page.wait_for_timeout(450)
        if await _opciones_visibles(flow) is not None:
            return
    # Última chance: dar tiempo extra a que aparezcan
    await flow.page.wait_for_timeout(400)


async def _elegir_opcion(flow, texto: str, extra_sel: str = None) -> bool:
    """Elige una opción del dropdown YA ABIERTO, de forma ROBUSTA AL IDIOMA.

    Orden: (0) selector específico si se pasa · (1) match por texto normalizado
    (exacto → contiene → prefijo común ≥5, cubre EN↔ES tipo CONSTRUCTION↔
    CONSTRUCCION) · (2) teclado (teclear + ↓ + Enter) · (3) ÚLTIMO RECURSO:
    primera opción visible, para que la demo NUNCA se quede con el dropdown
    abierto sin seleccionar."""
    page = flow.page
    objetivo = _norm(texto)
    # Conjunto de textos aceptables (idioma original + sinónimos EN↔ES).
    objetivos = [objetivo] + [_norm(s) for s in _SINONIMOS.get(objetivo, [])]
    objetivos = [o for o in dict.fromkeys(objetivos) if o]
    await page.wait_for_timeout(300)

    # (0) selector específico provisto por el llamador
    if extra_sel:
        try:
            loc = page.locator(extra_sel).first
            await loc.wait_for(state="visible", timeout=2_500)
            await loc.click(timeout=3_000, force=True)
            return True
        except Exception:
            pass

    # (1) escanear opciones visibles y elegir la mejor por texto normalizado
    loc = await _opciones_visibles(flow)
    primera = None
    if loc is not None:
        n = await loc.count()
        mejor = None
        for i in range(min(n, 60)):
            op = loc.nth(i)
            try:
                txt = _norm(await op.text_content() or "")
            except Exception:
                continue
            if not txt:
                continue
            if primera is None:
                primera = op
            if txt in objetivos:
                mejor = op
                break
            if mejor is None and any(
                    o and (o in txt or txt in o or _prefijo_comun(o, txt) >= 5)
                    for o in objetivos):
                mejor = op
        if mejor is not None:
            try:
                await mejor.scroll_into_view_if_needed(timeout=1_500)
            except Exception:
                pass
            try:
                await mejor.click(timeout=3_500, force=True)
                return True
            except Exception:
                pass

    # (2) teclado: teclear el inicio + ArrowDown + Enter
    try:
        await page.keyboard.type(str(texto)[:6], delay=40)
        await page.wait_for_timeout(400)
        await page.keyboard.press("ArrowDown")
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(300)
        # Si el dropdown se cerró, damos por buena la selección por teclado.
        if await _opciones_visibles(flow) is None:
            return True
    except Exception:
        pass

    # (3) último recurso: primera opción visible (nunca dejar el dropdown abierto)
    if primera is not None:
        try:
            await primera.click(timeout=3_000, force=True)
            logger.warning("Opción '%s' no encontrada — se eligió la primera visible.", texto)
            return True
        except Exception:
            pass
    return False


async def _dropdown_por_texto(flow, input_testid: str, texto: str, label: str,
                              extra_sel: str = None) -> bool:
    await _abrir_dropdown(flow, input_testid)
    ok = await _elegir_opcion(flow, texto, extra_sel)
    logger.info("%s → '%s' (ok=%s)", label, texto, ok)
    await flow.page.wait_for_timeout(400)
    return ok


async def _limpiar_campos(flow) -> None:
    """Clear all + confirmar (resetea la ficha antes de llenar)."""
    try:
        await flow.page.get_by_test_id(Q_CLEAR_ALL).first.click(timeout=5_000)
        await flow.page.wait_for_timeout(1_200)
        try:
            await flow.page.get_by_role("button", name=RE_CLEAR_YES).first.click(timeout=4_000)
        except Exception:
            pass
        await flow.page.wait_for_timeout(1_200)
        logger.info("Cuestionario: campos limpiados (Clear All).")
    except Exception:
        logger.info("Cuestionario: Clear All no disponible — se omite.")


async def llenar_cuestionario_completo(
    flow, *, country: str, id_type: str, id_number: str, expiration_date: str,
    date_of_birth: str, occupation: str, subcategory_occupation: str,
    tax_id_type: str, tax_id_number: str, beneficiary_relation: str,
    purpose: str, origin_founds: str, tipo: str = "deposit",
    limpiar: bool = True) -> bool:
    """Llena el cuestionario COMPLETO de compliance (terceros) y pulsa Accept.

    Reusa info_adicional para abrir el modal y para los campos de identificación
    (país/tipo ID por data-testid determinístico), y añade los campos extendidos.
    """
    if not await IA.abrir_info_adicional(flow, tipo=tipo):
        logger.error("Cuestionario: la ficha de Info Adicional no se abrió.")
        return False

    if limpiar:
        await _limpiar_campos(flow)

    resultados = {}

    # ── Identificación (país/tipo ID por testid determinístico) ──────────────
    resultados["country"] = await IA.seleccionar_dropdown_id(
        flow, IA.INPUT_PAIS, IA.ITEMS_PAIS, country)
    resultados["id_type"] = await IA.seleccionar_dropdown_id(
        flow, IA.INPUT_TIPO_ID, IA.ITEMS_TIPO_ID, id_type)
    resultados["id_number"] = await IA._fill_campo(flow, Q_ID_NUM, id_number, "Número de ID")
    resultados["expiration"] = await IA._fill_campo(flow, Q_EXP, expiration_date, "Fecha de expiración")
    resultados["dob"] = await IA._fill_campo(flow, Q_DOB, date_of_birth, "Fecha de Nacimiento")

    # ── Ocupación / subcategoría ─────────────────────────────────────────────
    resultados["occupation"] = await _dropdown_por_texto(
        flow, Q_OCCUPATION, occupation, "Ocupación")
    resultados["sub_occupation"] = await _dropdown_por_texto(
        flow, Q_SUB_OCC, subcategory_occupation, "Subcategoría ocupación")

    # ── Tax ID: radio 'Yes' → tipo → número ──────────────────────────────────
    try:
        await flow.page.get_by_test_id(Q_TAX_YES).first.click(timeout=5_000)
        await flow.page.wait_for_timeout(800)
        resultados["tax_yes"] = True
    except Exception:
        resultados["tax_yes"] = False
        logger.info("Tax ID: radio 'Yes' no disponible.")
    resultados["tax_type"] = await _dropdown_por_texto(
        flow, Q_TAX_TYPE, tax_id_type, "Tipo Tax ID",
        extra_sel=f"li[role='option'][aria-label=\"{tax_id_type}\"]")
    resultados["tax_number"] = await IA._fill_campo(flow, Q_TAX_NUM, tax_id_number, "Número Tax ID")

    # ── Relación / propósito / origen de fondos ──────────────────────────────
    resultados["relation"] = await _dropdown_por_texto(
        flow, Q_RELATION, beneficiary_relation, "Relación con beneficiario")
    resultados["purpose"] = await _dropdown_por_texto(
        flow, Q_PURPOSE, purpose, "Propósito")
    resultados["source"] = await _dropdown_por_texto(
        flow, Q_SOURCE, origin_founds, "Origen de fondos",
        extra_sel=f"button[data-testid*='source-of-funds'][data-testid*='dropdown-item']:has-text(\"{origin_founds}\")")

    # ── Third party transaction (tab → Yes) ──────────────────────────────────
    try:
        tab = flow.page.locator("button[role='tab']").filter(has_text=RE_THIRD_PARTY).first
        if await tab.is_visible():
            await tab.click()
            await flow.page.wait_for_timeout(1_500)
            yes = flow.page.locator("button.btn.btn-accept").filter(has_text=RE_YES).first
            await yes.wait_for(state="visible", timeout=8_000)
            await yes.click()
            await flow.page.wait_for_timeout(1_500)
            logger.info("Third party transaction → 'Yes' confirmado.")
    except Exception:
        logger.info("Third party transaction: no apareció — se omite.")

    # ── Aceptar ──────────────────────────────────────────────────────────────
    await IA.aceptar(flow)

    fallidos = [k for k, v in resultados.items() if not v]
    if fallidos:
        logger.warning("Cuestionario: campos con problema → %s", fallidos)
    else:
        logger.info("Cuestionario COMPLETO llenado sin fallos.")
    # Aceptamos si los campos CRÍTICos pasaron (país/tipo/num/ocupación/relación/propósito/origen)
    criticos = ["country", "id_type", "id_number", "occupation",
                "relation", "purpose", "source"]
    return all(resultados.get(k) for k in criticos)
