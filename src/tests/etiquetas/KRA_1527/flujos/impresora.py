"""
Impresora de recibos — prerrequisito de casi toda la etiqueta.

## Por qué existe (la hipótesis que explica el «SIN COMUNICACIÓN»)

El CP01 hacía el envío, la app decía *«Transaction Successful! Please give the
receipt to the customer»*… y la auditoría veía **cero** llamadas al agente. Once
peticiones, todas a la API de Hermes.

La pista está en el resto del proyecto: los money orders **sí** llegan al agente,
y su flujo empieza por `preparar_impresora()`; los cheques **sí** llegan, y
empiezan por `configurar_escaner()`. Ambos configuran su periférico en
**Configuración > Dispositivos** antes de operar. El recibo del money transfer
no configuraba nada.

Sin impresora seleccionada la aplicación no tiene a quién mandar el trabajo, así
que no invoca al Hardware Agent: no hay error, simplemente no llama. Eso encaja
con lo observado — la impresión «funciona» de cara al usuario porque el envío se
completa, pero el agente nunca entra en juego.

El diálogo de reimpresión (CP05) confirma el modelo: antes de imprimir pide
**Tipo de Impresión** e **Impresora**. Aquí se hace lo mismo, una vez, en la
pantalla de configuración.

## Lo que hace

```
Configuración > Dispositivos
  → combo «Printer» (el PRIMERO de los tres; los otros son Scanner y MO Printer)
  → elige la impresora indicada, o la primera real disponible
```

Es **best-effort y no lanza**: si no puede configurarla, devuelve el motivo para
que el caso lo anote en el reporte. Que falte la impresora no es un fallo del
fix que se audita — pero sí explica un SIN COMUNICACIÓN, y por eso conviene que
quede escrito en la evidencia.

    ok, detalle = await impresora.configurar(flow)
"""

import os
import re

from config.logger import get_logger

logger = get_logger("KRA1527.impresora")

TIMEOUT = 20_000

# Impresora a elegir. Vacío = la primera opción real de la lista.
# En TEST suele haber «MICROSOFT PRINT TO PDF (DEFAULT)», que sirve: lo que se
# audita es la llamada al agente, no el papel.
IMPRESORA = os.getenv("KRA1527_IMPRESORA_RECIBO", "").strip()

NAV_CONFIG = "settings-navbar-item"
OPCION_DISPOSITIVOS = "settings-2-navbar-dropdown-item"
MODAL_DENY = "modal-confirmation-deny-button"          # 'YES, Leave'
COMBO_SEL = "span[role='combobox']"
OPCION_SEL = ("li[role='option'], .p-dropdown-item, "
              "[data-testid$='-dropdown-item']")

# Etiquetas del combo de la impresora de recibos (bilingüe), y las de los OTROS
# dos combos, que hay que descartar para no configurar el equivocado.
ETIQUETAS_PRINTER = ("Printer", "Impresora")
RE_OTROS_COMBOS = re.compile(r"scanner|esc[aá]ner|mo\s*printer|impresora\s*mo",
                             re.I)
# Opciones que NO son una impresora de verdad.
RE_NO_IMPRESORA = re.compile(r"^\s*(select|seleccion|ninguna|none|--)?\s*$", re.I)


async def _click_testid(page, testid: str, desc: str, timeout: int = TIMEOUT) -> bool:
    try:
        b = page.get_by_test_id(testid).first
        await b.wait_for(state="visible", timeout=timeout)
        try:
            await b.click(timeout=6_000)
        except Exception:
            await b.click(force=True, timeout=6_000)
        logger.info("[Impresora] %s", desc)
        return True
    except Exception as e:
        logger.warning("[Impresora] No se pudo pulsar %s: %s", desc, str(e)[:90])
        return False


async def _cerrar_aviso_salida(page, timeout_ms: int = 2_500) -> None:
    """Cierra el «Warning: ¿salir de esta página?» si aparece.

    Se llama ANTES de esperar el submenú, no después: su overlay impide pulsar
    el submenú y el fallo salía como un timeout apuntando al sitio equivocado."""
    espera = 0
    while espera <= timeout_ms:
        try:
            btn = page.locator(f'[data-testid="{MODAL_DENY}"]')
            for i in range(min(await btn.count(), 5)):
                el = btn.nth(i)
                if await el.is_visible():
                    await el.click(force=True, timeout=3_000)
                    logger.info("[Impresora] Aviso de salida cerrado.")
                    await page.wait_for_timeout(400)
                    return
        except Exception:
            pass
        await page.wait_for_timeout(150)
        espera += 150


async def ir_a_dispositivos(flow, intentos: int = 3) -> bool:
    """Configuración > Dispositivos."""
    page = flow.page
    for intento in range(1, intentos + 1):
        await _cerrar_aviso_salida(page, timeout_ms=1_200)
        if not await _click_testid(page, NAV_CONFIG, "Menú Configuración"):
            continue
        await page.wait_for_timeout(600)
        await _cerrar_aviso_salida(page, timeout_ms=1_500)
        if await _click_testid(page, OPCION_DISPOSITIVOS, "Dispositivos abierto"):
            await _cerrar_aviso_salida(page, timeout_ms=2_500)
            await page.wait_for_timeout(1_200)
            return True
        logger.info("[Impresora] Dispositivos no respondió (intento %d/%d).",
                    intento, intentos)
    return False


async def _esperar_combos(page, minimo: int = 2, timeout_ms: int = 20_000) -> int:
    """Espera a que Dispositivos pinte sus combos (carga en diferido).

    Al llegar solo hay uno o dos; el de MO Printer aparece después. Contarlos de
    inmediato hacía elegir el combo equivocado."""
    espera, total = 0, 0
    while espera <= timeout_ms:
        try:
            total = await page.locator(COMBO_SEL).count()
            if total >= minimo:
                await page.wait_for_timeout(600)
                logger.info("[Impresora] Dispositivos listo: %d combo(s).", total)
                return total
        except Exception:
            pass
        await page.wait_for_timeout(300)
        espera += 300
    logger.warning("[Impresora] Dispositivos mostró solo %d combo(s) en %.0f s.",
                   total, timeout_ms / 1000)
    return total


async def _combo_impresora(page):
    """El combo «Printer», descartando Scanner y MO Printer.

    Los tres comparten `id="dropdown"`, así que se localiza por su etiqueta. El
    respaldo es el PRIMER combobox visible: el orden de la pantalla es Printer,
    Scanner, MO Printer."""
    await _esperar_combos(page)
    for etiqueta in ETIQUETAS_PRINTER:
        try:
            loc = page.locator(
                f"xpath=//*[normalize-space(text())='{etiqueta}']"
                f"/following::span[@role='combobox'][1]").first
            if await loc.count() and await loc.is_visible():
                logger.info("[Impresora] Combo hallado por la etiqueta '%s'.",
                            etiqueta)
                return loc
        except Exception:
            continue
    try:
        combos = page.locator(COMBO_SEL)
        for i in range(min(await combos.count(), 6)):
            el = combos.nth(i)
            if await el.is_visible():
                etiqueta = (await el.get_attribute("aria-label")) or ""
                # Si el primer visible resulta ser el escáner o el de MO, no es.
                if RE_OTROS_COMBOS.search(etiqueta):
                    continue
                logger.info("[Impresora] Combo: primer combobox visible "
                            "(respaldo).")
                return el
    except Exception:
        pass
    return None


async def _valor(combo) -> str:
    try:
        return ((await combo.get_attribute("aria-label"))
                or (await combo.inner_text()) or "").strip()
    except Exception:
        return ""


async def configurar(flow, impresora: str = None, evi=None):
    """Selecciona la impresora de recibos. Devuelve `(ok, detalle)`.

    No lanza: la etiqueta audita el token, no la configuración del equipo. Pero
    el detalle se anota en el reporte, porque una impresora sin configurar es la
    explicación más probable de un «SIN COMUNICACIÓN»."""
    page = flow.page
    objetivo = impresora if impresora is not None else IMPRESORA

    if not await ir_a_dispositivos(flow):
        return False, ("No se pudo abrir Configuración > Dispositivos, así que "
                       "no se pudo verificar la impresora de recibos.")

    combo = await _combo_impresora(page)
    if combo is None:
        return False, ("No apareció el combo «Printer» en Dispositivos.")

    actual = await _valor(combo)
    if actual and not RE_NO_IMPRESORA.search(actual):
        if not objetivo or objetivo.casefold() in actual.casefold():
            logger.info("[Impresora] Ya configurada: '%s'.", actual)
            if evi is not None:
                await evi.shot("impresora_configurada", locators=[combo])
            return True, f"Impresora de recibos ya configurada: «{actual}»."

    # Desplegar y elegir.
    try:
        try:
            await combo.click(timeout=6_000)
        except Exception:
            await combo.click(force=True, timeout=6_000)
        await page.wait_for_timeout(800)
    except Exception as e:
        return False, f"No se pudo desplegar el combo de impresora: {str(e)[:90]}"

    opciones = page.locator(OPCION_SEL)
    disponibles = []
    elegida = ""
    espera = 0
    while espera <= 10_000 and not elegida:
        total = min(await opciones.count(), 40)
        for i in range(total):
            el = opciones.nth(i)
            try:
                if not await el.is_visible():
                    continue
                texto = ((await el.inner_text()) or "").strip()
            except Exception:
                continue
            if not texto or RE_NO_IMPRESORA.search(texto):
                continue
            disponibles.append(texto)
            coincide = (objetivo.casefold() in texto.casefold()
                        if objetivo else True)
            if coincide:
                try:
                    await el.click(timeout=6_000)
                except Exception:
                    await el.click(force=True, timeout=6_000)
                elegida = texto
                break
        if elegida:
            break
        await page.wait_for_timeout(300)
        espera += 300

    if not elegida:
        return False, (f"No se pudo elegir impresora"
                       + (f" '{objetivo}'" if objetivo else "")
                       + ". Disponibles: "
                       + (", ".join(f"«{d}»" for d in disponibles[:8])
                          or "(ninguna)"))

    await page.wait_for_timeout(900)
    confirmado = await _valor(combo)
    logger.info("[Impresora] ✓ Seleccionada '%s' (el combo muestra '%s').",
                elegida, confirmado or "?")
    if evi is not None:
        await evi.shot("impresora_configurada", locators=[combo])
    # Salir de Configuración deja el aviso de «cambios sin guardar» pendiente;
    # cerrarlo aquí evita que bloquee el primer clic del flujo siguiente.
    await _cerrar_aviso_salida(page, timeout_ms=1_500)
    return True, f"Impresora de recibos: «{elegida}»."
