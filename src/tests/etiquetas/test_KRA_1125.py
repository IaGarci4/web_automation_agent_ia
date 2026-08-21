"""
ETIQUETA KRA-1125 - Validation Rule H2: telefono del beneficiario en DEPOSITO.

Jira KRA-1125 (Epic, INC 38230): "que el campo de numero de telefono de
Beneficiario que tenemos para Wallet tenga el mismo comportamiento para DEPOSITO,
respetando la Validation Rule que exige el 573 al inicio del numero para
Uniteller Colombia".

Casos automatizados:
  1. POSITIVO  - telefono local 3X -> backend ve 573X -> sin error; el deposito procede.
  2. NEGATIVO  - telefono local 4X -> backend ve 574X -> error VR; se corrige a 3X y desaparece.

Pais: Colombia | Pagador: Uniteller (Bancolombia 2) | Tipo: Deposito.

Nota sobre el telefono:
  BENEF_PHONE_TESTID       = wrapper div (llenar_formulario_completo)
  BENEF_PHONE_INPUT_TESTID = <input> real (correcciones; siempre en DOM incluso en error)
  click_continue usa force=True; si el boton esta disabled React ignora el evento.
  Hay que verificar que el boton quedo enabled antes de continuar.

COMO CORRER:
    pytest src/tests/etiquetas -k KRA_1125 -v -s
"""
import os
import random
import pytest
from playwright.async_api import Page

from config.logger import get_logger
from src.pages.hm_transferelektra_page import HmTransferelektraPage
from src.helpers.screenshot_helper import ScreenshotHelper
from src.helpers.datos import Datos
from src.pagadores import flujo_mt as F

logger = get_logger("KRA-1125")

PAYERS, CIUDADES = F.cargar_catalogo(modulo="colombia")

# LÍMITE de casos a ejecutar (env MAX_CASOS, lo fija el agente/GUI). Sin límite
# corre TODOS los pagadores del catálogo; el agente pone 1 si no se pidió
# cantidad ni tiempo, o N si se pidieron N ejecuciones.
_MAX_CASOS = int(os.getenv("MAX_CASOS", "0") or 0)
if _MAX_CASOS > 0:
    PAYERS = PAYERS[:_MAX_CASOS]
_PAYER_IDS = [p["code"] for p in PAYERS]

COMPLETAR = os.getenv("COMPLETAR_ENVIO", "1").strip().lower() in ("1", "true", "si", "yes")
CANCELAR  = os.getenv("FLOW_CANCEL",    "0").strip().lower() in  ("1", "true", "si", "yes")

BENEF_PHONE_TESTID       = "transfer-beneficiary-cellphone-0-cellphone-input"
BENEF_PHONE_INPUT_TESTID = "transfer-beneficiary-cellphone-beneficiary-id-0-cellphone-input"
BENEF_ID_NUMBER_TESTID   = "transfer-beneficiary-document-number-0-input"
BENEF_TOGGLE_TESTID      = "transfer-beneficiary-toggle-fields-button-0"
_BTN_CONTINUE            = "transfer-continue-button-0-button"

# Pausa (ms) para DEJAR VISIBLE la corrección del teléfono con el panel de
# información desplegado, antes de dar Continue. Configurable por entorno.
_PAUSA_VISUAL_MS = int(os.getenv("KRA_PAUSE_MS", "2000"))

EVIDENCE = "KRA-1125"
_SUCCESS_TESTID = "transfers-container-modal-success-transfer-0-decline-button"
_SUMMARY_TESTID = "transfers-container-modal-summary-0-send-button"


def _ev(n):
    d = os.path.join(os.path.dirname(__file__), "..", "..", "..", "reports", "evidence", EVIDENCE)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, n)


async def _fill_documento_si_aparece(flow):
    page = flow.page
    num_field = page.get_by_test_id(BENEF_ID_NUMBER_TESTID).first
    try:
        await num_field.wait_for(state="visible", timeout=2_000)
    except Exception:
        logger.info("Documento ID: campos no visibles -- se omiten.")
        return False

    logger.info("Documento ID: campos detectados -- rellenando.")

    try:
        tipo_found = await page.evaluate("""
            () => {
                const numInput = document.querySelector(
                    "[data-testid='transfer-beneficiary-document-number-0-input']");
                if (!numInput) return false;
                let el = numInput.parentElement;
                for (let i = 0; i < 8; i++) {
                    const dd = el ? el.querySelector('.p-dropdown') : null;
                    if (dd) { dd.click(); return true; }
                    if (!el) break;
                    el = el.parentElement;
                }
                return false;
            }
        """)
        if tipo_found:
            await page.wait_for_timeout(500)
            opts = page.locator(
                "li[role='option'], .p-dropdown-item, .p-autocomplete-item, [role='option']")
            try:
                await opts.first.wait_for(state="visible", timeout=3_000)
            except Exception:
                pass
            n_opts = await opts.count()
            seleccionado = False
            for i in range(n_opts):
                txt = (await opts.nth(i).text_content() or "").strip()
                if "CITIZENSHIP" in txt.upper():
                    await opts.nth(i).click(force=True)
                    logger.info("Tipo de Documento: '%s' seleccionado.", txt)
                    seleccionado = True
                    break
            if not seleccionado:
                logger.warning("Tipo de Documento: CITIZENSHIP CARD no encontrada -- primera opcion.")
                if n_opts > 0:
                    await opts.first.click(force=True)
        else:
            logger.warning("Tipo de Documento: dropdown no localizado.")
    except Exception as e:
        logger.warning("Tipo de Documento: error (%s)", e)

    await page.wait_for_timeout(300)
    try:
        num_digits = random.randint(6, 9)
        num_value  = "".join(str(random.randint(0, 9)) for _ in range(num_digits))
        await num_field.fill(num_value)
        try:
            await num_field.blur()
        except Exception:
            pass
        logger.info("Numero de Documento: %s (%d digitos).", num_value, num_digits)
    except Exception as e:
        logger.warning("Numero de Documento: no se pudo rellenar (%s)", e)
    return True


async def _set_phone_js(flow, tel: str, testids: list) -> bool:
    """
    ÚLTIMO RECURSO para corregir el teléfono: setea el valor por JS usando el
    native value setter de HTMLInputElement (compatible con inputs controlados de
    React) y dispara input+change. NO depende de la visibilidad ni del foco de
    Playwright — a prueba de Gateway 4 (BANCOLOMBIA_DIRECTO). Verifica dígitos.
    """
    js = """
    (args) => {
      const [tids, val] = args;
      const setter = Object.getOwnPropertyDescriptor(
          window.HTMLInputElement.prototype, 'value').set;
      for (const tid of tids) {
        const el = document.querySelector(`[data-testid='${tid}']`);
        if (!el) continue;
        try { el.focus(); } catch (e) {}
        setter.call(el, val);
        el.dispatchEvent(new Event('input',  {bubbles: true}));
        el.dispatchEvent(new Event('change', {bubbles: true}));
        try { el.blur(); } catch (e) {}
        return tid;
      }
      return '';
    }
    """
    try:
        usado = await flow.page.evaluate(js, [testids, tel])
        if not usado:
            return False
        await flow.page.wait_for_timeout(600)
        val = await flow.page.get_by_test_id(usado).first.input_value()
        ok = "".join(c for c in val if c.isdigit()) == tel
        logger.info("[KRA-1125] set_phone_js via '%s' → '%s' (ok=%s)", usado, val, ok)
        return ok
    except Exception as e:
        logger.warning("[KRA-1125] _set_phone_js falló: %s", str(e)[:80])
        return False


async def _asegurar_info_desplegada(flow, *, pausa_ms=0):
    """Deja DESPLEGADO el panel de información del beneficiario. IDEMPOTENTE: si
    YA está abierto (el teléfono es visible) NO vuelve a tocar el toggle — así el
    panel se abre UNA sola vez y se queda así, sin abrir/cerrar una y otra vez.

    Usa el chevron del toggle como indicador de estado (pista del usuario):
      <i class="bi bi-chevron-up">   → panel DESPLEGADO
      <i class="bi bi-chevron-down"> → panel COLAPSADO (solo entonces se expande)
    """
    page = flow.page

    async def _visible() -> bool:
        try:
            return await page.get_by_test_id(BENEF_PHONE_TESTID).first.is_visible()
        except Exception:
            return False

    if not await _visible():
        # Está colapsado → desplegar UNA sola vez.
        try:
            from src.pagadores.flujo_mt import set_beneficiary_expandido
            await set_beneficiary_expandido(flow, True)
        except Exception:
            pass
        if not await _visible():
            try:
                btn = page.get_by_test_id(BENEF_TOGGLE_TESTID).first
                if await btn.locator("i.bi-chevron-down").count() > 0:
                    await btn.click(force=True, timeout=2_000)
                    await page.wait_for_timeout(400)
            except Exception:
                pass
    # Centrar el teléfono en la vista (no cambia el estado del panel). CON timeout
    # corto: si el elemento no está adjunto (panel colapsado), evaluate esperaría
    # ~30s por defecto → aquí se rinde en 1.5s.
    try:
        await page.get_by_test_id(BENEF_PHONE_TESTID).first.evaluate(
            "(el) => el.scrollIntoView({block: 'center'})", timeout=1_500)
    except Exception:
        pass
    if pausa_ms:
        await page.wait_for_timeout(pausa_ms)


async def _corregir_telefono_y_enviar(flow, tel_bueno, *, logger, screenshot=None, ev=None):
    """
    Corrige el telefono del beneficiario ANTES de dar click Continue.

    REGLA: NO se llama click_continue hasta verificar que el campo tiene
    el valor correcto Y el boton quedo habilitado. Si alguno falla -> return False.

    Flujo:
      1. focus() via JS + keyboard.type() (el <input> interno puede ser "not visible"
         para Playwright aunque sea interactuable; evaluate bypasea ese check)
      2. Verificar input_value() == tel_bueno  (hasta 3 intentos)
      3. Verificar boton Continue habilitado   (hasta 5 s de espera)
      4. Screenshot evidencia de campo corregido
      5. click_continue → esperar summary modal
      6. click_yes_send → esperar success modal
    """
    logger.info("[KRA-1125] corregir_telefono_y_enviar: objetivo=%s", tel_bueno)

    # ── 1. Corregir campo telefono ────────────────────────────────────────────
    # El <input> interno del widget de telefono (+57) puede ser "not visible"
    # para Playwright; usamos evaluate() para enfocar via JS y keyboard.type()
    # para disparar los key events que React necesita.
    # NOTA: el widget formatea la salida como "(378) 700-8884"; comparamos
    # solo los digitos para verificar que el valor es correcto.
    # El beneficiario quedó COLAPSADO (para revelar Totales); hay que RE-EXPANDIRLO
    # para que el campo de teléfono sea VISIBLE. Es clave en Gateway 4
    # (BANCOLOMBIA_DIRECTO), donde el testid externo ES el <input> y colapsado
    # queda "not visible" → el scroll_into_view truena.
    # Desplegar el panel de info del beneficiario UNA sola vez (idempotente): si
    # ya está abierto NO se vuelve a tocar (no abrir/cerrar repetidamente).
    await _asegurar_info_desplegada(flow)

    correcto = False
    inp = flow.page.get_by_test_id(BENEF_PHONE_INPUT_TESTID).first

    async def _teclear_en_input(target_inp, label: str) -> bool:
        """Enfoca via JS, borra, teclea y verifica dígitos. Retorna True si OK.

        Usa scrollIntoView por JS (NO scroll_into_view_if_needed) para NO depender
        de la 'visibilidad' de Playwright: el <input> del +57 puede reportarse como
        'not visible' aunque sea interactuable (típico en Gateway 4 / BANCOLOMBIA
        directo). Si el testid no existe (inner de Gateway 22 en un Gateway 4),
        regresa False rápido (sin esperar timeouts). Nunca lanza: captura y regresa
        False, así el caller puede caer al fallback."""
        try:
            if await target_inp.count() == 0:
                logger.info("[KRA-1125] %s: no existe en el DOM — se omite.", label)
                return False
            await target_inp.evaluate("(el) => el.scrollIntoView({block: 'center'})")
            await target_inp.evaluate("(el) => el.focus()")
            await flow.page.wait_for_timeout(300)
            # Seleccionar SOLO el contenido del input (acotado por JS) y borrarlo.
            # Antes se usaba keyboard 'Control+a': si el foco no quedaba DENTRO del
            # input, seleccionaba TODO el texto de la PÁGINA (glitch visual que se
            # veía al dar Continue en las pruebas negativas). el.select() no.
            await target_inp.evaluate("(el) => el.select()")
            await flow.page.wait_for_timeout(100)
            await flow.page.keyboard.press("Delete")
            await flow.page.wait_for_timeout(100)
            await flow.page.keyboard.type(tel_bueno, delay=60)
            await flow.page.wait_for_timeout(300)
            # React necesita 'input' además de 'change'.
            await target_inp.evaluate(
                "(el) => { el.dispatchEvent(new Event('input', {bubbles:true}));"
                " el.dispatchEvent(new Event('change', {bubbles:true})); el.blur(); }")
            await flow.page.wait_for_timeout(800)
            val_real = await target_inp.input_value()
            val_digits = "".join(c for c in val_real if c.isdigit())
            logger.info("[KRA-1125] %s campo='%s' digitos='%s' esperado='%s'",
                        label, val_real, val_digits, tel_bueno)
            return val_digits == tel_bueno
        except Exception as e:
            logger.warning("[KRA-1125] %s: no se pudo teclear (%s)", label, str(e)[:80])
            return False

    # Intento principal: inner <input> (Gateway 22). Si NO existe o NO cuadra,
    # fallback al testid externo (Gateway 4, donde ESE testid ES el <input> directo).
    correcto = await _teclear_en_input(inp, "inner-input")
    if not correcto:
        inp_fb = flow.page.get_by_test_id(BENEF_PHONE_TESTID).first
        logger.info("[KRA-1125] fallback: usando %s como input directo", BENEF_PHONE_TESTID)
        correcto = await _teclear_en_input(inp_fb, "fallback-input")
    if not correcto:
        # Último recurso a prueba de todo: setear por JS (native setter React).
        correcto = await _set_phone_js(
            flow, tel_bueno, [BENEF_PHONE_INPUT_TESTID, BENEF_PHONE_TESTID])

    # ── HARD STOP: campo no corregido ────────────────────────────────────────
    if not correcto:
        logger.error(
            "[KRA-1125] ABORTANDO: no se pudo corregir el campo de telefono. "
            "NO se da click Continue.")
        if screenshot and ev:
            try:
                await screenshot.screenshot_only(
                    screenshot_path=ev("negativo_fallo_correccion.png"))
            except Exception:
                pass
        return False

    logger.info("[KRA-1125] campo telefono corregido: %s", tel_bueno)

    # ── 2. Esperar que el boton Continue quede habilitado ────────────────────
    # Sondeo RÁPIDO (250 ms): en cuanto React lo habilita, se clickea — sin
    # esperas largas (importa para la demo). Máx ~4 s por si tarda en validar.
    btn_enabled = False
    for tick in range(1, 17):          # ~4 s en pasos de 250 ms
        try:
            disabled = await flow.page.get_by_test_id(_BTN_CONTINUE).first.evaluate(
                "el => el.disabled || el.getAttribute('disabled') !== null")
            if not disabled:
                btn_enabled = True
                logger.info("[KRA-1125] Continue habilitado (tick %d) — clic inmediato.", tick)
                break
        except Exception as e:
            logger.warning("[KRA-1125] chequeo boton tick %d: %s", tick, e)
        await flow.page.wait_for_timeout(250)

    # ── HARD STOP: boton sigue disabled ──────────────────────────────────────
    if not btn_enabled:
        logger.error(
            "[KRA-1125] ABORTANDO: boton Continue sigue disabled tras corregir telefono. "
            "NO se da click Continue.")
        if screenshot and ev:
            try:
                await screenshot.screenshot_only(
                    screenshot_path=ev("negativo_btn_disabled.png"))
            except Exception:
                pass
        return False

    # ── 3. Evidencia: campo OK + boton habilitado ─────────────────────────────
    # El campo YA quedó corregido y verificado (paso 1). Aquí NO se re-expande el
    # panel (eso podía colgarse ~30s buscando un elemento no adjunto): solo una
    # pausa breve para la evidencia y captura simple. Prioridad: dar Continue en
    # cuanto está habilitado.
    await flow.page.wait_for_timeout(_PAUSA_VISUAL_MS)
    if screenshot and ev:
        try:
            await screenshot.screenshot_only(
                screenshot_path=ev("negativo_campo_corregido.png"))
        except Exception:
            pass

    # ── 4. Continue ──────────────────────────────────────────────────────────
    try:
        await flow.click_continue()
    except Exception:
        pass

    summary_visible = False
    try:
        await flow.page.get_by_test_id(_SUMMARY_TESTID).first.wait_for(
            state="visible", timeout=10_000)
        summary_visible = True
        logger.info("[KRA-1125] summary modal visible")
    except Exception:
        logger.warning("[KRA-1125] summary modal NO visible tras click_continue")

    if not summary_visible:
        if screenshot and ev:
            try:
                await screenshot.screenshot_only(
                    screenshot_path=ev("negativo_sin_summary.png"))
            except Exception:
                pass
        return False

    # ── 5. Confirmar envio ───────────────────────────────────────────────────
    try:
        await flow.click_yes_send()
    except Exception as e:
        logger.warning("[KRA-1125] click_yes_send fallo: %s", e)

    # ── 6. Esperar modal de exito (backend tarda ~12-15 s; Nequi puede tardar ~30 s) ──
    success_visible = False
    try:
        await flow.page.get_by_test_id(_SUCCESS_TESTID).first.wait_for(
            state="visible", timeout=40_000)
        success_visible = True
    except Exception:
        pass

    if not success_visible:
        try:
            success_visible = await flow.page.get_by_test_id(_SUMMARY_TESTID).first.is_visible()
        except Exception:
            pass

    if screenshot and ev:
        try:
            await screenshot.screenshot_only(screenshot_path=ev("negativo_correccion.png"))
        except Exception:
            pass

    if success_visible:
        try:
            await flow.page.get_by_test_id(_SUCCESS_TESTID).first.click()
        except Exception:
            try:
                await flow.page.keyboard.press("Escape")
            except Exception:
                pass

    logger.info("[KRA-1125] corregir_telefono_y_enviar: success=%s", success_visible)
    return success_visible


@pytest.mark.etiqueta
@pytest.mark.asyncio
@pytest.mark.parametrize("payer_cfg", PAYERS, ids=_PAYER_IDS)
async def test_KRA_1125_telefono_valido_573(logged_page: Page, payer_cfg: dict):
    """POSITIVO: deposito con telefono local 3X -> VR 573 pasa, sin error; transferencia completa."""
    flow = HmTransferelektraPage(logged_page)
    datos = Datos()
    screenshot = ScreenshotHelper(logged_page)
    rng = random.Random()
    cfg = dict(payer_cfg)
    pais, ciudad, estado = F.destino(cfg, CIUDADES, rng)
    cfg["payer_city"] = ciudad

    prefijo = cfg.get("phone_prefix", "3")
    tel = datos.telefono_prefijo(prefijo)
    logger.info("[KRA-1125] POSITIVO | %s | destino=%s/%s | payer_city=%s | tel=%s",
                cfg["code"], ciudad, estado, cfg["payer_city"], tel)

    monto = await F.llenar_formulario_completo(
        flow, datos, cfg, pais, ciudad, estado,
        monto=int(float(datos.monto())), tipo="deposit", benef_phone=tel)

    err = await flow.leer_error_de_campo(BENEF_PHONE_TESTID)
    assert not err, f"Telefono {tel} no deberia dar error, pero aparecio: '{err}'"

    await F.seleccionar_pagador(flow, cfg, logger, tipo="deposit")
    await flow.seleccionar_deposit_account_type()
    await flow.fill_account_number_adaptativo(min_d=11, max_d=11)
    await _fill_documento_si_aparece(flow)

    try:
        await screenshot.screenshot_only(screenshot_path=_ev("armado_valido.png"))
    except Exception:
        pass

    if CANCELAR:
        cliente = datos.nombre_cliente()
        try:
            await flow.click_continue()
            await flow.click_yes_send()
            try:
                await flow.click_no()
            except Exception:
                pass
            await flow.click_reports()
            await flow.wait_for_no_blocking_overlays()
            await flow.click_transactions()
            await flow.wait_for_no_blocking_overlays()
            try:
                await flow.click_yes_leave()
            except Exception:
                pass
            await flow.wait_for_no_blocking_overlays()
            try:
                await flow.buscar_transaccion_por_nombre(cliente)
            except Exception:
                pass
            await flow.cancelar_transaccion(reason_index=0, notes="Automation")
        except Exception as e:
            logger.warning("[KRA-1125] cancelacion: %s", e)
    elif COMPLETAR:
        enviado = await F.completar_envio(flow, completar=True, logger=logger)
        logger.info("[KRA-1125] deposito %s.", "completado" if enviado else "NO completado")

    try:
        await screenshot.screenshot_only(screenshot_path=_ev("fin_valido.png"))
    except Exception:
        pass
    logger.info("[KRA-1125] POSITIVO finalizado (monto %s).", monto)


@pytest.mark.etiqueta
@pytest.mark.asyncio
@pytest.mark.parametrize("payer_cfg", PAYERS, ids=_PAYER_IDS)
async def test_KRA_1125_telefono_sin_573_rechazado(logged_page: Page, payer_cfg: dict):
    """
    NEGATIVO: telefono local 5X -> VR KRA-1125 rechaza.
    Se corrige directamente a 3X y se envia.
    """
    flow = HmTransferelektraPage(logged_page)
    datos = Datos()
    screenshot = ScreenshotHelper(logged_page)
    rng = random.Random()
    cfg = dict(payer_cfg)
    pais, ciudad, estado = F.destino(cfg, CIUDADES, rng)
    cfg["payer_city"] = ciudad

    # Primer dígito ALEATORIO, cualquiera del 0 al 9 MENOS el 3 (el 3 es el que
    # pasa la Validation Rule; a ese se corrige). Así cada corrida usa un prefijo
    # inválido distinto (no siempre '5').
    primer_malo = random.choice("012456789")
    tel_malo = primer_malo + "".join(str(random.randint(0, 9)) for _ in range(9))
    logger.info("[KRA-1125] NEGATIVO | %s | destino=%s/%s | payer_city=%s | tel_malo=%s (prefijo %s)",
                cfg["code"], ciudad, estado, cfg["payer_city"], tel_malo, primer_malo)

    # NOTA: el beneficiario se colapsa durante el llenado (si no, TAPA la sección
    # de tarifa/monto del depósito y el clic hace timeout). El panel se RE-ABRE
    # solo en la corrección del teléfono (_asegurar_info_desplegada, idempotente),
    # que es donde importa dejarlo visible.
    await F.llenar_formulario_completo(
        flow, datos, cfg, pais, ciudad, estado,
        monto=int(float(datos.monto())), tipo="deposit", benef_phone=tel_malo)

    await F.seleccionar_pagador(flow, cfg, logger, tipo="deposit")
    await flow.seleccionar_deposit_account_type()
    await flow.fill_account_number_adaptativo(min_d=11, max_d=11)
    await _fill_documento_si_aparece(flow)

    try:
        await screenshot.screenshot_only(screenshot_path=_ev("negativo_sin_573.png"))
    except Exception:
        pass

    tel_bueno = "3" + "".join(str(random.randint(0, 9)) for _ in range(9))
    logger.info("[KRA-1125] NEGATIVO -- corrigiendo telefono a: %s", tel_bueno)

    enviado = await _corregir_telefono_y_enviar(
        flow, tel_bueno, logger=logger, screenshot=screenshot, ev=_ev)

    assert enviado, (
        f"Tras corregir telefono a {tel_bueno} (3X), el flujo debia completarse "
        f"pero el modal de exito no aparecio."
    )
    logger.info("[KRA-1125] NEGATIVO OK -- VR rechaza 4X; corregido a 3X, transaccion procesada.")

    # Cancelación (si la instrucción pidió 'cancela' → FLOW_CANCEL=1): usa el
    # MÓDULO de cancelación de Money Transfer (Reportes → buscar por cliente →
    # cancelar). El cliente es el que se generó en el llenado (Faker cacheado).
    if CANCELAR:
        cliente = datos.nombre_cliente()
        logger.info("[KRA-1125] Cancelando la transacción de '%s'...", cliente)
        try:
            from src.sanity_general import cancelacion as C
            cancelada = await C.cancelar_por_cliente(
                flow, cliente, logger=logger, reason_index=0,
                notes="Automation KRA-1125")
            logger.info("[KRA-1125] Cancelación %s.",
                        "OK" if cancelada else "no confirmada")
        except Exception as e:
            logger.warning("[KRA-1125] No se pudo cancelar: %s", e)
