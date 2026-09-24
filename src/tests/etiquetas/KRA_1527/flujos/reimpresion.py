"""
Reimpresión de recibo desde el historial — CP06 de KRA-1527.

Este módulo NO existe en el sanity ni en el repo viejo: es propio de la
etiqueta. Nace de la observación de que la reimpresión es una ruta **distinta**
al Hardware Agent: el CP01 imprime el recibo recién generado dentro del flujo de
envío; aquí se le pide a la app que vuelva a imprimir una transacción del
historial, y el diálogo de impresión es otro (elige tipo de impresión e
impresora antes de mandar el trabajo).

## El flujo, tal como se hace a mano

```
Reportes > Transacciones
  → Buscar                       (los filtros por defecto ya listan el día)
  → menú «Más Acciones» (···) de una fila cualquiera
  → «Imprimir Recibo» / «Print Receipt»      ← el mismo menú de Cancelar
  → modal «Imprimir Recibo»:
        Seleccione Tipo de Impresión → WINDOWS PRINTER
        Seleccione su Impresora      → la que traiga por defecto
  → «Imprimir»
```

## Dos detalles que definen el diseño de este módulo

**1. El menú se monta en `<body>`, no en la fila.** Es un
`<p-menu appendto="body">`, así que sus opciones NO están dentro del `<tr>`; y
como Angular deja los menús anteriores en el DOM, `.first` cae en uno oculto.
Por eso se recorren todas las coincidencias comprobando visibilidad, igual que
en el resto de la etiqueta.

**2. El texto del menú es «Imprimir Recibo», el del botón es «Imprimir».**
Buscar solo «Imprimir» encontraría el botón del modal (o al revés). Las dos
expresiones regulares son distintas a propósito y están ancladas.

## El error al final es esperado

Al pulsar Imprimir la app suele devolver un error de impresión. **No importa y
no invalida el caso**: la petición ya salió hacia el Hardware Agent, que es
exactamente lo que la etiqueta necesita auditar. El error se captura como
evidencia y se anota en el reporte, pero no marca fallo.
"""

import os
import re

from config.logger import get_logger

from . import modales as _MOD

logger = get_logger("KRA1527.reimpresion")

TIMEOUT = 15_000

# Tipo de impresión a elegir en el modal. WINDOWS PRINTER es el que enruta el
# trabajo por el agente local y abre el diálogo de Windows (de donde sale el
# PDF de evidencia). El combo tiene dos opciones — WINDOWS PRINTER y TICKET —
# como `li[role=option].p-dropdown-item` con su texto en `aria-label`. Si en
# algún ambiente no estuviera, `configurar_impresion` conserva el default y
# sigue (no falla).
TIPO_IMPRESION = os.getenv("KRA1527_TIPO_IMPRESION", "WINDOWS PRINTER").strip()
# Impresora concreta: vacío = respetar la que traiga por defecto
# («MICROSOFT PRINT TO PDF (PREDETERMINADO)» en el ambiente de TEST).
IMPRESORA = os.getenv("KRA1527_IMPRESORA", "").strip()

# ── Opción del menú de la transacción ───────────────────────────────────────
# Anclada: 'Imprimir Recibo', NO el 'Imprimir' del botón del modal.
RE_ITEM_RECIBO = re.compile(
    r"^\s*(re)?(print\s*receipt|imprimir\s*recibo|reimprimir\s*recibo)\s*$", re.I)
ITEM_TESTIDS = (
    "reports-transaction-menu--printReceipt-paragraph-semi-bold",
    "reports-transaction-menu-printReceipt-paragraph-semi-bold",
    "reports-transaction-menu--printreceipt-paragraph-semi-bold",
)
# Contenedores del p-menu montado en body.
MENU_CONTENEDORES = ("p-menu .p-menu-list", "p-menu", ".p-menu-overlay",
                     ".p-menu", "div[role='menu']")
# Solo los selectores que un p-menu usa de verdad. Barrer 'div, span' aquí
# multiplicaba las llamadas al navegador y hacía que el paso tardara medio
# minuto en el peor caso; para el barrido amplio se usa `get_by_text`, que
# filtra DENTRO del navegador.
MENU_ITEMS = (".p-menuitem-link", "li[role='menuitem']", ".p-menuitem",
              "a", "p")

# ── Modal «Imprimir Recibo» ─────────────────────────────────────────────────
MODAL = ("div[role='dialog']", "p-dialog", ".p-dialog", "div.modal-content",
         ".modal-content")
# Botón del modal: 'Imprimir'/'Print' EXACTO — para no pulsar 'Cancelar'.
RE_BTN_IMPRIMIR = re.compile(r"^\s*(imprimir|print)\s*$", re.I)
RE_BTN_CANCELAR = re.compile(r"^\s*(cancelar|cancel|close|cerrar)\s*$", re.I)
BTN_SELECTOR = ("#id-button", "[data-testid='test-id-button']",
                "buttonsimple button", "button.button.success", "button")
# Etiquetas del combo de tipo de impresión (ES/EN).
ETIQUETAS_TIPO = ("Seleccione Tipo de Impresión", "Select Print Type",
                  "Tipo de Impresión", "Print Type", "Tipo de Impresion")
ETIQUETAS_IMPRESORA = ("Seleccione su Impresora", "Select your Printer",
                       "Impresora", "Printer")
# Avisos posteriores (el error de impresión, o el 'Accept' de confirmación).
RE_ACEPTAR = re.compile(r"^\s*(accept|aceptar|ok|entendido|close|cerrar)\s*$", re.I)
FILAS = ("tr.report-transactions-result-row", "tbody tr",
         ".p-scroller-content .ng-star-inserted")


# ═══════════════════════════════════════════════════════════════════════════
# Utilidades (mismas reglas que el resto de la etiqueta)
# ═══════════════════════════════════════════════════════════════════════════

async def _visible(page, selector: str, limite: int = 12):
    """Primer elemento REALMENTE visible del selector, o None.

    No usa `.first`: Hermes deja menús y modales anteriores en el DOM y `.first`
    caía en uno oculto — el clic 'funcionaba' sobre nada."""
    try:
        loc = page.locator(selector)
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


async def _visibles(page, selector: str, limite: int = 40) -> list:
    """Todos los elementos visibles del selector."""
    salida = []
    try:
        loc = page.locator(selector)
        total = min(await loc.count(), limite)
    except Exception:
        return salida
    for i in range(total):
        el = loc.nth(i)
        try:
            if await el.is_visible():
                salida.append(el)
        except Exception:
            continue
    return salida


async def _click(el, timeout: int = 8_000) -> bool:
    """Clic normal; `force` SOLO como último recurso.

    `force=True` se salta las comprobaciones de accionabilidad, así que el clic
    'funciona' sobre algo que Angular no procesa y el fallo aparece 15-30 s
    después, en otro elemento. Ya nos costó varias vueltas."""
    try:
        try:
            await el.scroll_into_view_if_needed(timeout=2_000)
        except Exception:
            pass
        await el.click(timeout=timeout)
        return True
    except Exception:
        try:
            await el.click(force=True, timeout=6_000)
            return True
        except Exception:
            return False


async def _modal_visible(page):
    """El diálogo visible que contiene un combobox — el de impresión."""
    for sel in MODAL:
        for el in await _visibles(page, sel, limite=10):
            try:
                if await el.locator("span[role='combobox'], div.p-dropdown").count():
                    return el
            except Exception:
                continue
    return None


async def _esperar_modal(page, timeout_ms: int = TIMEOUT):
    """Espera a que el modal de impresión APAREZCA (no a que ya exista)."""
    espera = 0
    while espera <= timeout_ms:
        modal = await _modal_visible(page)
        if modal is not None:
            await page.wait_for_timeout(500)
            return modal
        await page.wait_for_timeout(200)
        espera += 200
    return None


async def esperar_modal_impresion(page, timeout_ms: int = TIMEOUT):
    """El modal «preferencias de impresión» de Hermes. Devuelve el locator.

    Público porque no es exclusivo de la reimpresión: el mismo diálogo sale
    en «Print Report By Cashier» (CP06) con su combo de Tipo de Impresión y
    su botón Print deshabilitado hasta que se elige WINDOWS PRINTER. Junto a
    `configurar_impresion` y `pulsar_imprimir` —que ya reciben `(page, modal)`
    y no saben de dónde vino— cubren los dos casos sin duplicar nada.
    """
    return await _esperar_modal(page, timeout_ms)


# ═══════════════════════════════════════════════════════════════════════════
# 1. Listar el historial
# ═══════════════════════════════════════════════════════════════════════════

async def buscar(flow, timeout_ms: int = 20_000) -> int:
    """Pulsa Buscar/Search en Reportes > Transacciones y espera las filas.

    Los filtros por defecto (Envío de Dinero + rango del día) ya listan
    transacciones, así que no hace falta filtrar por cliente: para esta etiqueta
    sirve cualquiera. Devuelve cuántas filas quedaron."""
    page = flow.page
    btn = page.locator("#id-button, [data-testid='test-id-button']").filter(
        has_text=re.compile(r"buscar|search", re.I))
    pulsado = False
    for i in range(min(await btn.count(), 5)):
        el = btn.nth(i)
        try:
            if await el.is_visible() and await el.is_enabled():
                pulsado = await _click(el, timeout=6_000)
                if pulsado:
                    logger.info("[Reimpresión] Buscar pulsado.")
                    break
        except Exception:
            continue
    if not pulsado:
        logger.warning("[Reimpresión] No pude pulsar Buscar — puede que el "
                       "reporte ya venga cargado.")

    # Las filas tardan ~2-3 s en renderizar tras Buscar.
    espera, total = 0, 0
    while espera <= timeout_ms:
        for sel in FILAS:
            try:
                n = await page.locator(sel).count()
            except Exception:
                n = 0
            if n > total:
                total = n
        if total:
            await page.wait_for_timeout(800)
            logger.info("[Reimpresión] %d transacción(es) en el historial.", total)
            return total
        await page.wait_for_timeout(400)
        espera += 400
    logger.warning("[Reimpresión] El historial salió vacío en %.0f s.",
                   timeout_ms / 1000)
    return 0


# ═══════════════════════════════════════════════════════════════════════════
# 2. Menú de la fila → «Imprimir Recibo»
# ═══════════════════════════════════════════════════════════════════════════

async def elegir_imprimir_recibo(flow, row_index: int = 0) -> bool:
    """Abre el menú «Más Acciones» de la fila y pulsa «Imprimir Recibo».

    El menú es el MISMO de la cancelación (`abrir_menu_transaccion`, que ya está
    probado con el kebab de esta tabla); lo único que cambia es la opción."""
    page = flow.page
    if not await flow.abrir_menu_transaccion(row_index, desc="Reimpresión"):
        return False
    await page.wait_for_timeout(400)

    # 1) Testids conocidos (documentados en el proyecto hermano ai_agent).
    for tid in ITEM_TESTIDS:
        try:
            loc = page.get_by_test_id(tid)
            for i in range(min(await loc.count(), 5)):
                el = loc.nth(i)
                if await el.is_visible():
                    if await _click(el):
                        logger.info("[Reimpresión] 'Imprimir Recibo' pulsado "
                                    "(testid %s).", tid)
                        return True
        except Exception:
            continue

    # 2) Dentro del p-menu montado en <body>, por TEXTO bilingüe.
    for contenedor in MENU_CONTENEDORES:
        menu = await _visible(page, contenedor, limite=8)
        if menu is None:
            continue
        for item_sel in MENU_ITEMS:
            try:
                items = menu.locator(item_sel)
                total = min(await items.count(), 25)
            except Exception:
                continue
            for i in range(total):
                el = items.nth(i)
                try:
                    if not await el.is_visible():
                        continue
                    texto = ((await el.inner_text()) or "").strip()
                except Exception:
                    continue
                if RE_ITEM_RECIBO.search(texto):
                    if await _click(el):
                        logger.info("[Reimpresión] 'Imprimir Recibo' pulsado "
                                    "por texto ('%s') en %s.", texto, contenedor)
                        return True

    # 3) Último recurso: `get_by_text` con el regex anclado. El filtrado ocurre
    #    DENTRO del navegador (una sola llamada, no una por elemento), y el
    #    ancla evita confundir la opción con el botón 'Imprimir' del modal o
    #    con un encabezado de columna.
    try:
        por_texto = page.get_by_text(RE_ITEM_RECIBO)
        for i in range(min(await por_texto.count(), 10)):
            el = por_texto.nth(i)
            try:
                if not await el.is_visible():
                    continue
                texto = ((await el.inner_text()) or "").strip()
            except Exception:
                continue
            if await _click(el):
                logger.info("[Reimpresión] 'Imprimir Recibo' pulsado por texto "
                            "suelto ('%s').", texto)
                return True
    except Exception:
        pass

    # Diagnóstico útil en vez de un fallo mudo: qué SÍ había en el menú.
    opciones = []
    for contenedor in MENU_CONTENEDORES:
        menu = await _visible(page, contenedor, limite=8)
        if menu is None:
            continue
        try:
            opciones = [t.strip() for t in await menu.locator(
                ".p-menuitem-link, li, p, span").all_inner_texts() if t.strip()]
        except Exception:
            pass
        if opciones:
            break
    logger.warning("[Reimpresión] No encontré 'Imprimir Recibo' en el menú. "
                   "Opciones visibles: %s",
                   ", ".join(f"'{o}'" for o in opciones[:8]) or "(ninguna)")
    return False


# ═══════════════════════════════════════════════════════════════════════════
# 3. Modal de impresión: tipo + impresora
# ═══════════════════════════════════════════════════════════════════════════

async def _combo_por_etiqueta(page, modal, etiquetas):
    """Combo (p-dropdown) que sigue a una de las etiquetas dadas.

    Se busca por etiqueta porque los dos combos del modal comparten
    `id="dropdown"` — es el mismo problema que el «MO Printer» de los money
    orders y se resuelve igual."""
    for etiqueta in etiquetas:
        try:
            loc = page.locator(
                f"xpath=//*[contains(normalize-space(text()),'{etiqueta}')]"
                f"/following::div[contains(@class,'p-dropdown')][1]")
            for i in range(min(await loc.count(), 4)):
                el = loc.nth(i)
                if await el.is_visible():
                    logger.info("[Reimpresión] Combo hallado por la etiqueta "
                                "'%s'.", etiqueta)
                    return el
        except Exception:
            continue
    return None


async def _valor_actual(combo) -> str:
    """Lo que el combo muestra hoy (viene en el aria-label del combobox)."""
    for sel in ("span[role='combobox']", ".p-dropdown-label"):
        try:
            el = combo.locator(sel).first
            if await el.count():
                return ((await el.get_attribute("aria-label"))
                        or (await el.inner_text()) or "").strip()
        except Exception:
            continue
    return ""


async def _elegir_en_combo(page, combo, valor: str) -> bool:
    """Despliega el combo y elige la opción `valor` (por aria-label o texto).

    Las opciones del p-dropdown se montan en `<body>` como
    `li[role='option'].p-dropdown-item`, y su texto vive en el atributo
    `aria-label` (además del `<span>` interno). Antes se leía solo el
    inner_text y, sobre todo, NO se confirmaba que el panel hubiera abierto:
    si el clic de apertura no desplegaba, el bucle sondeaba opciones que nunca
    existían y terminaba en «(ninguna)». Ahora la apertura se VERIFICA
    esperando a que aparezca al menos una opción, reintentando el clic sobre
    varios objetivos.
    """
    actual = await _valor_actual(combo)
    if valor.casefold() in actual.casefold():
        logger.info("[Reimpresión] '%s' ya estaba seleccionado.", actual)
        return True

    opciones = page.locator("li[role='option'], li.p-dropdown-item")

    async def _abrir() -> bool:
        # PrimeNG abre al clicar el label (span[role=combobox]) o el trigger.
        # Se prueba cada objetivo y se CONFIRMA la apertura esperando opciones.
        for sel in ("span[role='combobox']", ".p-dropdown-trigger",
                    ".p-dropdown-label", ""):
            try:
                el = combo.locator(sel).first if sel else combo
                if sel and not await el.count():
                    continue
                try:
                    await el.scroll_into_view_if_needed(timeout=2_000)
                except Exception:
                    pass
                await el.click(timeout=4_000)
            except Exception:
                continue
            try:
                await opciones.first.wait_for(state="visible", timeout=2_500)
                return True
            except Exception:
                continue
        return False

    if not await _abrir():
        logger.warning("[Reimpresión] El combo no desplegó opciones tras varios "
                       "intentos de apertura.")
        return False

    espera = 0
    while espera <= 6_000:
        total = min(await opciones.count(), 40)
        for i in range(total):
            el = opciones.nth(i)
            try:
                if not await el.is_visible():
                    continue
                aria = (await el.get_attribute("aria-label")) or ""
                texto = ((await el.inner_text()) or "").strip()
            except Exception:
                continue
            if (valor.casefold() in aria.casefold()
                    or valor.casefold() in texto.casefold()):
                try:
                    await el.scroll_into_view_if_needed(timeout=2_000)
                except Exception:
                    pass
                if await _click(el, timeout=6_000):
                    await page.wait_for_timeout(500)
                    logger.info("[Reimpresión] ✓ '%s' seleccionado.",
                                texto or aria)
                    return True
        await page.wait_for_timeout(300)
        espera += 300

    # No fallar a ciegas: listar lo que este ambiente sí ofrece (aria-label).
    disponibles = []
    try:
        for i in range(min(await opciones.count(), 12)):
            a = (await opciones.nth(i).get_attribute("aria-label")) or ""
            t = ((await opciones.nth(i).inner_text()) or "").strip()
            if a or t:
                disponibles.append(a or t)
    except Exception:
        pass
    logger.warning("[Reimpresión] '%s' no está entre las opciones. "
                   "Disponibles: %s", valor,
                   ", ".join(f"'{d}'" for d in disponibles) or "(ninguna)")
    return False


async def _elegir_tipo_impresion(page, modal, valor: str) -> bool:
    """Elige el Tipo de Impresión probando CADA combo del modal hasta dar con el
    que ofrece la opción objetivo, y la clica.

    ## Por qué no se busca por etiqueta

    El intento anterior localizaba el combo con
    `//*[texto='Select Print Type']/following::div.p-dropdown[1]`. En ESTE modal
    el `<label>` se renderiza DESPUÉS de su propio dropdown (patrón float-label),
    así que 'following' caía en el dropdown del SIGUIENTE campo —el de la
    impresora— cuyo valor es 'MAXI TICKET PRINTER'. Por eso el combo "no
    desplegaba opciones" (no tiene WINDOWS PRINTER/TICKET) y `_valor_actual`
    devolvía el nombre de la impresora. Aquí se ignoran etiqueta y orden: se abre
    cada combobox y se conserva el único que muestra la opción buscada.

    ## Selectores (los que confirmó el usuario a mano)

      combo:  <span role="combobox" class="p-dropdown-label" aria-label="TICKET">
      opción: <li role="option" class="p-dropdown-item"
                  aria-label="WINDOWS PRINTER"><span>WINDOWS PRINTER</span></li>

    Las opciones se montan en `<body>`, no dentro del combo, por eso se buscan en
    `page` y con aria-label EXACTO.
    """
    # 0) ¿ya está elegido en algún combo del modal?
    comboboxes = await _visibles(modal, "span[role='combobox']", limite=8)
    for cb in comboboxes:
        try:
            actual = ((await cb.get_attribute("aria-label"))
                      or (await cb.inner_text()) or "").strip()
        except Exception:
            actual = ""
        if valor.casefold() == actual.casefold():
            logger.info("[Reimpresión] '%s' ya estaba seleccionado como tipo.",
                        actual)
            return True

    # Opción objetivo (aria-label EXACTO) y sonda genérica de "hay opciones".
    opcion = page.locator(f"li[role='option'][aria-label='{valor}']")
    opcion_any = page.locator("li[role='option'], li.p-dropdown-item")

    # Candidatos a abrir: los comboboxes visibles; si no hay, los p-dropdown.
    abridores = comboboxes or await _visibles(modal, "div.p-dropdown", limite=8)
    for cb in abridores:
        # Abrir ESTE combo (clic en el combobox, o en su trigger).
        abierto = False
        for sel in ("", ".p-dropdown-trigger"):
            try:
                el = cb.locator(sel).first if sel else cb
                if sel and not await el.count():
                    continue
                try:
                    await el.scroll_into_view_if_needed(timeout=1_500)
                except Exception:
                    pass
                await el.click(timeout=3_000)
            except Exception:
                continue
            try:
                await opcion_any.first.wait_for(state="visible", timeout=2_000)
                abierto = True
                break
            except Exception:
                continue
        if not abierto:
            continue

        # El combo abrió opciones. ¿Está entre ellas la que buscamos?
        try:
            await opcion.first.wait_for(state="visible", timeout=1_500)
        except Exception:
            # No es este combo (p. ej. el de impresora): cerrar y seguir.
            try:
                await page.keyboard.press("Escape")
            except Exception:
                pass
            continue

        if await _click(opcion.first, timeout=6_000):
            await page.wait_for_timeout(500)
            logger.info("[Reimpresión] ✓ Tipo de impresión '%s' seleccionado.",
                        valor)
            return True
        # Si el clic falló, cerrar antes de probar el siguiente candidato.
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
    return False


async def configurar_impresion(page, modal, tipo: str = None,
                               impresora: str = None) -> bool:
    """Elige el Tipo de Impresión (WINDOWS PRINTER) y, si se pide, la impresora.

    La impresora se deja como venga por defecto salvo que se indique una: en
    TEST viene «MICROSOFT PRINT TO PDF (PREDETERMINADO)», que sirve igual para
    la etiqueta — lo que se audita es la llamada al agente, no el papel."""
    tipo = tipo or TIPO_IMPRESION
    if not await _elegir_tipo_impresion(page, modal, tipo):
        # El modal SIEMPRE trae un tipo válido preseleccionado. Si no se pudo
        # elegir el pedido, NO se falla: se cierra cualquier panel abierto y se
        # sigue a Imprimir con el default (la etiqueta audita la llamada al
        # agente, no el tipo de papel).
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        logger.warning("[Reimpresión] No pude elegir el tipo '%s'; se conserva "
                       "el que trae el modal por defecto y se continúa a "
                       "Imprimir.", tipo)

    impresora = impresora if impresora is not None else IMPRESORA
    if impresora:
        combo_imp = await _combo_por_etiqueta(page, modal, ETIQUETAS_IMPRESORA)
        if combo_imp is None:
            combos = await _visibles(modal, "div.p-dropdown", limite=6)
            combo_imp = combos[-1] if len(combos) > 1 else None
        if combo_imp is None or not await _elegir_en_combo(page, combo_imp, impresora):
            logger.warning("[Reimpresión] Sigo con la impresora por defecto.")
    else:
        combo_imp = await _combo_por_etiqueta(page, modal, ETIQUETAS_IMPRESORA)
        if combo_imp is not None:
            logger.info("[Reimpresión] Impresora por defecto: '%s'.",
                        await _valor_actual(combo_imp) or "(sin nombre)")
    return True


# ═══════════════════════════════════════════════════════════════════════════
# 4. Pulsar Imprimir
# ═══════════════════════════════════════════════════════════════════════════

async def pulsar_imprimir(page, modal) -> bool:
    """Pulsa «Imprimir» del modal, esperando a que esté HABILITADO.

    Se espera habilitado y no solo visible: un clic sobre un botón deshabilitado
    no hace nada y el caso moría después, esperando un modal que nunca abrió."""
    espera = 0
    while espera <= TIMEOUT:
        for sel in BTN_SELECTOR:
            try:
                botones = modal.locator(sel)
                total = min(await botones.count(), 12)
            except Exception:
                continue
            for i in range(total):
                el = botones.nth(i)
                try:
                    if not await el.is_visible():
                        continue
                    texto = ((await el.inner_text()) or "").strip()
                    if not RE_BTN_IMPRIMIR.search(texto):
                        continue
                    if RE_BTN_CANCELAR.search(texto):
                        continue
                    if not await el.is_enabled():
                        continue
                except Exception:
                    continue
                if await _click(el, timeout=8_000):
                    logger.info("[Reimpresión] ✓ Botón '%s' pulsado — la "
                                "petición va camino del Hardware Agent.", texto)
                    return True
        await page.wait_for_timeout(300)
        espera += 300
    logger.warning("[Reimpresión] El botón 'Imprimir' no llegó a estar "
                   "habilitado en %.0f s.", TIMEOUT / 1000)
    return False


async def leer_aviso_posterior(page, timeout_ms: int = 8_000) -> str:
    """Devuelve el texto del aviso que sale tras imprimir (suele ser un error).

    NO se trata como fallo: el error aparece DESPUÉS de que la petición salió
    hacia el agente, así que la comunicación —lo único que audita esta
    etiqueta— ya ocurrió. Se registra como nota del reporte."""
    espera = 0
    while espera <= timeout_ms:
        for sel in MODAL:
            for el in await _visibles(page, sel, limite=8):
                try:
                    texto = ((await el.inner_text()) or "").strip()
                except Exception:
                    continue
                # El propio modal de impresión también casa; se descarta por
                # sus combos.
                try:
                    if await el.locator("div.p-dropdown").count():
                        continue
                except Exception:
                    pass
                if texto:
                    return " ".join(texto.split())[:300]
        await page.wait_for_timeout(300)
        espera += 300
    return ""


async def cerrar_aviso(page, timeout_ms: int = 6_000) -> bool:
    """Cierra el aviso posterior (Accept/OK/Cerrar o la X).

    Importa dejarlo cerrado: sus overlays se comen los clics del resto de la
    pantalla y el siguiente caso empezaría agotando timeouts."""
    espera = 0
    while espera <= timeout_ms:
        candidatos = [
            '[data-testid="modal-notification-message-button"]',
            '[data-testid="modal-confirmation-confirm-button"]',
            "div[role='dialog'] button", ".p-dialog button",
            "div.modal-content button",
        ]
        for sel in candidatos:
            for el in await _visibles(page, sel, limite=12):
                try:
                    texto = ((await el.inner_text()) or "").strip()
                except Exception:
                    texto = ""
                # Se exige texto reconocible: pulsar un botón sin texto dentro
                # de un modal es una lotería (podría ser 'Reintentar' o el
                # propio 'Imprimir'). Para los botones de icono está la X, más
                # abajo.
                if not texto or not RE_ACEPTAR.search(texto):
                    continue
                if await _click(el, timeout=4_000):
                    logger.info("[Reimpresión] Aviso posterior cerrado%s.",
                                f" con '{texto}'" if texto else "")
                    await page.wait_for_timeout(600)
                    return True
        # La X del diálogo
        for el in await _visibles(page, ".p-dialog-header-close, "
                                        "[data-testid*='close-icon']", limite=6):
            if await _click(el, timeout=3_000):
                logger.info("[Reimpresión] Aviso posterior cerrado con la X.")
                await page.wait_for_timeout(600)
                return True
        await page.wait_for_timeout(300)
        espera += 300
    return False


# ═══════════════════════════════════════════════════════════════════════════
# Flujo completo
# ═══════════════════════════════════════════════════════════════════════════

async def reimprimir(flow, *, evi=None, paso: int = None, row_index: int = 0,
                     tipo: str = None, impresora: str = None):
    """Reimprime el recibo de una transacción del historial.

    Devuelve `(ok, detalle)`:
      • `ok=True`  → la petición de impresión SALIÓ (el error posterior, si
        aparece, va en `detalle`).
      • `ok=False` → no se llegó a pulsar Imprimir; `detalle` dice dónde se
        quedó, para no tener que reconstruirlo del log.

    Espera que la página ya esté en Reportes > Transacciones (lo hace
    `transacciones.ir_a_reportes_transacciones`)."""
    page = flow.page
    # Un diálogo interpuesto bloquea la tabla: buscar contra un overlay agota
    # el timeout y devuelve cero filas, como si el historial estuviera vacío.
    await _MOD.atender_bloqueantes(flow, logger)

    filas = await buscar(flow)
    if not filas:
        return False, ("El historial no tiene transacciones que reimprimir. "
                       "Corre antes un envío (CP01) o amplía el rango de fechas "
                       "del reporte.")
    if evi is not None:
        await evi.shot("historial_transacciones", paso=paso, selector=FILAS[0])

    if not await elegir_imprimir_recibo(flow, row_index):
        if evi is not None:
            await evi.shot("menu_sin_imprimir_recibo", paso=paso)
        return False, ("No se pudo pulsar 'Imprimir Recibo' en el menú de la "
                       "transacción (ver en el log las opciones que sí había).")

    modal = await _esperar_modal(page)
    if modal is None:
        if evi is not None:
            await evi.shot("modal_impresion_no_abrio", paso=paso)
        return False, ("La opción se pulsó pero el modal de impresión no abrió "
                       "en 15 s.")
    logger.info("[Reimpresión] Modal de impresión abierto.")
    if evi is not None:
        await evi.shot("modal_impresion", paso=paso, locators=[modal])

    if not await configurar_impresion(page, modal, tipo=tipo, impresora=impresora):
        if evi is not None:
            await evi.shot("tipo_impresion_fallo", paso=paso)
        return False, (f"No se pudo elegir el tipo de impresión "
                       f"'{tipo or TIPO_IMPRESION}' (ver opciones en el log).")
    if evi is not None:
        await evi.shot("tipo_impresion_windows_printer", paso=paso,
                       locators=[modal])

    if not await pulsar_imprimir(page, modal):
        if evi is not None:
            await evi.shot("boton_imprimir_no_habilitado", paso=paso)
        return False, "El botón 'Imprimir' del modal nunca se habilitó."

    await page.wait_for_timeout(2_500)
    aviso = await leer_aviso_posterior(page)
    if evi is not None:
        await evi.shot("impresion_disparada", paso=paso)
    if aviso:
        logger.info("[Reimpresión] Aviso posterior (esperado, no invalida el "
                    "caso): %s", aviso)
        await cerrar_aviso(page)
        return True, (f"Petición de impresión enviada. La app respondió: "
                      f"«{aviso}» — esperado: el error ocurre DESPUÉS de que la "
                      f"petición salió hacia el agente.")
    return True, "Petición de impresión enviada sin avisos posteriores."
