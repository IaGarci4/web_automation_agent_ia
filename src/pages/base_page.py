"""
BasePage — clase base para todos los Page Objects.

Fusiona lo mejor de HERMES2-qa + mejoras propias:
  - wait_and_click con retry automático si hay overlays
  - fill_input_by_testid para campos Angular (click + fill + wait)
  - select_dropdown_by_aria_label para dropdowns PrimeNG
  - wait_for_no_blocking_overlays detecta loaders, modales, etc.
  - format_selector / format_testid_selector para selectores dinámicos
  - Timeouts centralizados como constantes de clase
"""

import re
import time
from abc import ABC
from playwright.async_api import Page, Locator, expect
from config.logger import get_logger
from config.settings import TIMEOUT_ELEMENT, TIMEOUT_SHORT, TIMEOUT_MODAL


class BasePage(ABC):
    # ── Timeouts (ms) ─────────────────────────────────────────────────────────
    DEFAULT_WAIT    = 3_000
    SHORT_WAIT      = 1_000
    MEDIUM_WAIT     = 2_000
    LONG_WAIT       = 5_000
    FIELD_TIMEOUT   = 20_000
    MODAL_TIMEOUT   = TIMEOUT_MODAL

    def __init__(self, page: Page):
        self.page   = page
        self.logger = get_logger(self.__class__.__name__)

    # ── Navegación ────────────────────────────────────────────────────────────

    async def goto(self, url: str, timeout: int = 60_000) -> None:
        self.logger.info(f"Navegando a: {url}")
        await self.page.goto(url, wait_until="domcontentloaded", timeout=timeout)

    async def wait_for_url(self, pattern: str, timeout: int = 30_000) -> None:
        await self.page.wait_for_url(pattern, timeout=timeout)

    # ── Clicks ────────────────────────────────────────────────────────────────

    async def click(self, selector: str, timeout: int = TIMEOUT_ELEMENT) -> None:
        """Click estándar con .first para manejar múltiples matches en tests MULTI."""
        self.logger.info(f"Click: {selector}")
        await self.page.locator(selector).first.click(timeout=timeout)

    async def wait_and_click(self, selector: str, timeout: int = 30_000) -> None:
        """
        Click con retry automático:
          1. Intenta click normal
          2. Si falla → espera que desaparezcan overlays → reintenta
          3. Si vuelve a fallar → force click
        """
        self.logger.info(f"Wait and click: {selector}")
        # .first: evita el error de strict mode cuando el selector matchea
        # varios elementos (ej. [aria-label="dropdown"] aparece N veces)
        locator = self.page.locator(selector).first
        try:
            await locator.click(timeout=timeout)
            return
        except Exception as e:
            self.logger.warning(f"Click normal falló ({str(e)[:80]}), esperando overlays...")
            await self.wait_for_no_blocking_overlays(timeout=3_000)
            try:
                await locator.click(timeout=5_000)
                self.logger.info(f"✓ Click exitoso tras overlay wait: {selector}")
            except Exception:
                self.logger.warning("Reintento normal falló → force click")
                await locator.click(force=True)
                self.logger.info(f"✓ Force click: {selector}")

    async def click_testid(self, test_id: str, timeout: int = TIMEOUT_ELEMENT) -> None:
        """Click por data-testid."""
        locator = self.page.get_by_test_id(test_id)
        await expect(locator).to_be_visible(timeout=timeout)
        await locator.click()

    # ── Click adaptativo ──────────────────────────────────────────────────────

    async def smart_click(
        self,
        testid: str = None,
        css: str = None,
        texto: str = None,
        fallbacks: list = None,
        timeout: int = None,
        optional: bool = False,
    ) -> None:
        """
        Click ADAPTATIVO — resuelve en runtime los conflictos de localización
        típicos de HERMES2 sin necesidad de casos especiales:

          • testids/ids GENÉRICOS repetidos (test-id-button, typography...):
            si el selector matchea varios elementos, desambigua por texto;
            si el texto no matchea (ej. cambió el idioma), usa el primer
            match VISIBLE en vez de fallar por strict mode
          • elemento aún no renderizado: polling hasta el deadline
          • overlays/loaders que interceptan el click: espera + reintento
          • selector primario roto: prueba los FALLBACKS auditados por la
            extensión (ancestro testid, formcontrolname, aria-label, id...)
          • al agotar el tiempo: error con diagnóstico de TODO lo intentado

        Args:
            testid:    data-testid primario
            css:       selector CSS primario (alternativa a testid)
            texto:     texto visible para desambiguar matches múltiples
            fallbacks: selectores CSS alternativos (candidatos auditados)
            timeout:   deadline total en ms (default TIMEOUT_ELEMENT)
            optional:  si True y el elemento nunca aparece, NO falla — registra
                       y continúa (para elementos condicionales: branch, etc.)
        """
        # Elementos opcionales: ventana corta (no esperar 90s a algo que
        # puede no existir nunca, como el branch cuando no es requerido).
        timeout = timeout or (8_000 if optional else TIMEOUT_ELEMENT)
        deadline = time.monotonic() + timeout / 1000

        # Estrategias en orden: primaria + fallbacks auditados
        strategies = []
        if testid:
            strategies.append(("testid", testid))
        if css:
            strategies.append(("css", css))
        for fb in (fallbacks or []):
            strategies.append(("css", fb))
        if not strategies:
            raise ValueError("smart_click requiere testid o css")

        diag = []
        while True:
            diag = []
            for kind, sel in strategies:
                base = (self.page.get_by_test_id(sel) if kind == "testid"
                        else self.page.locator(sel))
                try:
                    count = await base.count()
                except Exception as e:
                    diag.append(f"{kind}:{sel} → error: {str(e)[:50]}")
                    continue
                if count == 0:
                    diag.append(f"{kind}:{sel} → 0 matches")
                    continue

                # Múltiples matches → desambiguar por texto
                loc = base
                if count > 1 and texto:
                    filtered = base.filter(has_text=texto)
                    try:
                        fcount = await filtered.count()
                    except Exception:
                        fcount = 0
                    if fcount >= 1:
                        loc, count = filtered, fcount

                # Elegir el primer match VISIBLE
                target = None
                for i in range(min(count, 15)):
                    cand = loc.nth(i)
                    try:
                        if await cand.is_visible():
                            target = cand
                            break
                    except Exception:
                        continue
                if target is None:
                    diag.append(f"{kind}:{sel} → {count} match(es), ninguno visible")
                    continue

                # Click — si un overlay intercepta, esperar y reintentar
                try:
                    await target.click(timeout=2_500)
                    extra = f" [texto~'{texto}']" if texto and count > 1 else ""
                    self.logger.info(f"✓ smart_click: {kind}={sel}{extra}")
                    return
                except Exception as e:
                    msg = str(e)
                    if "intercepts pointer events" in msg:
                        await self.wait_for_no_blocking_overlays(timeout=3_000)
                        try:
                            await target.click(timeout=2_500)
                            self.logger.info(
                                f"✓ smart_click (tras overlay): {kind}={sel}"
                            )
                            return
                        except Exception:
                            pass
                    # ÚLTIMO RECURSO: force click (como el repo HERMES2-qa con el
                    # botón Continuar: wait visible + click(force=True)). Ignora
                    # los chequeos de "estable/habilitado" que bloquean botones
                    # como Continue que están visibles pero la actionability
                    # de Playwright rechaza.
                    try:
                        await target.scroll_into_view_if_needed(timeout=2_000)
                    except Exception:
                        pass
                    try:
                        await target.click(force=True, timeout=2_500)
                        self.logger.info(f"✓ smart_click (force): {kind}={sel}")
                        return
                    except Exception:
                        pass
                    diag.append(f"{kind}:{sel} → click falló: {msg.splitlines()[0][:70]}")

            if time.monotonic() >= deadline:
                break
            await self.page.wait_for_timeout(400)

        if optional:
            self.logger.info(
                "smart_click opcional: el elemento no apareció — se omite "
                "(no requerido en este flujo)."
            )
            return

        raise AssertionError(
            "smart_click agotó el tiempo sin lograr el click.\n"
            "Estrategias probadas:\n  " + "\n  ".join(diag)
            + f"\nURL actual: {self.page.url}"
        )

    # ── Inputs ────────────────────────────────────────────────────────────────

    async def _esperar_editable(self, loc, timeout: int = 20_000) -> None:
        """
        Espera ACOTADA a que el campo sea editable. Si Playwright no lo marca
        editable a tiempo (pasa con inputs dentro de modales o con máscaras
        que reportan estado raro), NO se cuelga 90s: espera a que sea visible
        y deja que el fill lo intente igual. Evita el hang de 90s del modal
        de Payer.
        """
        try:
            await expect(loc).to_be_editable(timeout=timeout)
            return
        except Exception:
            self.logger.warning(
                "[fill] El campo no reportó 'editable' a tiempo — intento llenarlo igual."
            )
            try:
                await loc.wait_for(state="visible", timeout=5_000)
            except Exception:
                pass

    async def fill(self, selector: str, text: str) -> None:
        """
        Fill verificado: espera (acotada) que el campo sea editable, escribe y
        VERIFICA que el valor quedó. Si no, reintenta con teclado y, si aun así
        difiere (máscaras), advierte y continúa.
        """
        self.logger.info(f"Fill {selector}: {text}")
        await self._cerrar_autofill()
        loc = self.page.locator(selector).first
        await self._esperar_editable(loc)
        try:
            await loc.click(force=True)
        except Exception:
            pass
        await loc.fill(text)
        if not self._valor_coincide(await loc.input_value(), text):
            self.logger.warning(
                f"Valor no coincide en {selector} — reintentando con teclado"
            )
            await loc.clear()
            await loc.press_sequentially(text, delay=50)
            actual = await loc.input_value()
            if not self._valor_coincide(actual, text):
                # No abortar: campos con máscara (fecha, monto) reformatean el
                # valor. Se advierte y se continúa — la evidencia/diagnóstico
                # conservan la señal por si el dato quedó realmente mal.
                self.logger.warning(
                    f"[fill] Valor reformateado en {selector}: "
                    f"escribí '{text}', quedó '{actual}' — continúo."
                )

    async def fill_monto(self, test_id: str, valor) -> None:
        """
        Llena el campo de MONTO de forma robusta: LIMPIA primero (Ctrl+A +
        Delete) y luego TECLEA carácter por carácter, disparando los eventos
        input/change/blur. HERMES rechaza el monto si se pega de golpe o queda
        contenido residual ('Field required' / 'Amount must be at least $1.00').
        """
        valor = str(valor)
        await self._cerrar_autofill()
        campo = self.page.get_by_test_id(test_id)
        await self._esperar_editable(campo)
        await campo.click(force=True)
        # Limpiar lo que haya (selección total + borrar)
        try:
            await campo.press("Control+a")
            await campo.press("Delete")
        except Exception:
            try:
                await campo.fill("")
            except Exception:
                pass
        await self.page.wait_for_timeout(100)
        # Teclear de verdad para que Angular registre el valor
        await campo.press_sequentially(valor, delay=80)
        # Disparar validaciones
        try:
            await campo.evaluate(
                "i => { i.dispatchEvent(new Event('input',{bubbles:true}));"
                " i.dispatchEvent(new Event('change',{bubbles:true}));"
                " i.dispatchEvent(new Event('blur',{bubbles:true})); }")
        except Exception:
            pass
        await self.page.wait_for_timeout(150)
        # Verificación: si quedó vacío o distinto, reintenta una vez
        try:
            actual = (await campo.input_value()).strip()
            if not actual:
                await campo.click(force=True)
                await campo.press_sequentially(valor, delay=100)
        except Exception:
            pass
        self.logger.info(f"✓ monto '{valor}' escrito en {test_id}")

    async def fill_input_by_testid(
        self,
        test_id: str,
        value: str,
        field_name: str = None,
        wait_timeout: int = None,
        use_type: bool = False,
        delay: int = 600,
    ) -> None:
        """
        Patrón estándar para campos Angular:
          espera editable + click(force) + fill + VERIFICACIÓN del valor.
        Sin esperas fijas — espera explícita solo hasta que el campo esté listo.
        """
        field_name = field_name or test_id

        await self._cerrar_autofill()
        input_field = self.page.get_by_test_id(test_id)
        await self._esperar_editable(input_field)
        await input_field.click(force=True)

        if use_type:
            await input_field.press_sequentially(value, delay=delay)
        else:
            await input_field.fill(value)

        if not self._valor_coincide(await input_field.input_value(), value):
            self.logger.warning(
                f"Valor no coincide en {field_name} — reintentando con teclado"
            )
            await input_field.clear()
            await input_field.press_sequentially(value, delay=50)
            actual = await input_field.input_value()
            if not self._valor_coincide(actual, value):
                # No abortar: campos con máscara (fecha, monto) reformatean.
                self.logger.warning(
                    f"[fill] Valor reformateado en {field_name}: "
                    f"escribí '{value}', quedó '{actual}' — continúo."
                )
        self.logger.info(f"✓ {field_name} llenado: {value}")

    @staticmethod
    def _valor_coincide(actual: str, esperado: str) -> bool:
        """
        ¿El valor del campo corresponde al que escribimos, tolerando las
        transformaciones que aplican muchos campos de HERMES?
          • text-transform: uppercase/lowercase (ej. nombres → MAYÚSCULAS)
          • máscaras de formato (teléfono, monto '$216.25', fechas)
          • espacios/recortes
        Compara ignorando mayúsculas y, como respaldo, solo los caracteres
        alfanuméricos (descarta separadores de máscara).
        """
        a = (actual or "").strip()
        e = (esperado or "").strip()
        if a == e:
            return True
        if a.casefold() == e.casefold():           # mismo texto, distinto case
            return True
        import re as _re
        a2 = _re.sub(r"[^0-9a-zA-Záéíóúñ]", "", a).casefold()
        e2 = _re.sub(r"[^0-9a-zA-Záéíóúñ]", "", e).casefold()
        return bool(a2) and a2 == e2               # iguales sin separadores

    async def wait_and_fill(
        self,
        test_id: str,
        value: str,
        field_name: str = None,
        enable_timeout: int = None,
        wait_timeout: int = None,
        use_type: bool = False,
        delay: int = 600,
    ) -> None:
        """Espera que el campo esté habilitado antes de llenar (campos dinámicos)."""
        enable_timeout = enable_timeout or self.FIELD_TIMEOUT
        field_name     = field_name or test_id

        self.logger.info(f"Esperando habilitación de: {field_name}")
        input_field = self.page.get_by_test_id(test_id)
        await expect(input_field).to_be_enabled(timeout=enable_timeout)
        await input_field.click(force=True)

        if use_type:
            await input_field.press_sequentially(value, delay=delay)
        else:
            await input_field.fill(value)

        if await input_field.input_value() != value:
            await input_field.clear()
            await input_field.press_sequentially(value, delay=50)
        self.logger.info(f"✓ {field_name} llenado: {value}")

    async def fill_and_blur(
        self, test_id: str, value: str, field_name: str = None, wait_timeout: int = None
    ) -> None:
        """Fill + blur para disparar validaciones Angular."""
        wait_timeout = wait_timeout or self.DEFAULT_WAIT
        field_name   = field_name or test_id

        input_field = self.page.get_by_test_id(test_id)
        await input_field.click(force=True)
        await input_field.fill(value)
        await input_field.blur()
        await self.page.wait_for_timeout(wait_timeout)
        self.logger.info(f"✓ {field_name} llenado y validado: {value}")

    # ── Dropdowns PrimeNG ─────────────────────────────────────────────────────

    async def select_dropdown_by_aria_label(
        self,
        dropdown_selector: str,
        option_aria_label: str,
        wait_timeout: int = None,
    ) -> None:
        """Selecciona opción de dropdown PrimeNG usando aria-label."""
        wait_timeout = wait_timeout or self.DEFAULT_WAIT

        dropdown = self.page.locator(dropdown_selector).first
        await dropdown.wait_for(state="visible", timeout=TIMEOUT_ELEMENT)
        self.logger.info(f"Abriendo dropdown: {dropdown_selector}")
        await dropdown.click(force=True)
        await self.page.wait_for_timeout(1_500)

        option = self.page.locator(f'li[role="option"][aria-label="{option_aria_label}"]').first
        await option.wait_for(state="visible", timeout=TIMEOUT_ELEMENT)
        await option.click(force=True)
        await self.page.wait_for_timeout(wait_timeout)
        self.logger.info(f"✓ Opción seleccionada: {option_aria_label}")

    async def select_option_by_text(
        self,
        dropdown_selector: str,
        options_selector: str,
        option_text: str,
        timeout: int = TIMEOUT_ELEMENT,
    ) -> None:
        """
        Selecciona opción de dropdown. Muchos dropdowns de HERMES son
        TYPE-AHEAD: las opciones solo aparecen al teclear letra por letra
        (ej. 'Mexico Regular', 'Guadalajara'). Por eso, si el control es un
        input, se escribe el texto con delay para disparar el filtrado y
        recién entonces se elige la opción (exact → partial, sin importar
        mayúsculas). Como respaldo, Enter selecciona la opción resaltada.
        """
        self.logger.info(f"Seleccionando '{option_text}' en {dropdown_selector}")
        # Limpia overlays de autofill que puedan estar tapando el control
        await self._cerrar_autofill()
        # Cierra cualquier modal/overlay PrimeNG superior (p.ej. el modal de Payers
        # o un panel de autocomplete) que esté TAPANDO este dropdown — esa es la causa
        # de 'Opción no encontrada. Disponibles (0)'. Escape no afecta la selección
        # ya confirmada del pagador.
        try:
            await self.page.keyboard.press("Escape")
            await self.page.wait_for_timeout(120)
        except Exception:
            pass

        dropdown = self.page.locator(dropdown_selector).first
        await dropdown.wait_for(state="visible", timeout=min(timeout, 8_000))
        # click FORZADO con tope corto: si un overlay 'no bloqueante' cubre el campo,
        # un click normal espera accionabilidad hasta 30s. force + 4s evita ese cuelgue.
        try:
            await dropdown.click(force=True, timeout=4_000)
        except Exception:
            pass
        await self.page.wait_for_timeout(300)

        # ¿Es un input? → type-ahead letra por letra
        es_input = False
        try:
            es_input = (await dropdown.evaluate("el => el.tagName")) in ("INPUT", "TEXTAREA")
        except Exception:
            pass
        if es_input:
            try:
                await dropdown.fill("")
            except Exception:
                pass
            await dropdown.press_sequentially(option_text, delay=120)
            await self.page.wait_for_timeout(500)

        # Opciones candidatas (las que pasó el generador + clases comunes PrimeNG)
        sel = (options_selector + ", li[role='option'], .p-dropdown-item, "
               ".p-autocomplete-item, .ng-option, [role='option']")
        opciones = self.page.locator(sel)
        try:
            # Espera CORTA (no 90s): si no aparece pronto, caemos al Enter
            await opciones.first.wait_for(state="visible", timeout=4_000)
        except Exception:
            pass

        # Buscar match: exacto (casefold) primero, luego contiene
        objetivo = option_text.strip().casefold()
        n = await opciones.count()
        idx_parcial = -1
        for i in range(min(n, 40)):
            try:
                t = (await opciones.nth(i).inner_text()).strip().casefold()
            except Exception:
                continue
            if t == objetivo:
                await opciones.nth(i).click(force=True, timeout=4_000)
                self.logger.info(f"✓ '{option_text}' (exact match)")
                return
            if idx_parcial < 0 and objetivo in t:
                idx_parcial = i
        if idx_parcial >= 0:
            await opciones.nth(idx_parcial).click(force=True, timeout=4_000)
            self.logger.info(f"✓ '{option_text}' (partial match)")
            return

        # Respaldo: Enter (autocomplete suele seleccionar la opción resaltada)
        if es_input:
            await dropdown.press("Enter")
            await self.page.wait_for_timeout(400)
            self.logger.info(f"✓ '{option_text}' (Enter sobre type-ahead)")
            return

        self.logger.error(f"Opción '{option_text}' no encontrada. Disponibles ({n}):")
        for i in range(min(n, 10)):
            try:
                self.logger.error(f"  [{i}] '{await opciones.nth(i).text_content()}'")
            except Exception:
                pass
        raise Exception(f"Opción '{option_text}' no encontrada en {dropdown_selector}")

    async def select_typeahead(self, test_id: str, value: str,
                               options_selector: str = None) -> None:
        """
        Campo de AUTOCOMPLETADO dinámico (ciudades de HERMES: Transfer City,
        Beneficiary City). Técnica que pidió QA y que la app necesita:
          1. Llenado RÁPIDO para acercar el valor.
          2. Click en el MISMO input y re-tecleo MUY DESPACIO (letra por letra)
             para darle tiempo al dropdown a mostrar la coincidencia.
          3. Selecciona la opción que aparece (ej. 'GUADALAJARA, JALISCO,
             MEXICO'); si no, baja+Enter sobre la resaltada.
        """
        await self._cerrar_autofill()
        # Cerrar panel/overlay de un dropdown PREVIO (p.ej. el autocomplete de País)
        # que haya quedado abierto y tape ESTE campo. Escape no afecta la selección ya
        # confirmada; libera la zona para teclear/seleccionar la ciudad sin cuelgues.
        try:
            await self.page.keyboard.press("Escape")
            await self.page.wait_for_timeout(120)
        except Exception:
            pass
        field = self.page.get_by_test_id(test_id)
        # Espera de editable ACOTADA (6s, no 20s): el typeahead de Ciudad suele estar
        # listo en <1s; si tarda, igual intentamos llenar — no perder 20-30s aqui.
        await self._esperar_editable(field, timeout=6_000)
        sel = options_selector or (
            "li[role='option'], .p-autocomplete-item, .p-dropdown-item, "
            ".ng-option, [role='option'], .dropdown-item, button.dropdown-item, "
            "[data-testid$='-dropdown-item']")

        # UNA sola escritura (sin doble llenado). Se llena de una; el dropdown
        # dinámico muestra las coincidencias. Si la opción exacta es visible, se
        # clickea; si no, ArrowDown+Enter elige la sugerencia resaltada (que es
        # lo que de hecho funciona en HERMES).
        # click FORZADO con tope corto (no 30s por defecto): enfoca el input aunque
        # haya overlay; si no se puede, seguimos y tecleamos al foco.
        try:
            await field.click(force=True, timeout=4_000)
        except Exception:
            pass
        # fill() de Playwright espera ACTIONABILITY hasta 30s; si un overlay tapa el
        # campo se cuelga ~30s. Lo capamos a 4s y, si falla, TECLEAMOS al foco
        # (keyboard.type NO espera accionabilidad) — el force-click ya enfocó.
        try:
            await field.fill(value, timeout=4_000)
        except Exception:
            try:
                await self.page.keyboard.type(value, delay=20)
            except Exception:
                pass
        if await self._elegir_opcion(sel, value, espera_ms=1500):
            return

        # Respaldo A: CLICK por TEXTO EXACTO visible. Los catálogos custom (ej.
        # estados de EU / pagador ATM) despliegan la opción como una fila de texto
        # que NO cae en los selectores de arriba; hay que CLICKEARLA para habilitar
        # el siguiente campo (ArrowDown+Enter a veces NO confirma la selección).
        try:
            opt = self.page.get_by_text(value, exact=True)
            m = await opt.count()
            for i in range(min(m, 10)):
                o = opt.nth(i)
                try:
                    if await o.is_visible():
                        await o.click(timeout=2_500)
                        self.logger.info(f"✓ typeahead '{value}' (click por texto exacto)")
                        return
                except Exception:
                    continue
        except Exception:
            pass

        # Respaldo B: bajar a la sugerencia y Enter
        # keyboard.press va al elemento ENFOCADO sin esperar accionabilidad (a
        # diferencia de field.press, que espera hasta 30s si un overlay tapa el
        # campo — ESE era el cuelgue de ~30s que terminaba en 'sin opción').
        try:
            await self.page.keyboard.press("ArrowDown")
            await self.page.keyboard.press("Enter")
            self.logger.info(f"✓ typeahead '{value}' (ArrowDown+Enter)")
        except Exception:
            self.logger.warning(f"[typeahead] sin opción para '{value}' — continúo")

    async def _elegir_opcion(self, sel: str, value: str, espera_ms: int = 1500) -> bool:
        """
        Espera CORTA a que aparezca una opción visible que contenga `value` y
        la clickea. Devuelve True si seleccionó. NUNCA espera 90s: hace polling
        breve hasta `espera_ms` y se rinde rápido para no colgar el flujo.
        """
        objetivo = value.strip().casefold()
        opciones = self.page.locator(sel)
        import time as _t
        deadline = _t.monotonic() + espera_ms / 1000
        while _t.monotonic() < deadline:
            n = await opciones.count()
            for i in range(min(n, 25)):
                cand = opciones.nth(i)
                try:
                    if not await cand.is_visible():
                        continue
                    t = (await cand.inner_text()).strip().casefold()
                except Exception:
                    continue
                if objetivo in t:
                    await cand.click()
                    self.logger.info(f"✓ typeahead '{value}' → '{t}'")
                    return True
            await self.page.wait_for_timeout(200)
        return False

    # ── Cancelación de transacción (reusable en cualquier money transfer) ─────

    async def cancelar_transaccion(self, reason_index: int = 0,
                                   notes: str = "Automation",
                                   row_index: int = 0) -> None:
        """
        Cancela una transacción en Reportes > Transacciones — port fiel del
        repo HERMES2-qa. Reusable por cualquier flujo de money transfer.

        Pasos (inteligente, independiente del idioma):
          1. Abre el menú kebab de la fila `row_index` (0 = primera).
          2. Selecciona 'Cancel' del menú.
          3. Confirma el diálogo de bill payment si aparece (opcional).
          4. Reason: elige la opción `reason_index` del dropdown (cualquiera).
          5. Notes: escribe el texto (default 'Automation').
          6. Confirma con 'Cancelar Transacción'.

        Búsqueda por nombre: hazla antes con los campos del reporte; este
        método cancela la PRIMERA fila del resultado (row_index=0).
        """
        # ── 1) Abrir menú kebab de la fila. PRIMERO se espera a que RENDERICEN
        #       las filas del resultado (aparecen ~2-3 s después de dar Buscar).
        #       Antes el chequeo corría de inmediato con count()==0 y saltaba
        #       TODOS los selectores antes de que existieran las filas → "no abrí
        #       el menú". Ahora se espera la tabla y cada candidato tiene su propia
        #       espera breve. ──
        self.logger.info("[Cancelación] Abriendo menú de la transacción...")
        # Esperar a que aparezca alguna fila/kebab del reporte (hasta ~12 s)
        try:
            await self.page.locator(
                "tr.report-transactions-result-row, .p-scroller-content .ng-star-inserted, "
                ".td-options .icon, button.report-transaction-menu-toggle, "
                "[data-testid*='menu-toggle']"
            ).first.wait_for(state="visible", timeout=12_000)
            await self.page.wait_for_timeout(500)
        except Exception:
            self.logger.warning("[Cancelación] No aparecieron filas de resultado tras Buscar.")

        kebab_candidatos = [
            "button.report-transaction-menu-toggle",
            "[data-testid*='menu-toggle']",
            "[data-testid*='menu-icon']",
            f".p-scroller-content .ng-star-inserted:nth-of-type({row_index + 1}) .td-options .icon",
            ".td-options .icon",
            ".td-options button",
            "tr.report-transactions-result-row .icon",
        ]
        abierto = False
        for sel in kebab_candidatos:
            try:
                loc = self.page.locator(sel)
                # Espera BREVE por si ese selector tarda en aparecer (no salta al toque)
                try:
                    await loc.first.wait_for(state="visible", timeout=2_500)
                except Exception:
                    pass
                cnt = await loc.count()
                if cnt == 0:
                    continue
                target = loc.nth(row_index) if cnt > row_index else loc.first
                await target.scroll_into_view_if_needed(timeout=2_000)
                await target.click(force=True, timeout=3_000)
                self.logger.info(f"[Cancelación] Menú kebab abierto (selector: {sel}).")
                abierto = True
                break
            except Exception:
                continue
        if not abierto:
            self.logger.warning("[Cancelación] No abrí el menú kebab con los selectores conocidos.")
        await self.page.wait_for_timeout(400)

        # ── 2) Opción 'Cancel' del menú (testid del repo; se prueban variantes) ──
        for tid in ("reports-transaction-menu-cancel-paragraph-semi-bold",
                    "reports-transaction-menu--cancel-paragraph-semi-bold"):
            try:
                item = self.page.get_by_test_id(tid)
                if await item.count() == 0:
                    continue
                await item.first.click(force=True, timeout=4_000)
                break
            except Exception:
                continue
        await self.page.wait_for_timeout(500)

        # Confirmar diálogo de bill payment si aparece (opcional)
        try:
            conf = self.page.get_by_test_id("cancel-bill-payment-confirmation-deny-button")
            if await conf.is_visible(timeout=1500):
                await conf.click(force=True)
                await self.page.wait_for_timeout(800)
        except Exception:
            pass

        # ── 3) Confirmar que el modal ABRIÓ usando el input de Notes (testid
        #       conocido y estable). Si no aparece, el menú/cancel no abrió. ──
        notas = self.page.get_by_test_id("modal-cancel-transaction-notes-input")
        try:
            await notas.wait_for(state="visible", timeout=15_000)
            self.logger.info("[Cancelación] Modal de cancelación abierto.")
        except Exception:
            self.logger.warning(
                "[Cancelación] El modal no abrió (menú/Cancel no respondió) — abortando paso")
            raise

        # ── 4) Reason: abrir el combo probando selectores PrimeNG conocidos ──
        self.logger.info(f"[Cancelación] Reason (índice {reason_index})...")
        # Modal = el diálogo que CONTIENE el input de Notes (independiente del
        # idioma: 'Cancellation' / 'Cancelación').
        modal = self.page.locator("div[role='dialog'], p-dialog, .p-dialog").filter(
            has=self.page.get_by_test_id("modal-cancel-transaction-notes-input")).last
        if await modal.count() == 0:
            modal = self.page  # fallback: página completa

        reason_selectors = [
            ".select-dropdown-custom",           # custom de esta versión de HERMES
            "div#dropdown.select-dropdown-custom",
            "p-dropdown",
            ".p-dropdown",
            ".p-dropdown-label-empty",           # versión estándar PrimeNG
            ".p-dropdown-label",
            "span[role='combobox']",
            "[aria-haspopup='listbox']",
        ]
        combo = None
        for sel in reason_selectors:
            try:
                cand = modal.locator(sel)
                if await cand.count() > 0 and await cand.first.is_visible():
                    combo = cand.first
                    self.logger.info(f"[Cancelación] Reason combo encontrado: '{sel}'")
                    break
            except Exception:
                continue
        if combo is None:  # último recurso: el primer dropdown visible de la página
            # Diagnóstico: volcar el HTML del modal para ver el markup real del combo
            try:
                inner = await modal.first.inner_html()
                self.logger.warning(
                    "[Cancelación] Combo no hallado. HTML del modal (1500 chars):\n"
                    + (inner or "")[:1500])
            except Exception:
                pass
            combo = self.page.locator(
                ".select-dropdown-custom, p-dropdown, .p-dropdown, "
                "span[role='combobox'], [aria-haspopup='listbox']").first
        opciones = self.page.locator(
            "p-dropdownitem li[role='option'], li[role='option'], "
            ".p-dropdown-item, .select-dropdown-option")

        # El dropdown de Reason necesita un CLIC REAL para que PrimeNG dispare la
        # apertura (el force-click no abría la lista). Reintentamos con clic
        # normal y verificamos que las opciones aparezcan de verdad.
        abierto = False
        for intento in range(4):
            try:
                await combo.scroll_into_view_if_needed(timeout=2_000)
            except Exception:
                pass
            try:
                await combo.click(timeout=5_000)            # clic real (abre el combo)
            except Exception:
                try:
                    await combo.click(force=True, timeout=5_000)
                except Exception:
                    pass
            await self.page.wait_for_timeout(700)
            try:
                if await opciones.count() > 0 and await opciones.first.is_visible():
                    abierto = True
                    self.logger.info(f"[Cancelación] Combo abierto (intento {intento + 1}).")
                    break
            except Exception:
                pass
        if not abierto:
            self.logger.warning("[Cancelación] El combo no abrió tras 4 intentos.")
            await opciones.first.wait_for(state="visible", timeout=15_000)

        await opciones.nth(reason_index).click(force=True)
        await self.page.wait_for_timeout(1000)

        # ── 4) Notes ──
        self.logger.info(f"[Cancelación] Notes: '{notes}'")
        notas = self.page.get_by_test_id("modal-cancel-transaction-notes-input")
        await notas.wait_for(state="visible", timeout=30_000)
        await notas.click(force=True)
        await notas.fill(notes)
        await self.page.wait_for_timeout(800)

        # ── 5) Radio de confirmación SOLO si esta versión del modal lo tiene ──
        try:
            radio = self.page.locator(
                "input[data-testid='modal-cancel-transaction-confirmation-radio']")
            if await radio.count() > 0:
                modal = self.page.locator(
                    "div[role='dialog'], p-dialog, .p-dialog"
                ).filter(has_text=re.compile(r"cancellation|cancelaci[oó]n", re.I)).last
                await self._marcar_radio_confirmacion(modal)
        except Exception:
            pass

        # ── 6) Confirmar: 'Cancel Transaction' (segundo buttonsimple) ──
        self.logger.info("[Cancelación] Confirmando cancelación...")
        confirmar = self.page.locator("buttonsimple:nth-of-type(2) > button#id-button")
        await expect(confirmar).to_be_visible(timeout=30_000)
        await confirmar.click(force=True)
        await self.page.wait_for_timeout(2500)
        try:
            await self.page.locator(".p-dialog-mask").first.wait_for(
                state="detached", timeout=30_000)
        except Exception:
            pass
        self.logger.info("[Cancelación] ✓ Transacción cancelada.")

    async def _marcar_radio_confirmacion(self, modal) -> bool:
        """
        Marca el radio de confirmación del modal de cancelación. HERMES exige
        marcarlo para habilitar 'Cancel Transaction'. Port fiel del repo: prueba
        varios métodos (check, click, click al texto/contenedor, coordenadas, y
        setter nativo + eventos Angular) hasta que quede marcado. Tolerante.
        """
        self.logger.info("[Cancelación] Marcando radio de confirmación...")
        radio = modal.locator(
            "input[data-testid='modal-cancel-transaction-confirmation-radio']").first
        try:
            await radio.wait_for(state="attached", timeout=15_000)
        except Exception:
            self.logger.warning("[Cancelación] Radio de confirmación no encontrado — continuando")
            return False

        async def _checked() -> bool:
            try:
                return await radio.is_checked()
            except Exception:
                return False

        # 1) check al input real
        try:
            await radio.check(force=True, timeout=8_000)
        except Exception:
            pass
        await self.page.wait_for_timeout(500)
        # 2) click al input
        if not await _checked():
            try:
                await radio.click(force=True, timeout=8_000)
            except Exception:
                pass
        # 3) click al texto/label
        if not await _checked():
            txt = modal.locator(
                "[data-testid='modal-cancel-transactionconfirm-radio-h5-heading']").first
            try:
                if await txt.count() > 0:
                    await txt.click(force=True, timeout=5_000)
            except Exception:
                pass
        # 4) click al contenedor cursor-pointer
        if not await _checked():
            cont = modal.locator(
                "[data-testid='modal-cancel-transactionconfirm-radio-h5-heading']"
            ).locator("xpath=ancestor::div[contains(@class,'cursor-pointer')]").first
            try:
                if await cont.count() > 0:
                    await cont.click(force=True)
            except Exception:
                pass
        # 5) click por coordenadas
        if not await _checked():
            try:
                box = await radio.bounding_box()
                if box:
                    await self.page.mouse.click(
                        box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            except Exception:
                pass
        # 6) setter nativo + eventos (último recurso para Angular)
        if not await _checked():
            try:
                await radio.evaluate(
                    """radio => {
                        const s = Object.getOwnPropertyDescriptor(
                            HTMLInputElement.prototype, 'checked').set;
                        s.call(radio, true);
                        radio.dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
                        radio.dispatchEvent(new MouseEvent('mouseup', {bubbles:true}));
                        radio.dispatchEvent(new MouseEvent('click', {bubbles:true}));
                        radio.dispatchEvent(new Event('input', {bubbles:true}));
                        radio.dispatchEvent(new Event('change', {bubbles:true}));
                        radio.dispatchEvent(new Event('blur', {bubbles:true}));
                    }""")
            except Exception:
                pass
        ok = await _checked()
        self.logger.info(f"[Cancelación] Radio marcado = {ok}")
        return ok

    async def buscar_transaccion_por_nombre(self, nombre: str) -> None:
        """
        Busca una transacción por nombre de cliente en Reportes > Transacciones
        y dispara Buscar. Deja la primera fila lista para cancelar.
        """
        self.logger.info(f"[Reportes] Buscando por nombre: {nombre}")
        # Campo de búsqueda general del reporte (varía; probamos los comunes)
        campo = self.page.locator(
            "input[placeholder*='Buscar'], input[placeholder*='Search'], "
            "[data-testid*='search-input'] input, [data-testid*='search-input']").first
        # Campo de búsqueda: intento CORTO (2s). A menudo el reporte no tiene
        # este input (o usa otro), así que no vale la pena esperar 10s — si no
        # está pronto, se dispara Buscar igual (lista la transacción reciente).
        try:
            await campo.wait_for(state="visible", timeout=2_000)
            await campo.fill(nombre, timeout=2_000)
        except Exception:
            self.logger.info("[Reportes] Campo de búsqueda por nombre no disponible — busco directo.")
        # Botón Buscar/Search: 'test-id-button' es un data-testid GENÉRICO (lo
        # comparten varios botones), por eso smart_click tardaba tanto. Click
        # DIRECTO y corto, desambiguando por texto en ES/EN ('Buscar'/'Search')
        # y usando el id estable '#id-button'. Fallback a smart_click si falla.
        import re as _re
        btn_buscar = self.page.locator(
            "#id-button, [data-testid='test-id-button']"
        ).filter(has_text=_re.compile(r"buscar|search", _re.I)).first
        try:
            await btn_buscar.wait_for(state="visible", timeout=2_500)
            await btn_buscar.scroll_into_view_if_needed(timeout=1_200)
            await btn_buscar.click(timeout=2_500, force=True)
            self.logger.info("✓ Buscar/Search (click directo)")
        except Exception:
            await self.smart_click(testid="test-id-button",
                                   texto=_re.compile(r"buscar|search", _re.I),
                                   fallbacks=["button:has-text('Search')",
                                              "button:has-text('Buscar')", "#id-button"])
        await self.page.wait_for_timeout(800)

    async def click_fila_modal(self, texto: str = None, timeout: int = 12_000,
                               optional: bool = False) -> None:
        """
        Selecciona una FILA de un modal de resultados (pagador, branch, etc.).
        Estrategia:
          1. Click en la fila cuyo texto coincide (ej. 'ELEKTRA DIRECTO').
          2. Si ese texto no está (ej. el branch grabado no existe en esta
             lista), click en la PRIMERA fila visible del modal → 'cualquiera'.

        `optional=True`: la fila puede NO aparecer (ej. tabla de sucursal que
        solo sale a veces). Usa un timeout corto y si no aparece, sigue sin
        ruido ni esperas largas.
        """
        import time as _t
        if optional:
            timeout = min(timeout, 3_000)
            # Salida instantánea si no hay nada que parezca un modal/tabla
            try:
                presente = await self.page.locator(
                    "div[role='dialog'], .p-dialog, [role='row'], "
                    "tr.ng-star-inserted, [role='option']").count()
                if texto:
                    presente += await self.page.get_by_text(texto, exact=False).count()
                if presente == 0:
                    self.logger.info(f"[fila modal] opcional no presente ('{texto}') — sigo")
                    return
            except Exception:
                return
        deadline = _t.monotonic() + timeout / 1000
        # 1) Por texto exacto/parcial
        if texto:
            cand = self.page.get_by_text(texto, exact=False)
            while _t.monotonic() < deadline:
                try:
                    n = await cand.count()
                    for i in range(min(n, 10)):
                        if await cand.nth(i).is_visible():
                            await cand.nth(i).click(timeout=2500)
                            self.logger.info(f"✓ fila modal por texto: '{texto}'")
                            return
                except Exception:
                    pass
                # Si no aparece pronto, pasamos a 'primera fila'
                if _t.monotonic() - (deadline - timeout / 1000) > 4:
                    break
                await self.page.wait_for_timeout(300)

        # 2) Primera fila visible dentro de un modal/tabla de resultados
        filas = self.page.locator(
            "div[role='dialog'] tbody tr, .p-dialog tbody tr, "
            "div[role='dialog'] [role='option'], div[role='dialog'] li, "
            "tr.ng-star-inserted, [role='row']")
        end2 = _t.monotonic() + 6
        while _t.monotonic() < end2:
            try:
                n = await filas.count()
                for i in range(min(n, 25)):
                    fila = filas.nth(i)
                    if await fila.is_visible():
                        await fila.click(timeout=2500)
                        self.logger.info("✓ fila modal: primera disponible (cualquiera)")
                        return
            except Exception:
                pass
            await self.page.wait_for_timeout(300)
        self.logger.warning(f"[fila modal] no se pudo seleccionar fila ('{texto}') — continúo")

    async def _cerrar_autofill(self) -> None:
        """
        Cierra el overlay de autocompletado / 'Global search results' que
        HERMES muestra al teclear datos de cliente/beneficiario ya registrado
        (tabla con 'Close Table'). Best-effort: si no está, no hace nada.
        Esto evita que ese overlay bloquee el siguiente campo o botón.
        """
        try:
            cerrar = self.page.locator(
                "a:has-text('Close Table'), button:has-text('Close Table'), "
                "span:has-text('Close Table'), a:has-text('Cerrar tabla'), "
                "[data-testid*='close-table']"
            )
            # count() es INSTANTÁNEO — sin espera de 800ms por cada campo.
            if await cerrar.count() == 0:
                return
            primero = cerrar.first
            if await primero.is_visible():
                await primero.click(timeout=2000)
                await self.page.wait_for_timeout(200)
                self.logger.info("[Autofill] Overlay 'Close Table' cerrado.")
        except Exception:
            pass  # no estaba el overlay — seguir normal

    # ── Modales y tablas ──────────────────────────────────────────────────────

    async def wait_for_modal(
        self,
        modal_selector: str = 'div[role="dialog"]',
        timeout: int = None,
    ):
        """Espera a que aparezca un modal y retorna su locator."""
        timeout = timeout or self.MODAL_TIMEOUT
        modal = self.page.locator(modal_selector).first
        await modal.wait_for(state="visible", timeout=timeout)
        self.logger.info(f"Modal visible: {modal_selector}")
        return modal

    async def select_from_modal_table(
        self,
        text: str = None,
        modal_selector: str = 'div[role="dialog"].p-dialog',
        cell_selector: str = 'td.ng-star-inserted',
        wait_timeout: int = None,
    ) -> None:
        """Selecciona fila de tabla en modal por texto (o primera si text=None)."""
        wait_timeout = wait_timeout or self.MEDIUM_WAIT

        modal = self.page.locator(modal_selector).first
        await modal.wait_for(state="visible", timeout=TIMEOUT_ELEMENT)
        await self.page.wait_for_timeout(self.SHORT_WAIT)

        if text:
            cell = modal.locator(f'{cell_selector}:has-text("{text}")').first
            self.logger.info(f"Seleccionando fila: {text}")
        else:
            cell = modal.locator(cell_selector).first
            self.logger.info("Seleccionando primera fila")

        await cell.wait_for(state="visible", timeout=TIMEOUT_ELEMENT)
        await cell.click(force=True)
        await self.page.wait_for_timeout(wait_timeout)

    # ── Overlays y esperas ────────────────────────────────────────────────────

    async def wait_for_no_blocking_overlays(self, timeout: int = 3_000) -> None:
        """
        Espera hasta que no haya overlays que bloqueen eventos de puntero.
        Detecta: loaders, modales de notificación, dialog-mask, etc.
        """
        overlay_selectors = [
            "#maxi-loader",
            "modalnotificationsintrusive",
            ".p-dialog-mask",
            "div.p-component-overlay",
        ]
        script = """
        selectors => {
            for (const sel of selectors) {
                for (const el of document.querySelectorAll(sel)) {
                    const s = window.getComputedStyle(el);
                    if (s.display !== 'none' && s.visibility !== 'hidden' && s.pointerEvents !== 'none')
                        return false;
                }
            }
            return true;
        }
        """
        try:
            # arg= es keyword-only en la API async de Playwright — pasarlo
            # posicional lanzaba TypeError inmediato (warning en cada llamada)
            await self.page.wait_for_function(script, arg=overlay_selectors, timeout=timeout)
        except Exception:
            self.logger.warning("Overlay wait timeout — continuando (overlay no bloqueante)")

    async def wait(self, ms: int) -> None:
        """Espera fija en ms — usar con moderación."""
        await self.page.wait_for_timeout(ms)

    async def esperar_autocomplete_cp(
        self,
        city_testid: str = "transfer-customer-city-0-input",
        state_testid: str = "transfer-customer-state-0-input",
        timeout: int = 10_000,
        zip_testid: str = "transfer-customer-zip-code-0-input",
    ) -> None:
        """
        Flujo del autocompletado de CP en HERMES:
          1. El zip ya quedó escrito en el campo.
          2. Pausa breve (~1s) para que el valor se asiente.
          3. TAB → dispara el blur que detona la consulta del CP.
          4. Espera (bounded, hasta `timeout`) a que City/State se llenen,
             saliendo EN CUANTO aparezcan (normalmente ~2s, no los 10 completos).
        Tolerante: si no llegan a llenarse, registra warning y continúa.
        """
        # 1-2. Margen breve para que el valor del zip se asiente antes del blur
        await self.page.wait_for_timeout(400)
        # 3. TAB detona el autofill (blur del campo de zip)
        try:
            await self.page.get_by_test_id(zip_testid).first.press("Tab", timeout=2_000)
        except Exception:
            await self.page.keyboard.press("Tab")
        # 4. VIGILAR el City directamente y CONTINUAR apenas se llene. Antes se
        #    esperaba wait_for_no_blocking_overlays(10s) ANTES de mirar el City,
        #    lo que costaba ~10s aunque el autocomplete respondiera en 2s. Ahora
        #    se hace polling corto del value del City (funciona aunque el input
        #    esté disabled/readonly) y se sale EN CUANTO tiene valor → el
        #    siguiente formulario se despliega mucho antes.
        import time as _t
        city = self.page.get_by_test_id(city_testid).first
        deadline = _t.monotonic() + timeout / 1000
        paso = 250
        while _t.monotonic() < deadline:
            try:
                val = await city.input_value(timeout=800)
            except Exception:
                val = ""
            if (val or "").strip():
                self.logger.info(f"CP autocompletado → City='{val}' (continúo sin esperar el resto)")
                return
            await self.page.wait_for_timeout(paso)
        self.logger.warning("Autocomplete de CP no llenó City a tiempo — continuando")

    async def scroll_to(self, y: int, x: int = 0, selector: str = None) -> None:
        """
        Hace scroll a una posición. Sin `selector` mueve la ventana; con
        `selector` mueve ese contenedor (paneles/tablas con scroll propio).
        Reproduce tanto el scroll con rueda como con la barra lateral.
        """
        self.logger.info(f"Scroll → x={x} y={y}" + (f" en {selector}" if selector else ""))
        if selector:
            try:
                await self.page.locator(selector).first.evaluate(
                    "(el, p) => el.scrollTo(p.x, p.y)", {"x": x, "y": y})
                await self.page.wait_for_timeout(300)
                return
            except Exception:
                pass  # contenedor no encontrado → seguir con estrategia robusta

        # Estrategia robusta: intenta la ventana; si no se mueve (HERMES suele
        # tener el scroll en un contenedor interno), busca el elemento
        # scrolleable más grande y lo desplaza.
        await self.page.evaluate(
            """(p) => {
                const antes = window.scrollY;
                window.scrollTo(p.x, p.y);
                if (Math.abs(window.scrollY - p.y) < 5 && window.scrollY === antes) {
                    // La ventana no scrolleó: buscar el contenedor scrolleable mayor
                    let best = null, bestArea = 0;
                    for (const el of document.querySelectorAll('*')) {
                        const oy = getComputedStyle(el).overflowY;
                        if ((oy === 'auto' || oy === 'scroll')
                            && el.scrollHeight > el.clientHeight + 20) {
                            const a = el.clientWidth * el.clientHeight;
                            if (a > bestArea) { bestArea = a; best = el; }
                        }
                    }
                    if (best) best.scrollTo(p.x, p.y);
                }
            }""",
            {"x": x, "y": y},
        )
        await self.page.wait_for_timeout(300)

    # ── Sesión ────────────────────────────────────────────────────────────────

    async def save_session(self) -> None:
        """
        Guarda el estado de sesión (cookies + localStorage) para que los
        tests con fixture logged_page (CP02+) entren directo sin login.
        """
        from src.helpers.session_helper import SessionHelper
        await SessionHelper(self.page).save_state()

    # ── Notifications modal (reutilizable en todos los Page Objects) ──────────

    async def handle_notifications_modal(self, modal_timeout: int = 30_000) -> dict:
        """
        Maneja el modal 'Notificaciones Importantes' — port fiel de
        HERMES2-qa → LoginPage.close_notifications_modal().

        `modal_timeout`: cuánto esperar a que APAREZCA el modal. Es intrusivo
        ("Tiene que abrir todas sus notificaciones para poder continuar") y su
        aparición es impredecible (3s a 20s+); por eso esperamos generoso para
        no seguir el flujo antes de tiempo y fallar.

        Flujo (igual que un agente humano, y que el repo maduro):
          1. Espera que termine la navegación SSO → HERMES2 sin tocar el DOM
             durante los redirects (evita 'Execution context was destroyed')
          2. Cierra modales bloqueantes que NO son de notificaciones
          3. Detección rápida: espera modal O navbar de la app, lo primero
             que aparezca (sin esperas ciegas de 60s)
          4. LEE cada notificación no leída, una por una:
             filas tr[...row-toggle] y/o indicadores .not-read-indicator
          5. Al leerlas todas se habilita la X → espera explícita a enabled
             → click → espera a hidden. JS remove SOLO como último recurso.

        Returns:
            dict: {found: bool, count: int}
        """
        result = {"found": False, "count": 0}

        try:
            # ── Paso 1: esperar fin de navegación SSO → HERMES2 ─────────────
            try:
                await self.page.wait_for_url("**/transfers**", timeout=60_000)
            except Exception:
                pass  # ya estaba en la app o el flujo aterriza en otra URL
            try:
                await self.page.wait_for_load_state("domcontentloaded", timeout=60_000)
            except Exception:
                pass
            self.logger.info(f"[Notifications] URL actual: {self.page.url}")

            # ── Paso 2: cerrar modales bloqueantes que NO son notificaciones ─
            try:
                blocking = self.page.locator(
                    "div[role='dialog']:not(:has(p:has-text('Notificaciones Importantes')))"
                    ":not(:has(p:has-text('Important Notifications')))"
                )
                if await blocking.count() > 0:
                    btn = blocking.first.locator("button.p-dialog-header-close")
                    if await btn.is_visible():
                        await btn.click()
                        await self.page.wait_for_timeout(500)
                        self.logger.info(
                            "[Notifications] Modal bloqueante cerrado antes de procesar."
                        )
            except Exception:
                pass

            # ── Paso 3: esperar el fin de la carga REAL y luego el modal ────
            # El #maxi-loader queda en el DOM y cuenta como "visible" para
            # Playwright durante toda la carga (que puede tardar 60s+), y el
            # navbar también es "visible" aunque esté DEBAJO del loader. Por
            # eso NO sirve esperar elementos: hay que esperar a que el loader
            # deje de BLOQUEAR (estilo computado) y recién ahí decidir.
            self.logger.info("[Notifications] Esperando fin de carga (loader)...")
            loader_script = """
            () => {
                const el = document.querySelector('#maxi-loader');
                if (!el) return true;
                const s = window.getComputedStyle(el);
                return s.display === 'none'
                    || s.visibility === 'hidden'
                    || s.pointerEvents === 'none'
                    || s.opacity === '0';
            }
            """
            try:
                await self.page.wait_for_function(loader_script, timeout=90_000)
                self.logger.info("[Notifications] Loader liberado — app cargada.")
            except Exception:
                self.logger.warning(
                    "[Notifications] Loader sigue bloqueando tras 90s — continuando."
                )

            dialog = self.page.locator(
                "div[role='dialog']:has(p:has-text('Notificaciones Importantes')), "
                "div[role='dialog']:has(p:has-text('Important Notifications')), "
                "modalnotificationsintrusive"
            ).first
            close_btn = self.page.get_by_test_id(
                "notifications-modal-intrusive-close-icon-svg"
            )

            # Con la app ya cargada, darle tiempo REAL al modal. Su aparición es
            # impredecible (3s a 20s+); esperamos generoso (default 30s) para no
            # adelantarnos. Si en ese lapso no aparece, asumimos que no hay.
            self.logger.info(
                f"[Notifications] Esperando modal (max {modal_timeout // 1000}s)...")
            try:
                await close_btn.wait_for(state="visible", timeout=modal_timeout)
            except Exception:
                self.logger.info(
                    "[Notifications] Sin modal de notificaciones — continuando flujo."
                )
                return result

            result["found"] = True
            self.logger.info("[Notifications] Modal detectado — leyendo notificaciones...")

            # ── Paso 4a: leer filas de la tabla (svg verde = ya leída) ──────
            unread = 0
            rows = self.page.locator(
                "tr[data-testid*='notifications-intrusive-table-row-toggle']"
            )
            row_count = await rows.count()
            self.logger.info(f"[Notifications] Filas en tabla: {row_count}")

            for i in range(row_count):
                row = rows.nth(i)
                is_read = await row.locator("svg path[fill='#1A7832']").count() > 0
                if not is_read:
                    unread += 1
                    await row.scroll_into_view_if_needed()
                    await row.click()
                    await self.page.wait_for_timeout(300)
                    self.logger.info(
                        f"[Notifications] Notificación {i + 1}/{row_count} leída."
                    )
                else:
                    self.logger.info(
                        f"[Notifications] Notificación {i + 1}/{row_count} ya leída — skip."
                    )

            # ── Paso 4b: fallback del repo — indicadores .not-read-indicator ─
            not_read = self.page.locator(".not-read-indicator")
            safety = 0
            while await not_read.count() > 0 and safety < 20:
                safety += 1
                try:
                    indicator = not_read.nth(0)
                    await indicator.scroll_into_view_if_needed()
                    await indicator.click()
                    unread += 1
                    await self.page.wait_for_timeout(300)
                    self.logger.info("[Notifications] Indicador no-leído procesado.")
                    if not await self.page.locator(".btn-exit.disabled").count():
                        self.logger.info("[Notifications] X habilitada — todas leídas.")
                        break
                except Exception as e:
                    self.logger.warning(
                        f"[Notifications] Error procesando indicador: {str(e)[:80]}"
                    )
                    break

            result["count"] = unread
            self.logger.info(f"[Notifications] Total leídas en esta sesión: {unread}")

            # ── Paso 5: cerrar con la X (se habilita al leerlas todas) ──────
            closed = False
            try:
                # Espera explícita: hasta que la X esté habilitada (max 15s)
                await expect(close_btn).to_be_enabled(timeout=15_000)
                await close_btn.click(force=True)
                # Espera explícita: hasta que el modal desaparezca (max 5s)
                await close_btn.wait_for(state="hidden", timeout=5_000)
                self.logger.info("[Notifications] Modal cerrado con la X.")
                closed = True
            except Exception as e:
                self.logger.warning(
                    f"[Notifications] Cierre con X falló: {str(e)[:80]}"
                )

            if not closed:
                self.logger.warning(
                    "[Notifications] La X nunca cerró el modal — JS remove (último recurso)."
                )
                await self.page.evaluate("""
                    () => {
                        const dialogs = document.querySelectorAll("div[role='dialog']");
                        for (const d of dialogs) {
                            if (d.innerText.includes('Notificaciones Importantes') ||
                                d.innerText.includes('Important Notifications')) {
                                d.remove(); return true;
                            }
                        }
                        const el = document.querySelector('modalnotificationsintrusive');
                        if (el) el.remove();
                    }
                """)

            await self.wait_for_no_blocking_overlays()

        except Exception as e:
            self.logger.error(f"[Notifications] Error inesperado: {e}")

        return result

    # ── Idioma (navbar de Hermes) ─────────────────────────────────────────────

    async def cambiar_idioma(self, idioma: str = "es") -> None:
        """
        Ajusta el idioma de la interfaz según lo pedido en lenguaje natural.

        Regla (según el comportamiento real de Hermes):
          • Español (default): la app arranca en español → NO hace nada.
          • Inglés: 2 clics — abre el dropdown de idioma (language-navbar-item)
            y elige English (language-0-navbar-dropdown-item). Español sería
            language-1-navbar-dropdown-item, pero como es el default no se toca.

        Acepta: 'en'/'ingles'/'inglés'/'english' y 'es'/'español'/'spanish'.
        """
        t = (idioma or "").strip().lower()
        quiere_ingles = t in ("en", "eng", "ingles", "inglés", "english")
        # Destino según idioma: English = language-0, Español = language-1.
        destino_testid = ("language-0-navbar-dropdown-item" if quiere_ingles
                          else "language-1-navbar-dropdown-item")
        destino_txt = re.compile(r"english" if quiere_ingles else r"espa[nñ]ol|spanish", re.I)
        etiqueta = "English" if quiere_ingles else "Español"
        codigo = "en" if quiere_ingles else "es"
        try:
            opener = self.page.get_by_test_id("language-navbar-item")
            await opener.wait_for(state="visible", timeout=TIMEOUT_ELEMENT)
            # ¿Ya está en el idioma pedido? El navbar muestra el código actual
            # (EN/ES): si coincide, no se toca (evita clics innecesarios). Es
            # BIDIRECCIONAL: con sesión persistida la app puede haber quedado en
            # inglés, y ahora sí sabemos volver a español (antes no).
            try:
                actual = (await opener.inner_text() or "").strip().lower()
                if codigo in actual:
                    self.logger.info(f"[Idioma] Ya en {etiqueta} — no se cambia.")
                    return
            except Exception:
                pass
            await opener.click()
            item = self.page.get_by_test_id(destino_testid).first
            try:
                await item.wait_for(state="visible", timeout=5_000)
                await item.click()
            except Exception:
                fb = self.page.locator(
                    "[data-testid^='language-'][data-testid$='-navbar-dropdown-item']"
                ).filter(has_text=destino_txt).first
                await fb.click()
            await self.wait_for_no_blocking_overlays()
            self.logger.info(f"[Idioma] Cambiado a {etiqueta} (2 clics).")
        except Exception as e:
            self.logger.warning(f"[Idioma] No se pudo cambiar a {etiqueta}: {e} — continúo.")

    # ── Queries ───────────────────────────────────────────────────────────────

    async def is_visible(self, selector: str) -> bool:
        return await self.page.is_visible(selector)

    async def is_enabled(self, selector: str) -> bool:
        return await self.page.is_enabled(selector)

    async def get_text(self, selector: str) -> str:
        return await self.page.text_content(selector)

    async def filter_visible_elements(self, selector: str) -> list:
        """Retorna índices de los elementos visibles que coinciden con el selector."""
        elements = self.page.locator(selector)
        count    = await elements.count()
        return [i for i in range(count) if await elements.nth(i).is_visible()]

    # ── Selectores dinámicos ──────────────────────────────────────────────────

    def format_selector(self, pattern: str, *args, **kwargs) -> str:
        """
        Formatea un selector detectando el tipo automáticamente.
        Ejemplos:
            format_selector("#btn-{}-{}", 1, "ok")   → "#btn-1-ok"
            format_selector("btn-{}", 1)              → "[data-testid='btn-1']"
            format_selector("//button[@id='{}']", 1) → "//button[@id='1']"
        """
        formatted = pattern.format(*args, **kwargs) if (args or kwargs) else pattern
        if formatted.startswith(("#", ".", "[")) or " " in formatted:
            return formatted
        if formatted.startswith("//") or formatted.startswith("(//"):
            return formatted
        return f"[data-testid='{formatted}']"

    def format_testid_selector(self, testid_pattern: str, *args, **kwargs) -> str:
        formatted = testid_pattern.format(*args, **kwargs) if (args or kwargs) else testid_pattern
        return f"[data-testid='{formatted}']"

    async def trigger_field_validation(self, fallback_selector: str = None) -> None:
        """Click en otro elemento para disparar validaciones Angular."""
        try:
            if fallback_selector:
                await self.page.locator(fallback_selector).first.click(force=True)
            else:
                await self.page.locator('[class="ng-star-inserted"]').first.click(force=True)
        except Exception:
            await self.page.locator("body").click(force=True)
        await self.page.wait_for_timeout(self.SHORT_WAIT)
