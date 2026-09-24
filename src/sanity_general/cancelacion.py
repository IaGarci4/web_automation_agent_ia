"""
Módulo REUTILIZABLE de cancelación de transacciones para el sanity.

Navega Reportes → Transacciones, busca la transacción por el nombre del cliente
y la cancela (reusa `base_page.cancelar_transaccion`, que maneja kebab → Cancel →
Reason → Notes → Confirmar, independiente del idioma).

Lo usan los CPs que, además del envío, deben CANCELAR (ej. CP01, CP02).

API:
    await cancelar_por_cliente(flow, nombre_cliente, logger=..., screenshot=..., ev=...)
"""

from config.logger import get_logger
from src.helpers.session_helper import seleccionar_agencia, modal_agencia_visible

logger = get_logger("sanity.cancelacion")


async def cerrar_warning_salir(flow, timeout_ms: int = 4_000) -> bool:
    """Cierra el 'Warning: Are you sure you want to leave this page?' EN CUANTO
    aparece, sondeando cada 150 ms.

    Importante el ORDEN: este modal ES un overlay bloqueante, así que llamar
    antes a `wait_for_no_blocking_overlays` agotaba el timeout completo esperando
    que se fuera algo que solo se va al confirmar. Primero se confirma, después
    se esperan overlays."""
    btn = flow.page.get_by_test_id("modal-confirmation-deny-button").first
    espera = 0
    while espera <= timeout_ms:
        try:
            if await btn.is_visible():
                await btn.click(timeout=2_500)
                logger.info("[Cancelación] 'YES, Leave' confirmado (%.1f s).",
                            espera / 1000)
                await flow.page.wait_for_timeout(300)
                return True
        except Exception:
            pass
        await flow.page.wait_for_timeout(150)
        espera += 150
    return False


async def ir_a_reportes_transacciones(flow, multi: bool = False, agency: str = None) -> None:
    """Navega a Reportes → Transacciones, tolerando el diálogo 'salir del sitio'.

    MULTIAGENTE (multi=True): tras terminar una transacción la app RESETEA la
    agencia y vuelve a pedir 'Select an agency' — 1ª vez al entrar a Reportes
    (con confirmación PC) y 2ª vez al entrar a Transacciones (SIN confirmar). NO
    se re-clickea Reports/Transactions tras seleccionar (eso re-disparaba el
    modal). Al final, GUARDA: no se continúa hasta que el modal cierre (si no,
    la búsqueda tecleaba el nombre del cliente en el buscador de agencia)."""
    if not (multi and agency):
        # Flujo mono (sin agencia). ORDEN: navegar → cerrar el Warning en cuanto
        # aparezca → recién entonces esperar overlays (con timeout corto).
        await flow.click_reports()
        await cerrar_warning_salir(flow)
        await flow.wait_for_no_blocking_overlays(timeout=1_500)
        await flow.click_transactions()
        await cerrar_warning_salir(flow)
        await flow.wait_for_no_blocking_overlays(timeout=1_500)
        return

    # ── MULTIAGENTE ──────────────────────────────────────────────────────────
    # En cada vuelta, en ORDEN: (1) si hay modal de agencia → seleccionar (SIN
    # navegar; al cerrar la app suele quedar YA en Transacciones); (2) si ya
    # estamos en Transacciones → listo (va directo a search, sin re-navegar);
    # (3) si no, navegar Reports > Transactions. Así se evita la navegación
    # repetida y el cuelgue del 'Leave site?'.
    async def _en_transacciones():
        return "reports/transactions" in flow.page.url.lower()

    async def _leave_si_aparece():
        await cerrar_warning_salir(flow, timeout_ms=2_500)

    en_transacciones = False
    for intento in range(1, 8):
        # 1) Modal de agencia → seleccionar (NO navegar)
        if await modal_agencia_visible(flow.page):
            await seleccionar_agencia(flow.page, agency, timeout=12_000)
            await flow.wait_for_no_blocking_overlays()
            logger.info("[Cancelación][Multi] Agencia seleccionada (intento %d).", intento)
            continue
        # 2) ¿Ya en Transacciones? → listo, sin re-navegar
        if await _en_transacciones():
            en_transacciones = True
            logger.info("[Cancelación][Multi] En reporte de Transacciones (intento %d).", intento)
            break
        # 3) Navegar Reports > Transactions (el Warning se cierra al instante)
        await flow.click_reports()
        await _leave_si_aparece()
        await flow.wait_for_no_blocking_overlays(timeout=1_500)
        try:
            await flow.click_transactions()
        except Exception:
            pass
        await _leave_si_aparece()
        await flow.wait_for_no_blocking_overlays(timeout=1_500)
        # Poll corto: dar tiempo a que monte el modal de agencia o Transacciones
        t = 0
        while t < 10_000:
            if await modal_agencia_visible(flow.page) or await _en_transacciones():
                break
            await flow.page.wait_for_timeout(1_000)
            t += 1_000

    if not en_transacciones:
        logger.warning("[Cancelación][Multi] No confirmé llegar a Transacciones — "
                       "intento buscar de todas formas.")


async def cancelar_por_cliente(flow, nombre_cliente: str, *,
                               logger=logger, evi=None,
                               reason_index: int = 0, notes: str = "Automation",
                               multi: bool = False, agency: str = None) -> bool:
    """Busca la transacción del cliente en Reportes y la cancela.

    nombre_cliente : nombre usado en el envío (datos.nombre_cliente()).
    evi            : Evidencia (numeración automática) — captura la fila y el
                     resultado de la cancelación.
    multi/agency   : para perfiles MULTIAGENTE, re-selecciona la agencia al entrar
                     a Reportes (la app la resetea tras cada transacción).
    Devuelve True si la cancelación se ejecutó sin excepción.
    """
    logger.info("[Cancelación] Iniciando cancelación para cliente: %s", nombre_cliente)
    _primer = nombre_cliente.split()[0] if nombre_cliente else None
    _sel = "tbody tr, tr.report-transactions-result-row"

    await ir_a_reportes_transacciones(flow, multi=multi, agency=agency)

    # Buscar por nombre del cliente
    try:
        await flow.buscar_transaccion_por_nombre(nombre_cliente)
    except Exception as e:
        logger.warning("[Cancelación] Búsqueda por nombre falló (%s) — intento cancelar la 1ª fila.",
                       str(e)[:80])

    # Evidencia: fila localizada (antes de cancelar)
    if evi is not None:
        await evi.shot("transaccion_encontrada", search_text=_primer, selector=_sel)

    # Cancelar (kebab → Cancel → Reason → Notes → Confirmar)
    try:
        await flow.cancelar_transaccion(reason_index=reason_index, notes=notes)
    except Exception as e:
        logger.warning("[Cancelación] cancelar_transaccion falló: %s", str(e)[:120])
        if evi is not None:
            await evi.shot("cancelacion_fallo")
        return False

    await flow.wait_for_no_blocking_overlays()

    # Evidencia final: resultado de la cancelación
    if evi is not None:
        await evi.shot("cancelacion_exitosa", search_text=_primer, selector=_sel)

    logger.info("[Cancelación] Cancelación ejecutada para: %s", nombre_cliente)
    return True
