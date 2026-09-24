"""
HmTransferelektraPage — Page Object para el flujo: hm_transferelektra

Pantalla real de Transfers de Hermes2. La reutilizan TODOS los pagadores del
catálogo (src/pagadores/<pais>/payers.json) vía src/pagadores/flujo_mt.py —
un solo flujo estable parametrizado, en vez de un Page Object por pagador.

PATRON: Los métodos aceptan los valores como parámetros.
        Las constantes se definen en el test/flujo, no aquí.
"""

import asyncio
import re

from config.logger import get_logger
from .locators import HmTransferelektraLocators
from .base_page import BasePage

logger = get_logger("hm_transferelektra_page")


class HmTransferelektraPage(BasePage):
    """Page Object para el flujo hm_transferelektra."""

    # ── Locators (para usar en screenshot locators=[...]) ──────────────

    @property
    def transfer_customer_cellphone_0_cellphone_input_input(self):
        return self.page.get_by_test_id(HmTransferelektraLocators.TRANSFER_CUSTOMER_CELLPHONE_0_CELLPHONE_INPUT)

    @property
    def transfer_customer_name_0_input_input(self):
        return self.page.get_by_test_id(HmTransferelektraLocators.TRANSFER_CUSTOMER_NAME_0_INPUT)

    @property
    def transfer_customer_first_lastname_0_input_input(self):
        return self.page.get_by_test_id(HmTransferelektraLocators.TRANSFER_CUSTOMER_FIRST_LASTNAME_0_INPUT)

    @property
    def transfer_customer_second_lastname_0_input_input(self):
        return self.page.get_by_test_id(HmTransferelektraLocators.TRANSFER_CUSTOMER_SECOND_LASTNAME_0_INPUT)

    @property
    def transfer_customer_address_0_input_input(self):
        return self.page.get_by_test_id(HmTransferelektraLocators.TRANSFER_CUSTOMER_ADDRESS_0_INPUT)

    @property
    def transfer_customer_zip_code_0_input_input(self):
        return self.page.get_by_test_id(HmTransferelektraLocators.TRANSFER_CUSTOMER_ZIP_CODE_0_INPUT)

    @property
    def transfer_beneficiary_country_0_dropdown_input_input(self):
        return self.page.get_by_test_id(HmTransferelektraLocators.TRANSFER_BENEFICIARY_COUNTRY_0_DROPDOWN_INPUT)

    @property
    def transfer_beneficiary_name_0_dropdown_input_input(self):
        return self.page.get_by_test_id(HmTransferelektraLocators.TRANSFER_BENEFICIARY_NAME_0_DROPDOWN_INPUT)

    @property
    def transfer_beneficiary_first_lastname_0_input_input(self):
        return self.page.get_by_test_id(HmTransferelektraLocators.TRANSFER_BENEFICIARY_FIRST_LASTNAME_0_INPUT)

    @property
    def transfer_beneficiary_second_lastname_0_input_input(self):
        return self.page.get_by_test_id(HmTransferelektraLocators.TRANSFER_BENEFICIARY_SECOND_LASTNAME_0_INPUT)

    @property
    def transfer_beneficiary_cellphone_0_cellphone_input_input(self):
        return self.page.get_by_test_id(HmTransferelektraLocators.TRANSFER_BENEFICIARY_CELLPHONE_0_CELLPHONE_INPUT)

    @property
    def transfer_beneficiary_address_0_input_input(self):
        return self.page.get_by_test_id(HmTransferelektraLocators.TRANSFER_BENEFICIARY_ADDRESS_0_INPUT)

    @property
    def transfer_beneficiary_zip_code_0_input_input(self):
        return self.page.get_by_test_id(HmTransferelektraLocators.TRANSFER_BENEFICIARY_ZIP_CODE_0_INPUT)

    @property
    def transfer_beneficiary_city_0_input_input(self):
        return self.page.get_by_test_id(HmTransferelektraLocators.TRANSFER_BENEFICIARY_CITY_0_INPUT)

    @property
    def transfer_beneficiary_state_0_input_input(self):
        return self.page.get_by_test_id(HmTransferelektraLocators.TRANSFER_BENEFICIARY_STATE_0_INPUT)

    @property
    def transfer_beneficiary_date_of_birth_0_input_input(self):
        return self.page.get_by_test_id(HmTransferelektraLocators.TRANSFER_BENEFICIARY_DATE_OF_BIRTH_0_INPUT)

    @property
    def transfer_beneficiary_email_0_input_input(self):
        return self.page.get_by_test_id(HmTransferelektraLocators.TRANSFER_BENEFICIARY_EMAIL_0_INPUT)

    @property
    def transfer_payers_money_info_city_0_cash_dropdown_input_input(self):
        return self.page.get_by_test_id(HmTransferelektraLocators.TRANSFER_PAYERS_MONEY_INFO_CITY_0_CASH_DROPDOWN_INPUT)

    @property
    def transfers_money_info_modal_search_payer_0_input_search_input_input(self):
        return self.page.get_by_test_id(HmTransferelektraLocators.TRANSFERS_MONEY_INFO_MODAL_SEARCH_PAYER_0_INPUT_SEARCH_INPUT)

    @property
    def modal_cancel_transaction_notes_input_input(self):
        return self.page.get_by_test_id(HmTransferelektraLocators.MODAL_CANCEL_TRANSACTION_NOTES_INPUT)


    # ── NAVEGACIÓN (sesión ya iniciada por logged_page) ─────────────────

    async def navigate(self) -> None:
        """Va a la URL inicial del flujo — sin recargar si ya está ahí."""
        from config import settings
        target = getattr(settings, "APP_URL", None) or "https://test-hermes.maxilabs.net/transfers"
        if self.page.url.split("?")[0].rstrip("/") == target.rstrip("/"):
            logger.info("navigate: ya en la URL inicial — sin recargar")
            await self.wait_for_no_blocking_overlays()
            return
        logger.info(f"navigate: {target}")
        await self.goto(target)
        # Una recarga completa puede reabrir el modal de notificaciones
        await self.handle_notifications_modal()
        await self.wait_for_no_blocking_overlays()

    # ── TRANSFERS ───────────────────────────────────────────

    async def fill_transfer_customer_cellphone_0_cellphone_input(self, transfer_customer_cellphone_0_cellphone_input: str) -> None:
        """Ingresa texto en: transfer-customer-cellphone-0-cellphone-input"""
        logger.info(f"fill_transfer_customer_cellphone_0_cellphone_input: {transfer_customer_cellphone_0_cellphone_input}")
        await self.fill_input_by_testid(
            HmTransferelektraLocators.TRANSFER_CUSTOMER_CELLPHONE_0_CELLPHONE_INPUT, transfer_customer_cellphone_0_cellphone_input
        )

    async def fill_transfer_customer_name_0_input(self, transfer_customer_name_0_input: str) -> None:
        """Ingresa texto en: transfer-customer-name-0-input"""
        logger.info(f"fill_transfer_customer_name_0_input: {transfer_customer_name_0_input}")
        await self.fill_input_by_testid(
            HmTransferelektraLocators.TRANSFER_CUSTOMER_NAME_0_INPUT, transfer_customer_name_0_input
        )

    async def fill_transfer_customer_first_lastname_0_input(self, transfer_customer_first_lastname_0_input: str) -> None:
        """Ingresa texto en: transfer-customer-first-lastName-0-input"""
        logger.info(f"fill_transfer_customer_first_lastname_0_input: {transfer_customer_first_lastname_0_input}")
        await self.fill_input_by_testid(
            HmTransferelektraLocators.TRANSFER_CUSTOMER_FIRST_LASTNAME_0_INPUT, transfer_customer_first_lastname_0_input
        )

    async def fill_transfer_customer_second_lastname_0_input(self, transfer_customer_second_lastname_0_input: str) -> None:
        """Ingresa texto en: transfer-customer-second-lastname-0-input"""
        logger.info(f"fill_transfer_customer_second_lastname_0_input: {transfer_customer_second_lastname_0_input}")
        await self.fill_input_by_testid(
            HmTransferelektraLocators.TRANSFER_CUSTOMER_SECOND_LASTNAME_0_INPUT, transfer_customer_second_lastname_0_input
        )

    async def click_close_table(self) -> None:
        """
        Cierra la tabla de coincidencia (OPCIONAL): solo aparece si el teléfono
        o nombre del cliente coincide con un registro existente. Si no apareció,
        no hace nada y sigue de inmediato (sin esperas largas).
        """
        logger.info("click_close_table (opcional)...")
        await self._cerrar_autofill()

    async def fill_transfer_customer_address_0_input(self, transfer_customer_address_0_input: str) -> None:
        """Ingresa texto en: transfer-customer-address-0-input"""
        logger.info(f"fill_transfer_customer_address_0_input: {transfer_customer_address_0_input}")
        await self.fill_input_by_testid(
            HmTransferelektraLocators.TRANSFER_CUSTOMER_ADDRESS_0_INPUT, transfer_customer_address_0_input
        )

    # ── Validador de direcciones reales (PostGrid) del cliente ──────────────
    _DIR_CANON = {
        "N": "N", "NORTH": "N", "S": "S", "SOUTH": "S", "E": "E", "EAST": "E",
        "W": "W", "WEST": "W", "NE": "NE", "NW": "NW", "SE": "SE", "SW": "SW",
        "ST": "ST", "STREET": "ST", "AVE": "AVE", "AV": "AVE", "AVENUE": "AVE",
        "BLVD": "BLVD", "BOULEVARD": "BLVD", "RD": "RD", "ROAD": "RD",
        "DR": "DR", "DRIVE": "DR", "LN": "LN", "LANE": "LN", "CT": "CT",
        "COURT": "CT", "PL": "PL", "PLACE": "PL", "SQ": "SQ", "SQUARE": "SQ",
        "PKWY": "PKWY", "PARKWAY": "PKWY", "HWY": "HWY", "HIGHWAY": "HWY",
        "LOOP": "LOOP", "WAY": "WAY", "TER": "TER", "TERRACE": "TER",
    }

    def _tokens_calle(self, texto: str) -> set:
        """Conjunto de tokens canónicos de una calle (sin puntuación, sin orden).
        '601 LAKESIDE AVE E' y '601 LAKESIDE E AVE' → {601, LAKESIDE, E, AVE}."""
        bruto = re.sub(r"[^A-Za-z0-9 ]", " ", (texto or "").upper())
        out = set()
        for tok in bruto.split():
            out.add(self._DIR_CANON.get(tok, tok))
        return out

    async def _direccion_en_error(self) -> bool:
        """True si el campo de dirección quedó INVÁLIDO y bloquea Continuar.

        Señal precisa (código del front, Big C 2026-09-22): el input toma la clase
        `invalid-error-input` y se pinta el nodo `transfer-customer-address-0-error`
        cuando `address` tiene el error `isAddressNotValidated`. Respaldo textual
        por si cambia el DOM."""
        try:
            inp = self.page.get_by_test_id(
                HmTransferelektraLocators.TRANSFER_CUSTOMER_ADDRESS_0_INPUT).first
            if "invalid-error-input" in ((await inp.get_attribute("class")) or ""):
                return True
        except Exception:
            pass
        try:
            err = self.page.locator(
                '[data-testid="transfer-customer-address-0-error"]').first
            if await err.count() and await err.is_visible():
                return True
        except Exception:
            pass
        try:
            loc = self.page.get_by_text(re.compile(
                r"no\s*(ha\s*sido\s*)?verificad|no\s*ha\s*sido\s*validad|"
                r"selecciona una direcci|not\s*verified|p\.?o\.?\s*box|faltan datos",
                re.I))
            for i in range(min(await loc.count(), 6)):
                if await loc.nth(i).is_visible():
                    return True
        except Exception:
            pass
        return False

    async def sugerencias_direccion_por_red(self, texto: str,
                                            espera_ms: int = 1_500) -> list:
        """TECLEA la dirección y captura la respuesta del endpoint `suggestions`.

        El panel es un overlay propio (provider 'postgrid'); leer la RED es
        exacto y no depende del DOM. El autocomplete se dispara con pulsaciones
        reales (`.fill()` no lo dispara), por eso aquí se teclea de verdad.
        Devuelve la ÚLTIMA lista `data` capturada."""
        inp = self.page.get_by_test_id(
            HmTransferelektraLocators.TRANSFER_CUSTOMER_ADDRESS_0_INPUT).first
        capturas = []

        async def _guardar(resp):
            try:
                body = await resp.json()
            except Exception:
                return
            if isinstance(body, dict) and isinstance(body.get("data"), list):
                capturas.append(body["data"])

        def _on(resp):
            try:
                if "suggestions" in resp.url.lower():
                    asyncio.ensure_future(_guardar(resp))
            except Exception:
                pass

        self.page.on("response", _on)
        try:
            try:
                await inp.click(timeout=3_000)
            except Exception:
                try:
                    await inp.click(force=True, timeout=3_000)
                except Exception:
                    pass
            try:
                await inp.fill("")
            except Exception:
                pass
            if texto:
                try:
                    await inp.press_sequentially(texto, delay=60)
                except Exception:
                    try:
                        await inp.type(texto, delay=60)
                    except Exception:
                        pass
            await self.page.wait_for_timeout(espera_ms)
        finally:
            try:
                self.page.remove_listener("response", _on)
            except Exception:
                pass
        return capturas[-1] if capturas else []

    async def seleccionar_direccion_sugerida_cliente(
            self, direccion_escrita: str = "", zip_esperado: str = "",
            ciudad_esperada: str = "", timeout: int = 3_500) -> tuple:
        """Resuelve el validador de direcciones reales del cliente leyendo la RED.

        Elige la sugerencia que casa con el ZIP; si ninguna casa, elige la
        PRIMERA real (número+calle) y Hermes ajusta zip/ciudad/estado. Devuelve
        (ok, estado): 'OK' | 'SIN_PANEL_OK' | 'INVALIDO' | 'NO_MATCH'."""
        data = await self.sugerencias_direccion_por_red(direccion_escrita)
        if not data:
            if await self._direccion_en_error():
                logger.warning("Dirección '%s' (%s): sin sugerencias y el campo "
                               "exige una válida.", direccion_escrita, zip_esperado)
                return (False, "INVALIDO")
            logger.info("Dirección '%s': sin sugerencias y sin error — se acepta "
                        "tal cual.", direccion_escrita)
            return (True, "SIN_PANEL_OK")

        zp = (zip_esperado or "").strip()
        cd = (ciudad_esperada or "").strip().upper()

        def _sec(it):
            return (it.get("secondaryText") or "").upper()

        def _numero_primero(it):
            return bool(re.match(r"^\s*\d", it.get("mainText") or ""))

        objetivo = None
        if zp:
            objetivo = next((it for it in data
                             if zp in _sec(it) and _numero_primero(it)), None)
        if objetivo is None and cd:
            objetivo = next((it for it in data
                             if cd in _sec(it) and _numero_primero(it)), None)
        # RESPALDO: cualquier sugerencia real (número+calle). El validador valida
        # la dirección; al elegir una real, Hermes ajusta ciudad/estado/zip y el
        # envío continúa. Así el flujo NUNCA se atora por esta validación.
        if objetivo is None:
            objetivo = next((it for it in data if _numero_primero(it)), None)

        if objetivo is None:
            ofrecidas = " | ".join(
                f'{it.get("mainText","")} [{it.get("secondaryText","")}]'
                for it in data)[:240]
            logger.warning("Dirección '%s' (%s): sin sugerencias número+calle. "
                           "Ofrecidas: %s", direccion_escrita, zp, ofrecidas)
            try:
                await self.page.keyboard.press("Escape")
            except Exception:
                pass
            return (False, "NO_MATCH")

        if not (zp and zp in _sec(objetivo)):
            logger.info("Dirección: sin match de zip '%s'; se elige una real "
                        "cualquiera → '%s [%s]' (Hermes ajusta zip/ciudad).",
                        zp, objetivo.get("mainText"), objetivo.get("secondaryText"))

        main = (objetivo.get("mainText") or "").strip()
        sec = (objetivo.get("secondaryText") or "").strip()
        escr = self._tokens_calle(direccion_escrita)
        if escr and not escr.issubset(self._tokens_calle(main)):
            logger.warning("Dirección: casa ZIP pero la calle difiere ('%s' vs "
                           "sugerencia '%s').", direccion_escrita, main)
        fila = self.page.get_by_text(main, exact=False).first
        clicado = False
        try:
            await fila.scroll_into_view_if_needed(timeout=1_500)
        except Exception:
            pass
        try:
            await fila.click(timeout=4_000)
            clicado = True
        except Exception:
            try:
                await fila.click(force=True, timeout=3_000)
                clicado = True
            except Exception:
                clicado = False
        if not clicado:
            logger.warning("Dirección: no pude clicar la sugerencia '%s'.", main)
            return (False, "NO_MATCH")
        await self.page.wait_for_timeout(600)
        if await self._direccion_en_error():
            logger.warning("Dirección: tras elegir '%s [%s]' el campo sigue en "
                           "error.", main, sec)
            return (False, "NO_MATCH")
        logger.info("Dirección: ✓ elegida → '%s [%s]'", main, sec)
        return (True, "OK")

    _ADDR_SUGGESTION_TESTID = "transfer-customer-address-suggestion-0"

    def _elegir_sugerencia(self, data, zip_preferido):
        """(idx, item) de la sugerencia número+calle que casa con el ZIP; si no,
        la primera número+calle. (None, None) si no hay ninguna útil."""
        def _numini(it):
            return bool(re.match(r"^\s*\d", it.get("mainText") or ""))
        idx = None
        if zip_preferido:
            for k, it in enumerate(data):
                if _numini(it) and zip_preferido in (it.get("secondaryText") or ""):
                    idx = k
                    break
        if idx is None:
            for k, it in enumerate(data):
                if _numini(it):
                    idx = k
                    break
        return (idx, data[idx]) if idx is not None else (None, None)

    async def _click_sugerencia(self, idx, texto_main):
        """Clic en la fila de sugerencia (todas comparten el mismo testid → .nth)."""
        try:
            filas = self.page.get_by_test_id(self._ADDR_SUGGESTION_TESTID)
            n = await filas.count()
            if n:
                fila = filas.nth(idx if 0 <= idx < n else 0)
                try:
                    await fila.scroll_into_view_if_needed(timeout=1_500)
                except Exception:
                    pass
                await fila.click(timeout=4_000)
                return True
        except Exception:
            pass
        try:
            await self.page.get_by_text(texto_main, exact=False).first.click(timeout=4_000)
            return True
        except Exception:
            return False

    def _escuchar_verificacion(self):
        """Listener de /address/verification → guarda el status. Devuelve (estado, on)."""
        estado = {"status": None, "recibido": False}

        async def _grab(resp):
            try:
                b = await resp.json()
            except Exception:
                return
            d = b.get("data") if (isinstance(b, dict)
                                  and isinstance(b.get("data"), dict)) else b
            if isinstance(d, dict) and d.get("status") is not None:
                estado["status"] = str(d.get("status"))
                estado["recibido"] = True

        def _on(resp):
            try:
                if "address/verification" in resp.url.lower():
                    asyncio.ensure_future(_grab(resp))
            except Exception:
                pass

        self.page.on("response", _on)
        return estado, _on

    async def _asegurar_zip_direccion(self, zip_val: str) -> None:
        """Tras verificar la dirección, garantiza que el ZIP del cliente quede
        poblado (normalmente lo llena el front desde la verificación; si quedó
        vacío, lo ponemos). Al setear el ZIP, el front autocompleta ciudad/estado
        y NO re-invalida la dirección (confirmado por Big C 2026-09-22)."""
        if not zip_val:
            return
        try:
            zi = self.page.get_by_test_id(
                HmTransferelektraLocators.TRANSFER_CUSTOMER_ZIP_CODE_0_INPUT).first
            if ((await zi.input_value()) or "").strip():
                return
            await self.fill_transfer_customer_zip_code_0_input(zip_val)
            try:
                await self.esperar_autocomplete_cp()
            except Exception:
                pass
        except Exception:
            pass

    async def resolver_direccion_cliente(self, semilla_calle: str,
                                         zip_preferido: str = "",
                                         ciudad: str = "", estado: str = "",
                                         intentos: int = 2) -> tuple:
        """HÍBRIDO (real + fallback determinista). Confirmado con el front (Big C
        2026-09-22): la dirección solo queda válida al SELECCIONAR una sugerencia y
        que POST /address/verification devuelva status != 'failed' → el front pone
        isAddressValidated=true, rellena ciudad/estado/ZIP y desbloquea Continuar.

        1) FLUJO REAL (con `intentos`): teclear (≥6) → elegir sugerencia → esperar
           /address/verification. No se re-teclea ni se toca el ZIP (re-invalida).
        2) FALLBACK: si PostGrid no verifica, se INTERCEPTA /address/verification
           (y /address/suggestions) con page.route devolviendo 'verified', para que
           la validación NUNCA detenga el flujo.
        Devuelve (ok, {'direccion','zip','ciudad','modo'}, sugerencias)."""
        data_final = []
        for intento in range(1, max(1, intentos) + 1):
            data = await self.sugerencias_direccion_por_red(semilla_calle)
            if data:
                data_final = data
                idx, elegido = self._elegir_sugerencia(data, zip_preferido)
                if elegido is not None:
                    sec = elegido.get("secondaryText") or ""
                    main = elegido.get("mainText") or ""
                    m = re.search(r"\b(\d{5})\b", sec)
                    zsel = m.group(1) if m else (zip_preferido or "")
                    cd = (sec.replace(zsel, "").strip(" ,").upper() if zsel else sec.upper())
                    estado_v, _on = self._escuchar_verificacion()
                    try:
                        if await self._click_sugerencia(idx, main):
                            ok = False
                            for _i in range(8):
                                if (estado_v["status"] or "").lower() == "failed":
                                    break
                                if not await self._direccion_en_error() and (
                                        estado_v["recibido"] or _i >= 2):
                                    ok = True
                                    break
                                await self.page.wait_for_timeout(300)
                            if ok:
                                await self._asegurar_zip_direccion(zsel)
                                logger.info("Dirección: ✓ '%s' [%s %s] verificada "
                                            "(flujo real).", main, cd, zsel)
                                return (True, {"direccion": main, "zip": zsel,
                                               "ciudad": cd, "modo": "real"}, data)
                    finally:
                        try:
                            self.page.remove_listener("response", _on)
                        except Exception:
                            pass
            logger.info("Dirección '%s': intento real %d/%d no verificó%s.",
                        semilla_calle, intento, max(1, intentos),
                        " — voy al intercept" if intento >= intentos else ", reintento")
            try:
                await self.page.keyboard.press("Escape")
            except Exception:
                pass

        info = await self._resolver_por_intercept(
            semilla_calle, zip_preferido, ciudad, estado, data_final)
        await self._asegurar_zip_direccion(info.get("zip"))
        ok = not await self._direccion_en_error()
        info["modo"] = "intercept"
        (logger.info if ok else logger.warning)(
            "Dirección: %s vía intercept → '%s [%s %s]'.",
            "✓ verificada" if ok else "⚠ siguió en error",
            info.get("direccion"), info.get("ciudad"), info.get("zip"))
        return (ok, info, data_final)

    async def _resolver_por_intercept(self, calle: str, zip_pref: str,
                                      ciudad: str, estado: str, data: list) -> dict:
        """Fallback 100% determinista: intercepta /address/suggestions y
        /address/verification con page.route y responde 'verified' con datos
        coherentes, así el front marca isAddressValidated=true pase lo que pase."""
        import json as _json
        zsel = (zip_pref or "").strip()
        cd = (ciudad or "").strip().upper()
        st = (estado or "").strip().upper()
        if (not zsel or not cd) and data:
            it = next((x for x in data
                       if re.match(r"^\s*\d", x.get("mainText") or "")), data[0])
            sec = it.get("secondaryText") or ""
            m = re.search(r"\b(\d{5})\b", sec)
            if not zsel and m:
                zsel = m.group(1)
            if not cd:
                cd = sec.replace(zsel, "").strip(" ,").upper()
            if not calle.strip():
                calle = it.get("mainText") or calle
        sug = _json.dumps({"status": 200, "message": "ok", "data": [
            {"id": "auto-0", "mainText": calle,
             "secondaryText": f"{cd} {zsel}".strip(), "provider": "postgrid"}]})
        # La verificación real viaja bajo `data:{...}` (como /suggestions); el
        # front lee address/city/state/zipCode de ahí. Si no se anida, marca
        # verificado pero deja ZIP/Ciudad/Estado vacíos (y el ZIP es requerido).
        ver = _json.dumps({"status": 200, "message": "ok", "data": {
            "provider": "postgrid", "status": "verified", "id": "auto-0",
            "address": calle, "city": cd, "state": st,
            "country": "US", "zipCode": zsel, "errors": []}})

        async def _r_sug(route):
            try:
                await route.fulfill(status=200, content_type="application/json", body=sug)
            except Exception:
                try:
                    await route.continue_()
                except Exception:
                    pass

        async def _r_ver(route):
            try:
                await route.fulfill(status=200, content_type="application/json", body=ver)
            except Exception:
                try:
                    await route.continue_()
                except Exception:
                    pass

        await self.page.route("**/address/suggestions", _r_sug)
        await self.page.route("**/address/verification", _r_ver)
        try:
            await self.sugerencias_direccion_por_red(calle, espera_ms=800)
            await self._click_sugerencia(0, calle)
            for _ in range(7):
                if not await self._direccion_en_error():
                    break
                await self.page.wait_for_timeout(300)
        finally:
            for pat, fn in (("**/address/suggestions", _r_sug),
                            ("**/address/verification", _r_ver)):
                try:
                    await self.page.unroute(pat, fn)
                except Exception:
                    pass
        return {"direccion": calle, "zip": zsel, "ciudad": cd}

    async def fill_transfer_customer_zip_code_0_input(self, transfer_customer_zip_code_0_input: str) -> None:
        """Ingresa texto en: transfer-customer-zip-code-0-input"""
        logger.info(f"fill_transfer_customer_zip_code_0_input: {transfer_customer_zip_code_0_input}")
        await self.fill_input_by_testid(
            HmTransferelektraLocators.TRANSFER_CUSTOMER_ZIP_CODE_0_INPUT, transfer_customer_zip_code_0_input
        )

    async def click_transfer_beneficiary_toggle_fi(self) -> None:
        """Click en: transfer-beneficiary-toggle-fields-button-0"""
        logger.info("click_transfer_beneficiary_toggle_fi...")
        await self.smart_click(testid=HmTransferelektraLocators.TRANSFER_BENEFICIARY_TOGGLE_FIELDS_BUTTON_0, fallbacks=['[aria-label="Toggle Beneficiary Fields"]'])

    async def click_transfer_beneficiary_clear_0_i(self) -> None:
        """Click en: transfer-beneficiary-clear-0-icon-svg"""
        logger.info("click_transfer_beneficiary_clear_0_i...")
        await self.smart_click(testid=HmTransferelektraLocators.TRANSFER_BENEFICIARY_CLEAR_0_ICON_SVG)

    async def fill_transfer_beneficiary_country_0_dropdown_input(self, transfer_beneficiary_country_0_dropdown_input: str) -> None:
        """Ingresa texto en: transfer-beneficiary-country-0-dropdown-input"""
        logger.info(f"fill_transfer_beneficiary_country_0_dropdown_input: {transfer_beneficiary_country_0_dropdown_input}")
        await self.select_typeahead(HmTransferelektraLocators.TRANSFER_BENEFICIARY_COUNTRY_0_DROPDOWN_INPUT, transfer_beneficiary_country_0_dropdown_input)

    async def click_beneficiary(self) -> None:
        """Click en: Beneficiary"""
        logger.info("click_beneficiary...")
        await self.smart_click(testid=HmTransferelektraLocators.TRANSFER_BENEFICIARY_SUBTITLE_0, texto="Beneficiary", fallbacks=['#beneficiarySection'])

    async def fill_transfer_beneficiary_name_0_dropdown_input(self, transfer_beneficiary_name_0_dropdown_input: str) -> None:
        """Ingresa texto en: transfer-beneficiary-name-0-dropdown-input"""
        logger.info(f"fill_transfer_beneficiary_name_0_dropdown_input: {transfer_beneficiary_name_0_dropdown_input}")
        await self.select_typeahead(HmTransferelektraLocators.TRANSFER_BENEFICIARY_NAME_0_DROPDOWN_INPUT, transfer_beneficiary_name_0_dropdown_input)

    async def fill_transfer_beneficiary_first_lastname_0_input(self, transfer_beneficiary_first_lastname_0_input: str) -> None:
        """Ingresa texto en: transfer-beneficiary-first-lastname-0-input"""
        logger.info(f"fill_transfer_beneficiary_first_lastname_0_input: {transfer_beneficiary_first_lastname_0_input}")
        await self.fill_input_by_testid(
            HmTransferelektraLocators.TRANSFER_BENEFICIARY_FIRST_LASTNAME_0_INPUT, transfer_beneficiary_first_lastname_0_input
        )

    async def fill_transfer_beneficiary_second_lastname_0_input(self, transfer_beneficiary_second_lastname_0_input: str) -> None:
        """Ingresa texto en: transfer-beneficiary-second-lastname-0-input"""
        logger.info(f"fill_transfer_beneficiary_second_lastname_0_input: {transfer_beneficiary_second_lastname_0_input}")
        await self.fill_input_by_testid(
            HmTransferelektraLocators.TRANSFER_BENEFICIARY_SECOND_LASTNAME_0_INPUT, transfer_beneficiary_second_lastname_0_input
        )

    async def fill_transfer_beneficiary_cellphone_0_cellphone_input(self, transfer_beneficiary_cellphone_0_cellphone_input: str) -> None:
        """Ingresa texto en: transfer-beneficiary-cellphone-0-cellphone-input"""
        logger.info(f"fill_transfer_beneficiary_cellphone_0_cellphone_input: {transfer_beneficiary_cellphone_0_cellphone_input}")
        await self.fill_input_by_testid(
            HmTransferelektraLocators.TRANSFER_BENEFICIARY_CELLPHONE_0_CELLPHONE_INPUT, transfer_beneficiary_cellphone_0_cellphone_input
        )

    async def fill_transfer_beneficiary_address_0_input(self, transfer_beneficiary_address_0_input: str) -> None:
        """Ingresa texto en: transfer-beneficiary-address-0-input"""
        logger.info(f"fill_transfer_beneficiary_address_0_input: {transfer_beneficiary_address_0_input}")
        await self.fill_input_by_testid(
            HmTransferelektraLocators.TRANSFER_BENEFICIARY_ADDRESS_0_INPUT, transfer_beneficiary_address_0_input
        )

    async def fill_transfer_beneficiary_zip_code_0_input(self, transfer_beneficiary_zip_code_0_input: str) -> None:
        """Ingresa texto en: transfer-beneficiary-zip-code-0-input"""
        logger.info(f"fill_transfer_beneficiary_zip_code_0_input: {transfer_beneficiary_zip_code_0_input}")
        await self.fill_input_by_testid(
            HmTransferelektraLocators.TRANSFER_BENEFICIARY_ZIP_CODE_0_INPUT, transfer_beneficiary_zip_code_0_input
        )

    async def fill_transfer_beneficiary_city_0_input(self, transfer_beneficiary_city_0_input: str) -> None:
        """Ingresa texto en: transfer-beneficiary-city-0-input"""
        logger.info(f"fill_transfer_beneficiary_city_0_input: {transfer_beneficiary_city_0_input}")
        await self.select_typeahead(HmTransferelektraLocators.TRANSFER_BENEFICIARY_CITY_0_INPUT, transfer_beneficiary_city_0_input)

    async def fill_transfer_beneficiary_state_0_input(self, transfer_beneficiary_state_0_input: str) -> None:
        """Ingresa texto en: transfer-beneficiary-state-0-input"""
        logger.info(f"fill_transfer_beneficiary_state_0_input: {transfer_beneficiary_state_0_input}")
        await self.select_typeahead(HmTransferelektraLocators.TRANSFER_BENEFICIARY_STATE_0_INPUT, transfer_beneficiary_state_0_input)

    async def fill_transfer_beneficiary_date_of_birth_0_input(self, transfer_beneficiary_date_of_birth_0_input: str) -> None:
        """Ingresa texto en: transfer-beneficiary-date-of-birth-0-input"""
        logger.info(f"fill_transfer_beneficiary_date_of_birth_0_input: {transfer_beneficiary_date_of_birth_0_input}")
        await self.fill_input_by_testid(
            HmTransferelektraLocators.TRANSFER_BENEFICIARY_DATE_OF_BIRTH_0_INPUT, transfer_beneficiary_date_of_birth_0_input
        )

    async def fill_transfer_beneficiary_email_0_input(self, transfer_beneficiary_email_0_input: str) -> None:
        """Ingresa texto en: transfer-beneficiary-email-0-input"""
        logger.info(f"fill_transfer_beneficiary_email_0_input: {transfer_beneficiary_email_0_input}")
        await self.fill_input_by_testid(
            HmTransferelektraLocators.TRANSFER_BENEFICIARY_EMAIL_0_INPUT, transfer_beneficiary_email_0_input
        )

    async def scroll_219px(self) -> None:
        """Scroll para visualizar contenido (rueda o barra)."""
        await self.scroll_to(219, 0, selector="div")

    async def fill_transfer_payers_money_info_city_0_cash_dropdown_input(self, transfer_payers_money_info_city_0_cash_dropdown_input: str) -> None:
        """Ingresa texto en: transfer-payers-money-info-city-0-cash-dropdown-input"""
        logger.info(f"fill_transfer_payers_money_info_city_0_cash_dropdown_input: {transfer_payers_money_info_city_0_cash_dropdown_input}")
        await self.select_typeahead(HmTransferelektraLocators.TRANSFER_PAYERS_MONEY_INFO_CITY_0_CASH_DROPDOWN_INPUT, transfer_payers_money_info_city_0_cash_dropdown_input)

    # Tabs de TIPO de envío (sección Transfer). El testid es estable por índice:
    # transfer-payers-0-tab-title-{0..4}. Cash=0 (default/activo), Deposit=1,
    # Domicilio/Home=2, Móvil/Mobile=3, ATM=4.
    _TAB_TIPO_ENVIO = {"cash": 0, "deposit": 1, "home": 2, "mobile": 3, "atm": 4}

    async def tipos_envio_disponibles(self) -> dict:
        """
        Lee del DOM qué tipos de envío están DISPONIBLES para el país/pagador
        actualmente seleccionado. La disponibilidad la refleja Hermes con la
        clase 'disabled-tab' en el <li> de cada tab (ver análisis del código:
        transfers-payers.component.ts::checkPayerByCountry). No adivina: lee la
        verdad que la app ya resolvió contra el backend legacy.

        Devuelve {'cash': True/False, 'deposit': ..., ...}. None si el tab no
        existe en el DOM.
        """
        js = """
        () => {
          const map = {0:'cash', 1:'deposit', 2:'home', 3:'mobile', 4:'atm'};
          const res = {};
          for (const i of Object.keys(map)) {
            const a = document.querySelector(
              `[data-testid='transfer-payers-0-tab-title-${i}']`);
            if (!a) { res[map[i]] = null; continue; }
            const li = a.closest('li');
            const disabled = li ? li.classList.contains('disabled-tab') : false;
            res[map[i]] = !disabled;
          }
          return res;
        }
        """
        try:
            return await self.page.evaluate(js)
        except Exception as e:
            logger.warning(f"tipos_envio_disponibles: no se pudo leer el DOM ({e})")
            return {}

    async def seleccionar_tipo_envio(self, tipo: str = "cash") -> None:
        """
        Selecciona el TIPO de envío clickeando su tab (Cash/Deposit/Home/Mobile/
        ATM). Cash es el default activo, así que no requiere clic. Para los demás
        se clickea transfer-payers-0-tab-title-<idx>. Si el tab está deshabilitado
        (el pagador no soporta ese tipo) se registra y continúa.
        """
        tipo = (tipo or "cash").strip().lower()
        idx = self._TAB_TIPO_ENVIO.get(tipo, 0)
        if tipo == "cash":
            logger.info("seleccionar_tipo_envio: cash (default/activo) — sin clic")
            return
        logger.info(f"seleccionar_tipo_envio: {tipo} (tab índice {idx})")
        # Aviso (no bloqueante) si el tipo pedido no está disponible para la
        # selección actual — lo sabemos leyendo 'disabled-tab' del DOM.
        try:
            disp = await self.tipos_envio_disponibles()
            if disp.get(tipo) is False:
                logger.warning(f"[tipo] '{tipo}' aparece DESHABILITADO (disabled-tab) para "
                               f"el país/pagador actual. Intento igual, pero puede no aplicar.")
        except Exception:
            pass
        testid = f"transfer-payers-0-tab-title-{idx}"
        try:
            tab = self.page.get_by_test_id(testid).first
            await tab.wait_for(state="visible", timeout=5_000)
            await tab.scroll_into_view_if_needed(timeout=1_500)
            await tab.click(force=True, timeout=4_000)
            await self.wait_for_no_blocking_overlays(timeout=2_000)
            logger.info(f"✓ tipo de envío seleccionado: {tipo}")
        except Exception as e:
            logger.warning(f"No se pudo seleccionar el tipo '{tipo}' ({testid}): {e} — continúo")

    async def click_mexico_regular(self) -> None:
        """Selecciona 'MEXICO REGULAR' en Fee Type.

        REINTENTA hasta 3 veces: el panel del dropdown a veces abre VACÍO
        (0 opciones) por timing —tras colapsar el beneficiario y hacer scroll,
        el control aún no está listo—. Entre intentos limpia overlays y re-scroll
        al campo, que es lo que estabiliza el 'Opción no encontrada (0)'.
        """
        logger.info("click_mexico_regular...")
        sel = self.format_testid_selector(
            HmTransferelektraLocators.TRANSFER_PAYERS_MONEY_INFO_FEE_TYPE_0_CASH_DROPDOWN_INPUT_click)
        ultimo_error = None
        for intento in range(1, 4):
            try:
                await self.select_option_by_text(
                    sel, "li[role='option'], .p-dropdown-item", "MEXICO REGULAR")
                return
            except Exception as e:
                ultimo_error = e
                logger.warning(f"click_mexico_regular: intento {intento}/3 falló "
                               f"({str(e)[:60]}) — reintento")
                try:
                    await self.wait_for_no_blocking_overlays(timeout=2_000)
                    await self.page.locator(sel).first.scroll_into_view_if_needed(timeout=1_500)
                    await self.page.wait_for_timeout(700)
                except Exception:
                    pass
        raise ultimo_error if ultimo_error else Exception("click_mexico_regular: no se pudo seleccionar")

    # ── DEPÓSITO — campos propios (data-testid confirmados) ───────────────────
    async def seleccionar_deposit_account_type(self, opcion: int = None) -> None:
        """
        Tipo de cuenta (Depósito). Es un dropdown que SOLO a veces está
        habilitado. Si lo está, elige: 1=Cheques, 2=Ahorros (aleatorio si no se
        indica). Si no está visible/habilitado, se omite sin fallar.
        Testids:
          botón : transfer-payers-money-info-account-number-0-deposit-button
          op 1  : ...-0-deposit-1-list-item   (Cheques)
          op 2  : ...-0-deposit-2-list-item   (Ahorros)
        """
        import random as _r
        btn = self.page.get_by_test_id(
            "transfer-payers-money-info-account-number-0-deposit-button").first
        try:
            if await btn.count() == 0 or not await btn.is_visible():
                logger.info("account type: dropdown no visible — se omite.")
                return
            try:
                if await btn.is_disabled():
                    logger.info("account type: dropdown deshabilitado — se omite.")
                    return
            except Exception:
                pass
            await btn.scroll_into_view_if_needed(timeout=1_500)
            await btn.click(force=True, timeout=4_000)
            await self.page.wait_for_timeout(300)
            op = opcion or _r.choice([1, 2])
            item = self.page.get_by_test_id(
                f"transfer-payers-money-info-account-number-0-deposit-{op}-list-item").first
            await item.wait_for(state="visible", timeout=3_000)
            await item.click(force=True, timeout=3_000)
            logger.info(f"account type: opción {op} ({'Cheques' if op == 1 else 'Ahorros'})")
        except Exception as e:
            logger.warning(f"account type: no se pudo seleccionar ({e}) — se omite.")

    _ACCOUNT_NUMBER_TESTID = "transfer-payers-money-info-account-number-0-deposit-input"

    async def fill_deposit_account_number(self, valor: str) -> None:
        """Número de cuenta (Depósito): transfer-payers-money-info-account-number-0-deposit-input."""
        logger.info(f"fill_deposit_account_number: {valor}")
        await self.fill_input_by_testid(self._ACCOUNT_NUMBER_TESTID, valor)

    async def leer_error_de_campo(self, testid: str) -> str:
        """
        Lee el mensaje de validación (text-danger/error-input/invalid-feedback)
        que Hermes muestra junto al campo con ese data-testid. Devuelve '' si no
        hay error. Sirve para cualquier campo (cuenta, teléfono, etc.).
        """
        js = """
        (tid) => {
          const inp = document.querySelector(`[data-testid='${tid}']`);
          if (!inp) return "";
          let cont = inp.closest("formfieldcontrol, .form-input, .field, .form-floating, div") || inp.parentElement;
          for (let i = 0; i < 5 && cont; i++) {
            const e = cont.querySelector(
              "p.text-danger, .error-input, .invalid-feedback, small.text-danger, "
              + "[class*='error'], .text-danger");
            if (e && e.textContent && e.textContent.trim()) return e.textContent.trim();
            cont = cont.parentElement;
          }
          return "";
        }
        """
        try:
            return (await self.page.evaluate(js, testid)) or ""
        except Exception:
            return ""

    async def _leer_error_cuenta(self) -> str:
        """Error de validación (si hay) junto al campo Número de cuenta."""
        return await self.leer_error_de_campo(self._ACCOUNT_NUMBER_TESTID)

    @staticmethod
    def _digitos_requeridos(msg: str):
        """Extrae del mensaje de error cuántos dígitos pide. Si hay dos números
        (rango 'entre 14 y 18'), devuelve el mínimo; si hay uno ('al menos 14'),
        ese. None si no hay número."""
        import re as _re
        nums = [int(x) for x in _re.findall(r"\d+", msg or "")]
        if not nums:
            return None
        return min(nums) if len(nums) >= 2 else nums[0]

    async def fill_account_number_adaptativo(self, min_d: int = 11, max_d: int = 18,
                                             intentos: int = 4) -> str:
        """
        Llena el Número de cuenta y se AUTO-CORRIGE por longitud: escribe un número
        aleatorio, dispara la validación (blur), lee el error del campo; si pide
        más/menos dígitos, limpia y reescribe con la longitud correcta. Reintenta
        hasta `intentos`. Devuelve el número aplicado (o el último intentado).

        Es la opción que acordamos: leer el mensaje del DOM (no DevTools) y ajustar.
        """
        import random as _r
        field = self.page.get_by_test_id(self._ACCOUNT_NUMBER_TESTID).first
        longitud = _r.randint(11, 16)
        ultimo = ""
        for intento in range(1, intentos + 1):
            longitud = max(min_d, min(longitud, max_d))
            valor = "".join(str(_r.randint(0, 9)) for _ in range(longitud))
            ultimo = valor
            try:
                await field.fill("")
            except Exception:
                pass
            await self.fill_input_by_testid(self._ACCOUNT_NUMBER_TESTID, valor)
            # Disparar validación (blur → si no, click en el body)
            try:
                await field.blur()
            except Exception:
                try:
                    await self.trigger_field_validation()
                except Exception:
                    pass
            await self.page.wait_for_timeout(400)

            err = await self._leer_error_cuenta()
            if not err:
                logger.info(f"✓ número de cuenta OK ({longitud} dígitos, intento {intento}).")
                return valor
            req = self._digitos_requeridos(err)
            logger.warning(f"número de cuenta rechazado ({longitud}d): '{err[:70]}' → "
                           f"requiere {req if req else 'otra longitud'}")
            if req and min_d <= req <= max_d:
                # Si pide 'más', usar exactamente lo pedido; margen +0 (mínimo requerido).
                longitud = req if req != longitud else min(req + 1, max_d)
            else:
                longitud = min(longitud + 2, max_d)  # sin número claro → escalar
        logger.warning(f"número de cuenta: no se resolvió la validación tras {intentos} intentos "
                       f"(último {ultimo}).")
        return ultimo

    async def listar_fee_types(self) -> list:
        """Abre el dropdown Fee Type (Cash) y LEE las tarifas disponibles (para
        el analizer). Cierra con Escape sin cambiar la selección."""
        sel = self.format_testid_selector(
            HmTransferelektraLocators.TRANSFER_PAYERS_MONEY_INFO_FEE_TYPE_0_CASH_DROPDOWN_INPUT_click)
        vals = []
        try:
            dd = self.page.locator(sel).first
            await dd.click(force=True, timeout=4_000)
            await self.page.wait_for_timeout(400)
            opts = self.page.locator(
                "li[role='option'], .p-dropdown-item, .p-autocomplete-item, [role='option']")
            try:
                await opts.first.wait_for(state="visible", timeout=3_000)
            except Exception:
                pass
            n = await opts.count()
            for i in range(min(n, 50)):
                try:
                    t = (await opts.nth(i).inner_text()).strip()
                    if t:
                        vals.append(" ".join(t.split()))
                except Exception:
                    pass
            try:
                await self.page.keyboard.press("Escape")
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"listar_fee_types: {e}")
        return list(dict.fromkeys(vals))

    async def listar_pagadores_disponibles(self, max_filas: int = 80) -> list:
        """Abre el modal Payer Search (sin filtrar) y LEE la lista de pagadores
        disponibles para la selección actual (país+tipo+ciudad). Para el analizer:
        así descubrimos el catálogo de pagadores sin hardcodearlo."""
        out = []
        try:
            await self.click_transfer_payers_money_info_pay()
            loc = HmTransferelektraLocators.TRANSFERS_MONEY_INFO_MODAL_SEARCH_PAYER_0_INPUT_SEARCH_INPUT
            try:
                await self.page.get_by_test_id(loc).first.wait_for(state="visible", timeout=6_000)
            except Exception:
                pass
            await self.page.wait_for_timeout(600)
            filas = self.page.locator(
                "div[role='dialog'] tbody tr, .p-datatable-tbody tr, .modal.show tbody tr, "
                ".p-dialog tbody tr, div[role='dialog'] [role='row']")
            n = await filas.count()
            for i in range(min(n, max_filas)):
                try:
                    f = filas.nth(i)
                    if await f.is_visible():
                        t = (await f.inner_text()).strip()
                        if t:
                            out.append(" ".join(t.split()))
                except Exception:
                    pass
            await self._cerrar_modal_pagador()
        except Exception as e:
            logger.warning(f"listar_pagadores_disponibles: {e}")
        return list(dict.fromkeys(out))

    async def seleccionar_fee_type(self, tipo: str = "cash", texto: str = "MEXICO REGULAR") -> None:
        """
        Selecciona la Tarifa (Fee Type) del sub-formulario del TIPO dado. El
        testid sigue el patrón: transfer-payers-money-info-fee-type-0-<tipo>-dropdown-input.
        Intenta por `texto` (ej. 'MEXICO REGULAR'); si no existe para ese tipo,
        elige la PRIMERA opción disponible. Es lo que habilita el campo Cantidad
        y el modal de Pagador — omitirla dejaba el form inválido.
        """
        sel = f"[data-testid='transfer-payers-money-info-fee-type-0-{tipo}-dropdown-input']"
        if texto:
            try:
                await self.select_option_by_text(sel, "li[role='option'], .p-dropdown-item", texto)
                return
            except Exception:
                logger.info(f"fee-type ({tipo}): '{texto}' no está — elijo la primera opción")
        try:
            dd = self.page.locator(sel).first
            await dd.click(force=True, timeout=4_000)
            await self.page.wait_for_timeout(400)
            opt = self.page.locator(
                "li[role='option'], .p-dropdown-item, [role='option']").first
            await opt.wait_for(state="visible", timeout=4_000)
            await opt.click(force=True, timeout=3_000)
            logger.info(f"fee-type ({tipo}): primera opción")
        except Exception as e:
            logger.warning(f"fee-type ({tipo}): no se pudo seleccionar ({e})")

    async def click_transfer_payers_money_info_amo(self, monto) -> None:
        """Escribe el monto (limpia primero + teclea) en el campo Amount."""
        logger.info(f"click_transfer_payers_money_info_amo: {monto}")
        await self.fill_monto(HmTransferelektraLocators.TRANSFER_PAYERS_MONEY_INFO_AMOUNT_0_CASH_AMOUNT_INPUT, monto)

    async def click_transfer_payers_money_info_pay(self) -> None:
        """Click en: transfer-payers-money-info-payer-0-cash-input"""
        logger.info("click_transfer_payers_money_info_pay...")
        await self.smart_click(testid=HmTransferelektraLocators.TRANSFER_PAYERS_MONEY_INFO_PAYER_0_CASH_INPUT, fallbacks=['#payer', '[formcontrolname="payer"]', 'input[name="payer"]'])

    async def click_payer_field(self, tipo: str = "cash") -> None:
        """Abre el campo Payer del sub-formulario del TIPO dado (abre el modal de
        búsqueda de pagador). El testid sigue el patrón por tipo:
        transfer-payers-money-info-payer-0-<tipo>-input."""
        testid = f"transfer-payers-money-info-payer-0-{tipo}-input"
        logger.info(f"click_payer_field ({tipo}): {testid}")
        await self.smart_click(testid=testid,
                               fallbacks=['#payer', '[formcontrolname="payer"]', 'input[name="payer"]'])

    async def fill_transfers_money_info_modal_search_payer_0_input_search_input(self, transfers_money_info_modal_search_payer_0_input_search_input: str) -> None:
        """Ingresa texto en: transfers-money-info-modal-search-payer-0-input-search-input"""
        logger.info(f"fill_transfers_money_info_modal_search_payer_0_input_search_input: {transfers_money_info_modal_search_payer_0_input_search_input}")
        await self.fill_input_by_testid(
            HmTransferelektraLocators.TRANSFERS_MONEY_INFO_MODAL_SEARCH_PAYER_0_INPUT_SEARCH_INPUT, transfers_money_info_modal_search_payer_0_input_search_input
        )

    async def buscar_pagador_rapido(self, search: str, row: str = "") -> bool:
        """Busqueda RAPIDA del pagador en el modal: fill de un tiro (dispara el
        filtro Angular) + poll CORTO (150ms) por la fila objetivo. Evita el camino
        pesado de fill_input_by_testid (cerrar autofill + verificacion + reteclear
        char-por-char). Si el fill rapido falla, cae al metodo robusto. Devuelve
        True si selecciono la fila objetivo."""
        import time as _t
        loc = HmTransferelektraLocators.TRANSFERS_MONEY_INFO_MODAL_SEARCH_PAYER_0_INPUT_SEARCH_INPUT
        logger.info(f"buscar_pagador_rapido: {search}" + (f" -> '{row}'" if row else ""))
        objetivo = (row or search)
        inp = self.page.get_by_test_id(loc).first
        try:
            await inp.wait_for(state="visible", timeout=6000)
            await self.page.wait_for_timeout(120)
        except Exception:
            pass
        escrito = False
        for intento in range(3):
            try:
                await inp.click(force=True, timeout=3000)
            except Exception:
                pass
            try:
                await inp.fill("", timeout=3000)
                await inp.fill(search, timeout=3000)
            except Exception:
                try:
                    await self.page.keyboard.type(search, delay=25)
                except Exception:
                    pass
            try:
                actual = (await inp.input_value()) or ""
            except Exception:
                actual = ""
            if search.lower()[:5] in actual.lower():
                escrito = True
                break
            await self.page.wait_for_timeout(300)
        if not escrito:
            logger.warning(f"buscar_pagador_rapido: NO se pudo escribir '{search}' en el modal")
        cand = self.page.get_by_text(objetivo, exact=False)
        deadline = _t.monotonic() + 6
        seleccionado = False
        while _t.monotonic() < deadline:
            try:
                n = await cand.count()
                for i in range(min(n, 10)):
                    if await cand.nth(i).is_visible():
                        await cand.nth(i).click(timeout=2500)
                        logger.info(f"✓ pagador rapido: '{objetivo}'")
                        seleccionado = True
                        break
            except Exception:
                pass
            if seleccionado:
                break
            await self.page.wait_for_timeout(80)   # sondeo más ágil
        await self._cerrar_modal_pagador()
        if not seleccionado:
            raise RuntimeError(
                f"pagador '{objetivo}' no encontrado en el modal "
                f"(filtro escrito={escrito}) — calculo abortado")
        return seleccionado

    async def _cerrar_modal_pagador(self) -> None:
        """Cierra el modal Payer Search si quedo abierto tras seleccionar el pagador
        y ESPERA a que desaparezca (max 4s)."""
        loc = HmTransferelektraLocators.TRANSFERS_MONEY_INFO_MODAL_SEARCH_PAYER_0_INPUT_SEARCH_INPUT
        search_inp = self.page.get_by_test_id(loc).first
        try:
            if not await search_inp.is_visible():
                return
        except Exception:
            return
        for sel in ("button.p-dialog-header-close",
                    "div[role='dialog'] button[aria-label='Close']",
                    ".p-dialog-header-icons button"):
            try:
                x = self.page.locator(sel).first
                if await x.is_visible():
                    await x.click(force=True, timeout=2000)
                    break
            except Exception:
                pass
        try:
            if await search_inp.is_visible():
                await self.page.keyboard.press("Escape")
        except Exception:
            pass
        try:
            await search_inp.wait_for(state="hidden", timeout=2500)
            logger.info("modal pagador cerrado")
        except Exception:
            logger.warning("modal pagador NO se cerro — puede tapar campos")

    async def click_elektra_directo(self) -> None:
        """Selecciona fila de modal: ELEKTRA DIRECTO"""
        logger.info("click_elektra_directo...")
        await self.click_fila_modal("ELEKTRA DIRECTO")

    async def scroll_250px(self) -> None:
        """Scroll para visualizar contenido (rueda o barra)."""
        await self.scroll_to(250, 0, selector="div")

    async def click_branch(self) -> None:
        """Click en: Branch"""
        logger.info("click_branch...")
        await self.smart_click(css=HmTransferelektraLocators.BUTTON_ID_1, texto=re.compile(r"branch|sucursal", re.I), fallbacks=['[data-testid="()=>function yt(St){return O(St),St.value}(it)-branch-selected-0-cash-button"]'], optional=True)

    async def click_daz_jal_san_joaquin_guad(self) -> None:
        """
        Selecciona la sucursal/branch (OPCIONAL): la tabla de branch no siempre
        aparece. Si no salió, sigue sin esperas largas.
        """
        logger.info("click_daz_jal_san_joaquin_guad (opcional)...")
        await self.click_fila_modal("DAZ JAL SAN JOAQUIN GUAD", optional=True)

    async def scroll_230px(self) -> None:
        """Scroll para visualizar contenido (rueda o barra)."""
        await self.scroll_to(230, 0, selector="div")

    async def scroll_130px(self) -> None:
        """Scroll para visualizar contenido (rueda o barra)."""
        await self.scroll_to(130, 0, selector="div")

    async def click_continue(self) -> None:
        """Click en: Continue.

        Ruta RÁPIDA primero: limpia overlays (2.5s) e intenta un click directo
        (force, 4s) sobre el botón visible — evita los reintentos largos de
        smart_click cuando el botón ya está listo. Si falla, cae a smart_click
        (robusto, con sus fallbacks)."""
        logger.info("click_continue...")
        # Estrategia del repo original, que aquí SÍ funciona: esperar a que el
        # botón sea visible y clickear con **force=True**.
        #
        # El matiz que costó entender: `force=True` se salta DOS verificaciones,
        # y solo una de ellas nos interesa.
        #   • "recibe eventos de puntero": en esta pantalla hay overlays no
        #     bloqueantes que la hacen fallar. Sin force, el click agota su
        #     timeout, se reintenta, y de ahí el scroll una y otra vez.
        #   • "está habilitado": esta sí importa — clickear a la fuerza un botón
        #     deshabilitado parece funcionar y Angular lo ignora en silencio.
        # Por eso se comprueba 'habilitado' A MANO y se clickea con force.
        loc = self.page.get_by_test_id(
            HmTransferelektraLocators.TRANSFER_CONTINUE_BUTTON_0_BUTTON)
        espera, limite = 0, 15_000
        scrolleado = False
        while espera <= limite:
            try:
                total = min(await loc.count(), 8)
            except Exception:
                total = 0
            for i in range(total):
                btn = loc.nth(i)
                try:
                    if not (await btn.is_visible() and await btn.is_enabled()):
                        continue
                    if not scrolleado:
                        try:
                            await btn.scroll_into_view_if_needed(timeout=1_000)
                        except Exception:
                            pass
                        scrolleado = True
                    await btn.click(timeout=4_000, force=True)
                    logger.info("✓ click_continue (habilitado a los %.1f s)",
                                espera / 1000)
                    return
                except Exception:
                    continue
            await self.page.wait_for_timeout(150)
            espera += 150
        # Diagnóstico antes del respaldo: sin esto no se sabe si el botón no
        # existe, está oculto o está deshabilitado.
        try:
            n = await loc.count()
            estados = []
            for i in range(min(n, 8)):
                b = loc.nth(i)
                estados.append(f"#{i} visible={await b.is_visible()} "
                               f"habilitado={await b.is_enabled()}")
            logger.warning("Continue no clickeable en %.0f s — %d candidato(s): %s",
                           limite / 1000, n, " · ".join(estados) or "(ninguno)")
        except Exception:
            pass
        # Respaldo por JS (lo mismo que se hace en Chronos cuando los overlays
        # interceptan el puntero): dispara el click desde el propio elemento.
        try:
            hecho = await self.page.evaluate(
                "() => { const b = document.querySelector("
                "'[data-testid=\"transfer-continue-button-0-button\"]');"
                " if (!b || b.disabled) return false; b.click(); return true; }")
            if hecho:
                logger.info("✓ click_continue (por JS)")
                return
        except Exception:
            pass
        await self.wait_for_no_blocking_overlays(timeout=1_500)
        await self.smart_click(testid=HmTransferelektraLocators.TRANSFER_CONTINUE_BUTTON_0_BUTTON, texto="Continue")

    async def click_yes_send(self) -> None:
        """Click en: YES, Send"""
        logger.info("click_yes_send...")
        await self.smart_click(testid=HmTransferelektraLocators.TRANSFERS_CONTAINER_MODAL_SUMMARY_0_SEND_BUTTON, texto="YES, Send")

    async def click_no(self) -> None:
        """Click en: NO ('¿desea hacer otra transacción?').

        Ruta RÁPIDA primero (click directo, 2.5s) para no tardar en cerrar el
        modal de éxito; si falla, cae a smart_click robusto."""
        logger.info("click_no...")
        try:
            btn = self.page.get_by_test_id(
                HmTransferelektraLocators.TRANSFERS_CONTAINER_MODAL_SUCCESS_TRANSFER_0_DECLINE_BUTTON).first
            await btn.click(timeout=2_500, force=True)
            logger.info("✓ click_no (ruta rápida)")
            return
        except Exception:
            logger.info("ruta rápida NO no aplicó — uso smart_click")
        await self.smart_click(testid=HmTransferelektraLocators.TRANSFERS_CONTAINER_MODAL_SUCCESS_TRANSFER_0_DECLINE_BUTTON, texto="NO")

    async def click_reports(self) -> None:
        """Click en: Reports"""
        logger.info("click_reports...")
        await self.smart_click(testid=HmTransferelektraLocators.REPORTS_NAVBAR_ITEM, texto="Reports", fallbacks=['[aria-label="dropdown"]'])

    async def click_transactions(self) -> None:
        """Click en 'Transacciones'/'Transactions' del menú Reportes.

        El ÍNDICE del item cambia entre perfiles (mono: reports-2; multiagente:
        reports-1 = Transacciones, reports-2 = Tipo de Cambio). Por eso se
        selecciona POR TEXTO (EN/ES, ambos contienen 'Transac'), no por índice."""
        logger.info("click_transactions...")
        rx = re.compile(r"transac", re.I)  # Transactions / Transacciones
        item_sel = "a.dropdown-item[data-testid*='navbar-dropdown-item']"

        async def _item():
            return self.page.locator(item_sel).filter(has_text=rx).first

        # Abrir el dropdown de Reportes si el item no está visible aún
        try:
            visible = await (await _item()).is_visible()
        except Exception:
            visible = False
        if not visible:
            await self.smart_click(testid="reports-navbar-item", texto="Reports")
            await self.page.wait_for_timeout(500)

        # 1) Click por TEXTO (robusto mono/multi, EN/ES)
        try:
            it = await _item()
            await it.wait_for(state="visible", timeout=6_000)
            await it.click(force=True, timeout=4_000)
            logger.info("✓ click_transactions (por texto Transac)")
            return
        except Exception:
            pass

        # 2) Fallbacks por testid conocidos: multi=reports-1, mono=reports-2
        for tid in ("reports-1-navbar-dropdown-item", "reports-2-navbar-dropdown-item"):
            try:
                el = self.page.get_by_test_id(tid).first
                await el.wait_for(state="visible", timeout=3_000)
                txt = ((await el.inner_text()) or "").strip().lower()
                if "transac" in txt:
                    await el.click(force=True, timeout=4_000)
                    logger.info("✓ click_transactions (testid=%s)", tid)
                    return
            except Exception:
                continue

        # 3) Último recurso: el que sea reports-1 (según DOM multiagente provisto)
        await self.smart_click(testid="reports-1-navbar-dropdown-item", texto="Transactions",
                               fallbacks=['[aria-label="dropdown item"]'])

    async def click_yes_leave(self) -> None:
        """Click en: YES, Leave"""
        logger.info("click_yes_leave...")
        await self.smart_click(testid=HmTransferelektraLocators.MODAL_CONFIRMATION_DENY_BUTTON, texto="YES, Leave")

    # ── REPORTS_TRANSACTION ─────────────────────────────────

    async def click_search(self) -> None:
        """Click en: Search"""
        logger.info("click_search...")
        # 'test-id-button' es GENÉRICO → se desambigua por texto bilingüe (EN/ES).
        await self.smart_click(testid=HmTransferelektraLocators.TEST_ID_BUTTON,
                               texto=re.compile(r"search|buscar", re.I))

    async def click_cancel(self) -> None:
        """Click en: Cancel"""
        logger.info("click_cancel...")
        await self.smart_click(testid=HmTransferelektraLocators.REPORTS_TRANSACTION_MENU__CANCEL_ICON_SVG, texto="Cancel")

    async def click_client_request_no_reason(self) -> None:
        """Selecciona la opción 'Client request (No reason)' del dropdown."""
        logger.info("click_client_request_no_reason...")
        await self.select_option_by_text(
            self.format_testid_selector(HmTransferelektraLocators.SELECT_FIELD_DROPDOWN_INPUT_click),
            "li[role='option'], .p-dropdown-item",
            "Client request (No reason)",
        )

    async def fill_modal_cancel_transaction_notes_input(self, modal_cancel_transaction_notes_input: str) -> None:
        """Ingresa texto en: modal-cancel-transaction-notes-input"""
        logger.info(f"fill_modal_cancel_transaction_notes_input: {modal_cancel_transaction_notes_input}")
        await self.fill_input_by_testid(
            HmTransferelektraLocators.MODAL_CANCEL_TRANSACTION_NOTES_INPUT, modal_cancel_transaction_notes_input
        )

    async def click_transfers(self) -> None:
        """Click en: Transfers"""
        logger.info("click_transfers...")
        await self.smart_click(css=HmTransferelektraLocators.DROPDOWN,
                               texto=re.compile(r"transfers?|env[ií]o|transferencia", re.I))
