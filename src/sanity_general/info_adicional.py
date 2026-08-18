"""
Capa ESTABLE de "Información Adicional" (customer-id / Request ID).

Reemplaza la lógica frágil del sanity manual (HERMES2-qa `additional_info_tab.py`),
que seleccionaba los dropdowns POR TEXTO escaneando `button.dropdown-item` — lo que
truena cuando Hermes carga lento (las opciones aún no están renderizadas).

Estrategia nueva (verificada contra DOM en vivo, ambiente TEST):
  • Cada campo Y cada OPCIÓN de dropdown tiene un `data-testid` determinístico.
  • Las opciones existen en el DOM aunque el dropdown esté cerrado → se resuelve
    texto→testid UNA vez y se hace click al testid EXACTO. Cero dependencia de
    timing de render, e independiente del idioma (los textos país/tipo de ID son
    iguales en EN/ES).
  • Ancla de "modal cargado": `compliance-customer-id-form-title-h5-heading`.

Mapa completo en docs/sanity_general/CP01_info_adicional_DOM.md

API pública:
  await abrir_info_adicional(flow, tipo="cash")
  await llenar_info_adicional_simple(flow, pais, tipo_id, num_id, exp, dob)
  await aceptar(flow)
"""

import os
import re
import unicodedata

from config.logger import get_logger

logger = get_logger("sanity.info_adicional")

# La llamada al backend que dispara el modal de compliance/ficha a veces TARDA
# mucho (Hermes lento). Espera generosa y configurable para no rendirse antes.
MODAL_TIMEOUT_MS = int(os.getenv("IA_MODAL_TIMEOUT_MS", "120000"))

# ── Anclas / selectores estables (DOM en vivo) ──────────────────────────────
ANCLA_MODAL = "compliance-customer-id-form-title-h5-heading"

# Botón que ABRE la ficha, por tipo de envío
BTN_ABRIR = "transfer-payers-money-info-additional-info-0-{tipo}-additional-info-button-button"

# Inputs de los dropdowns de la ficha
INPUT_PAIS    = "compliance-id-info-form-country-customer-id-dropdown-input"
INPUT_TIPO_ID = "compliance-id-info-form-id-type-customer-id-dropdown-input"

# Prefijos de las OPCIONES (…-{N}-dropdown-item)
ITEMS_PAIS    = "compliance-id-info-form-country-customer-id-"
ITEMS_TIPO_ID = "compliance-id-info-form-id-type-customer-id-"

# Inputs de texto / fecha
INPUT_NUM_ID  = "compliance-id-info-form-id-number-customer-id-input"
INPUT_EXP     = "compliance-id-info-form-expiration-date-customer-id-input"
INPUT_DOB     = "request-id-birth-date-input"

# Botón Aceptar (sin data-testid → por clase + texto EN/ES)
SEL_ACEPTAR   = "button.footer-btn-accept"
RE_ACEPTAR    = re.compile(r"aceptar|accept", re.I)

# Modal intermedio "Compliance information needed" que sale al dar Continue.
# Su botón (class btn-accept, data-bs-dismiss=modal) es el que ABRE la ficha.
# Textos: EN "Add Additional Info" / ES "Añadir/Agregar Información Adicional".
RE_ADD_INFO   = re.compile(r"add(itional)?\s*info|informaci[oó]n adicional", re.I)


def _norm(txt: str) -> str:
    """Normaliza para comparar: sin acentos, mayúsculas, sin dobles espacios."""
    if txt is None:
        return ""
    t = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).strip().upper()


async def esperar_ficha(flow, timeout: int = 20_000) -> bool:
    """Espera a que la ficha de Información Adicional esté cargada (ancla visible)."""
    try:
        await flow.page.get_by_test_id(ANCLA_MODAL).first.wait_for(
            state="visible", timeout=timeout)
        return True
    except Exception:
        # Fallback: el input de país visible también indica ficha cargada.
        try:
            await flow.page.get_by_test_id(INPUT_PAIS).first.wait_for(
                state="visible", timeout=4_000)
            return True
        except Exception:
            return False


RE_COMPLIANCE_TITLE = re.compile(
    r"compliance information needed|informaci[oó]n de cumplimiento", re.I)


async def _click_modal_compliance_needed(flow, timeout: int = 10_000) -> bool:
    """Pulsa 'Add Additional Info' en el modal 'Compliance information needed'
    que aparece al dar Continue (es el que ABRE la ficha).

    OJO: el botón 'Additional Info' del PROPIO formulario también contiene ese
    texto pero está OCULTO detrás del modal — por eso NO se usa get_by_role/text
    con .first (enganchaba el equivocado). El botón del modal es específico:
    `button.btn-accept[data-bs-dismiss='modal']`."""
    # 1) Confirmar que el modal está en pantalla (por su título EN/ES)
    try:
        await flow.page.get_by_text(RE_COMPLIANCE_TITLE).first.wait_for(
            state="visible", timeout=timeout)
    except Exception:
        logger.info("Modal 'Compliance information needed' no detectado (por título).")

    # 2) Botón del modal: clickea el PRIMERO VISIBLE de entre los candidatos.
    return await _click_boton_add_info_visible(flow)


async def _click_boton_add_info_visible(flow) -> bool:
    """Clickea 'Add Additional Info' — el PRIMER botón VISIBLE de entre todos los
    candidatos. Hay VARIOS btn-accept en el DOM (uno por pestaña Transfer 1/2/3);
    `.first` solía agarrar uno OCULTO → por eso antes 'no encontraba' el botón.
    Iterar por visibilidad lo resuelve. Selector-based (independiente del idioma),
    con respaldo por texto EN/ES."""
    selectores = [
        "button.btn-accept[data-bs-dismiss='modal']",
        ".modal.show button.btn-accept",
        "div[role='dialog'] button.btn-accept",
    ]
    for sel in selectores:
        loc = flow.page.locator(sel)
        try:
            n = await loc.count()
        except Exception:
            n = 0
        for i in range(n):
            b = loc.nth(i)
            try:
                if await b.is_visible():
                    await b.click(timeout=4_000)
                    logger.info("Modal compliance → 'Add Additional Info' pulsado (%s #%d).",
                                sel, i)
                    return True
            except Exception:
                continue
    # Respaldo por TEXTO (EN/ES). El botón 'Additional Info' del formulario también
    # abre la ficha, así que clickear el primer visible por texto es válido.
    try:
        loc = flow.page.get_by_role("button", name=RE_ADD_INFO)
        n = await loc.count()
        for i in range(n):
            b = loc.nth(i)
            try:
                if await b.is_visible():
                    await b.click(timeout=4_000)
                    logger.info("'Add Additional Info' por texto pulsado (#%d).", i)
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


async def _ficha_visible(flow) -> bool:
    """Chequeo RÁPIDO (sin esperas) de si la ficha llenable ya está en pantalla."""
    try:
        return await flow.page.get_by_test_id(ANCLA_MODAL).first.is_visible()
    except Exception:
        return False


async def abrir_info_adicional(flow, tipo: str = "cash", timeout: int = None) -> bool:
    """Abre la ficha de Información Adicional. Idempotente y PACIENTE (SIN re-Continue).

    La llamada que dispara el modal 'Compliance information needed' (con el botón
    'Add Additional Info') a veces TARDA MUCHO en Hermes. Aquí se ESPERA con
    paciencia (poll cada 2s hasta MODAL_TIMEOUT_MS) y, en cuanto el botón está
    VISIBLE, se pulsa. NO se re-da Continue (no ayuda y puede estorbar). Fallback:
    botón 'Additional Info' del sub-formulario (data-testid)."""
    if timeout is None:
        timeout = MODAL_TIMEOUT_MS
    if await esperar_ficha(flow, timeout=2_000):
        logger.info("Ficha de Info Adicional ya visible — no se re-abre.")
        return True

    paso = 2_000
    transcurrido = 0
    while transcurrido < timeout:
        if await _ficha_visible(flow):
            logger.info("Ficha de Info Adicional visible.")
            return True
        if await _click_boton_add_info_visible(flow):
            if await esperar_ficha(flow, timeout=15_000):
                logger.info("Ficha cargada tras 'Add Additional Info'.")
                return True
        await flow.page.wait_for_timeout(paso)
        transcurrido += paso
        if transcurrido % 10_000 == 0:
            logger.info("Esperando modal de compliance… (%ds de %ds)",
                        transcurrido // 1000, timeout // 1000)

    # Fallback final: botón 'Additional Info' del sub-formulario (data-testid)
    testid = BTN_ABRIR.format(tipo=tipo)
    try:
        btn = flow.page.get_by_test_id(testid).first
        await btn.wait_for(state="visible", timeout=6_000)
        await btn.click(timeout=6_000)
        logger.info("Abriendo Info Adicional vía botón del sub-formulario (%s).", tipo)
    except Exception as e:
        logger.warning("Botón 'Additional Info' del sub-formulario no disponible (%s): %s",
                       tipo, str(e)[:80])

    ok = await esperar_ficha(flow, timeout=20_000)
    logger.info("Ficha de Info Adicional %s.", "cargada" if ok else "NO cargada")
    return ok


async def seleccionar_dropdown_id(flow, input_testid: str, items_prefix: str,
                                  texto: str, timeout: int = 12_000) -> bool:
    """Selecciona una opción de un dropdown de la ficha por data-testid EXACTO.

    1. Click en el input (abre el dropdown).
    2. Resuelve texto→testid entre [data-testid^=items_prefix][data-testid$=-dropdown-item]
       comparando el texto normalizado (sin acentos, mayúsculas).
    3. Click al testid exacto de la opción.
    4. Verifica que el input tomó el valor; si no, reintenta 1 vez.
    """
    objetivo = _norm(texto)

    async def _intento() -> bool:
        # Abrir el dropdown
        try:
            await flow.page.get_by_test_id(input_testid).first.click(timeout=timeout)
        except Exception:
            try:
                await flow.smart_click(input_testid)
            except Exception:
                pass
        await flow.page.wait_for_timeout(250)

        # Resolver texto → testid de la opción (los items ya están en el DOM)
        sel = f"[data-testid^='{items_prefix}'][data-testid$='-dropdown-item']"
        opciones = flow.page.locator(sel)
        try:
            await opciones.first.wait_for(state="attached", timeout=6_000)
        except Exception:
            pass
        n = await opciones.count()
        target_tid = None
        exacto = None
        contiene = None
        for i in range(n):
            op = opciones.nth(i)
            try:
                t = _norm(await op.inner_text())
            except Exception:
                continue
            if not t:
                continue
            if t == objetivo:
                exacto = await op.get_attribute("data-testid")
                break
            if contiene is None and (objetivo in t or t in objetivo):
                contiene = await op.get_attribute("data-testid")
        target_tid = exacto or contiene
        if not target_tid:
            logger.warning("Dropdown %s: no encontré opción '%s' (de %d).",
                           items_prefix, texto, n)
            return False

        # Click a la opción por su testid exacto
        try:
            await flow.page.get_by_test_id(target_tid).first.click(timeout=6_000)
        except Exception:
            try:
                await flow.smart_click(target_tid)
            except Exception:
                return False
        await flow.page.wait_for_timeout(300)

        # Verificar el valor del input
        try:
            val = await flow.page.get_by_test_id(input_testid).first.input_value()
            ok = _norm(val) == objetivo or objetivo in _norm(val)
            logger.info("Dropdown %s → '%s' (input='%s', ok=%s)",
                        items_prefix, texto, val, ok)
            return ok
        except Exception:
            return True  # no pudimos leer el valor, asumimos aplicado

    if await _intento():
        return True
    logger.info("Dropdown %s: reintentando selección de '%s'.", items_prefix, texto)
    return await _intento()


async def _fill_campo(flow, testid: str, valor: str, label: str) -> bool:
    """Llena un input de texto/fecha por testid, disparando input+change (React)."""
    try:
        el = flow.page.get_by_test_id(testid).first
        await el.wait_for(state="visible", timeout=8_000)
        await el.click()
        try:
            await el.fill("")
        except Exception:
            pass
        await el.fill(valor)
        try:
            await el.evaluate(
                "(e)=>{e.dispatchEvent(new Event('input',{bubbles:true}));"
                "e.dispatchEvent(new Event('change',{bubbles:true}));e.blur();}")
        except Exception:
            pass
        logger.info("%s = '%s'", label, valor)
        return True
    except Exception as e:
        logger.warning("%s: no se pudo llenar (%s)", label, str(e)[:80])
        return False


async def llenar_info_adicional_simple(flow, pais: str, tipo_id: str, num_id: str,
                                       exp: str, dob: str, tipo: str = "cash") -> bool:
    """Llena la ficha simple de Info Adicional (Identificación del Cliente) y
    verifica cada paso. NO pulsa Aceptar (eso lo hace `aceptar`).

    pais    : país de emisión (ej. 'EL SALVADOR')
    tipo_id : tipo de identificación (ej. 'MATRICULA CONSULAR')
    num_id  : número de ID
    exp     : fecha de expiración mm/dd/yyyy
    dob     : fecha de nacimiento mm/dd/yyyy
    """
    if not await abrir_info_adicional(flow, tipo=tipo):
        logger.error("Info Adicional no se abrió — abortando llenado.")
        return False

    ok_pais = await seleccionar_dropdown_id(flow, INPUT_PAIS, ITEMS_PAIS, pais)
    ok_tipo = await seleccionar_dropdown_id(flow, INPUT_TIPO_ID, ITEMS_TIPO_ID, tipo_id)
    ok_num  = await _fill_campo(flow, INPUT_NUM_ID, num_id, "Número de ID")
    ok_exp  = await _fill_campo(flow, INPUT_EXP, exp, "Fecha de expiración")
    ok_dob  = await _fill_campo(flow, INPUT_DOB, dob, "Fecha de Nacimiento")

    todo = ok_pais and ok_tipo and ok_num and ok_exp and ok_dob
    logger.info("Info Adicional llenada (pais=%s tipo=%s num=%s exp=%s dob=%s) → ok=%s",
                ok_pais, ok_tipo, ok_num, ok_exp, ok_dob, todo)
    return todo


async def _requiere_info(flow, timeout: int = 5_000) -> bool:
    """True si tras dar Continue aparece el modal de compliance o la ficha —
    o sea, si ESTE flujo/pagador exige Información Adicional. Detección rápida."""
    try:
        await flow.page.get_by_text(RE_COMPLIANCE_TITLE).first.wait_for(
            state="visible", timeout=timeout)
        return True
    except Exception:
        pass
    for probe in (
        lambda: flow.page.get_by_test_id(ANCLA_MODAL).first,
        lambda: flow.page.locator("button.btn-accept[data-bs-dismiss='modal']").first,
    ):
        try:
            if await probe().is_visible():
                return True
        except Exception:
            continue
    return False


async def llenar_si_requerida(flow, pais: str, tipo_id: str, num_id: str,
                              exp: str, dob: str, tipo: str = "cash",
                              timeout: int = 5_000) -> bool:
    """Llena la Info Adicional SOLO si el flujo la exige (algunos pagadores no
    la piden). Idempotente y seguro para CPs donde la ficha puede o no aparecer
    (ej. CP02 OFAC con WALMART). Devuelve:
      • True  si no era requerida, o si se llenó y aceptó bien.
      • False si apareció pero no se pudo llenar.
    """
    if not await _requiere_info(flow, timeout=timeout):
        logger.info("Info Adicional NO requerida en este flujo — se omite.")
        return True
    ok = await llenar_info_adicional_simple(
        flow, pais=pais, tipo_id=tipo_id, num_id=num_id, exp=exp, dob=dob, tipo=tipo)
    if ok:
        await aceptar(flow)
    return ok


async def aceptar(flow, timeout: int = 12_000) -> bool:
    """Pulsa Aceptar en la ficha y espera a que la ficha se cierre."""
    clicked = False
    try:
        btn = flow.page.locator(SEL_ACEPTAR).first
        await btn.wait_for(state="visible", timeout=timeout)
        await btn.click()
        clicked = True
    except Exception:
        # Fallback por rol + texto EN/ES
        try:
            await flow.page.get_by_role("button", name=RE_ACEPTAR).first.click(timeout=6_000)
            clicked = True
        except Exception as e:
            logger.warning("No se pudo pulsar Aceptar: %s", str(e)[:80])

    if clicked:
        try:
            await flow.page.get_by_test_id(ANCLA_MODAL).first.wait_for(
                state="hidden", timeout=timeout)
        except Exception:
            pass
        logger.info("Info Adicional: Aceptar pulsado.")
    return clicked
