"""
Modales interpuestos que aparecen a mitad de un flujo y hay que atender.

## Por qué existe este módulo

Hermes va sumando diálogos entre un clic y su resultado. Cuando aparece uno que
el script no conoce, no falla limpio: se queda **esperando algo que ya no puede
llegar**. Cada espera agota su timeout, cada reintento vuelve a agotarlo, y lo
que se ve por fuera es «se quedó muchísimo tiempo así… y después sí funcionó».
No era lentitud: era un modal encima.

Eso pasó con el diálogo de **recibo digital** (`Transaction Confirmation → «Does
the customer want to receive the digital receipt?»`). Nadie lo cerraba, así que
tras el envío: el modal de éxito no aparecía (15 s perdidos), el cierre con NO
sondeaba en vano (8 s), la navegación a Reportes chocaba con el overlay, y la
búsqueda para cancelar no encontraba filas (20 s). Minutos de reloj por un botón
sin pulsar.

## La regla

**SI está, lo cierro; si no está, sigo.** Comprobarlo cuesta milisegundos
(`count()` sobre un selector que no existe devuelve 0 al instante), así que se
puede preguntar en todos los puntos donde el flujo podría toparse con él sin
penalizar a los casos donde no sale.

## Qué botón se pulsa y por qué

En el diálogo del recibo digital se pulsa **«NO, Print»**, no «YES, Send»:

  • «YES, Send» manda el recibo por SMS/correo → **no invoca al Hardware Agent**.
  • «NO, Print» fuerza la impresión física → **sí lo invoca**, que es justo lo
    que esta etiqueta necesita ejercitar.

O sea que atender este modal no es solo desbloquear el flujo: elegir mal el
botón dejaría el caso pasando sin haber probado nada.

    from .modales import atender_bloqueantes, descartar_recibo_digital
    await atender_bloqueantes(flow, logger)
"""

import re

from config.logger import get_logger

logger_default = get_logger("KRA1527.modales")

# ── Recibo digital ──────────────────────────────────────────────────────────
# La clase del botón es lo más específico que ofrece el DOM; el testid es el
# genérico `test-id-button`, que hay a decenas por pantalla y no distingue nada.
SEL_NO_PRINT = "button.btn-no-print"
RE_NO_PRINT = re.compile(r"no\s*,?\s*print|no\s*,?\s*imprim", re.I)
RE_TITULO_RECIBO = re.compile(
    r"digital receipt|recibo digital|transaction confirmation|"
    r"confirmaci[oó]n de (la )?transacci[oó]n", re.I)

_DIALOGOS = "div[role='dialog'], .p-dialog, p-dialog, .modal.show, .modal-content"


def _page(destino):
    """Acepta indistintamente un flow (page object) o una Page de Playwright.

    Los módulos de flujo trabajan con `flow`, pero algunos casos —el de imprimir
    el balance, por ejemplo— solo tienen la página. Obligar a envolverla en un
    page object para poder cerrar un modal sería ceremonia sin propósito."""
    return getattr(destino, "page", destino)


async def _primer_visible(page, selector: str, limite: int = 6):
    """Primer elemento del selector que esté REALMENTE visible, o None.

    `.first` no sirve aquí: Angular deja en el DOM los modales ya cerrados, así
    que el primero que casa suele ser un fantasma sin pintar."""
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


async def _click(el, timeout: int = 4_000) -> bool:
    try:
        await el.click(timeout=timeout)
        return True
    except Exception:
        try:
            await el.click(force=True, timeout=3_000)
            return True
        except Exception:
            return False


async def descartar_recibo_digital(flow, logger=None, timeout_ms: int = 0) -> bool:
    """Pulsa «NO, Print» del diálogo de recibo digital si está en pantalla.

    timeout_ms=0 (default) → una sola comprobación instantánea: para llamarlo
    «por si acaso» en cualquier punto del flujo sin costo.

    timeout_ms>0 → sondea cada 200 ms esperando que el modal monte. Se usa justo
    después de «Sí, Enviar», que es donde SÍ se espera que aparezca; así se
    pulsa en cuanto está, en vez de dormir un tiempo fijo a ciegas.

    Devuelve True solo si se pulsó (para poder anotarlo en el reporte)."""
    log = logger or logger_default
    page = _page(flow)
    espera = 0
    while True:
        boton = await _primer_visible(page, SEL_NO_PRINT)
        if boton is None:
            # Respaldo por texto: si algún día cambia la clase del botón, el
            # texto bilingüe sigue identificándolo. Se busca DENTRO de un
            # diálogo para no pulsar un «print» cualquiera de la pantalla.
            dialogo = await _primer_visible(page, _DIALOGOS)
            if dialogo is not None:
                try:
                    cand = dialogo.get_by_role("button", name=RE_NO_PRINT).first
                    if await cand.count() and await cand.is_visible():
                        boton = cand
                except Exception:
                    boton = None
        if boton is not None:
            if await _click(boton):
                log.info("[Modal] Recibo digital → «NO, Print» pulsado (%.1f s). "
                         "Se imprime en físico, que es lo que invoca al "
                         "Hardware Agent.", espera / 1000)
                await page.wait_for_timeout(400)
                return True
            log.warning("[Modal] Vi el diálogo de recibo digital pero no pude "
                        "pulsar «NO, Print»: el flujo puede quedarse esperando.")
            return False
        if espera >= timeout_ms:
            return False
        await page.wait_for_timeout(200)
        espera += 200


async def atender_bloqueantes(flow, logger=None) -> list:
    """Cierra los modales interpuestos que estén en pantalla AHORA MISMO.

    Punto único al que llamar antes de navegar o de esperar algo: si hay un
    diálogo encima, esperar overlays o buscar filas es tiempo tirado.

    Devuelve la lista de los que atendió (vacía casi siempre, y eso está bien:
    preguntar es gratis)."""
    atendidos = []
    if await descartar_recibo_digital(flow, logger):
        atendidos.append("recibo digital")
    return atendidos
