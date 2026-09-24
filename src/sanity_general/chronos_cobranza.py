"""
Chronos · Cobranza (Collection) — CP09.

Dos pantallas:
  • Agent Monitor  → agregar DEPÓSITO y OTRO CARGO a un agente.
  • Collection     → validar/ajustar el BALANCE del agente.

Port del POM del repo viejo (`ChronosMainPage.cp09_*`). Chronos NO usa
data-testid: todo va por XPath/CSS/`formcontrolname` y por ÍNDICE de columna.

Detalles del original que aquí se respetan:
  • Los modales se cierran con `evaluate("el.click()")` (los overlays de Chronos
    interceptan el click normal de Playwright).
  • El balance viene como texto contable: los PARÉNTESIS significan negativo.
    Si el balance NO tiene paréntesis y es distinto de 0, no se ajusta nada.
  • El monto a aplicar es -(balance + 1) — así lo hace el código original
    (su docstring dice "+2", pero el código suma 1).

La sesión de Chronos la maneja `chronos.py` (cookies reutilizadas).
"""

import re

from config.logger import get_logger
from src.sanity_general import chronos as CR

logger = get_logger("sanity.chronos.cobranza")

TIMEOUT = 180_000
NOTA = "test"
MONTO_UNO = "1"

# ── Menú: Collection > Agent Monitor / Collection ───────────────────────────
COLLECTION_OPTION = ("//mat-expansion-panel-header[.//mat-panel-title"
                     "[normalize-space()='Collection']]")
AGENT_MONITOR_LINK = ('a[href="/Chronos/Frontend/collection/agent-monitor"], '
                      'a[href="/application/collection/agent-monitor"]')
COLLECTION_SUB = ("//mat-expansion-panel[.//mat-expansion-panel-header"
                  "[.//mat-panel-title[normalize-space()='Collection']]]"
                  "//div[normalize-space()='Collection']")

# ── Agent Monitor ───────────────────────────────────────────────────────────
AM_SEARCH_INPUT = 'input[placeholder="Agent Code, Agent Name, ZipCode"]'
AM_DEPOSITS_PANEL = 'div[role="tabpanel"]#ngb-tab-9-panel'
AM_AMOUNT = 'input[formcontrolname="amount"]'
RE_DEPOSITS = re.compile(r"deposits?|dep[oó]sitos?", re.I)
RE_ADD_DEPOSIT_TITLE = re.compile(r"add\s*deposit|agregar\s*dep[oó]sito", re.I)
RE_OTHER_CHARGES = re.compile(r"other\s*charges|otros\s*cargos", re.I)
RE_ADD = re.compile(r"^\s*add\s*$|^\s*agregar\s*$", re.I)
RE_YES = re.compile(r"^\s*(yes|s[ií])\s*$", re.I)
RE_CLOSE = re.compile(r"close|cerrar", re.I)
RE_WARN_DEP = re.compile(r"same date and amount", re.I)
RE_OK_DEP = re.compile(r"operation successfully completed", re.I)
RE_OK_CHARGE = re.compile(r"other charges was saved successfully", re.I)
OTHER_CHARGES_PANEL = "app-agent-monitor-other-charges"
MEMO_TYPE_LABEL = "4406-02 Balance Transfer Credit"

# ── Collection (balance) ────────────────────────────────────────────────────
COL_SEARCH_BAR = "#AgentSearchBar"
COL_BALANCE = ('//div[contains(@class,"col-sm-4")]//input'
               '[@type="text" and @disabled]')
COL_NOTES = 'textarea[formcontrolname="notes"]'


def _fila_agente(agency_code: str) -> str:
    """Fila de la tabla cuya 1ª celda es el código de agencia."""
    return (f'//p-table//tbody[contains(@class,"ui-table-tbody")]'
            f'//tr[td[1]//div[normalize-space()="{agency_code}"]]')


def _fila_agente_simple(agency_code: str) -> str:
    return (f'//tbody[contains(@class,"ui-table-tbody")]'
            f'//tr[td//div[normalize-space()="{agency_code}"]]')


async def _click_js(locator) -> None:
    """Click por JS: los overlays de Chronos interceptan el click normal."""
    await locator.evaluate("(el) => el.click()")


# Botones de los modales de Chronos.
#
# Se buscan GLOBALMENTE y se filtra por la VISIBILIDAD DEL BOTÓN. No sirve usar
# `div.modal-content` como guarda: Chronos deja los modales anteriores en el DOM
# (ocultos), `.first` caía en uno de esos y parecía que "no había modal".
#
# `[appautofocus]` es el discriminador fino: en el Warning SOLO el botón **Yes**
# lo lleva; el **No** tiene idénticas clases (`btn btn-blue`) pero sin ese
# atributo. Por eso Yes y No se distinguen sin ambigüedad.
BTN_YES = "button.btn-blue[appautofocus]"
BTN_NO = "button.btn-blue:not([appautofocus])"
RE_NO = re.compile(r"^\s*(no)\s*$", re.I)


async def _visible(page, selector: str, patron, limite: int = 12):
    """Primer botón **realmente visible** que casa selector + texto, o None.

    Recorre TODAS las coincidencias, no solo `.first`. Esto es esencial: Chronos
    deja los modales anteriores en el DOM (ocultos), así que `.first` resolvía a
    un botón viejo e invisible y el `Yes` real —el del modal nuevo, más abajo en
    el DOM— nunca se encontraba. Fue justo lo que pasó en 'Other Charges' después
    de que el depósito dejara su modal atrás."""
    loc = page.locator(selector).filter(has_text=patron)
    try:
        total = min(await loc.count(), limite)
    except Exception:
        return None
    for i in range(total):
        btn = loc.nth(i)
        try:
            if await btn.is_visible():
                return btn
        except Exception:
            continue
    return None


async def _resolver_guardado(page, re_exito, desc: str,
                             timeout_ms: int = 30_000) -> bool:
    """Resuelve TODO lo que sale después de pulsar 'Add', en cualquier orden.

    Chronos puede mostrar el Warning de duplicado antes, después o en lugar del
    modal de éxito. Antes esto eran dos pasos rígidos (confirmar → cerrar) con
    esperas fijas: si el Warning llegaba tarde, el paso de éxito se quedaba los
    120 s del timeout esperando detrás de él.

    Regla importante: **'Yes' se pulsa UNA sola vez**. Ese botón confirma crear
    el registro duplicado, así que repetirlo genera depósitos/cargos de más
    (fue lo que dejó la nota vacía en la corrida anterior)."""
    yes_usado = False
    espera = 0
    while espera <= timeout_ms:
        # 1) ¿Ya está el modal de éxito? → cerrar y terminar.
        #    Igual que con los botones: se recorren todas las coincidencias,
        #    porque los textos de modales previos siguen en el DOM.
        exito = await _visible(page, "p.modal-text", re_exito)
        try:
            if exito is not None:
                cerrar = await _visible(page, "div.modal-content button", RE_CLOSE) \
                    or await _visible(page, "button", RE_CLOSE)
                if cerrar is not None:
                    await _click_js(cerrar)
                logger.info("[Cobranza] %s", desc)
                await page.wait_for_timeout(500)
                return True
        except Exception:
            pass
        # 2) ¿Warning de duplicado? → Yes (solo la primera vez).
        if not yes_usado:
            btn = await _visible(page, BTN_YES, RE_YES)
            if btn is not None:
                await _click_js(btn)
                yes_usado = True
                logger.info("[Cobranza] Warning de duplicado → Yes (%.1f s).",
                            espera / 1000)
                await page.wait_for_timeout(700)
                continue
        await page.wait_for_timeout(200)
        espera += 200
    logger.warning("[Cobranza] No se confirmó '%s' en %.0f s.", desc,
                   timeout_ms / 1000)
    return False


async def limpiar_modales(page, *, timeout_ms: int = 1_000, vueltas: int = 3) -> int:
    """Desbloquea la pantalla cerrando modales REZAGADOS. Nunca pulsa 'Yes'.

    Se usa ANTES de una acción (pestañas, menú, lecturas). Si quedó un Warning
    colgado, lo correcto es **cancelarlo con 'No'**: desbloquea igual y, a
    diferencia de 'Yes', no crea un registro duplicado a espaldas del caso.

    Orden: Close → No → X. Barato: si no hay nada visible sale en ~1 s."""
    candidatos = (
        ("div.modal-content button", RE_CLOSE, "Close"),
        ("button", RE_CLOSE, "Close"),
        (BTN_NO, RE_NO, "No"),
    )
    cerrados = 0
    for _ in range(vueltas):
        actuo = False
        espera = 0
        while espera <= timeout_ms and not actuo:
            for sel, patron, etiqueta in candidatos:
                btn = await _visible(page, sel, patron)
                if btn is None:
                    continue
                try:
                    await _click_js(btn)
                    logger.info("[Cobranza] Modal rezagado cerrado con '%s'.",
                                etiqueta)
                    cerrados += 1
                    actuo = True
                    await page.wait_for_timeout(500)
                    break
                except Exception:
                    continue
            if actuo:
                break
            await page.wait_for_timeout(150)
            espera += 150
        if not actuo:
            try:                      # último recurso: la X del encabezado
                x = page.locator("div.modal-header button.close, "
                                 "div.modal-header .close, "
                                 "div.modal-header span.close").first
                if await x.is_visible():
                    await _click_js(x)
                    logger.info("[Cobranza] Modal rezagado cerrado con la X.")
                    cerrados += 1
                    await page.wait_for_timeout(500)
                    continue
            except Exception:
                pass
            break
    return cerrados


# ── Navegación ──────────────────────────────────────────────────────────────

async def ir_a_agent_monitor(page) -> None:
    """Menu → Collection → Agent Monitor."""
    await CR._click_listo(page, page.locator(CR.TOOLBAR_MENU).first, "Menu abierto")
    await page.wait_for_timeout(1_000)
    await CR._click_listo(page, page.locator(COLLECTION_OPTION).first, "Collection")
    await page.wait_for_timeout(600)
    await CR._click_listo(page, page.locator(AGENT_MONITOR_LINK).first, "Agent Monitor")
    await page.wait_for_timeout(1_500)


async def ir_a_collection(page) -> None:
    """Menu → Collection → Collection (submenú)."""
    await limpiar_modales(page)          # el menú también se bloquea con modales
    await CR._click_listo(page, page.locator(CR.TOOLBAR_MENU).first, "Menu abierto")
    await page.wait_for_timeout(1_000)
    sub = page.locator(COLLECTION_SUB).first
    try:
        if not await sub.is_visible():
            await CR._click_listo(page, page.locator(COLLECTION_OPTION).first,
                                  "Collection (expandido)")
            await page.wait_for_timeout(600)
    except Exception:
        pass
    await CR._click_listo(page, sub, "Collection (submenú)")
    await page.wait_for_timeout(1_500)


async def buscar_agente(page, agency_code: str, *, en_collection: bool = False) -> bool:
    """Filtra por código de agencia y abre su fila."""
    sel = COL_SEARCH_BAR if en_collection else AM_SEARCH_INPUT
    try:
        inp = page.locator(sel).first
        await inp.wait_for(state="visible", timeout=TIMEOUT)
        await inp.click()
        try:
            await inp.clear()
        except Exception:
            pass
        await inp.type(agency_code, delay=90)
        await page.wait_for_timeout(2_000)
        xp = _fila_agente_simple(agency_code) if en_collection else _fila_agente(agency_code)
        fila = page.locator(xp).first
        await fila.wait_for(state="visible", timeout=TIMEOUT)
        await CR._click_listo(page, fila, f"Agente {agency_code} abierto")
        await page.wait_for_timeout(2_000)
        return True
    except Exception as e:
        logger.warning("[Cobranza] No se pudo abrir el agente %s: %s",
                       agency_code, str(e)[:100])
        return False


# ── Agent Monitor: depósito y otro cargo ────────────────────────────────────

async def agregar_deposito(page, monto: str = MONTO_UNO, nota: str = NOTA) -> bool:
    """Pestaña Deposits → monto + notas → Add → confirma y valida la 1ª fila."""
    logger.info("[Cobranza] Agregando depósito de $%s…", monto)
    try:
        await limpiar_modales(page)
        tab = page.locator('a[role="tab"]').filter(has_text=RE_DEPOSITS).nth(1)
        await CR._click_listo(page, tab, "Pestaña Deposits")

        panel = page.locator(AM_DEPOSITS_PANEL).first
        amount = page.locator(AM_AMOUNT).first
        await amount.wait_for(state="visible", timeout=TIMEOUT)
        await amount.click()
        try:
            await amount.clear()
        except Exception:
            pass
        await amount.type(str(monto), delay=90)

        try:
            titulo = page.locator("b").filter(has_text=RE_ADD_DEPOSIT_TITLE).first
            await titulo.wait_for(state="visible", timeout=30_000)
            await titulo.scroll_into_view_if_needed(timeout=5_000)
            await page.wait_for_timeout(800)
        except Exception:
            pass

        notas = panel.locator('textarea[formcontrolname="notes"]').first
        await notas.wait_for(state="visible", timeout=TIMEOUT)
        await notas.click()
        await notas.fill(nota)

        add = panel.locator(
            "div.row.col-12.justify-content-center > button.btn.btn-blue").first
        await CR._click_listo(page, add, "Add (depósito)")

        await _resolver_guardado(page, RE_OK_DEP, "Depósito guardado")

        # Validación: 1ª fila con el monto y la nota (columnas 2 y 4).
        try:
            tabla = panel.locator("div.ui-table-scrollable-body "
                                  "table.ui-table-scrollable-body-table "
                                  "tbody.ui-table-tbody").first
            fila = tabla.locator("tr").first
            await fila.wait_for(state="visible", timeout=TIMEOUT)
            imp = (await fila.locator("td").nth(2).inner_text() or "").strip()
            nts = (await fila.locator("td").nth(4).inner_text() or "").strip()
            logger.info("[Cobranza] Depósito en tabla → monto='%s' notas='%s'", imp, nts)
        except Exception:
            logger.info("[Cobranza] No se pudo leer la fila del depósito (no crítico).")
        return True
    except Exception as e:
        logger.warning("[Cobranza] No se pudo agregar el depósito: %s", str(e)[:110])
        return False


async def agregar_otro_cargo(page, monto: str = MONTO_UNO, nota: str = NOTA) -> bool:
    """Pestaña Other Charges → Credit + memo type + monto + notas → Add."""
    logger.info("[Cobranza] Agregando otro cargo de $%s…", monto)
    try:
        # CLAVE: si quedó un Warning abierto del paso anterior, este clic se
        # colgaba los 120 s del timeout esperando detrás del modal.
        await limpiar_modales(page)
        tab = page.get_by_role("tab", name="Other Charges", exact=True)
        await CR._click_listo(page, tab, "Pestaña Other Charges", timeout=45_000)
        panel = page.locator(OTHER_CHARGES_PANEL).first

        # El original marca Debit y luego Credit (queda Credit).
        for rid, etiqueta in (("#perTransfer", "Debit"), ("#perTransfer2", "Credit")):
            try:
                radio = panel.locator(rid).first
                await radio.wait_for(state="visible", timeout=30_000)
                await radio.check(force=True)
            except Exception:
                logger.info("[Cobranza] Radio %s no disponible.", etiqueta)

        try:
            memo = panel.locator('[formcontrolname="memoType"]').first
            await memo.wait_for(state="visible", timeout=TIMEOUT)
            await memo.select_option(label=MEMO_TYPE_LABEL)
            logger.info("[Cobranza] Memo type: %s", MEMO_TYPE_LABEL)
        except Exception as e:
            logger.warning("[Cobranza] Memo type no se pudo elegir: %s", str(e)[:80])

        credito = panel.locator('input[formcontrolname="creditAmount"]').first
        await credito.wait_for(state="visible", timeout=TIMEOUT)
        try:
            await credito.scroll_into_view_if_needed(timeout=5_000)
        except Exception:
            pass
        await credito.click()
        try:
            await credito.clear()
        except Exception:
            pass
        await credito.type(str(monto), delay=90)

        notas = panel.locator('[formcontrolname="notes"] input[role="searchbox"]').first
        await notas.wait_for(state="visible", timeout=TIMEOUT)
        await notas.click()
        await notas.fill(nota)

        add = panel.locator("button").filter(has_text=RE_ADD).last
        await CR._click_listo(page, add, "Add (otro cargo)")

        # Si el guardado no se confirma, se devuelve False: el caso debe fallar
        # ahí, con la pantalla del error a la vista, en vez de seguir como si
        # el cargo se hubiera aplicado.
        return await _resolver_guardado(page, RE_OK_CHARGE, "Otro cargo guardado")
    except Exception as e:
        logger.warning("[Cobranza] No se pudo agregar el otro cargo: %s", str(e)[:110])
        return False


# ── Collection: validar/ajustar el balance ──────────────────────────────────

async def validar_balance(page, nota: str = NOTA) -> dict:
    """Lee el balance del agente y, si aplica, lo ajusta.

    Regla del original: los PARÉNTESIS del texto contable indican negativo. Si
    el balance NO tiene paréntesis y es != 0, no se hace nada. En otro caso se
    aplica un monto de -(balance + 1).

    Devuelve {'balance': str, 'aplicado': str|None, 'ajustado': bool}.
    """
    balance_txt = ""
    await limpiar_modales(page)
    try:
        campo = page.locator(COL_BALANCE).first
        await campo.wait_for(state="visible", timeout=TIMEOUT)
        balance_txt = (await campo.input_value() or "").strip()
    except Exception as e:
        logger.warning("[Cobranza] No se pudo leer el balance: %s", str(e)[:90])
        return {"balance": "", "aplicado": None, "ajustado": False}

    tiene_parentesis = "(" in balance_txt and ")" in balance_txt
    limpio = (balance_txt.replace("(", "").replace(")", "")
              .replace("$", "").replace(",", "").strip())
    m = re.search(r"-?\d+(\.\d+)?", limpio)
    if not m:
        logger.error("[Cobranza] No se pudo extraer el número del balance: '%s'",
                     balance_txt)
        return {"balance": balance_txt, "aplicado": None, "ajustado": False}
    valor = float(m.group())
    logger.info("[Cobranza] Balance del agente: '%s' (%.2f, negativo=%s)",
                balance_txt, valor, tiene_parentesis)

    if not tiene_parentesis and valor != 0:
        logger.info("[Cobranza] Balance positivo distinto de 0 — no se ajusta.")
        return {"balance": balance_txt, "aplicado": None, "ajustado": False}

    resultado = -(valor + 1)
    final = str(int(resultado)) if float(resultado).is_integer() else f"{resultado:.2f}"
    logger.info("[Cobranza] Aplicando monto %s…", final)
    try:
        amount = page.locator(AM_AMOUNT).first
        await CR._click_listo(page, amount, "Campo de monto")
        try:
            await amount.clear()
        except Exception:
            pass
        await amount.type(final, delay=90)

        notas = page.locator(COL_NOTES).first
        await notas.wait_for(state="visible", timeout=TIMEOUT)
        await notas.click()
        await notas.fill(nota)

        add = page.get_by_role("button", name="Add", exact=True)
        await CR._click_listo(page, add, "Add (balance)")
        await page.wait_for_timeout(3_000)

        await _resolver_guardado(page, RE_OK_DEP, "Balance ajustado")
        return {"balance": balance_txt, "aplicado": final, "ajustado": True}
    except Exception as e:
        logger.warning("[Cobranza] No se pudo ajustar el balance: %s", str(e)[:110])
        return {"balance": balance_txt, "aplicado": final, "ajustado": False}
