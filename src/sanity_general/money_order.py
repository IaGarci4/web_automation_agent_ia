"""
Money Orders (Services > Money Order) — CP22 y KRA-1527.

Port del `MoneyOrderPage` del repo QA viejo a funciones sobre una `page`, al
estilo del resto de módulos de `sanity_general`.

Flujo completo:
  Configuración → registrar PIN de la impresora MO y seleccionarla
  Services > Money Order → datos del comprador → alta del MO
  Compliance pide Additional Info → se llena (con FOTO del ID)
  Imprimir el MO  ← aquí es donde habla el Hardware Agent (impresora «MO Printer»)
  Reportes > Transacciones (tipo MONEY ORDER) → anular los MO creados

Por qué el módulo vive aquí y no dentro del test: la etiqueta **KRA-1527** lo
reutiliza tal cual para auditar la comunicación con el agente durante la
impresión. Un solo flujo, dos usos — sanity y seguridad.

Notas de la pantalla (lo frágil y cómo se maneja):
  • La FOTO del ID es obligatoria y usa la webcam. El conftest ya expone una
    cámara simulada, así que funciona sin hardware.
  • «Take Picture» y «Save Picture» comparten data-testid: son el mismo botón
    que cambia de texto. Se pulsa dos veces con espera en medio.
  • El monto se divide solo: $3,000 genera 3 money orders de $1,000.
  • La impresora MO por defecto es un simulador (`S SATO WS412-DT_sim`).
"""

import os
import random
import re

from config.logger import get_logger

logger = get_logger("sanity.money_order")

TIMEOUT = 30_000
IMPRESORA_MO = os.getenv("MO_PRINTER", "S SATO WS412-DT_sim")

# ── Configuración de la impresora ───────────────────────────────────────────
NAV_CONFIG = "settings-navbar-item"
CONFIG_IMPRESORA_MO = "settings-2-navbar-dropdown-item"   # selección de impresora
CONFIG_REGISTRO_MO = "settings-3-navbar-dropdown-item"    # registro de PIN
MODAL_DENY = "modal-confirmation-deny-button"             # 'YES, Leave'
BTN_GUARDAR_REGISTRO = "registration-inventory-form-save-button-button"

# ── Navegación al módulo ────────────────────────────────────────────────────
NAV_SERVICIOS = "services-navbar-item"
MENU_MONEY_ORDER = "services-2-navbar-dropdown-item"

# ── Formulario del comprador ────────────────────────────────────────────────
MO_SERIE = "customer-money-order-form-mo-serial-no"
MO_TELEFONO = "customer-money-order-form-cellphone-cellphone-input"
MO_CHECK_NOMBRE = "customer-money-order-form-confirm-print-purchaser-name-checkbox"
MO_NOMBRE = "customer-money-order-form-name-input"
MO_APELLIDO1 = "customer-money-order-form-first-lastname-input"
MO_APELLIDO2 = "customer-money-order-form-second-lastname-input"
MO_PAY_TO = "customer-money-order-form-payToOrder-input"
MO_MONTO = "customer-money-order-form-amount-amount-input"
MO_BTN_ADD = "customer-money-order-form-button-add-icon-icon-svg"

# ── Additional Info (compliance) ────────────────────────────────────────────
RE_ADD_INFO = re.compile(r"add\s*additional\s*info|informaci[oó]n\s*adicional", re.I)
AI_PAIS = "compliance-id-info-form-country-customer-id-dropdown-input"
AI_TIPO_ID = "compliance-id-info-form-id-type-customer-id-dropdown-input"
AI_NUM_ID = "compliance-id-info-form-id-number-customer-id-input"
AI_EXPIRA = "compliance-id-info-form-expiration-date-customer-id-input"
AI_NACIMIENTO = "request-id-birth-date-input"
AI_OCUPACION = "compliance-customer-info-form-occupation-dropdown-input"
AI_SUB_OCUPACION = "compliance-customer-info-form-sub-occupation-dropdown-input"
AI_TAX_SI = "compliance-tax-id-yes-radio"
AI_TAX_TIPO = "compliance-tax-id-type-dropdown-input"
AI_TAX_NUM = "compliance-tax-id-id-number-tax-id"
AI_DIRECCION = "address-form-address-input"
AI_CP = "address-form-zip-code-input"
AI_RAZON = "request-id-purchase-reason-purchase-reason-input"
AI_BTN_ACEPTAR = "button.footer-btn-accept"
AI_FOTO_CAROUSEL = "compliance-customer-id-form-carousel-element-container-0"
# Icono de cámara de la tarjeta 'Front of ID' — el otro disparador posible.
AI_FOTO1_ICONO = ("compliance-customer-id-form-photo-selector-0-"
                  "photo-id-valid-camera-icon-svg")
AI_FOTO_BOTON = "compliance-customer-id-form-webcam-modal-save"  # Take y Save
AI_FOTO2 = "compliance-customer-id-form-photo-selector-1-photo-id-valid-camera-icon-svg"
AI_FOTO2_REQUERIDA = ("compliance-customer-id-form-photo-selector-1-"
                      "photo-id-valid-camera-error-paragraph-small")

# Valores fijos del formulario (los mismos del sanity original).
AI_FIJOS = {"expira": "07/03/2030", "nacimiento": "10/03/1984", "cp": "66451",
            "ocupacion": "CONSTRUCTION", "sub_ocupacion": "WORKER",
            "tax_tipo": "Social Security Number"}

# ── Impresión ───────────────────────────────────────────────────────────────
BTN_IMPRIMIR_MO = "money-order-summary-button-print-button"
PRINT_NUM_INPUT = "money-order-print-next-mo-number-input"
PRINT_CONFIRMAR = "money-order-print-next-modal-confirm-button-button"
PRINT_ACEPTAR = "money-order-print-modal-confirm-button-button"
# Modales de ERROR de la impresión. El repo viejo los declara pero nunca los
# usa: si salen, allá el caso también se quedaría esperando. Aquí se detectan
# para poder decir QUÉ pasó en vez de un timeout mudo.
PRINT_ERROR_1 = "money-order-error-modal-modal-description-two-h5-heading"
PRINT_ERROR_2 = "money-order-message-modal-description-one-h5-heading"
PRINT_ERROR_OK = "money-order-error-modal-modal-confirm-button-button"
PRINT_REINTENTAR = "money-order-message-modal-try-button-button"

# ── Reportes / anulación ────────────────────────────────────────────────────
NAV_REPORTES = "reports-navbar-item"
REPORTES_TRANSACCIONES = "reports-2-navbar-dropdown-item"
TIPO_TRANSACCION = "p-dropdown#dropdown"
BTN_BUSCAR = "test-id-button"
RE_VOID = re.compile(r"si,?\s*invalidar|yes,?\s*void", re.I)
BTN_VOID_MODAL = "modal-message-cancel-button-button"
RE_YES_LEAVE = re.compile(r"yes.*leave|s[ií].*salir", re.I)


async def _click_loc(loc, timeout: int = TIMEOUT) -> None:
    """Click sobre un locator: primero normal, `force` solo si falla."""
    try:
        await loc.click(timeout=timeout)
    except Exception:
        await loc.click(force=True, timeout=8_000)


async def _click(page, testid: str, desc: str, timeout: int = TIMEOUT) -> bool:
    """Click como lo hace el repo original: **sin `force`**, y force solo como
    último recurso.

    Esto no es un detalle. `force=True` se salta las verificaciones de
    accionabilidad, así que el click 'funciona' sobre un elemento que Angular
    no procesa: el paso se reporta OK y el fallo aparece 15-30 s más tarde,
    esperando el modal que nunca abrió. Nos costó varias vueltas en la cámara
    del ID y en el botón Print."""
    try:
        b = page.get_by_test_id(testid).first
        await b.wait_for(state="visible", timeout=timeout)
        try:
            await b.scroll_into_view_if_needed(timeout=3_000)
        except Exception:
            pass
        try:
            await b.click(timeout=timeout)              # como el original
        except Exception:
            await b.click(force=True, timeout=8_000)    # último recurso
        logger.info("[MO] %s", desc)
        return True
    except Exception as e:
        logger.warning("[MO] No se pudo pulsar %s: %s", desc, str(e)[:90])
        return False


async def _visible(page, selector: str, limite: int = 10):
    """Primer elemento REALMENTE visible del selector, o None.

    Recorre todas las coincidencias en vez de quedarse con `.first`: Hermes deja
    los modales anteriores en el DOM (ocultos) y `.first` caía en uno de esos —
    el aviso se daba por ausente y su overlay seguía bloqueando la pantalla."""
    loc = page.locator(selector)
    try:
        total = min(await loc.count(), limite)
    except Exception:
        return None
    for i in range(total):
        el = loc.nth(i)
        try:
            if await el.is_visible():
                return el
        except Exception:
            continue
    return None


async def _hay_warning(page) -> bool:
    """True si el aviso «¿salir de esta página?» está en pantalla."""
    return await _visible(page, f'[data-testid="{MODAL_DENY}"]') is not None


async def _esperar_warning(page, timeout_ms: int) -> bool:
    """Espera a que el aviso APAREZCA (no a que exista ya). True si salió.

    Esto era el agujero: el aviso tarda un instante en renderizar tras pulsar
    el menú, y una comprobación instantánea lo daba por ausente. Entonces nadie
    lo cerraba, su overlay se quedaba encima y el siguiente clic agotaba su
    timeout completo — de ahí la sensación de 'tarda muchísimo'."""
    espera = 0
    while espera <= timeout_ms:
        if await _hay_warning(page):
            return True
        await page.wait_for_timeout(150)
        espera += 150
    return False


async def _cerrar_warning(page, timeout_ms: int = 4_000, vueltas: int = 3,
                          aparecer_ms: int = 2_000) -> bool:
    """Espera el 'Warning: ¿salir de esta página?', lo cierra y VERIFICA que se fue.

    Verificar no es adorno: mientras el modal siga ahí, sus overlays se comen
    los clics de la pantalla de fondo y el fallo aparece en otro elemento."""
    cerrado = False
    if not await _esperar_warning(page, aparecer_ms):
        return False
    for _ in range(vueltas):
        if not await _hay_warning(page):
            return cerrado
        pulsado = False
        btn = await _visible(page, f'[data-testid="{MODAL_DENY}"]')
        if btn is None:
            btn = await _visible(page, "button.btn-outline-danger")
        try:
            if btn is not None:
                await btn.click(force=True, timeout=3_000)
                pulsado = True
                logger.info("[MO] Aviso de salida cerrado.")
        except Exception:
            pulsado = False
        if not pulsado:
            break
        cerrado = True
        espera = 0
        while espera <= timeout_ms:
            if not await _hay_warning(page):
                await page.wait_for_timeout(400)
                return True
            await page.wait_for_timeout(150)
            espera += 150
    return cerrado


# ── Configuración de la impresora de Money Orders ───────────────────────────

async def _ir_a_config(page, submenu: str, desc: str, intentos: int = 3) -> bool:
    """Configuración → <submenú>, sorteando el aviso «¿salir de esta página?».

    ORDEN CLAVE: el aviso se cierra ANTES de esperar el submenú, no después.
    Estando ya en una pantalla de Configuración con cambios sin guardar, ese
    modal aparece al intentar navegar y su overlay **impide** que el submenú
    sea clickeable — el fallo salía como un timeout de 30 s sobre el submenú,
    apuntando al sitio equivocado."""
    for intento in range(1, intentos + 1):
        await _cerrar_warning(page, timeout_ms=1_500)   # restos de la pantalla previa
        if not await _click(page, NAV_CONFIG, "Menú Configuración", timeout=15_000):
            continue
        await page.wait_for_timeout(600)
        # El aviso puede saltar AL ABRIR el menú: fuera antes de seguir.
        await _cerrar_warning(page, timeout_ms=2_000)
        if await _click(page, submenu, desc, timeout=12_000):
            await _cerrar_warning(page, timeout_ms=2_500)  # y otra vez al navegar
            await page.wait_for_timeout(1_200)
            return True
        logger.info("[MO] %s no respondió (intento %d/%d) — reintento tras "
                    "cerrar avisos.", desc, intento, intentos)
    logger.warning("[MO] No se pudo llegar a %s.", desc)
    return False


async def registrar_impresora(page) -> bool:
    """Configuración → Money Order Settings → guardar el registro (si aplica).

    Es BEST-EFFORT: si el inventario ya está registrado, el botón Guardar no
    aparece y eso no es un error. Antes se esperaban 30 s y se daba por fallado
    todo el prerrequisito; ahora se registra el hecho y se sigue — quien decide
    de verdad es la impresión."""
    logger.info("[MO] Registrando la impresora de Money Orders…")
    if not await _ir_a_config(page, CONFIG_REGISTRO_MO, "Money Order Settings"):
        return False
    ok = await _click(page, BTN_GUARDAR_REGISTRO, "Registro guardado",
                      timeout=12_000)
    if not ok:
        logger.info("[MO] Sin botón de guardar — el registro ya estaba hecho "
                    "o esta pantalla no lo pide. Continúo.")
    await page.wait_for_timeout(1_500)
    # Tras guardar queda un aviso pendiente que bloquearía el siguiente paso.
    await _cerrar_warning(page, timeout_ms=2_000)
    return True


async def _esperar_dispositivos(page, minimo: int = 3, timeout_ms: int = 20_000) -> int:
    """Espera a que la pantalla de Dispositivos termine de pintar sus combos.

    La lista de periféricos se carga en diferido: al llegar solo hay dos combos
    (Printer y Scanner) y el de MO Printer aparece después. Contarlos de
    inmediato hacía elegir el del ESCÁNER — de ahí que las opciones fueran
    'PANINI, CANON' en vez de impresoras."""
    espera = 0
    total = 0
    while espera <= timeout_ms:
        try:
            total = await page.locator("div.p-dropdown").count()
            if total >= minimo:
                logger.info("[MO] Dispositivos listo: %d desplegables.", total)
                await page.wait_for_timeout(600)
                return total
        except Exception:
            pass
        await page.wait_for_timeout(300)
        espera += 300
    logger.warning("[MO] Dispositivos mostró solo %d desplegable(s) en %.0f s "
                   "(se esperaban %d).", total, timeout_ms / 1000, minimo)
    return total


async def _combo_impresora_mo(page):
    """Desplegable «MO Printer» en Configuración > Dispositivos.

    Hay TRES comboboxes casi idénticos (Printer, Scanner, MO Printer) que
    comparten `id="dropdown"`. Se localiza por su ETIQUETA — igual que hace
    `cheques.py` con el escáner — y, si eso falla, por el ÚLTIMO `div.p-dropdown`
    esperando a que sea visible, que es como lo resuelve el repo original."""
    await _esperar_dispositivos(page)
    for etiqueta in ("MO Printer", "Impresora MO", "MO printer",
                     "Money Order Printer", "MO PRINTER"):
        try:
            loc = page.locator(
                f"xpath=//*[normalize-space(text())='{etiqueta}']"
                f"/following::div[contains(@class,'p-dropdown')][1]").first
            if await loc.count():
                await loc.wait_for(state="visible", timeout=8_000)
                logger.info("[MO] Combo de impresora hallado por la etiqueta "
                            "'%s'.", etiqueta)
                return loc
        except Exception:
            continue
    # Respaldo del repo original: el ÚLTIMO p-dropdown, ESPERANDO a que sea
    # visible (no filtrando por visibles, que es lo que fallaba).
    try:
        ultimo = page.locator("div.p-dropdown").last
        await ultimo.wait_for(state="visible", timeout=15_000)
        logger.info("[MO] Combo de impresora: el último p-dropdown (respaldo).")
        return ultimo
    except Exception as e:
        logger.warning("[MO] No apareció el desplegable de la impresora: %s",
                       str(e)[:90])
        return None


async def seleccionar_impresora(page, impresora: str = None) -> bool:
    """Configuración > Dispositivos → elegir la impresora de Money Orders.

    OJO: no se configura en 'Money Order Settings' — esa pantalla lo dice
    explícitamente ('For Money Orders printer settings, go to Devices'). El
    submenú lleva a **Devices**, donde conviven las tres impresoras."""
    impresora = impresora or IMPRESORA_MO
    logger.info("[MO] Seleccionando la impresora '%s' en Dispositivos…", impresora)
    if not await _ir_a_config(page, CONFIG_IMPRESORA_MO, "Dispositivos"):
        return False
    await page.wait_for_timeout(1_500)

    # ¿Ya está elegida? El combobox lleva el nombre en su aria-label.
    try:
        ya = page.locator(f"span[role='combobox'][aria-label='{impresora}']")
        if await ya.count():
            logger.info("[MO] La impresora ya estaba seleccionada.")
            return True
    except Exception:
        pass

    combo = await _combo_impresora_mo(page)
    if combo is None:
        logger.warning("[MO] No encontré el desplegable de la impresora MO en "
                       "Dispositivos.")
        return False
    try:
        # Como el repo original: se pulsa el TRIGGER del p-dropdown, no el
        # contenedor (clickear el contenedor no siempre despliega).
        try:
            await combo.locator(".p-dropdown-trigger").first.click(
                force=True, timeout=8_000)
        except Exception:
            await combo.click(force=True, timeout=8_000)
        await page.wait_for_timeout(900)
        opcion = page.locator("li[role='option'], .p-dropdown-item").filter(
            has_text=impresora).first
        try:
            await opcion.wait_for(state="visible", timeout=10_000)
        except Exception:
            # Nombre distinto en este ambiente: se listan las opciones reales
            # en vez de fallar a ciegas.
            todas = page.locator("li[role='option'], .p-dropdown-item")
            textos = [t.strip() for t in await todas.all_inner_texts()][:10]
            logger.warning("[MO] '%s' no está entre las impresoras. "
                           "Disponibles: %s", impresora,
                           ", ".join(f"'{t}'" for t in textos) or "(ninguna)")
            return False
        await opcion.click(force=True, timeout=8_000)
        await page.wait_for_timeout(800)
        logger.info("[MO] ✓ Impresora '%s' seleccionada.", impresora)
        return True
    except Exception as e:
        logger.warning("[MO] No se pudo elegir la impresora: %s", str(e)[:100])
        return False


async def preparar_impresora(page) -> bool:
    """Prerrequisito para imprimir un MO: registro (opcional) + SELECCIÓN.

    Lo que decide es la selección de la impresora en Dispositivos; el registro
    del inventario es best-effort porque suele venir hecho del ambiente."""
    await registrar_impresora(page)
    return await seleccionar_impresora(page)


# ── Alta del Money Order ────────────────────────────────────────────────────

async def abrir_money_order(page, intentos: int = 3) -> bool:
    """Services > Money Order.

    Se llega DESDE la pantalla de configuración, que tiene cambios sin guardar:
    el aviso «¿salir de esta página?» va a salir sí o sí. Por eso se cierra
    antes de cada clic, no después."""
    logger.info("[MO] Abriendo Services > Money Order…")
    for intento in range(1, intentos + 1):
        await _cerrar_warning(page, timeout_ms=1_500)
        if not await _click(page, NAV_SERVICIOS, "Menú Services", timeout=15_000):
            continue
        await page.wait_for_timeout(600)
        await _cerrar_warning(page, timeout_ms=2_000)
        if await _click(page, MENU_MONEY_ORDER, "Money Order", timeout=12_000):
            await _cerrar_warning(page, timeout_ms=2_500)
            await page.wait_for_timeout(1_500)
            return True
        logger.info("[MO] Money Order no respondió (intento %d/%d).",
                    intento, intentos)
    logger.warning("[MO] No se pudo abrir Services > Money Order.")
    return False


async def llenar_comprador(page, telefono: str, nombre: str,
                           apellido1: str, apellido2: str) -> bool:
    """Datos del comprador + marcar 'imprimir su nombre en el MO'."""
    try:
        await page.get_by_test_id(MO_TELEFONO).first.fill(telefono)
        await page.get_by_test_id(MO_CHECK_NOMBRE).first.check()
        await page.get_by_test_id(MO_NOMBRE).first.fill(nombre)
        await page.get_by_test_id(MO_APELLIDO1).first.fill(apellido1)
        await page.get_by_test_id(MO_APELLIDO2).first.fill(apellido2)
        logger.info("[MO] Comprador: %s %s %s", nombre, apellido1, apellido2)
        return True
    except Exception as e:
        logger.warning("[MO] No se pudo llenar el comprador: %s", str(e)[:100])
        return False


async def agregar_money_order(page, pay_to: str, monto: str = "3000") -> bool:
    """'Pay to the Order of' + monto + Add.

    Ojo: el sistema DIVIDE el monto en varios MO de $1,000. $3,000 → 3 MO."""
    try:
        await page.get_by_test_id(MO_PAY_TO).first.fill(pay_to)
        await page.get_by_test_id(MO_MONTO).first.fill(str(monto))
        await _click_loc(page.get_by_test_id(MO_BTN_ADD).first)
        logger.info("[MO] Money Order agregado: %s por $%s", pay_to, monto)
        await page.wait_for_timeout(4_000)
        return True
    except Exception as e:
        logger.warning("[MO] No se pudo agregar el MO: %s", str(e)[:100])
        return False


async def numero_de_serie(page) -> str:
    """Número de serie del MO en curso (el que se usará al imprimir)."""
    try:
        loc = page.get_by_test_id(MO_SERIE).first
        await loc.wait_for(state="visible", timeout=TIMEOUT)
        serie = ((await loc.text_content()) or "").strip()
        logger.info("[MO] Número de serie: %s", serie)
        return serie
    except Exception as e:
        logger.warning("[MO] No se pudo leer el número de serie: %s", str(e)[:90])
        return ""


# ── Additional Info (compliance) ────────────────────────────────────────────

async def abrir_additional_info(page, timeout_ms: int = TIMEOUT) -> bool:
    """Pulsa 'Add Additional Info' del modal de compliance."""
    try:
        btn = page.locator("button").filter(has_text=RE_ADD_INFO).first
        await btn.wait_for(state="visible", timeout=timeout_ms)
        await _click_loc(btn)
        logger.info("[MO] 'Add Additional Info' pulsado.")
        await page.wait_for_timeout(1_500)
        return True
    except Exception as e:
        logger.warning("[MO] No apareció 'Add Additional Info': %s", str(e)[:90])
        return False


async def _opcion_dropdown(page, testid: str, texto: str = None,
                           prefijo: str = "", desc: str = "") -> bool:
    """Abre un dropdown y elige por texto; si no se indica, una al azar."""
    try:
        await _click_loc(page.get_by_test_id(testid).first)
        await page.wait_for_timeout(800)
    except Exception as e:
        logger.warning("[MO] No se pudo abrir %s: %s", desc or testid, str(e)[:80])
        return False
    candidatos = []
    if prefijo:
        candidatos.append(page.locator(f"button[data-testid*='{prefijo}']"))
    candidatos += [page.locator("button[data-testid*='dropdown-item']"),
                   page.locator("li[role='option']"),
                   page.locator(".p-dropdown-panel li, .p-overlay-open li")]
    for loc in candidatos:
        try:
            opciones = loc.filter(has_text=texto) if texto else loc
            total = await opciones.count()
            if not total:
                continue
            idx = 0 if texto else random.randint(0, total - 1)
            await _click_loc(opciones.nth(idx), timeout=8_000)
            logger.info("[MO] %s: '%s'", desc or testid,
                        texto or f"opción {idx + 1}/{total}")
            await page.wait_for_timeout(600)
            return True
        except Exception:
            continue
    logger.warning("[MO] %s: sin opciones seleccionables.", desc or testid)
    return False


async def _fecha(page, testid: str, valor: str, desc: str) -> None:
    """Escribe una fecha cerrando antes el datepicker (si se abrió)."""
    try:
        campo = page.get_by_test_id(testid).first
        await campo.click()
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(300)
        await campo.press_sequentially(valor, delay=50)
        logger.info("[MO] %s: %s", desc, valor)
    except Exception as e:
        logger.warning("[MO] No se pudo escribir %s: %s", desc, str(e)[:80])


async def _abrir_camara_id(page, timeout_ms: int = 12_000) -> bool:
    """Abre el modal de la webcam del ID y CONFIRMA que abrió.

    Dos aprendizajes al comparar con el repo original:
      • El clic va **sin `force`**. Con force el clic 'funciona' sobre el
        contenedor sin activar nada, el modal nunca abre, y el fallo aparece
        25 s después esperando un botón que no existe — apuntando al sitio
        equivocado.
      • El disparador puede ser el ICONO de la cámara de la tarjeta
        'Front of ID' o el contenedor del carrusel. Se prueban ambos y se
        VERIFICA que el modal apareció antes de seguir."""
    disparadores = (
        (AI_FOTO1_ICONO, "icono de cámara 'Front of ID'"),
        (AI_FOTO_CAROUSEL, "contenedor del carrusel"),
    )
    for testid, desc in disparadores:
        try:
            trigger = page.get_by_test_id(testid).first
            if not await trigger.count():
                continue
            await trigger.wait_for(state="visible", timeout=8_000)
            try:
                await trigger.scroll_into_view_if_needed(timeout=3_000)
            except Exception:
                pass
            try:
                await trigger.click(timeout=8_000)          # SIN force
            except Exception:
                await trigger.click(force=True, timeout=5_000)
            logger.info("[MO] Foto: pulsado el %s.", desc)
            boton = page.get_by_test_id(AI_FOTO_BOTON).first
            espera = 0
            while espera <= timeout_ms:
                try:
                    if await boton.is_visible():
                        logger.info("[MO] Modal de la webcam abierto (%.1f s).",
                                    espera / 1000)
                        return True
                except Exception:
                    pass
                await page.wait_for_timeout(300)
                espera += 300
            logger.info("[MO] El %s no abrió el modal — pruebo otro disparador.",
                        desc)
        except Exception as e:
            logger.info("[MO] %s no utilizable: %s", desc, str(e)[:70])
            continue
    logger.warning("[MO] No se pudo abrir el modal de la webcam del ID. "
                   "Revisa la tarjeta 'Front of ID' en Additional Info.")
    return False


async def _foto_take_and_save(page, desc: str = "foto") -> bool:
    """«Take Picture» → «Save Picture» dentro del modal de la webcam.

    Son el MISMO botón (mismo data-testid) que cambia de texto, así que se
    pulsa dos veces. Cada pulsación espera a que esté HABILITADO —la webcam
    tarda en dar señal— tal como hace el repo original; sin esa espera el
    primer clic se pierde y la foto nunca se guarda."""
    boton = page.get_by_test_id(AI_FOTO_BOTON).first
    try:
        await boton.wait_for(state="visible", timeout=25_000)
    except Exception as e:
        logger.warning("[MO] El modal de la webcam no ofreció el botón (%s): %s",
                       desc, str(e)[:80])
        return False
    for _ in range(15):
        if await boton.is_enabled():
            break
        await page.wait_for_timeout(1_000)
    await boton.click()
    logger.info("[MO] %s: capturada.", desc.capitalize())
    await page.wait_for_timeout(2_000)

    # Segunda pulsación: ahora el botón dice «Save Picture».
    try:
        if await boton.is_visible():
            for _ in range(15):
                if await boton.is_enabled():
                    break
                await page.wait_for_timeout(1_000)
            await boton.click()
            logger.info("[MO] %s: guardada.", desc.capitalize())
    except Exception as e:
        logger.warning("[MO] No se pudo guardar la %s: %s", desc, str(e)[:80])
        return False
    await page.wait_for_timeout(1_500)
    return True


async def tomar_foto_id(page) -> bool:
    """Foto del ID: abre la cámara, 'Take Picture' y luego 'Save Picture'."""
    try:
        # Si quedó un 'Try again' de un intento anterior, primero eso.
        try:
            reintentar = page.locator("button").filter(has_text="Try again").first
            if await reintentar.is_visible():
                await reintentar.click()
                await page.wait_for_timeout(2_500)
        except Exception:
            pass

        if not await _abrir_camara_id(page):
            return False
        await page.wait_for_timeout(4_000)      # la webcam tarda en encender

        return await _foto_take_and_save(page, "foto del ID")
    except Exception as e:
        logger.warning("[MO] No se pudo tomar la foto del ID: %s", str(e)[:100])
        return False


async def _aceptar_disponible(page) -> bool:
    try:
        b = page.locator(AI_BTN_ACEPTAR).first
        return await b.is_visible() and await b.is_enabled()
    except Exception:
        return False


async def llenar_additional_info(page, num_id: str, tax_id: str,
                                 direccion: str, razon: str,
                                 evi=None) -> bool:
    """Llena el formulario completo de Additional Info y lo acepta.

    La segunda foto del ID solo se toma si la pantalla la exige: pedirla siempre
    alargaba el caso sin motivo."""
    logger.info("[MO] Llenando Additional Info…")
    await _opcion_dropdown(page, AI_PAIS, prefijo="compliance-id-info-form-country",
                           desc="País del ID")
    await _opcion_dropdown(page, AI_TIPO_ID, prefijo="compliance-id-info-form-id-type",
                           desc="Tipo de ID")
    try:
        await page.get_by_test_id(AI_NUM_ID).first.fill(num_id)
    except Exception as e:
        logger.warning("[MO] Número de ID: %s", str(e)[:80])
    await _fecha(page, AI_EXPIRA, AI_FIJOS["expira"], "Expiración del ID")
    await _fecha(page, AI_NACIMIENTO, AI_FIJOS["nacimiento"], "Fecha de nacimiento")

    await _opcion_dropdown(page, AI_OCUPACION, AI_FIJOS["ocupacion"],
                           "compliance-customer-info-form-occupation", "Ocupación")
    await _opcion_dropdown(page, AI_SUB_OCUPACION, AI_FIJOS["sub_ocupacion"],
                           "compliance-customer-info-form-sub-occupation",
                           "Sub-ocupación")

    await _click(page, AI_TAX_SI, "Tiene Tax ID: sí", timeout=10_000)
    await page.wait_for_timeout(500)
    await _opcion_dropdown(page, AI_TAX_TIPO, AI_FIJOS["tax_tipo"],
                           "compliance-tax-id-type", "Tipo de Tax ID")
    try:
        await page.get_by_test_id(AI_TAX_NUM).first.fill(tax_id)
    except Exception:
        pass

    try:
        await page.get_by_test_id(AI_DIRECCION).first.fill(direccion)
        cp = page.get_by_test_id(AI_CP).first
        await cp.fill(AI_FIJOS["cp"])
        await cp.press("Tab")
        logger.info("[MO] Dirección y CP escritos — esperando ciudad/estado…")
        await page.wait_for_timeout(9_000)      # el CP autocompleta lento
        await page.get_by_test_id(AI_RAZON).first.fill(razon)
    except Exception as e:
        logger.warning("[MO] Dirección/razón: %s", str(e)[:90])

    if not await tomar_foto_id(page):
        return False
    if evi is not None:
        await evi.shot("additional_info_con_foto")

    # ¿Ya se puede aceptar? Si no, la pantalla pide una SEGUNDA foto.
    # El repo original lo decide por dos señales: el mensaje de error del
    # segundo selector, o la clase 'photo-required' de su contenedor.
    if not await _aceptar_disponible(page):
        try:
            selector2 = page.get_by_test_id(AI_FOTO2).first
            requiere = False
            if await selector2.count() and await selector2.is_visible():
                aviso = page.get_by_test_id(AI_FOTO2_REQUERIDA).first
                if await aviso.count() and await aviso.is_visible():
                    requiere = True
                if not requiere:
                    contenedor = selector2.locator(
                        "xpath=ancestor::*[contains(@class,'img-container')][1]")
                    if await contenedor.count():
                        clases = await contenedor.get_attribute("class") or ""
                        requiere = "photo-required" in clases
            if requiere:
                logger.info("[MO] Se exige una SEGUNDA foto del ID.")
                await selector2.click(timeout=10_000)
                await page.wait_for_timeout(3_000)
                await _foto_take_and_save(page, "segunda foto")
            else:
                logger.info("[MO] Segunda foto no requerida.")
        except Exception as e:
            logger.info("[MO] Segunda foto: %s", str(e)[:80])

    # ACEPTAR — el paso que devuelve a la pantalla del Money Order.
    # CLAVE: hay que esperar a que el botón se HABILITE. Pulsarlo antes (o con
    # force) deja el formulario abierto en silencio; el caso seguía como si
    # hubiera vuelto y el 'Print MO' de después no encontraba su pantalla.
    try:
        aceptar = page.locator(AI_BTN_ACEPTAR).first
        await aceptar.wait_for(state="visible", timeout=15_000)
        for _ in range(15):
            if await aceptar.is_enabled():
                break
            await page.wait_for_timeout(1_000)
        if not await aceptar.is_enabled():
            logger.warning("[MO] El botón Accept sigue deshabilitado: falta "
                           "algún dato o la foto del ID no se registró.")
            return False
        await aceptar.click(timeout=10_000)
        logger.info("[MO] ✓ Additional Info aceptada — de vuelta al Money Order.")
        await page.wait_for_timeout(2_500)
        return True
    except Exception as e:
        logger.warning("[MO] No se pudo aceptar Additional Info: %s", str(e)[:100])
        return False


# ── Impresión (aquí habla el Hardware Agent) ────────────────────────────────

async def imprimir(page, serie: str, evi=None) -> bool:
    """Print MO → número de serie → confirmar → aceptar el resultado.

    Este es el paso que invoca al agente de hardware: la etiqueta KRA-1527
    envuelve EXACTAMENTE esta llamada con su auditoría."""
    logger.info("[MO] Imprimiendo el Money Order #%s…", serie)
    if not await _click(page, BTN_IMPRIMIR_MO, "Print MO"):
        return False

    # Tras 'Print MO' pueden salir TRES cosas: el modal del número, un modal de
    # error, o nada (porque seguimos en otra pantalla). Se sondean las tres para
    # poder decir cuál ocurrió.
    campo = page.get_by_test_id(PRINT_NUM_INPUT).first
    espera, limite = 0, 20_000
    estado = ""
    while espera <= limite:
        try:
            if await campo.is_visible():
                estado = "numero"
                break
        except Exception:
            pass
        for tid in (PRINT_ERROR_1, PRINT_ERROR_2):
            try:
                err = page.get_by_test_id(tid).first
                if await err.count() and await err.is_visible():
                    texto = ((await err.inner_text()) or "").strip()
                    logger.error("[MO] La impresión devolvió un error: «%s»",
                                 texto[:160])
                    estado = "error"
                    break
            except Exception:
                continue
        if estado:
            break
        await page.wait_for_timeout(400)
        espera += 400

    if estado != "numero":
        if estado != "error":
            logger.warning("[MO] Tras 'Print MO' no apareció el modal del "
                           "número (%.0f s). Comprueba que se volvió a la "
                           "pantalla del Money Order: si Additional Info quedó "
                           "abierta, 'Print MO' no existe en ese contexto.",
                           limite / 1000)
        if evi is not None:
            await evi.shot("impresion_sin_modal")
        return False

    try:
        await campo.fill(str(serie))
        await _click(page, PRINT_CONFIRMAR, "Impresión confirmada")
    except Exception as e:
        logger.warning("[MO] No se pudo confirmar la impresión: %s", str(e)[:100])
        return False
    try:
        aceptar = page.get_by_test_id(PRINT_ACEPTAR).first
        await aceptar.wait_for(state="visible", timeout=45_000)
        if evi is not None:
            await evi.shot("mo_impreso")
        await aceptar.click()
        logger.info("[MO] ✓ Money Order #%s impreso.", serie)
        await page.wait_for_timeout(1_500)
        return True
    except Exception as e:
        logger.warning("[MO] No llegó la confirmación de impresión: %s", str(e)[:100])
        return False


# ── Reportes y anulación ────────────────────────────────────────────────────

async def ir_a_reportes_money_order(page) -> bool:
    """Reportes > Transacciones y filtrar por tipo MONEY ORDER."""
    try:
        # Mismo cuidado que en las otras navegaciones: el aviso primero.
        await _cerrar_warning(page, timeout_ms=1_500)
        await page.get_by_test_id(NAV_REPORTES).first.click(force=True)
        await page.wait_for_timeout(600)
        await _cerrar_warning(page, timeout_ms=2_000)
        await page.get_by_test_id(REPORTES_TRANSACCIONES).first.click(force=True)
        await _cerrar_warning(page, timeout_ms=2_500)
        await page.wait_for_timeout(2_000)
        await page.locator(TIPO_TRANSACCION).first.click(force=True)
        await page.wait_for_timeout(600)
        opcion = page.get_by_role("option", name="MONEY ORDER")
        await opcion.wait_for(state="visible", timeout=15_000)
        await opcion.click(force=True)
        logger.info("[MO] Reportes filtrado por MONEY ORDER.")
        await page.wait_for_timeout(600)
        return True
    except Exception as e:
        logger.warning("[MO] No se pudo abrir el reporte de MO: %s", str(e)[:100])
        return False


async def buscar(page) -> None:
    """Pulsa Buscar en el reporte de transacciones."""
    try:
        await page.get_by_test_id(BTN_BUSCAR).first.click(force=True, timeout=TIMEOUT)
        await page.wait_for_timeout(3_000)
    except Exception as e:
        logger.warning("[MO] No se pudo buscar: %s", str(e)[:90])


async def anular_money_orders(page, cliente: str, maximo: int = 3,
                              evi=None) -> int:
    """Anula los MO en estado Open del cliente. Devuelve cuántos anuló.

    La tabla se REFRESCA en cada vuelta porque al anular uno cambian los
    índices: buscar todas las filas de una vez y recorrerlas daría errores de
    elemento obsoleto."""
    logger.info("[MO] Anulando los Money Orders de '%s'…", cliente)
    anulados = 0
    for vuelta in range(maximo):
        await buscar(page)
        await page.wait_for_timeout(1_500)
        fila = page.locator(
            f"tr:has(td:has-text('{cliente}')):has(*:has-text('Open'))").first
        try:
            if not await fila.is_visible():
                logger.info("[MO] No quedan MO en estado Open.")
                break
        except Exception:
            break
        try:
            boton = fila.locator("td.td-custom-options div.report-transaction-cell").first
            await boton.wait_for(state="visible", timeout=15_000)
            await boton.click(force=True)
            await page.wait_for_timeout(1_200)
            confirmar = page.get_by_role("button", name=RE_VOID).or_(
                page.get_by_test_id(BTN_VOID_MODAL))
            await confirmar.first.wait_for(state="visible", timeout=15_000)
            await confirmar.first.click(force=True)
            await page.wait_for_timeout(2_000)
            anulados += 1
            logger.info("[MO] Money Order %d anulado.", anulados)
            if evi is not None:
                await evi.shot(f"mo_anulado_{anulados}")
        except Exception as e:
            logger.warning("[MO] Fallo al anular (vuelta %d): %s",
                           vuelta + 1, str(e)[:100])
            break
    logger.info("[MO] Total anulados: %d", anulados)
    return anulados
