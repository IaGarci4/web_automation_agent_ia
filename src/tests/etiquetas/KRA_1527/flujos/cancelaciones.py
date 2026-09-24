"""
Cancelación de CUALQUIER transacción creada por la etiqueta.

## Por qué un solo módulo

La etiqueta crea transacciones reales en TEST para que la aplicación invoque al
Hardware Agent: envíos, pagos de servicios, cheques, money orders. Si no se
cancelan, quedan vivas — ensucian los reportes del ambiente, cuadran mal los
balances y el siguiente que abra el reporte no sabe qué es basura de
automatización y qué es una prueba de alguien.

En el repo viejo la cancelación está repartida: una para Money Transfer (con
modal de notas), otra para Bill Payment (sin notas), y los money orders se
**invalidan** desde su propio reporte. Aquí se unifica lo que comparten —el
reporte de Transacciones, el menú «···» de la fila y la opción *Cancel*— y se
deja que el propio diálogo decida el camino.

## La decisión de diseño que importa

**Se delega en `flow.cancelar_transaccion`, el flujo del sanity.** Está estable
desde hace tiempo: abre el kebab, pulsa *Cancel*, espera el modal, elige Reason,
escribe Notes y confirma. No se reimplementa nada de eso.

La primera versión de este módulo se adelantaba: pulsaba *Cancel* por su cuenta
y luego intentaba adivinar qué diálogo había salido. Se equivocaba —el botón
«Cancel Transaction» del propio modal de notas parecía una confirmación
simple— y acababa cancelando sin llenar Reason ni Notes; como Reason es
obligatorio, el botón estaba deshabilitado y no ocurría nada, aunque el log
dijera «Confirmación pulsada». Lección: cuando ya existe un camino probado, se
usa el camino probado.

Solo se improvisa cuando ese camino lanza porque el modal de notas no existe
para ese tipo — Bill Payment y cheques confirman con un simple *YES, Cancel*.

Los money orders NO pasan por aquí: se invalidan con
`money_order.anular_money_orders`, desde Services > Money Order > Reportes,
porque la operación de la app es *Void*, no *Cancel*.

    await cancelaciones.cancelar(flow, tipo="cheque", evi=evi)
"""

import re

from config.logger import get_logger

from . import modales as _MOD

logger = get_logger("KRA1527.cancelacion")

TIMEOUT = 15_000

# Tipos del combo «Tipo de Transacción» del reporte, bilingües.
# La clave es lo que se pide desde el test; el valor, cómo lo escribe la app.
TIPOS = {
    "money_transfer": r"money\s*transfer|env[íi]o\s*de\s*dinero",
    "bill_payment": r"bill\s*payment|pago\s*de\s*servicio",
    "cheque": r"check|cheque",
    "money_order": r"money\s*order|orden\s*de\s*pago",
    "recarga": r"top\s*up|recarga",
}

RE_CANCEL_MENU = re.compile(r"^\s*(cancel|cancelar)\s*$", re.I)
# ⚠️ OJO: este regex NO debe casar con «Cancel Transaction», que es el botón de
# ENVIAR del modal de notas del Money Transfer. Cuando lo hacía, el módulo creía
# estar ante una confirmación simple, lo pulsaba sin llenar Reason ni Notes —y
# como Reason es obligatorio, el botón estaba deshabilitado y no pasaba nada,
# aunque el log dijera «Confirmación pulsada».
RE_YES_CANCEL = re.compile(r"^\s*(yes|s[ií])\s*,?\s*(cancel|cancelar)", re.I)
RE_BUSCAR = re.compile(r"buscar|search", re.I)
FILAS = "tr.report-transactions-result-row, tbody tr"


async def _visible(page, selector: str, limite: int = 12):
    """Primer elemento REALMENTE visible del selector, o None."""
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


async def _click(el, timeout: int = 8_000) -> bool:
    try:
        await el.click(timeout=timeout)
        return True
    except Exception:
        try:
            await el.click(force=True, timeout=6_000)
            return True
        except Exception:
            return False


# ═══════════════════════════════════════════════════════════════════════════
# Filtro del reporte
# ═══════════════════════════════════════════════════════════════════════════

async def seleccionar_tipo(flow, tipo: str) -> bool:
    """Cambia el combo «Tipo de Transacción» del reporte.

    El combo lleva su valor actual en el `aria-label`, así que se localiza por
    rol y se elige la opción por texto — sin depender del idioma ni de un
    índice de posición."""
    page = flow.page
    patron = TIPOS.get(tipo)
    if not patron:
        logger.warning("[Cancelación] Tipo desconocido '%s'. Conocidos: %s",
                       tipo, ", ".join(TIPOS))
        return False
    if tipo == "money_transfer":
        logger.info("[Cancelación] El reporte ya abre en Envío de Dinero.")
        return True
    try:
        # El combo de tipo lleva su valor ACTUAL en el aria-label, y el reporte
        # abre en Envío de Dinero: se localiza por ese nombre. Solo si no
        # aparece se cae al primer combobox — la pantalla tiene dos («Tipo de
        # Transacción» y «Buscar Por») y quedarse con `.first` a ciegas es
        # justo el tipo de suposición que luego falla en otro idioma.
        combo = page.get_by_role(
            "combobox", name=re.compile(TIPOS["money_transfer"], re.I)).first
        if not await combo.count():
            combo = page.get_by_role("combobox").first
        await combo.wait_for(state="visible", timeout=TIMEOUT)
        await _click(combo, timeout=6_000)
        await page.wait_for_timeout(600)
        opcion = page.get_by_role("option", name=re.compile(patron, re.I)).first
        await opcion.wait_for(state="visible", timeout=8_000)
        texto = ((await opcion.inner_text()) or "").strip()
        if not await _click(opcion, timeout=6_000):
            return False
        await page.wait_for_timeout(800)
        logger.info("[Cancelación] Tipo de transacción → '%s'.", texto)
        return True
    except Exception as e:
        # Listar lo disponible en vez de fallar a ciegas.
        try:
            todas = page.get_by_role("option")
            textos = [t.strip() for t in await todas.all_inner_texts()][:12]
        except Exception:
            textos = []
        logger.warning("[Cancelación] No pude elegir el tipo '%s' (%s). "
                       "Opciones vistas: %s", tipo, str(e)[:70],
                       ", ".join(f"'{t}'" for t in textos) or "(ninguna)")
        return False


async def buscar(flow, timeout_ms: int = 20_000) -> int:
    """Pulsa Buscar y espera las filas. Devuelve cuántas quedaron."""
    page = flow.page
    btn = page.locator("#id-button, [data-testid='test-id-button']").filter(
        has_text=RE_BUSCAR)
    for i in range(min(await btn.count(), 5)):
        el = btn.nth(i)
        try:
            if await el.is_visible() and await el.is_enabled():
                if await _click(el, timeout=6_000):
                    logger.info("[Cancelación] Buscar pulsado.")
                    break
        except Exception:
            continue
    espera, total = 0, 0
    while espera <= timeout_ms:
        try:
            total = await page.locator(FILAS).count()
        except Exception:
            total = 0
        if total:
            await page.wait_for_timeout(700)
            return total
        await page.wait_for_timeout(400)
        espera += 400
    return 0


# ═══════════════════════════════════════════════════════════════════════════
# El menú y sus dos caminos
# ═══════════════════════════════════════════════════════════════════════════

async def _confirmar_simple(flow) -> bool:
    """Pulsa «YES, Cancel» de la confirmación (Bill Payment, cheques)."""
    page = flow.page
    candidatos = ('[data-testid="modal-confirmation-confirm-button"]',
                  '[data-testid="confirmation-modal-accept-button-button"]')
    for sel in candidatos:
        el = await _visible(page, sel)
        if el is not None and await _click(el, timeout=6_000):
            logger.info("[Cancelación] Confirmación pulsada.")
            await page.wait_for_timeout(1_000)
            return True
    try:
        btn = page.get_by_role("button", name=RE_YES_CANCEL).first
        await btn.wait_for(state="visible", timeout=6_000)
        if await _click(btn, timeout=6_000):
            logger.info("[Cancelación] Confirmación pulsada (por texto).")
            await page.wait_for_timeout(1_000)
            return True
    except Exception:
        pass
    logger.warning("[Cancelación] No pude confirmar la cancelación.")
    return False


RE_CANCELADA = re.compile(r"cancell?ed|cancelad[oa]", re.I)


async def _esperar_estatus_cancelado(page, timeout_ms: int = 8_000) -> bool:
    """Espera a que la tabla muestre el estatus Cancelled/Cancelado.

    Sondea cada 400 ms en vez de dormir un tiempo fijo. La diferencia no es
    cosmética: la cancelación es lo último de cada caso, así que una pausa fija
    se paga en TODOS los casos de la etiqueta, una y otra vez."""
    espera = 0
    while espera <= timeout_ms:
        try:
            if await page.get_by_text(RE_CANCELADA).first.is_visible():
                logger.info("[Cancelación] Estatus Cancelado visible (%.1f s).",
                            espera / 1000)
                return True
        except Exception:
            pass
        await page.wait_for_timeout(400)
        espera += 400
    # No es un fallo: la fila puede estar fuera de la vista o la columna llamarse
    # de otra forma. Solo significa que la evidencia quizá salga con el estatus
    # anterior.
    return False


# ═══════════════════════════════════════════════════════════════════════════
# API
# ═══════════════════════════════════════════════════════════════════════════

async def cancelar(flow, tipo: str = "money_transfer", *, evi=None,
                   paso: int = None, row_index: int = 0,
                   notes: str = "KRA-1527 automation",
                   reason_index: int = 0):
    """Cancela la transacción más reciente del tipo indicado.

    Devuelve `(ok, detalle)`. Se espera que la página ya esté en
    Reportes > Transacciones (lo hace `transacciones.ir_a_reportes_transacciones`).

    No lanza excepción si no puede: la cancelación es limpieza, y tumbar el
    caso por no haber podido limpiar ocultaría el resultado de lo que sí se
    estaba probando. El detalle queda en el reporte para saber que hay un
    registro vivo en TEST."""
    page = flow.page
    # Con un diálogo encima, el combo no se abre y Buscar no devuelve filas:
    # el módulo concluiría «no hay transacciones que cancelar» cuando en
    # realidad no ha podido ni mirar.
    await _MOD.atender_bloqueantes(flow, logger)
    await seleccionar_tipo(flow, tipo)
    filas = await buscar(flow)
    if not filas:
        return False, (f"No hay transacciones de tipo '{tipo}' en el rango del "
                       f"reporte: no se pudo cancelar nada.")
    if evi is not None:
        await evi.shot(f"por_cancelar_{tipo}", paso=paso, selector=FILAS)

    # ── El camino probado PRIMERO ───────────────────────────────────────────
    # `flow.cancelar_transaccion` es el flujo del sanity: abre el kebab, pulsa
    # Cancel, espera el modal, elige Reason, escribe Notes y confirma. Está
    # estable desde hace tiempo y se delega en él tal cual.
    #
    # La versión anterior de este módulo se adelantaba: pulsaba Cancel por su
    # cuenta y luego «detectaba» qué diálogo había salido. Se equivocaba —el
    # botón «Cancel Transaction» del propio modal de notas parecía una
    # confirmación simple— y acababa cancelando sin llenar nada. Peor: al haber
    # pulsado Cancel antes, ya no podía delegar. Ahora se delega de entrada y
    # solo se improvisa si el modal de notas no existe para ese tipo.
    try:
        await flow.cancelar_transaccion(reason_index=reason_index,
                                        notes=notes, row_index=row_index)
        ok, detalle = True, "Cancelada con motivo y notas."
    except Exception as e:
        # `cancelar_transaccion` lanza cuando el modal de notas no aparece. Eso
        # NO siempre es un fallo: Bill Payment y cheques se cancelan con una
        # confirmación simple. El menú ya está abierto y Cancel ya se pulsó, así
        # que aquí solo falta confirmar.
        logger.info("[Cancelación] Sin modal de notas (%s) — pruebo la "
                    "confirmación simple, que es como cancelan los cheques y "
                    "los pagos de servicios.", str(e)[:70])
        ok = await _confirmar_simple(flow)
        detalle = ("Cancelada con confirmación simple (este tipo no pide notas)."
                   if ok else
                   "No apareció el modal de notas ni una confirmación que pulsar.")

    try:
        await flow.wait_for_no_blocking_overlays(timeout=3_000)
    except Exception:
        pass
    # Esperar a que la tabla refresque el estatus a Cancelled/Cancelado. Antes
    # era una pausa fija de 6 s: cuando la app respondía en medio segundo se
    # regalaban cinco y medio, y cuando tardaba más de seis la evidencia salía
    # igual con el estatus viejo. Ahora se sondea y se sale en cuanto aparece.
    if ok:
        await _esperar_estatus_cancelado(page)
    if evi is not None:
        await evi.shot(f"cancelacion_{tipo}", paso=paso,
                       search_text="Cancel" if ok else None, selector=FILAS)
    logger.info("[Cancelación] %s → %s", tipo, detalle)
    return ok, detalle


async def cancelar_money_transfer(flow, **kw):
    return await cancelar(flow, "money_transfer", **kw)


async def cancelar_bill_payment(flow, **kw):
    return await cancelar(flow, "bill_payment", **kw)


async def cancelar_cheque(flow, **kw):
    return await cancelar(flow, "cheque", **kw)
