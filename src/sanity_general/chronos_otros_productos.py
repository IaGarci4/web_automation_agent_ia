"""
Chronos — Other Products > Search Other Products > pestaña **Check**.

## Para qué existe

Un cheque procesado en Hermes **no se puede cancelar desde Hermes**: el menú
kebab del reporte de transacciones no ofrece la opción `Cancel` para el tipo
CHECKS (comprobado en CP03: el menú abre, la opción no está, y el cheque queda
vivo en TEST). La baja se hace en Chronos, rechazándolo por el emisor.

## Ruta real (verificada contra la app)

    Menu → Other Products → Search Other Products → pestaña Check
      → Agent: se elige en un MODAL («Search Agent»), no se teclea
      → Check Number: <número>  → Search
      → clic en la fila del resultado                    → Check Detail
      → pestaña Issuer
      → en la tabla de Status, clic en la fila «Edited Checks Hold»
                                                          → Edited Checks
      → Reason: <cualquiera de la lista> → Reject → Close
      → Go Back ×2
      → validar Status = Rejected (la columna queda a la derecha)

## Dos cosas que NO eran como parecían

1. **`Edited Checks Hold` no es una pestaña**: es una FILA de la tabla de
   Status dentro de Issuer. Buscarla entre las pestañas no la encuentra nunca.

2. **En la lista de Reason NO existe «Other»**. Las opciones son concretas
   (`Altered Check`, `Amount Discrepancy`, `Unreadable MICR`…). Pedir un motivo
   inexistente hace fallar `select_option`, así que si el configurado no está
   se toma **la primera opción real** y se deja escrito en el log cuál se usó.

## Aviso sobre los selectores

Chronos no usa `data-testid`. Aquí los campos se localizan **por su etiqueta
visible** (`Check Number:`, `Reason:`) con XPath `label → siguiente input`, que
es lo único verificable mirando la pantalla y no depende de nombres de atributo
que no podemos comprobar. Cada paso que falla deja una captura y nombra en el
log la constante a ajustar.
"""

import re

from config import settings
from config.logger import get_logger
from src.sanity_general import chronos as CH

logger = get_logger("sanity.chronos.otros")

TIMEOUT = CH.TIMEOUT

# ── Navegación ──────────────────────────────────────────────────────────────
TOOLBAR_MENU      = CH.TOOLBAR_MENU
RE_OTHER_PROD     = re.compile(r"other\s*products", re.I)
OTHER_PRODUCTS    = ("//mat-panel-title[contains(translate(text(),"
                     "'OTHERPRDUCS','otherprducs'),'other product')]")
SEARCH_OTHER_LINK = ("a[href*='search-other-products'], "
                     "a[href*='other-products/search'], "
                     "a[href*='searchotherproducts']")
RE_SEARCH_OTHER   = re.compile(r"search\s*other\s*products", re.I)

# ── Pestañas ────────────────────────────────────────────────────────────────
TABS         = ("a[role='tab'], ul.nav-tabs a, li.nav-item a, .mat-tab-label, "
                ".nav-link, a.nav-item")
RE_TAB_CHECK = re.compile(r"^\s*check\s*$", re.I)
RE_TAB_ISSUER = re.compile(r"^\s*issuer\s*$", re.I)

# ── Modal «Search Agent» ────────────────────────────────────────────────────
RE_MODAL_AGENTE = re.compile(r"search\s*agent", re.I)
MODAL           = "div.modal-content, .modal-dialog, div[role='dialog']"

# ── Botones ─────────────────────────────────────────────────────────────────
BOTONES       = "button, input[type='submit'], a.btn"
RE_BTN_SEARCH = re.compile(r"^\s*(search|buscar)\s*$", re.I)
RE_BTN_REJECT = re.compile(r"^\s*(reject|rechazar)\s*$", re.I)
RE_GO_BACK    = re.compile(r"go\s*back|regresar|volver|atr[aá]s", re.I)
RE_CLOSE      = re.compile(r"^\s*(close|cerrar|ok|aceptar)\s*$", re.I)

# ── Tablas ──────────────────────────────────────────────────────────────────
FILAS = ("table tbody tr:not(.handle), "
         "p-table table.ui-table-scrollable-body-table tbody tr:not(.handle)")
RE_COL_NUM_CHECK = re.compile(r"number\s*check|check\s*number", re.I)
RE_COL_STATUS    = re.compile(r"^\s*status\s*$", re.I)
RE_REJECTED      = re.compile(r"reject", re.I)
RE_EDITED_HOLD   = re.compile(r"edited\s*checks?\s*hold", re.I)


# ── Utilidades ──────────────────────────────────────────────────────────────

async def _click_por_texto(page, patron, *, selectores=BOTONES, desc="",
                           timeout=TIMEOUT, raiz=None) -> bool:
    """Clic en el primer elemento VISIBLE cuyo texto case con `patron`.

    `visible=true` no es cosmético: Chronos deja pestañas y botones de pantallas
    anteriores en el DOM, y `.first` engancharía uno oculto.
    """
    base = raiz if raiz is not None else page
    try:
        loc = base.locator(selectores).locator("visible=true").filter(
            has_text=patron).first
        await loc.wait_for(state="visible", timeout=timeout)
        await loc.scroll_into_view_if_needed()
        await loc.click(timeout=15_000)
        if desc:
            logger.info("[Chronos/Otros] %s", desc)
        return True
    except Exception as e:
        logger.warning("[Chronos/Otros] No pude pulsar %s: %s",
                       desc or patron.pattern, str(e)[:100])
        return False


def _campo_tras_etiqueta(page, etiqueta: str, tipo: str = "input"):
    """Localizador del campo que sigue a una ETIQUETA visible.

    Es la estrategia principal de este módulo. Los nombres de atributo de
    Chronos no se pueden verificar sin el DOM —adivinarlos costó una corrida
    entera buscando `input[name*="CheckNumber"]`, que no existe— pero el texto
    de la etiqueta sale en pantalla y no cambia.
    """
    xp = (f"//*[contains(normalize-space(.), '{etiqueta}')]"
          f"[not(.//*[contains(normalize-space(.), '{etiqueta}')])]"
          f"/following::{tipo}[1]")
    return page.locator(f"xpath={xp}").locator("visible=true").first


async def _captura_fallo(page, etapa: str, constante: str) -> None:
    """Deja una captura y dice QUÉ constante ajustar.

    Sin esto, un fallo de selector en una corrida completa solo deja un
    «no pude pulsar X» y hay que reproducir el caso entero para ver la
    pantalla. Con la captura y el nombre de la constante, el arreglo se hace
    mirando el archivo.
    """
    destino = (settings.EVIDENCE_DIR / "KRA-1527" / "chronos_fallos" /
               f"{etapa}.png")
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(destino), full_page=True)
        logger.warning("[Chronos/Otros] Pantalla del fallo → %s", destino)
    except Exception:
        pass
    logger.warning("[Chronos/Otros] Ajusta `%s` en "
                   "src/sanity_general/chronos_otros_productos.py", constante)


async def _indice_columna(page, patron) -> int:
    """Índice de la columna cuyo encabezado case con `patron` (-1 si no hay).

    Se DESCUBRE del encabezado en vez de fijarse: Chronos lee sus tablas por
    posición, y `chronos.py` ya documenta esa fragilidad del port original.
    """
    try:
        ths = page.locator("table thead th").locator("visible=true")
        for i in range(await ths.count()):
            if patron.search((await ths.nth(i).inner_text() or "").strip()):
                return i
    except Exception:
        pass
    return -1


# ── Navegación ──────────────────────────────────────────────────────────────

async def ir_a_buscar_otros_productos(page) -> bool:
    """Menu → Other Products → Search Other Products."""
    try:
        await CH._click_listo(page, page.locator(TOOLBAR_MENU).first, "Menu abierto")
    except Exception as e:
        logger.warning("[Chronos/Otros] No abrió el Menu: %s", str(e)[:90])
        return False

    if not await _click_por_texto(
            page, RE_OTHER_PROD,
            selectores="mat-panel-title, .mat-expansion-panel-header, a, span",
            desc="Other Products", timeout=30_000):
        try:
            await CH._click_listo(page, page.locator(OTHER_PRODUCTS).first,
                                  "Other Products (xpath)")
        except Exception:
            return False

    try:
        link = page.locator(SEARCH_OTHER_LINK).locator("visible=true").first
        await link.wait_for(state="visible", timeout=20_000)
        await link.click(timeout=15_000)
        logger.info("[Chronos/Otros] Search Other Products (href)")
    except Exception:
        if not await _click_por_texto(page, RE_SEARCH_OTHER,
                                      selectores="a, span, li",
                                      desc="Search Other Products (texto)"):
            return False

    try:
        await page.wait_for_load_state("networkidle", timeout=30_000)
    except Exception:
        pass
    logger.info("[Chronos/Otros] Buscador de otros productos abierto.")
    return True


async def abrir_pestana_check(page) -> bool:
    """Activa la pestaña **Check** del buscador."""
    ok = await _click_por_texto(page, RE_TAB_CHECK, selectores=TABS,
                                desc="Pestaña Check", timeout=60_000)
    if ok:
        await page.wait_for_timeout(1_500)
    return ok


# ── Formulario de búsqueda ──────────────────────────────────────────────────

async def elegir_agente(page, codigo: str) -> bool:
    """Elige el agente en el modal «Search Agent».

    El campo Agent es de solo lectura: al lado tiene un icono que abre un modal
    con su propio buscador y una tabla de resultados. Se teclea el código
    (`0040`) y se pulsa la fila (`0040-OK`). Si el campo ya trae un agente
    —porque la sesión lo fija— no se toca.
    """
    campo = _campo_tras_etiqueta(page, "Agent:")
    try:
        if await campo.count() and (await campo.input_value() or "").strip():
            logger.info("[Chronos/Otros] Agente ya fijado: '%s'",
                        (await campo.input_value()).strip())
            return True
    except Exception:
        pass

    # El icono que abre el modal es el primer accionable tras la etiqueta.
    abierto = False
    for tipo in ("button", "i", "span", "a", "img"):
        try:
            icono = _campo_tras_etiqueta(page, "Agent:", tipo=tipo)
            if await icono.count():
                await icono.click(timeout=10_000)
                modal = page.locator(MODAL).locator("visible=true").filter(
                    has_text=RE_MODAL_AGENTE).first
                await modal.wait_for(state="visible", timeout=15_000)
                abierto = True
                logger.info("[Chronos/Otros] Modal 'Search Agent' abierto (%s).",
                            tipo)
                break
        except Exception:
            continue
    if not abierto:
        logger.warning("[Chronos/Otros] No se abrió el modal 'Search Agent'.")
        return False

    modal = page.locator(MODAL).locator("visible=true").filter(
        has_text=RE_MODAL_AGENTE).first
    try:
        inp = modal.locator("input[type='text'], input:not([type])").locator(
            "visible=true").first
        await inp.click()
        await inp.fill("")
        await inp.type(str(codigo).split("-")[0], delay=90)
        await page.wait_for_timeout(2_500)
    except Exception as e:
        logger.warning("[Chronos/Otros] No pude teclear el agente: %s", str(e)[:90])
        return False

    # La fila cuyo Agent Code empieza por el código buscado.
    try:
        filas = modal.locator("table tbody tr").locator("visible=true")
        await filas.first.wait_for(state="visible", timeout=20_000)
        for i in range(min(await filas.count(), 20)):
            fila = filas.nth(i)
            primera = (await fila.locator("td").first.inner_text() or "").strip()
            if primera.upper().startswith(str(codigo).split("-")[0].upper()):
                await fila.click(timeout=10_000)
                await page.wait_for_timeout(2_000)
                logger.info("[Chronos/Otros] Agente '%s' seleccionado.", primera)
                return True
        logger.warning("[Chronos/Otros] Ninguna fila de agente empieza por %s.",
                       codigo)
    except Exception as e:
        logger.warning("[Chronos/Otros] Error eligiendo el agente: %s", str(e)[:90])
    return False


async def buscar_cheque(page, *, numero_cheque: str,
                        agencia: str = None) -> bool:
    """Elige el agente (si hace falta), escribe el número y pulsa Search."""
    if agencia:
        await elegir_agente(page, agencia)      # best effort: no bloquea

    try:
        campo = _campo_tras_etiqueta(page, "Check Number")
        await campo.wait_for(state="visible", timeout=45_000)
        await campo.click()
        await campo.fill("")
        await campo.type(str(numero_cheque), delay=80)
        logger.info("[Chronos/Otros] Check Number = %s", numero_cheque)
    except Exception as e:
        logger.warning("[Chronos/Otros] No encontré el campo Check Number "
                       "por su etiqueta: %s", str(e)[:100])
        return False

    if not await _click_por_texto(page, RE_BTN_SEARCH, desc="Search pulsado"):
        return False
    await page.wait_for_timeout(2_500)
    try:
        await page.wait_for_load_state("networkidle", timeout=30_000)
    except Exception:
        pass
    return True


def _celda_con_valor(page, valor: str):
    """Celda cuyo texto es EXACTAMENTE `valor`.

    Chronos pinta el dato en un `<div>` DENTRO del `<td>`:

        <td class="p-1 ui-resizable-column ng-star-inserted">
          <div class="ng-star-inserted"> 839241 </div>
        </td>

    Recorrer filas leyendo celdas por índice de columna no lo encontraba y
    además gastaba la espera entera. Buscar el valor y subir a su fila es más
    corto, más rápido y no depende del orden de las columnas — que en esta
    tabla, además, cambia con el scroll horizontal.
    """
    patron = re.compile(rf"^\s*{re.escape(str(valor))}\s*$")
    return page.locator("td").filter(has_text=patron).locator(
        "visible=true").first


async def abrir_registro(page, numero_cheque: str,
                         timeout: int = 25_000) -> bool:
    """Clic en el registro del resultado cuyo número de cheque coincide.

    `timeout` corto a propósito: si la búsqueda devolvió algo, la fila está
    pintada en segundos. Esperar 60 s solo alargaba el fallo.
    """
    celda = _celda_con_valor(page, numero_cheque)
    try:
        await celda.wait_for(state="visible", timeout=timeout)
    except Exception:
        # Diagnóstico útil: decir QUÉ se ve, no solo que no está lo buscado.
        try:
            filas = page.locator(FILAS).locator("visible=true")
            n = await filas.count()
            muestra = ""
            if n:
                muestra = " | ".join(
                    (await filas.first.inner_text() or "").split("\n"))[:160]
            logger.warning("[Chronos/Otros] El cheque %s no aparece. La tabla "
                           "tiene %d fila(s) visible(s). Primera: %s",
                           numero_cheque, n, muestra or "(vacía)")
        except Exception:
            logger.warning("[Chronos/Otros] El cheque %s no aparece y no pude "
                           "leer la tabla.", numero_cheque)
        return False

    # Subir de la celda a su fila: el clic sobre la fila es lo que abre el
    # detalle (así se hace a mano).
    fila = celda.locator("xpath=ancestor::tr[1]")
    try:
        await fila.scroll_into_view_if_needed()
    except Exception:
        pass
    destino = fila if await fila.count() else celda
    await CH._click_listo(page, destino, f"Registro del cheque {numero_cheque}")

    # Confirmar que se abrió el detalle en vez de asumirlo: si el clic no
    # navegó, el resto del flujo fallaría en cascada con mensajes confusos.
    try:
        await page.locator(TABS).locator("visible=true").filter(
            has_text=RE_TAB_ISSUER).first.wait_for(state="visible",
                                                   timeout=30_000)
        logger.info("[Chronos/Otros] Check Detail abierto.")
    except Exception:
        logger.warning("[Chronos/Otros] Se pulsó el registro pero no apareció "
                       "el detalle (no veo la pestaña Issuer).")
        return False
    return True


# ── Detalle del cheque ──────────────────────────────────────────────────────

async def abrir_pestana_issuer(page) -> bool:
    """Pestaña **Issuer** del Check Detail."""
    ok = await _click_por_texto(page, RE_TAB_ISSUER, selectores=TABS,
                                desc="Pestaña Issuer", timeout=45_000)
    if ok:
        await page.wait_for_timeout(2_000)
    return ok


async def abrir_edited_checks_hold(page) -> bool:
    """Clic en «Edited Checks Hold» de la tabla de Status (dentro de Issuer).

    Dos correcciones que costaron una corrida cada una:

    1. NO es una pestaña, es una fila de la tabla `Status | Date Of
       Validation | Released | Rejected`.

    2. El accionable es el **`div.handle`** interno, no el `<td>`:

           <td class="p-1 ui-resizable-column ng-star-inserted">
             <div class="handle ng-star-inserted"> Edited Checks Hold </div>
           </td>

       Al pulsar el `<td>` el clic no dispara nada — el log decía «abierto» y
       la pantalla seguía en Issuer, así que el paso siguiente encontraba un
       `select` de Reason vacío y el fallo aparecía dos pasos más allá de su
       causa. Por eso ahora, además, se CONFIRMA la navegación.
    """
    candidatos = [
        ("div.handle", "div.handle"),                 # el accionable real
        ("td div, th div", "div dentro de la celda"),
        ("a, span, td", "celda o enlace"),            # último recurso
    ]
    pulsado = False
    for selector, desc in candidatos:
        try:
            loc = page.locator(selector).locator("visible=true").filter(
                has_text=RE_EDITED_HOLD).first
            await loc.wait_for(state="visible", timeout=20_000)
            await loc.scroll_into_view_if_needed()
            await loc.click(timeout=12_000)
            logger.info("[Chronos/Otros] 'Edited Checks Hold' pulsado (%s).", desc)
            pulsado = True
        except Exception:
            continue

        # ¿Navegó de verdad? El marcador de la pantalla «Edited Checks» es el
        # botón Reject. Sin esta comprobación, un clic que no hace nada se
        # daba por bueno.
        try:
            await page.locator(BOTONES).locator("visible=true").filter(
                has_text=RE_BTN_REJECT).first.wait_for(state="visible",
                                                       timeout=20_000)
            logger.info("[Chronos/Otros] Pantalla 'Edited Checks' abierta.")
            return True
        except Exception:
            logger.info("[Chronos/Otros] El clic en %s no abrió la pantalla — "
                        "pruebo el siguiente selector.", desc)

    if pulsado:
        logger.warning("[Chronos/Otros] Se pulsó 'Edited Checks Hold' pero no "
                       "apareció el botón Reject: la pantalla no cambió.")
    else:
        logger.warning("[Chronos/Otros] No encontré 'Edited Checks Hold' en la "
                       "tabla de Status.")
    return False


async def _leer_check_number_detalle(page, timeout: int = 10_000) -> str:
    """Check Number del detalle, leído por su etiqueta. '' si no se puede.

    Es una comprobación de seguridad, no un paso del flujo: si no se puede
    leer, se continúa. Por eso el margen es corto — bloquear aquí sería pagar
    minutos por un dato que igualmente se ignora cuando falta.
    """
    try:
        campo = _campo_tras_etiqueta(page, "Check Number")
        await campo.wait_for(state="visible", timeout=timeout)
        valor = ((await campo.input_value()) or "").strip()
        if not valor:
            valor = ((await campo.inner_text()) or "").strip()
        if valor:
            logger.info("[Chronos/Otros] Check Number del detalle: %s", valor)
        return valor
    except Exception:
        logger.info("[Chronos/Otros] No pude leer el Check Number del detalle "
                    "— continúo (es solo una comprobación).")
        return ""


async def elegir_motivo(page, motivo: str = None) -> str:
    """Selecciona el Reason. Devuelve el motivo usado ('' si no pudo).

    El catálogo trae 20 motivos, «Other» entre ellos (es el que usa
    KRA1527_CHEQUE_MOTIVO por defecto). Si el configurado no estuviera, se
    toma la primera opción real: para una limpieza de prueba cualquiera
    sirve, y fallar por el nombre del motivo dejaría el cheque vivo sin
    necesidad.
    """
    # Se prueban varios localizadores y se acepta el PRIMERO QUE TENGA
    # OPCIONES. Un `select` vacío significa que enganchamos otro control de la
    # pantalla: la versión anterior lo daba por bueno y fallaba diciendo «el
    # select no tiene opciones», que apunta a la app cuando el error era el
    # selector.
    # ORDEN medido, no supuesto: `formcontrolname="IdRejectReason"` es el que
    # acierta en esta pantalla. Tenerlo en segundo lugar costaba 30 s por
    # corrida —15 s agotando la búsqueda por etiqueta y 15 más hasta dar con
    # él—. Los respaldos siguen ahí por si la app cambia, pero ya no se pagan
    # en el camino normal.
    sel, opciones = None, []
    candidatos = [
        (lambda: page.locator(CH.REJECT_REASON_SEL).locator("visible=true").first,
         "formcontrolname IdRejectReason"),
        (lambda: _campo_tras_etiqueta(page, "Reason", tipo="select"),
         "etiqueta 'Reason'"),
        (lambda: page.locator("select").locator("visible=true").first,
         "primer select visible"),
    ]
    for hacer, desc in candidatos:
        try:
            cand = hacer()
            # Corto: si el localizador es el bueno, el control ya está pintado
            # (venimos de confirmar que la pantalla 'Edited Checks' abrió).
            await cand.wait_for(state="visible", timeout=8_000)
            textos = []
            for o in await cand.locator("option").all():
                txt = (await o.inner_text() or "").strip()
                if txt:
                    textos.append(txt)
            if textos:
                sel, opciones = cand, textos
                logger.info("[Chronos/Otros] Select de Reason por %s "
                            "(%d opciones).", desc, len(textos))
                break
            logger.info("[Chronos/Otros] El select por %s está vacío — "
                        "pruebo el siguiente.", desc)
        except Exception:
            continue

    if sel is None:
        logger.warning("[Chronos/Otros] No encontré un select de Reason con "
                       "opciones. ¿Se abrió la pantalla 'Edited Checks'?")
        return ""

    elegido = None
    if motivo and motivo in opciones:
        elegido = motivo
    elif motivo:
        logger.info("[Chronos/Otros] El motivo '%s' no está en la lista "
                    "(%d opciones). Se usa la primera disponible.",
                    motivo, len(opciones))
    if elegido is None and opciones:
        elegido = opciones[0]
    if not elegido:
        logger.warning("[Chronos/Otros] El select de Reason no tiene opciones.")
        return ""

    try:
        await sel.select_option(label=elegido)
        logger.info("[Chronos/Otros] Reason = '%s'", elegido)
        return elegido
    except Exception as e:
        logger.warning("[Chronos/Otros] No pude seleccionar '%s': %s",
                       elegido, str(e)[:90])
        return ""


async def pulsar_reject(page) -> bool:
    """Pulsa **Reject** y cierra el modal de confirmación que salga."""
    if not await _click_por_texto(page, RE_BTN_REJECT, desc="Reject pulsado",
                                  timeout=30_000):
        return False
    await page.wait_for_timeout(3_000)
    # Chronos confirma con un modal; da igual si dice éxito o error, aquí solo
    # se cierra: el veredicto real lo da el Status del listado.
    error = await CH._leer_modal_error(page, timeout_ms=5_000)
    if error:
        logger.warning("[Chronos/Otros] Chronos rechazó la operación: %s",
                       error[:160])
        await CH.cerrar_modal_error(page)
        return False
    await _click_por_texto(page, RE_CLOSE, desc="Modal cerrado", timeout=20_000)
    await page.wait_for_timeout(2_000)
    return True


async def volver(page, veces: int = 2) -> None:
    """Pulsa **Go Back** `veces` (el flujo pide dos para llegar al listado)."""
    for i in range(1, veces + 1):
        if not await _click_por_texto(page, RE_GO_BACK,
                                      selectores=f"{BOTONES}, a",
                                      desc=f"Go Back ({i}/{veces})",
                                      timeout=30_000):
            break
        await page.wait_for_timeout(2_500)


async def leer_status(page, numero_cheque: str, timeout: int = 25_000) -> str:
    """Status del cheque en el listado. '' si no se pudo leer.

    Se localiza la fila por el número (igual que `abrir_registro`) y luego la
    celda de Status por el índice de su encabezado, haciendo scroll horizontal
    porque esa columna queda fuera de la vista inicial.
    """
    celda_num = _celda_con_valor(page, numero_cheque)
    try:
        await celda_num.wait_for(state="visible", timeout=timeout)
    except Exception:
        logger.warning("[Chronos/Otros] No encuentro el cheque %s en el "
                       "listado para leer su status.", numero_cheque)
        return ""

    fila = celda_num.locator("xpath=ancestor::tr[1]")
    col = await _indice_columna(page, RE_COL_STATUS)
    try:
        if col >= 0:
            celda = fila.locator("td").nth(col)
            await celda.scroll_into_view_if_needed()
            valor = (await celda.inner_text() or "").strip()
        else:
            # Sin encabezado 'Status' reconocible: buscar el estado en la fila.
            texto = await fila.inner_text() or ""
            m = RE_REJECTED.search(texto)
            valor = m.group(0) if m else ""
        logger.info("[Chronos/Otros] Status del cheque %s = '%s'",
                    numero_cheque, valor)
        return valor
    except Exception as e:
        logger.warning("[Chronos/Otros] No pude leer el status: %s", str(e)[:90])
        return ""


# ── Flujo completo ──────────────────────────────────────────────────────────

async def rechazar_cheque(page, *, numero_cheque: str, agencia: str = None,
                          motivo: str = None, evi=None, paso: int = None):
    """Rechaza el cheque en Chronos. Devuelve `(ok, detalle)`.

    `ok=True` solo si el Status queda en **Rejected**: el modal de Chronos
    confirma que aceptó la orden, no que el registro cambió de estado. Esa
    distinción es la que evita dar por limpio un cheque que sigue vivo.
    """
    if not await CH.abrir_chronos(page):
        return False, "No se pudo abrir Chronos (sesión/login)."

    if not await ir_a_buscar_otros_productos(page):
        await _captura_fallo(page, "01_menu_other_products",
                             "OTHER_PRODUCTS / SEARCH_OTHER_LINK")
        return False, "No se llegó a Search Other Products."
    if not await abrir_pestana_check(page):
        await _captura_fallo(page, "02_pestana_check", "RE_TAB_CHECK / TABS")
        return False, "No se pudo abrir la pestaña Check."

    agencia = agencia or getattr(settings, "AGENCY_CODE", None)
    if not await buscar_cheque(page, numero_cheque=numero_cheque,
                               agencia=agencia):
        await _captura_fallo(page, "03_formulario_busqueda",
                             "_campo_tras_etiqueta('Check Number') / RE_BTN_SEARCH")
        return False, f"No se pudo buscar el cheque {numero_cheque}."
    if not await abrir_registro(page, numero_cheque):
        await _captura_fallo(page, "04_resultado_busqueda",
                             "FILAS / RE_COL_NUM_CHECK")
        return False, (f"El cheque {numero_cheque} no apareció en el buscador "
                       f"de Chronos.")

    if not await abrir_pestana_issuer(page):
        await _captura_fallo(page, "05_pestana_issuer", "RE_TAB_ISSUER / TABS")
        return False, "No se pudo abrir la pestaña Issuer."

    # Confirmación de que estamos en el cheque correcto, antes de rechazar nada.
    #
    # NO se usa `CH.leer_check_number_issuer`: ese busca
    # `input[name="CheckNumberIssuerEdited"]`, que existe en la OTRA pantalla
    # de Chronos (Processing > Edited Checks). Aquí no está, y con el timeout
    # de 120 s de ese módulo se perdían dos minutos por corrida para acabar
    # ignorando el resultado. Se lee por etiqueta y con margen corto.
    leido = await _leer_check_number_detalle(page)
    if leido and leido.replace(",", "") != str(numero_cheque):
        logger.warning("[Chronos/Otros] ⚠ El detalle abierto es del cheque %s, "
                       "no del %s — abortando para no rechazar el cheque "
                       "equivocado.", leido, numero_cheque)
        return False, (f"Detalle equivocado: se abrió {leido} en lugar de "
                       f"{numero_cheque}.")

    if not await abrir_edited_checks_hold(page):
        await _captura_fallo(page, "06_edited_checks_hold", "RE_EDITED_HOLD")
        return False, "No se encontró la fila 'Edited Checks Hold'."

    usado = await elegir_motivo(page, motivo)
    if not usado:
        await _captura_fallo(page, "07_reason", "_campo_tras_etiqueta('Reason')")
        return False, "No se pudo seleccionar el Reason."

    if not await pulsar_reject(page):
        await _captura_fallo(page, "08_reject", "RE_BTN_REJECT")
        return False, "Chronos no aceptó el rechazo."

    await volver(page, veces=2)

    status = await leer_status(page, numero_cheque)
    if evi is not None:
        try:
            await evi.shot("cheque_rechazado_chronos", paso=paso)
        except Exception:
            pass
    if RE_REJECTED.search(status or ""):
        return True, f"Rechazado en Chronos (motivo '{usado}', status '{status}')."
    await _captura_fallo(page, "09_status_final", "RE_GO_BACK / RE_COL_STATUS")
    return False, (f"Se rechazó con motivo '{usado}' pero el status quedó en "
                   f"'{status or '(no leído)'}' en lugar de Rejected.")
