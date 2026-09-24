"""
Ficha de Depósitos (Deposit Slip) — CP10, lado Hermes.

Flujo: botón del footer → modal de cámara → elegir cámara → Take Picture →
Save Picture → monto → Send. El caso alternativo además hace zoom (100→300%),
limpia el formulario, borra la foto y la vuelve a tomar.

Notas de la pantalla (lo que la hace frágil y cómo se resuelve aquí):
  • La cámara es REAL: el navegador debe exponer un dispositivo. Los flags y el
    `add_init_script` del conftest simulan una webcam (lienzo negro).
  • Los botones de la barra de la foto (retomar / borrar / zoom) no tienen
    data-testid: se ubican por el atributo `icon` del componente
    `smallbuttonicon`, que sí es estable.
  • 'Take Picture' y 'Save Picture' comparten sitio y a veces texto: se
    desambiguan por texto bilingüe y se espera a que el botón cambie.
"""

import re

from config.logger import get_logger

from . import modales as _MOD

logger = get_logger("sanity.deposit_slip")

TIMEOUT = 30_000

# ── Entrada y modal ─────────────────────────────────────────────────────────
BTN_FOOTER = "footer-deposit-button"
MODAL = "p-dialog, div[role='dialog']"
RE_MODAL_TITULO = re.compile(r"take a picture|capture una foto|deposit slip|"
                             r"ficha de dep[oó]sito", re.I)
TEXTO_CAMARA = ".icon-camera__text"

# ── Cámara ──────────────────────────────────────────────────────────────────
DROPDOWN_CAMARA = "p-dropdown[data-testid*='camera-dropdown-input']"
TRIGGER_CAMARA = "[aria-label='dropdown trigger']"
OPCION_LISTA = "li[role='option']"
RE_TOMAR = re.compile(r"take picture|capturar foto", re.I)
RE_GUARDAR = re.compile(r"save picture|guardar foto|guardar|save", re.I)

# ── Barra de la foto (sin testid: se ubican por el icono) ───────────────────
def _boton_icono(icono: str) -> str:
    return (f"smallbuttonicon[icon='{icono}'] "
            f".btn.button-component.outline:visible")

BTN_RETOMAR = _boton_icono("Camera")
BTN_BORRAR_FOTO = _boton_icono("Trash")
BTN_ZOOM_MAS = _boton_icono("ZoomIn")
BTN_ZOOM_MENOS = _boton_icono("ZoomOut")
VALOR_ZOOM = ".zoom-value"

# ── Formulario y envío ──────────────────────────────────────────────────────
INPUT_MONTO = "deposit-slip-form-amount-input"
BTN_LIMPIAR = "deposit-slip-form-clear-icon-svg"
# OJO: 'test-id-button' es un testid GENÉRICO en Hermes — lo comparten muchos
# botones de la app (Buscar, Imprimir, etc.). Quedarse con `.first` puede
# apuntar a otro botón, y si ese está deshabilitado parece que el envío nunca
# se habilita. Por eso se desambigua por TEXTO (bilingüe) entre todos los que
# haya visibles.
BTN_ENVIAR = "test-id-button"
RE_ENVIAR = re.compile(r"^\s*(send|enviar)", re.I)
TOAST_TITULO = ".ng-star-inserted.toast-title > p#typography"
TOAST_TEXTO = ".toast-message > p#typography"
RE_EXITO = re.compile(r"success|éxito|exito", re.I)
RE_ENVIADA = re.compile(r"deposit slip sent|ficha.*enviad", re.I)


async def _click(locator, *, force: bool = False, timeout: int = TIMEOUT) -> bool:
    """Click defensivo: espera visible, hace scroll y clickea."""
    try:
        target = locator.first
        await target.wait_for(state="visible", timeout=timeout)
        try:
            await target.scroll_into_view_if_needed(timeout=5_000)
        except Exception:
            pass
        await target.click(timeout=timeout, force=force)
        return True
    except Exception as e:
        logger.warning("[Ficha] Click falló: %s", str(e)[:90])
        return False


async def abrir(flow) -> bool:
    """Abre la Ficha de Depósitos desde el footer."""
    page = flow.page
    logger.info("[Ficha] Abriendo la Ficha de Depósitos…")
    if not await _click(page.get_by_test_id(BTN_FOOTER), force=True):
        return False
    modal = page.locator(MODAL).filter(has_text=RE_MODAL_TITULO).first
    try:
        await modal.wait_for(state="visible", timeout=TIMEOUT)
    except Exception:
        logger.warning("[Ficha] El modal no apareció.")
        return False
    await page.wait_for_timeout(1_000)
    logger.info("[Ficha] Modal abierto.")
    return True


async def seleccionar_camara(flow) -> bool:
    """Elige la primera cámara del desplegable (si hace falta elegir)."""
    page = flow.page
    dd = page.locator(DROPDOWN_CAMARA).first
    try:
        await dd.wait_for(state="visible", timeout=TIMEOUT)
    except Exception:
        logger.info("[Ficha] Sin desplegable de cámara — se omite.")
        return True
    await page.wait_for_timeout(800)
    try:
        actual = (await dd.inner_text() or "").strip()
    except Exception:
        actual = ""
    if actual:                       # ya hay una cámara elegida
        logger.info("[Ficha] Cámara activa: %s", actual[:50])
        return True
    await _click(dd.locator(TRIGGER_CAMARA), force=True)
    ok = await _click(page.locator(OPCION_LISTA), force=True, timeout=10_000)
    logger.info("[Ficha] Cámara elegida del desplegable (%s).", "ok" if ok else "falló")
    return ok


async def _video_con_datos(page, timeout_ms: int = 15_000) -> bool:
    """Espera a que el `<video>` de la cámara tenga fotogramas de verdad.

    `readyState >= 2` (HAVE_CURRENT_DATA) más un tamaño real. Sin esta espera
    se pulsaba 'Take Picture' sobre un vídeo aún vacío: el clic «funcionaba»,
    no capturaba nada, y el fallo aparecía 60 s después en 'Save Picture'.
    """
    espera = 0
    while espera <= timeout_ms:
        try:
            listo = await page.evaluate(
                "() => { const v = document.querySelector('video');"
                " return !!v && v.readyState >= 2 && v.videoWidth > 0; }")
            if listo:
                return True
        except Exception:
            pass
        await page.wait_for_timeout(300)
        espera += 300
    return False


async def _botones_visibles(page) -> list:
    """Textos de los botones visibles. Solo para el diagnóstico del fallo."""
    try:
        textos = await page.locator("button:visible").all_inner_texts()
    except Exception:
        return []
    return [t.strip().replace("\n", " ")[:40] for t in textos if t.strip()][:12]


async def tomar_foto(flow) -> bool:
    """Take Picture → Save Picture, verificando que la captura ocurrió.

    La versión anterior clicaba con `force=True` y daba el paso por bueno
    porque el clic no lanzó excepción. `force` se salta justo la comprobación
    que aquí importa —que el botón esté habilitado y reciba el clic—, así que
    un 'Take Picture' pulsado antes de que la cámara tuviera imagen se
    registraba como éxito y el caso moría dos pasos más allá, culpando a
    'Save Picture'. Es el mismo error que ya nos costó una tarde en Chronos
    con 'Edited Checks Hold': confirmar SIEMPRE que la pantalla cambió.
    """
    page = flow.page
    if not await seleccionar_camara(flow):
        return False
    if not await _video_con_datos(page):
        logger.warning("[Ficha] La cámara no entregó imagen (el <video> sigue "
                       "sin fotogramas). Se intenta igual, pero si falla la "
                       "captura, mira el script de cámara del conftest.")

    tomar = page.locator("button:visible").filter(has_text=RE_TOMAR)
    guardar = page.locator("button:visible").filter(has_text=RE_GUARDAR)

    # Dos intentos cortos en vez de uno largo: si el primero no capturó, lo que
    # hace falta es volver a pulsar, no esperar más.
    for intento in (1, 2):
        if not await _click(tomar, timeout=10_000):
            # Sin `force` el clic espera a que el botón esté habilitado. Si aun
            # así no se puede, se fuerza — pero se verifica después.
            await _click(tomar, force=True, timeout=5_000)
        try:
            await guardar.first.wait_for(state="visible", timeout=8_000)
            break
        except Exception:
            logger.info("[Ficha] Intento %d: 'Take Picture' no produjo la "
                        "captura ('Save Picture' no apareció).", intento)
            await page.wait_for_timeout(1_500)
    else:
        logger.warning("[Ficha] La cámara no capturó tras 2 intentos. Botones "
                       "visibles: %s", await _botones_visibles(page) or "(ninguno)")
        return False

    if not await _click(guardar, timeout=10_000):
        if not await _click(guardar, force=True, timeout=5_000):
            logger.warning("[Ficha] 'Save Picture' está visible pero no se "
                           "pudo pulsar. Botones visibles: %s",
                           await _botones_visibles(page) or "(ninguno)")
            return False
    # Confirmar que la foto QUEDÓ: la barra de zoom solo existe con foto
    # guardada. Sin esta espera se escribía el monto sobre un formulario que
    # todavía se estaba re-renderizando y el valor se perdía (el envío no se
    # habilitaba nunca y el fallo salía 30 s más tarde).
    try:
        await page.locator(VALOR_ZOOM).first.wait_for(state="visible",
                                                      timeout=15_000)
        logger.info("[Ficha] Foto tomada y guardada (barra de zoom visible).")
    except Exception:
        await page.wait_for_timeout(1_500)
        logger.info("[Ficha] Foto tomada y guardada (sin barra de zoom).")
    return True


def _a_numero(texto: str):
    """'$ 333.00' / '1,234.50' → float. None si no hay número."""
    limpio = "".join(c for c in (texto or "") if c.isdigit() or c == ".")
    limpio = limpio.rstrip(".")
    try:
        return float(limpio) if limpio else None
    except ValueError:
        return None


PANEL_CALENDARIO = ("p-datepicker, .p-datepicker, .ui-datepicker, "
                    ".p-datepicker-panel")


async def _cerrar_calendario(page) -> None:
    """Cierra el calendario que abre el Tab al salir del monto.

    El campo siguiente al monto es **Deposit Date**, y PrimeNG despliega su
    calendario al recibir el foco. No rompe nada —el botón Send queda fuera
    del panel— pero el desplegable tapa el campo Bank justo en la captura de
    evidencia, que es la que se adjunta al ticket. Un revisor que abre
    `Step01` ve un calendario encima del banco y pregunta.

    Se devuelve el foco con Shift+Tab en vez de pulsar Escape: la ficha vive
    dentro de un diálogo, y un Escape que se propague lo cerraría entero.
    """
    try:
        panel = page.locator(PANEL_CALENDARIO).locator("visible=true").first
        if not await panel.count():
            return
        await page.keyboard.press("Shift+Tab")
        await page.wait_for_timeout(300)
        if await panel.count():
            # Respaldo: clic en una zona muerta del formulario.
            await page.locator("body").click(position={"x": 5, "y": 5})
            await page.wait_for_timeout(300)
        logger.info("[Ficha] Calendario de la fecha cerrado.")
    except Exception as e:
        logger.info("[Ficha] No hizo falta cerrar el calendario (%s).",
                    str(e)[:60])


async def _limpiar_campo(page, campo) -> None:
    """Vacía el campo con máscara (fill + selección + borrado)."""
    try:
        await campo.click()
        await campo.press("Control+A")
        await campo.press("Delete")
        await campo.fill("")
    except Exception:
        pass
    await page.wait_for_timeout(250)


async def escribir_monto(flow, monto: str = "333",
                         confirmar_envio: bool = True) -> bool:
    """Escribe el monto y verifica que la APP lo aceptó de verdad.

    Historia de dos fallos, por si vuelve a aparecer:

    1. La máscara del campo se llena de derecha a izquierda; teclear '333' del
       tirón producía '33.00' — un dígito perdido, reproducible.
    2. `fill('333')` dejaba el campo con el texto '333' **sin formatear**. Ese
       "333" en crudo es la señal de que la máscara nunca procesó el valor: el
       control de Angular seguía vacío y el botón Send jamás se habilitaba,
       aunque el campo se viera correcto. Validar solo el texto era engañoso.

    Por eso el criterio de éxito es el estado REAL de la app: el valor numérico
    coincide **y** el botón de envío queda habilitado. Si no, se prueba la
    siguiente forma de escribir."""
    page = flow.page
    campo = page.get_by_test_id(INPUT_MONTO).first
    try:
        await campo.wait_for(state="visible", timeout=TIMEOUT)
    except Exception as e:
        logger.warning("[Ficha] No apareció el campo de monto: %s", str(e)[:90])
        return False

    objetivo = _a_numero(str(monto))
    if objetivo is None:
        logger.warning("[Ficha] Monto inválido: %r", monto)
        return False
    digitos = str(monto).strip()
    entero = objetivo == int(objetivo)
    # Teclear (que sí dispara los eventos de la máscara) primero; `fill` al
    # final, solo como último recurso.
    intentos = [
        ("teclear", digitos),
        ("teclear_mascara", f"{int(objetivo)}00" if entero else digitos),
        ("teclear_lento", digitos),
        ("fill", digitos),
    ]
    valor = ""
    for modo, texto in intentos:
        await _limpiar_campo(page, campo)
        try:
            if modo == "fill":
                await campo.fill(texto)
                # `fill` no siempre notifica a Angular: se avisa a mano.
                await campo.evaluate(
                    "(el) => { el.dispatchEvent(new Event('input', {bubbles:true}));"
                    " el.dispatchEvent(new Event('change', {bubbles:true})); }")
            else:
                await campo.click()
                await campo.type(texto, delay=200 if modo == "teclear_lento" else 120)
            await campo.press("Tab")            # blur: aquí formatea la máscara
            await page.wait_for_timeout(600)
            valor = (await campo.input_value() or "").strip()
        except Exception as e:
            logger.warning("[Ficha] Error escribiendo el monto (%s): %s",
                           modo, str(e)[:70])
            continue

        if _a_numero(valor) != objetivo:
            logger.info("[Ficha] '%s' vía %s dejó '%s' — pruebo otra forma.",
                        texto, modo, valor)
            continue
        # El Tab de arriba dejó el foco en Deposit Date con su calendario
        # desplegado. Se cierra ANTES de dar el monto por bueno, para que la
        # captura de evidencia salga con el formulario limpio.
        await _cerrar_calendario(page)
        if not confirmar_envio:
            logger.info("[Ficha] Monto %s aplicado (campo='%s', vía %s).",
                        monto, valor, modo)
            return True
        # Prueba de fuego: ¿la app lo aceptó? El botón debe habilitarse.
        if await enviar_habilitado(flow, timeout_ms=6_000, silencioso=True):
            logger.info("[Ficha] Monto %s aplicado y aceptado (campo='%s', "
                        "vía %s).", monto, valor, modo)
            return True
        logger.info("[Ficha] '%s' quedó en el campo con %s pero el envío sigue "
                    "deshabilitado (la máscara no lo registró) — pruebo otra forma.",
                    valor, modo)
    logger.warning("[Ficha] No se pudo aplicar el monto %s (quedó '%s').",
                   monto, valor)
    return False


async def _boton_enviar(page):
    """Botón de envío REAL, entre todos los que comparten el testid genérico.

    Se recorren todas las coincidencias (no `.first`) y se prefiere la que dice
    Send/Enviar. Si ninguna tiene ese texto, se usa la única visible."""
    loc = page.get_by_test_id(BTN_ENVIAR)
    try:
        total = min(await loc.count(), 12)
    except Exception:
        return None
    visibles = []
    for i in range(total):
        btn = loc.nth(i)
        try:
            if not await btn.is_visible():
                continue
            texto = (await btn.inner_text() or "").strip()
            visibles.append((btn, texto))
            if RE_ENVIAR.search(texto):
                return btn
        except Exception:
            continue
    return visibles[0][0] if visibles else None


async def enviar_habilitado(flow, timeout_ms: int = TIMEOUT,
                            silencioso: bool = False) -> bool:
    """True cuando el botón de envío queda habilitado (sondeo rápido).

    `silencioso`: no registra el diagnóstico — lo usa `escribir_monto`, que
    consulta esto varias veces a propósito mientras busca la forma de escribir
    que la máscara acepta."""
    page = flow.page
    espera = 0
    while espera <= timeout_ms:
        btn = await _boton_enviar(page)
        if btn is not None:
            try:
                if await btn.is_enabled():
                    return True
            except Exception:
                pass
        await page.wait_for_timeout(200)
        espera += 200
    if silencioso:
        return False
    # Diagnóstico: sin esto el fallo no dice si el problema es el botón o el monto.
    try:
        monto = (await page.get_by_test_id(INPUT_MONTO).first.input_value() or "").strip()
    except Exception:
        monto = "?"
    loc = page.get_by_test_id(BTN_ENVIAR)
    try:
        textos = [t.strip() for t in await loc.all_inner_texts()][:8]
    except Exception:
        textos = []
    logger.warning("[Ficha] El envío no se habilitó. Monto en el campo='%s' · "
                   "botones '%s' encontrados: %s", monto, BTN_ENVIAR,
                   textos or "(ninguno)")
    return False


async def enviar(flow) -> bool:
    """Pulsa Send y confirma el toast de éxito ('Deposit Slip sent.')."""
    page = flow.page
    if not await enviar_habilitado(flow):
        return False
    btn = await _boton_enviar(page)
    if btn is None or not await _click(btn):
        return False
    # Si Hermes interpone un diálogo (recibo digital y compañía), el toast de
    # éxito no monta: esperarlo sería agotar dos timeouts contra un aviso que
    # no puede llegar hasta que el modal se cierre.
    await _MOD.atender_bloqueantes(flow, logger)
    titulo = page.locator(TOAST_TITULO).filter(has_text=RE_EXITO).first
    texto = page.locator(TOAST_TEXTO).filter(has_text=RE_ENVIADA).first
    for loc, desc in ((titulo, "Success"), (texto, "Deposit Slip sent")):
        try:
            await loc.wait_for(state="visible", timeout=TIMEOUT)
        except Exception:
            logger.warning("[Ficha] No apareció el aviso '%s'.", desc)
            return False
    logger.info("[Ficha] ✓ Ficha enviada.")
    return True


# ── Caso alternativo: zoom, limpiar, borrar/retomar foto ────────────────────

async def zoom(flow, veces: int = 4, acercar: bool = True) -> str:
    """Pulsa zoom + / − N veces y devuelve el valor mostrado (ej. '300%')."""
    page = flow.page
    selector = BTN_ZOOM_MAS if acercar else BTN_ZOOM_MENOS
    for _ in range(veces):
        await _click(page.locator(selector), force=True, timeout=10_000)
        await page.wait_for_timeout(900)
    try:
        valor = (await page.locator(VALOR_ZOOM).first.inner_text() or "").strip()
    except Exception:
        valor = ""
    logger.info("[Ficha] Zoom %s → %s", "in" if acercar else "out", valor or "?")
    return valor


async def limpiar_formulario(flow) -> bool:
    """Icono de limpiar: deja el formulario vacío (el envío debe deshabilitarse)."""
    page = flow.page
    ok = await _click(page.get_by_test_id(BTN_LIMPIAR), force=True)
    await page.wait_for_timeout(2_000)
    return ok


async def envio_deshabilitado(flow, timeout_ms: int = 15_000) -> bool:
    """True si el botón de envío está deshabilitado (validación del caso alt.)."""
    btn = flow.page.get_by_test_id(BTN_ENVIAR).first
    espera = 0
    while espera <= timeout_ms:
        try:
            if await btn.is_visible() and not await btn.is_enabled():
                return True
        except Exception:
            pass
        await flow.page.wait_for_timeout(200)
        espera += 200
    return False


async def borrar_foto(flow) -> bool:
    """Borra la foto: vuelve el marco de la cámara ('Deposit Slip')."""
    page = flow.page
    if not await _click(page.locator(BTN_BORRAR_FOTO), force=True):
        return False
    try:
        await page.locator(TEXTO_CAMARA).first.wait_for(state="visible",
                                                        timeout=TIMEOUT)
        logger.info("[Ficha] Foto borrada — marco de cámara visible.")
        return True
    except Exception:
        logger.warning("[Ficha] No se confirmó el borrado de la foto.")
        return False


async def retomar_foto(flow) -> bool:
    """Botón de retomar + vuelve a tomar y guardar."""
    await _click(flow.page.locator(BTN_RETOMAR), force=True)
    await flow.page.wait_for_timeout(1_000)
    return await tomar_foto(flow)
