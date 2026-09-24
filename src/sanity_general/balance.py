"""
Reportes de Balance (Hermes) — CP12.

Dos reportes distintos bajo el menú Reportes:
  • BALANCE CONTINUO — tarjetas de resumen, menú de opciones (Ver / Imprimir /
    Exportar a PDF / Exportar a Excel), visor de PDF y descarga.
  • BALANCE POR CAJERO — estado vacío inicial y búsqueda por rango de fechas.

Notas de la pantalla:
  • Al entrar puede salir el modal 'Warning: ¿salir de esta página?' — se cierra
    igual que en el resto del sanity.
  • Varias piezas NO tienen data-testid (el tipo de reporte, las opciones del
    menú, el visor de PDF): van por CSS/XPath, que es lo que hay.
  • Las opciones del menú se identifican por POSICIÓN (li[1]..li[4]); por eso se
    valida que sean cuatro antes de pulsar, para no clickear a ciegas si el
    orden cambia.
"""

import os
import re

from config.logger import get_logger

logger = get_logger("sanity.balance")

TIMEOUT = 15_000

# ── Navegación ──────────────────────────────────────────────────────────────
NAVBAR_REPORTES = "reports-navbar-item"
DROPDOWN_BALANCE = "reports-0-navbar-dropdown-item"
DROPDOWN_CAJERO = "reports-1-navbar-dropdown-item"
MODAL_DENY = "modal-confirmation-deny-button"      # es el 'YES, Leave'
MODAL_CONTENIDO = "div.modal-content:visible, .modal.show"

# ── Balance Continuo: tarjetas de resultado ─────────────────────────────────
TOTAL_A_PAGAR = "total-to-pay-description-h4-heading"
BALANCE_FINAL = "final-balance-description-h4-heading"
RESUMEN_TRANSACCIONES = "transactions-summary-card-title-h5-heading"
MONEY_TRANSFERS = "money-transfers-card-title-h5-heading"
BTN_OPCIONES = "report-options-button"

# ── Tipo de reporte y búsqueda (sin testid) ─────────────────────────────────
# OJO: `id="dropdown"` está REPETIDO en la app (PrimeNG lo pone en cada
# p-dropdown), así que '#dropdown' + .first abría un control cualquiera y la
# opción '#dropdown_0' nunca aparecía. Se trabaja con el componente completo y
# se recorren los visibles.
TIPO_REPORTE = "p-dropdown"
OPCIONES_DROPDOWN = "li[role='option'], .p-dropdown-item, [role='option']"
RE_CONTINUO = re.compile(r"contin", re.I)          # CONTINUO / CONTINUOUS
BTN_BUSCAR = ".button.success.md"
RE_BUSCAR = re.compile(r"^\s*(search|buscar)\s*$", re.I)

# ── Menú de opciones (por posición) ─────────────────────────────────────────
OPCIONES_MENU = "//div/ul/li"
OPCION_VER, OPCION_IMPRIMIR, OPCION_PDF, OPCION_EXCEL = 0, 1, 2, 3

# ── Visor de PDF ────────────────────────────────────────────────────────────
VISOR_PDF = "//div[@class='pdfViewer removePageBorders']"
BOTONES_VISOR = ".btn.button-component.outline.BlueAccentTwo"

# ── Balance por Cajero ──────────────────────────────────────────────────────
CAJERO_MENSAJE_VACIO = ".h4-heading"
CAJERO_BTN_BUSCAR = "reports-by-cashier-search-button"
CAJERO_BTN_IMPRIMIR = "reports-by-cashier-print-button"

RE_YES_LEAVE = re.compile(r"yes.*leave|s[ií].*salir", re.I)


async def _modal_visible(page) -> bool:
    """True si el modal 'salir de esta página' está en pantalla."""
    for sel in (MODAL_CONTENIDO, f'[data-testid="{MODAL_DENY}"]'):
        try:
            if await page.locator(sel).first.is_visible():
                return True
        except Exception:
            continue
    return False


async def _cerrar_warning(page, timeout_ms: int = 3_000, vueltas: int = 3) -> bool:
    """Cierra el 'Warning: ¿salir de esta página?' y VERIFICA que se fue.

    Lo de verificar no es adorno: antes solo se clickeaba y se daba por hecho.
    Cuando el modal seguía ahí, su overlay bloqueaba el desplegable de tipo de
    reporte — y como el click va con force=True, 'funcionaba' sin efecto y las
    opciones nunca aparecían. El síntoma apuntaba al desplegable, no al modal."""
    cerrado = False
    for vuelta in range(1, vueltas + 1):
        # ¿Sigue ahí?
        if not await _modal_visible(page):
            return cerrado
        pulsado = False
        for loc, etiqueta in ((page.get_by_test_id(MODAL_DENY), "testid"),
                              (page.get_by_role("button", name=RE_YES_LEAVE), "texto"),
                              (page.locator("button").filter(has_text=RE_YES_LEAVE),
                               "texto (button)")):
            try:
                btn = loc.first
                if not await btn.is_visible():
                    continue
                await btn.click(force=True, timeout=3_000)
                pulsado = True
                logger.info("[Balance] Aviso de salida cerrado (%s, vuelta %d).",
                            etiqueta, vuelta)
                break
            except Exception:
                continue
        if not pulsado:
            break
        cerrado = True
        # Esperar a que DESAPAREZCA antes de seguir.
        espera = 0
        while espera <= timeout_ms:
            if not await _modal_visible(page):
                await page.wait_for_timeout(400)
                return True
            await page.wait_for_timeout(150)
            espera += 150
        logger.warning("[Balance] El aviso de salida sigue en pantalla tras la "
                       "vuelta %d — reintento.", vuelta)
    if await _modal_visible(page):
        logger.error("[Balance] No se pudo cerrar el aviso de salida; su overlay "
                     "va a bloquear los clics de la pantalla.")
    return cerrado


async def _abrir_reporte(page, dropdown_testid: str, desc: str) -> bool:
    """Reportes → <submenú>. Cierra el aviso de salida si sale."""
    try:
        await page.get_by_test_id(NAVBAR_REPORTES).first.click(force=True,
                                                               timeout=TIMEOUT)
        await page.wait_for_timeout(900)
        await page.get_by_test_id(dropdown_testid).first.click(force=True,
                                                               timeout=TIMEOUT)
        await _cerrar_warning(page)
        await page.wait_for_timeout(1_500)
        logger.info("[Balance] %s abierto.", desc)
        return True
    except Exception as e:
        logger.warning("[Balance] No se pudo abrir %s: %s", desc, str(e)[:100])
        return False


async def abrir_balance(page) -> bool:
    """Reportes → Balance."""
    return await _abrir_reporte(page, DROPDOWN_BALANCE, "Reportes > Balance")


async def abrir_balance_por_cajero(page) -> bool:
    """Reportes → Balance por Cajero."""
    return await _abrir_reporte(page, DROPDOWN_CAJERO,
                                "Reportes > Balance por Cajero")


async def _abrir_dropdown_tipo(page, timeout_ms: int = 10_000) -> bool:
    """Abre el desplegable de TIPO DE REPORTE y espera sus opciones.

    Se recorren todos los `p-dropdown` VISIBLES en vez de quedarse con el
    primero: la página tiene varios y el id 'dropdown' está repetido."""
    # Primero fuera el aviso de salida: su overlay come los clics del combo.
    await _cerrar_warning(page)
    dropdowns = page.locator(TIPO_REPORTE)
    try:
        total = min(await dropdowns.count(), 6)
    except Exception:
        total = 0
    for i in range(total):
        dd = dropdowns.nth(i)
        try:
            if not await dd.is_visible():
                continue
            await dd.click(force=True, timeout=5_000)
            await page.wait_for_timeout(700)
            if await page.locator(OPCIONES_DROPDOWN).count():
                logger.info("[Balance] Desplegable de tipo de reporte abierto "
                            "(#%d de %d).", i + 1, total)
                return True
            # ¿Apareció un modal que se tragó el click? Se cierra y se reintenta.
            if await _modal_visible(page):
                await _cerrar_warning(page)
                await dd.click(force=True, timeout=5_000)
                await page.wait_for_timeout(700)
                if await page.locator(OPCIONES_DROPDOWN).count():
                    logger.info("[Balance] Desplegable abierto tras cerrar el aviso.")
                    return True
            # No desplegó opciones: cerrarlo para no dejar la pantalla a medias.
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(300)
        except Exception:
            continue
    logger.warning("[Balance] Ningún desplegable (%d encontrados) mostró "
                   "opciones de tipo de reporte.", total)
    return False


async def _elegir_tipo_continuo(page) -> str:
    """Elige la opción CONTINUO del desplegable (o la primera). Devuelve su texto."""
    opciones = page.locator(OPCIONES_DROPDOWN)
    try:
        total = min(await opciones.count(), 20)
    except Exception:
        total = 0
    textos = []
    preferida = None
    for i in range(total):
        op = opciones.nth(i)
        try:
            if not await op.is_visible():
                continue
            texto = (await op.inner_text() or "").strip()
            textos.append(texto)
            if preferida is None and RE_CONTINUO.search(texto):
                preferida = (op, texto)
        except Exception:
            continue
    if preferida is None and textos:
        # Sin coincidencia por texto: la primera visible (como el sanity original).
        for i in range(total):
            op = opciones.nth(i)
            try:
                if await op.is_visible():
                    preferida = (op, (await op.inner_text() or "").strip())
                    break
            except Exception:
                continue
    if preferida is None:
        logger.warning("[Balance] El desplegable no ofreció opciones.")
        return ""
    op, texto = preferida
    await op.click(force=True, timeout=8_000)
    await page.wait_for_timeout(600)
    logger.info("[Balance] Tipo de reporte: '%s' (de %s).", texto,
                ", ".join(f"'{t}'" for t in textos[:6]) or "?")
    return texto


async def _pulsar_buscar(page) -> bool:
    """Pulsa el botón Buscar/Search del reporte."""
    candidatos = (
        page.get_by_role("button", name=RE_BUSCAR),
        page.locator(BTN_BUSCAR),
    )
    for loc in candidatos:
        try:
            total = min(await loc.count(), 6)
        except Exception:
            continue
        for i in range(total):
            btn = loc.nth(i)
            try:
                if not await btn.is_visible():
                    continue
                await btn.click(force=True, timeout=6_000)
                return True
            except Exception:
                continue
    logger.warning("[Balance] No encontré el botón Buscar del reporte.")
    return False


async def buscar_balance_continuo(page) -> bool:
    """Elige el tipo de reporte BALANCE CONTINUO y pulsa Buscar."""
    if not await _abrir_dropdown_tipo(page):
        return False
    if not await _elegir_tipo_continuo(page):
        return False
    if not await _pulsar_buscar(page):
        return False
    logger.info("[Balance] BALANCE CONTINUO — búsqueda lanzada.")
    await page.wait_for_timeout(4_000)
    return True


async def validar_tarjetas(page) -> dict:
    """Comprueba las tarjetas del resultado. Devuelve {nombre: visible}.

    'Balance final' se reporta pero NO se exige: no aparece en todos los tipos
    de reporte, y en el sanity original tampoco era bloqueante."""
    piezas = {
        "total_a_pagar": TOTAL_A_PAGAR,
        "resumen_transacciones": RESUMEN_TRANSACCIONES,
        "money_transfers": MONEY_TRANSFERS,
        "boton_opciones": BTN_OPCIONES,
        "balance_final": BALANCE_FINAL,          # informativo
    }
    estado = {}
    for nombre, testid in piezas.items():
        try:
            loc = page.get_by_test_id(testid).first
            await loc.wait_for(state="visible", timeout=TIMEOUT)
            estado[nombre] = True
        except Exception:
            estado[nombre] = False
    faltan = [n for n, ok in estado.items()
              if not ok and n != "balance_final"]
    if faltan:
        logger.warning("[Balance] Faltan tarjetas del reporte: %s", ", ".join(faltan))
    else:
        logger.info("[Balance] ✓ Tarjetas del reporte visibles%s.",
                    "" if estado["balance_final"] else " (sin 'Balance final')")
    return estado


async def abrir_opciones(page) -> int:
    """Abre el menú de opciones del reporte y devuelve cuántas tiene."""
    try:
        await page.get_by_test_id(BTN_OPCIONES).first.click(force=True,
                                                            timeout=TIMEOUT)
        await page.wait_for_timeout(800)
        total = await page.locator(OPCIONES_MENU).count()
        logger.info("[Balance] Menú de opciones abierto (%d opciones).", total)
        return total
    except Exception as e:
        logger.warning("[Balance] No se pudo abrir el menú de opciones: %s",
                       str(e)[:100])
        return 0


async def elegir_opcion(page, indice: int, desc: str) -> bool:
    """Pulsa una opción del menú por posición (0=Ver, 1=Imprimir, 2=PDF, 3=Excel)."""
    try:
        opcion = page.locator(OPCIONES_MENU).nth(indice)
        await opcion.wait_for(state="visible", timeout=8_000)
        texto = (await opcion.inner_text() or "").strip()
        await opcion.click(force=True, timeout=8_000)
        logger.info("[Balance] Opción '%s' pulsada (%s).", texto or desc, desc)
        await page.wait_for_timeout(2_500)
        return True
    except Exception as e:
        logger.warning("[Balance] No se pudo pulsar la opción %s: %s",
                       desc, str(e)[:100])
        return False


async def validar_visor_pdf(page, minimo_botones: int = 3) -> int:
    """Espera el visor de PDF y devuelve cuántos botones de acción tiene."""
    try:
        await page.locator(VISOR_PDF).first.wait_for(state="visible",
                                                     timeout=TIMEOUT)
    except Exception as e:
        logger.warning("[Balance] El visor de PDF no apareció: %s", str(e)[:90])
        return 0
    total = await page.locator(BOTONES_VISOR).count()
    if total < minimo_botones:
        logger.warning("[Balance] El visor tiene %d botón(es); se esperaban al "
                       "menos %d.", total, minimo_botones)
    else:
        logger.info("[Balance] ✓ Visor de PDF con %d botones.", total)
    return total


async def descargar_pdf(page, carpeta: str, nombre_defecto="balance.pdf") -> str:
    """Pulsa el primer botón del visor (Exportar a PDF) y guarda la descarga.

    Devuelve la ruta del archivo, o '' si no se pudo descargar."""
    os.makedirs(carpeta, exist_ok=True)
    try:
        async with page.expect_download(timeout=60_000) as info:
            await page.locator(BOTONES_VISOR).first.click(force=True,
                                                          timeout=TIMEOUT)
        descarga = await info.value
        destino = os.path.join(carpeta, descarga.suggested_filename or nombre_defecto)
        await descarga.save_as(destino)
        await page.wait_for_timeout(1_500)
        logger.info("[Balance] PDF guardado en %s", destino)
        return destino
    except Exception as e:
        logger.warning("[Balance] No se pudo descargar el PDF: %s", str(e)[:110])
        return ""


def texto_del_pdf(ruta: str) -> str:
    """Texto plano del PDF (cadena vacía si no se puede leer).

    Un PDF escaneado devuelve texto vacío; el caso lo trata como 'no
    verificable' en vez de fallar, igual que el sanity original."""
    try:
        import pypdf
    except ImportError:
        logger.warning("[Balance] pypdf no está instalado — no se valida el "
                       "contenido del PDF (pip install pypdf).")
        return ""
    try:
        lector = pypdf.PdfReader(ruta)
        return "".join(p.extract_text() or "" for p in lector.pages)
    except Exception as e:
        logger.warning("[Balance] No se pudo leer el PDF: %s", str(e)[:90])
        return ""


async def mensaje_vacio_cajero(page) -> str:
    """Texto del estado vacío de Balance por Cajero ('' si no aparece)."""
    try:
        loc = page.locator(CAJERO_MENSAJE_VACIO).first
        await loc.wait_for(state="visible", timeout=TIMEOUT)
        texto = (await loc.inner_text() or "").strip()
        logger.info("[Balance] Estado inicial por cajero: '%s'", texto[:70])
        return texto
    except Exception:
        logger.warning("[Balance] No apareció el mensaje de estado vacío.")
        return ""


async def buscar_por_cajero(page) -> bool:
    """Pulsa Buscar en Balance por Cajero y espera el resultado."""
    try:
        await page.get_by_test_id(CAJERO_BTN_BUSCAR).first.click(force=True,
                                                                 timeout=TIMEOUT)
        logger.info("[Balance] Búsqueda por cajero lanzada.")
        await page.wait_for_timeout(10_000)     # el reporte tarda en poblarse
        return True
    except Exception as e:
        logger.warning("[Balance] No se pudo buscar por cajero: %s", str(e)[:100])
        return False
