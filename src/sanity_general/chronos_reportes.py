"""
Reportes de Chronos (CP16–CP21) — navegar, imprimir por fecha y descargar Excel.
(Migración/mejora de `HERMES2-qa/src/models_chronos/agent_ar_aging_page.py` y los
`go_to_*` de `chronos_main_page.py`.)

Todos estos reportes comparten el mismo patrón:
    Menu → Reports → <sub-opción> → (BeginDate) → Search → tabla → botón Excel.

Por eso se resuelven con funciones GENÉRICAS parametrizadas por un `ReporteCfg`
(nombre del link, patrón de URL y del título). Así CP16 (A/R Aging) y sus
hermanos CP17–CP21 se agregan solo declarando su config, sin duplicar lógica.

La sesión de Chronos se reutiliza con `chronos.abrir_chronos` (cookies + login
solo si expiró); igual que en CP07/CP14.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from config import settings
from config.logger import get_logger
from src.sanity_general import chronos as CH

logger = get_logger("sanity.chronos_reportes")

TIMEOUT = 360_000   # los reportes de Chronos pueden tardar mucho en cargar

# ── Selectores compartidos ───────────────────────────────────────────────────
MENU        = "//button[@title='Menu']"
REPORTS     = "//mat-panel-title[contains(text(),'Reports')]"
INPUT_BEGIN = "//input[@name='BeginD']"
INPUT_END   = "//input[@name='EndD']"
TITULO      = "h1.custom-app-name"
TABLA       = "p-table >> div.ui-table-scrollable-view"
FILAS       = ("p-table >> div.ui-table-scrollable-body "
               "table.ui-table-scrollable-body-table tbody.ui-table-tbody tr")
BTN_EXCEL   = "button.btn.btn-green.btn-spinner"
BTN_PDF     = "button.btn.btn-blue.btn-spinner.ml-15"    # 'Download' (PDF)
BTN_OPEN_NEW = "button.btn.btn-blue.ml-2"                # 'Open in new window'
# Agent Balance (CP18): modal de búsqueda de agente + checkboxes.
AGENT_SEARCH_BTN   = "#btnSearchAgentModal1"
AGENT_SEARCH_INPUT = "//input[@name='search']"
EXCEL_CHECK        = "#excelCheckbox"
VIEW_CHECK         = "#viewCheckbox"


@dataclass
class ReporteCfg:
    """Config de un reporte de Chronos."""
    clave: str            # etiqueta corta (log/evidencia)
    link_name: str        # nombre del link en el submenú Reports
    url_frag: str         # fragmento de URL en TEST (ej. 'reports/ar-aging')
    url_frag_prod: str    # fragmento de URL en PROD (ej. 'reports/ar-aging')
    titulo_re: str        # regex del título de la pantalla (ej. 'A/R Aging')
    con_fecha: bool = True   # si el reporte pide Begin Date + Search
    exact: bool = True       # si el nombre del link se matchea EXACTO


# ── Catálogo de reportes (CP16 y sitio para CP17–CP21) ───────────────────────
AR_AGING = ReporteCfg(
    clave="agent_ar_aging",
    link_name="A/R Aging ",
    url_frag="reports/ar-aging",
    url_frag_prod="reports/ar-aging",
    titulo_re=r"A/R Aging",
    con_fecha=True,
)

AGENT_AR = ReporteCfg(
    clave="agent_ar",
    link_name="Agent A/R",
    url_frag="reports/agent-ar",
    url_frag_prod="reports/agent-ar",
    titulo_re=r"Agent A/R",
    con_fecha=True,
    exact=False,   # el link viejo no usa exact
)

AGENT_BALANCE = ReporteCfg(
    clave="agent_balance",
    link_name="Agent Balance ",
    url_frag="reports/agent-balance",
    url_frag_prod="reports/agent-balance",
    titulo_re=r"Agent Balance",
    con_fecha=False,   # usa las fechas por defecto de la pantalla
    exact=False,
)

DASHBOARD = ReporteCfg(
    clave="agent_dashboard",
    link_name="Dashboard ",
    url_frag="reports/dashboard",
    url_frag_prod="reports/dashboard",
    titulo_re=r"Dashboard",
    con_fecha=True,
)

# Dashboard: su campo de fecha es //input[@name='dp'] (no BeginD).
DASHBOARD_INPUT_BEGIN = "//input[@name='dp']"
DASHBOARD_TABLA = ("div.ui-table-scrollable-wrapper")

AGENT_PROFIT = ReporteCfg(
    clave="agent_profit",
    link_name="Agent Profit ",
    url_frag="reports/agent-profit",
    url_frag_prod="reports/agent-profit",
    titulo_re=r"Agent Profit",
    con_fecha=True,
)

AGENT_PROFIT_OP = ReporteCfg(
    clave="agent_profit_op",
    link_name="Agent Profit O.P. ",
    url_frag="reports/agent-profit-op",
    url_frag_prod="reports/agent-profit-op",
    titulo_re=r"Agent Profit O\.P\.",
    con_fecha=True,
)

# Filas de las tablas de Profit / Profit OP.
PROFIT_ROWS = ("div.ui-table-scrollable-body table.ui-table-scrollable-body-table "
               "tbody.ui-table-tbody tr")


async def abrir_reporte(page, cfg: ReporteCfg, timeout: int = TIMEOUT) -> bool:
    """Menu → Reports → sub-opción del reporte. Confirma por URL y título."""
    logger.info("[Reportes] Abriendo reporte '%s'…", cfg.clave)
    await CH._click_listo(page, page.locator(MENU).first, "Menu", timeout=timeout)
    await page.wait_for_timeout(800)
    await CH._click_listo(page, page.locator(REPORTS).first, "Reports", timeout=timeout)
    await page.wait_for_timeout(800)
    link = page.get_by_role("link", name=cfg.link_name, exact=cfg.exact).first
    await CH._click_listo(page, link, f"Sub-opción '{cfg.link_name.strip()}'",
                          timeout=timeout)

    # Confirmar por URL (según ambiente) y por el título de la pantalla.
    frag = settings.por_ambiente(cfg.url_frag, cfg.url_frag_prod)
    try:
        from playwright.async_api import expect
        await expect(page).to_have_url(re.compile(rf".*/{re.escape(frag)}/?$"),
                                       timeout=timeout)
    except Exception:
        logger.info("[Reportes] URL no confirmó el patrón '%s' — sigo por título.", frag)
    try:
        await page.locator(TITULO).filter(
            has_text=re.compile(cfg.titulo_re, re.I)).first.wait_for(
            state="visible", timeout=timeout)
    except Exception:
        logger.warning("[Reportes] No se confirmó el título '%s'.", cfg.titulo_re)
        return False
    logger.info("[Reportes] Reporte '%s' abierto.", cfg.clave)
    return True


async def imprimir_por_fecha(page, begin_date: str, timeout: int = TIMEOUT,
                             input_begin: str = INPUT_BEGIN,
                             tabla: str = TABLA) -> int:
    """Llena Begin Date, pulsa Search y espera la tabla. Devuelve nº de filas.

    `input_begin` y `tabla` son configurables porque algunos reportes usan otro
    campo de fecha (ej. Dashboard: //input[@name='dp']) u otra tabla."""
    try:
        await page.locator(input_begin).first.fill(begin_date, timeout=8_000)
    except Exception as e:
        logger.info("[Reportes] Begin Date no disponible (%s) — busco directo.",
                    str(e)[:70])
    await CH._click_listo(page, page.get_by_role("button", name="Search").first,
                          "Search", timeout=timeout)
    # Esperar a que la tabla del reporte sea visible.
    try:
        from playwright.async_api import expect
        await expect(page.locator(tabla).first).to_be_visible(timeout=timeout)
    except Exception:
        logger.warning("[Reportes] La tabla del reporte no se hizo visible.")
        return 0
    await page.wait_for_timeout(1_000)
    try:
        n = await page.locator(FILAS).count()
    except Exception:
        n = 0
    logger.info("[Reportes] Reporte cargado — %d fila(s).", n)
    return n


async def imprimir_agent_ar(page, begin_date: str, end_date: str,
                            excel_path: str = None, pdf_path: str = None,
                            timeout: int = TIMEOUT):
    """Reporte Agent A/R (CP17): Begin+End Date → Excel (antes de View) → View →
    PDF (después) → 'Open in new window' (abre pestaña con el reporte).

    Devuelve la PÁGINA del reporte (pestaña nueva) para que el caso la capture y
    la cierre. Si no se abre la pestaña, devuelve None."""
    logger.info("[Reportes] Agent A/R — Begin=%s End=%s", begin_date, end_date)
    try:
        await page.locator(INPUT_BEGIN).first.fill(begin_date, timeout=8_000)
        await page.locator(INPUT_END).first.fill(end_date, timeout=8_000)
    except Exception as e:
        logger.warning("[Reportes] Fechas Begin/End: %s", str(e)[:90])

    # Excel ANTES de View (como el flujo original).
    if excel_path:
        await descargar_excel(page, excel_path, timeout=timeout)

    # View: genera el reporte.
    await CH._click_listo(page, page.get_by_role("button", name="View").first,
                          "View", timeout=timeout)

    # PDF DESPUÉS de View.
    if pdf_path:
        try:
            async with page.expect_download(timeout=timeout) as info:
                btn = page.locator(BTN_PDF).filter(
                    has_text=re.compile("download", re.I)).first
                await CH._click_listo(page, btn, "Descargar PDF", timeout=timeout)
            dl = await info.value
            await dl.save_as(pdf_path)
            logger.info("[Reportes] PDF guardado en %s", pdf_path)
        except Exception as e:
            logger.warning("[Reportes] No se pudo descargar el PDF: %s", str(e)[:120])

    # 'Open in new window' → pestaña nueva con el reporte renderizado.
    report_page = None
    try:
        async with page.context.expect_page(timeout=timeout) as new_info:
            await CH._click_listo(page, page.locator(BTN_OPEN_NEW).first,
                                  "Open in new window", timeout=timeout)
        report_page = await new_info.value
        try:
            await report_page.wait_for_load_state("networkidle", timeout=timeout)
        except Exception:
            pass
        logger.info("[Reportes] Reporte Agent A/R abierto en pestaña nueva.")
    except Exception as e:
        logger.warning("[Reportes] No se abrió la pestaña del reporte: %s", str(e)[:120])
    return report_page


async def imprimir_agent_balance(page, agent_code: str, excel_path: str = None,
                                 pdf_path: str = None, timeout: int = TIMEOUT):
    """Reporte Agent Balance (CP18): elige el agente en el modal, marca Excel,
    descarga Excel, marca View, pulsa View, descarga PDF y abre el reporte en una
    pestaña nueva (fechas por defecto de la pantalla). Devuelve la pestaña o None."""
    logger.info("[Reportes] Agent Balance — agente=%s", agent_code)

    # 1) Elegir el agente en el modal de búsqueda.
    await CH._click_listo(page, page.locator(AGENT_SEARCH_BTN).first,
                          "Buscar agente", timeout=timeout)
    caja = page.locator(AGENT_SEARCH_INPUT).first
    await caja.wait_for(state="visible", timeout=timeout)
    await caja.click()
    await caja.press_sequentially(str(agent_code), delay=50)
    await page.wait_for_timeout(1_000)
    fila = page.locator("td div", has_text=str(agent_code)).first
    await CH._click_listo(page, fila, f"Agente {agent_code}", timeout=timeout)

    # 2) Excel: marcar el checkbox (si no está) y descargar.
    if excel_path:
        try:
            chk = page.locator(EXCEL_CHECK).first
            await chk.wait_for(state="visible", timeout=timeout)
            if not await chk.is_checked():
                await chk.click(timeout=8_000)
        except Exception as e:
            logger.info("[Reportes] Checkbox Excel: %s", str(e)[:80])
        await descargar_excel(page, excel_path, timeout=timeout)

    # 3) Asegurar el checkbox View.
    try:
        vchk = page.locator(VIEW_CHECK).first
        if await vchk.is_visible() and not await vchk.is_checked():
            await vchk.click(timeout=8_000)
    except Exception:
        pass

    # 4) View (sin tocar fechas — se usan las por defecto).
    await CH._click_listo(page, page.get_by_role("button", name="View").first,
                          "View", timeout=timeout)

    # 5) PDF después de View.
    if pdf_path:
        try:
            async with page.expect_download(timeout=timeout) as info:
                btn = page.locator(BTN_PDF).filter(
                    has_text=re.compile("download", re.I)).first
                await CH._click_listo(page, btn, "Descargar PDF", timeout=timeout)
            dl = await info.value
            await dl.save_as(pdf_path)
            logger.info("[Reportes] PDF guardado en %s", pdf_path)
        except Exception as e:
            logger.warning("[Reportes] No se pudo descargar el PDF: %s", str(e)[:120])

    # 6) Abrir el reporte en pestaña nueva.
    report_page = None
    try:
        async with page.context.expect_page(timeout=timeout) as new_info:
            await CH._click_listo(page, page.locator(BTN_OPEN_NEW).first,
                                  "Open in new window", timeout=timeout)
        report_page = await new_info.value
        try:
            await report_page.wait_for_load_state("networkidle", timeout=timeout)
        except Exception:
            pass
        logger.info("[Reportes] Reporte Agent Balance abierto en pestaña nueva.")
    except Exception as e:
        logger.warning("[Reportes] No se abrió la pestaña del reporte: %s", str(e)[:120])
    return report_page


async def _tabla_con_filas(page, rows_sel: str, timeout: int) -> bool:
    """True si la tabla muestra al menos una fila dentro del timeout (no lanza)."""
    try:
        filas = page.locator(rows_sel)
        await filas.first.wait_for(state="visible", timeout=timeout)
        return (await filas.count()) > 0
    except Exception:
        return False


async def imprimir_por_rango_view(page, begin_date: str, end_date: str,
                                  excel_path: str = None, rows_sel: str = PROFIT_ROWS,
                                  timeout: int = TIMEOUT) -> int:
    """Reporte por rango con botón VIEW (CP20 Profit O.P. / CP21 Profit).

    Llena Begin+End, pulsa View (hasta 2 veces verificando la tabla) y, si la
    tabla no aparece, resta 1 día al Begin y reintenta (igual que el original).
    0 filas es VÁLIDO (fines de semana sin transacciones): no falla, descarga el
    Excel igual. Devuelve el nº de filas visto."""
    import datetime as _dt
    try:
        cur = _dt.datetime.strptime(begin_date, "%m/%d/%Y").date()
    except Exception:
        cur = None
    filas = 0
    for intento in (1, 2):
        b = cur.strftime("%m/%d/%Y") if cur else begin_date
        logger.info("[Reportes] Rango+View intento %d — Begin=%s End=%s",
                    intento, b, end_date)
        try:
            await page.locator(INPUT_BEGIN).first.fill(b, timeout=8_000)
            await page.locator(INPUT_END).first.fill(end_date, timeout=8_000)
        except Exception as e:
            logger.warning("[Reportes] Fechas Begin/End: %s", str(e)[:90])

        await CH._click_listo(page, page.get_by_role("button", name="View").first,
                              "View (1)", timeout=timeout)
        if await _tabla_con_filas(page, rows_sel, timeout=15_000):
            filas = await page.locator(rows_sel).count()
            break
        await CH._click_listo(page, page.get_by_role("button", name="View").first,
                              "View (2)", timeout=timeout)
        if await _tabla_con_filas(page, rows_sel, timeout=30_000):
            filas = await page.locator(rows_sel).count()
            break
        if intento == 1 and cur:
            cur -= _dt.timedelta(days=1)
            logger.info("[Reportes] Tabla vacía — resto 1 día al Begin (→ %s).",
                        cur.strftime("%m/%d/%Y"))
        else:
            # 0 filas es válido (fin de semana): no se falla, se descarga igual.
            logger.info("[Reportes] Tabla sin filas tras los intentos (posible fin "
                        "de semana). Se continúa a la descarga.")

    if excel_path:
        await descargar_excel(page, excel_path, timeout=timeout)
    return filas


async def descargar_excel(page, save_path: str, timeout: int = TIMEOUT) -> bool:
    """Pulsa el botón Excel y guarda el archivo descargado en `save_path`."""
    logger.info("[Reportes] Descargando Excel → %s", save_path)
    try:
        async with page.expect_download(timeout=timeout) as info:
            btn = page.locator(BTN_EXCEL).filter(has_text=re.compile("excel", re.I)).first
            await CH._click_listo(page, btn, "Botón Excel", timeout=timeout)
        download = await info.value
        await download.save_as(save_path)
        logger.info("[Reportes] Excel guardado en %s", save_path)
        return True
    except Exception as e:
        logger.warning("[Reportes] No se pudo descargar el Excel: %s", str(e)[:120])
        return False
