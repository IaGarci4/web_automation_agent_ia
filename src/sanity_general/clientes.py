"""
CP13 — Búsqueda de clientes en Settings > Cliente.
(Rescate/mejora de `HERMES2-qa/src/sanity_general/test_CP13_Busqueda_de_clientes.py`
+ `src/models/customer_module.py::cp13_*`.)

Filosofía (igual que `balance.py` y `money_order.py`): el test NO conoce
selectores ni tiempos; solo orquesta pasos y captura evidencia. Toda la lógica
frágil vive aquí, endurecida sobre lo que ya sabemos estable en el agente:

  • Navegación por el navbar de Settings con cierre proactivo del aviso
    «¿salir de esta página?» (mismo patrón que en Money Order — el aviso tarda
    un instante en renderizar y si no se cierra su overlay bloquea el clic).
  • Clicks sin `force` primero (respetan la accionabilidad de Angular) y `force`
    solo como último recurso.
  • Búsqueda con espera REAL de la tabla de resultados (no un sleep fijo) y
    reintento si Angular tardó en pintar la primera respuesta.
  • Selección de beneficiario tolerante: intenta por texto exacto (como el
    original) y, si el nombre viene con espacios raros o segundo apellido vacío,
    cae a coincidencia parcial por el nombre.

Pasos (QMetry):
  1. Settings > Cliente carga.
  2. Buscar cliente por nombre + primer apellido → aparece la tabla.
  3. Seleccionar el primer resultado → cargan los campos de beneficiario.
  4. Elegir beneficiario del dropdown → los valores coinciden con lo esperado.

Fuente de los locators: `HERMES2-qa/src/models/locators/customer_module_locators.py`
(la web app es idéntica en el agente — los data-testid no cambian).
"""
import re

from config.logger import get_logger

logger = get_logger("sanity.clientes")

TIMEOUT = 30_000

# ── Navegación (Settings > Cliente) ──────────────────────────────────────────
NAV_SETTINGS      = "settings-navbar-item"
MENU_CLIENTE      = "settings-0-navbar-dropdown-item"
MODAL_DENY        = "modal-confirmation-deny-button"   # «YES, Leave» / «Sí, salir»

# ── Formulario de cliente (búsqueda) ─────────────────────────────────────────
CUST_NOMBRE       = "customer-admin-configurations-name-input"
CUST_APELLIDO1    = "customer-admin-configurations-first-last-name-input"
CUST_APELLIDO2    = "customer-admin-configurations-second-last-name-input"

# Tabla de resultados de la búsqueda + primera fila.
TABLA_RESULTADOS  = ".table-search-modal"
PRIMERA_FILA      = "//tbody/tr/td[1]"

# ── Beneficiario ─────────────────────────────────────────────────────────────
BENEF_NOMBRE      = "beneficiary-admin-configurations-name-dropdown-input"
BENEF_APELLIDO1   = "beneficiary-admin-configurations-first-last-name-input"
BENEF_APELLIDO2   = "beneficiary-admin-configurations-second-last-name-input"
BENEF_DROPDOWN    = "input-filter-dropdown"   # contenedor de opciones del dropdown


# ── Helpers de bajo nivel ────────────────────────────────────────────────────
async def _cerrar_warning(page, timeout_ms: int = 1_500) -> bool:
    """Cierra el aviso «¿salir de esta página?» si está (o aparece) en pantalla.

    Devuelve True si lo cerró. No lanza: si no hay aviso, no pasa nada."""
    espera, paso = 0, 250
    while espera <= timeout_ms:
        try:
            btn = page.get_by_test_id(MODAL_DENY).first
            if await btn.is_visible():
                await btn.click(timeout=5_000)
                logger.info("[CP13] Aviso de salida cerrado.")
                await page.wait_for_timeout(400)
                return True
        except Exception:
            pass
        await page.wait_for_timeout(paso)
        espera += paso
    return False


async def _click(page, testid: str, desc: str, timeout: int = TIMEOUT) -> bool:
    """Click estable: espera visible, hace scroll, intenta sin `force` y solo
    recurre a `force` como último recurso (mismo criterio que money_order._click)."""
    try:
        b = page.get_by_test_id(testid).first
        await b.wait_for(state="visible", timeout=timeout)
        try:
            await b.scroll_into_view_if_needed(timeout=3_000)
        except Exception:
            pass
        try:
            await b.click(timeout=timeout)
        except Exception:
            await b.click(force=True, timeout=8_000)
        logger.info("[CP13] %s", desc)
        return True
    except Exception as e:
        logger.warning("[CP13] No se pudo pulsar %s: %s", desc, str(e)[:100])
        return False


# ── Paso 1: navegar a Settings > Cliente ─────────────────────────────────────
async def abrir_settings_cliente(page, intentos: int = 3) -> bool:
    """Settings > Cliente. Cierra el aviso de salida antes de cada clic (puede
    haber cambios sin guardar en la pantalla previa)."""
    logger.info("[CP13] Abriendo Settings > Cliente…")
    for intento in range(1, intentos + 1):
        await _cerrar_warning(page, timeout_ms=1_500)
        if not await _click(page, NAV_SETTINGS, "Menú Settings", timeout=15_000):
            continue
        await page.wait_for_timeout(700)
        await _cerrar_warning(page, timeout_ms=2_000)
        if await _click(page, MENU_CLIENTE, "Cliente", timeout=12_000):
            # Tras entrar puede aparecer el modal de confirmación → cerrarlo.
            await _cerrar_warning(page, timeout_ms=2_500)
            await page.wait_for_timeout(1_000)
            # Confirmar que el formulario de búsqueda quedó disponible.
            try:
                await page.get_by_test_id(CUST_NOMBRE).first.wait_for(
                    state="visible", timeout=10_000)
                return True
            except Exception:
                logger.info("[CP13] El campo de nombre aún no aparece "
                            "(intento %d/%d).", intento, intentos)
        logger.info("[CP13] Cliente no respondió (intento %d/%d).",
                    intento, intentos)
    logger.warning("[CP13] No se pudo abrir Settings > Cliente.")
    return False


# ── Paso 2: buscar cliente ───────────────────────────────────────────────────
async def buscar_cliente(page, nombre: str, apellido1: str,
                         intentos: int = 2) -> bool:
    """Teclea nombre + primer apellido y espera la tabla de resultados.

    Mejora sobre el original: en vez de un sleep fijo de 5 s, espera de verdad a
    que la tabla sea visible; si Angular tardó y no salió, reescribe y reintenta."""
    logger.info("[CP13] Buscando cliente — nombre=%s, apellido=%s",
                nombre, apellido1)
    tabla = page.locator(TABLA_RESULTADOS)
    for intento in range(1, intentos + 1):
        try:
            campo_nombre = page.get_by_test_id(CUST_NOMBRE).first
            await campo_nombre.click()
            await campo_nombre.fill("")
            await campo_nombre.fill(nombre)
            await page.wait_for_timeout(500)

            campo_ap1 = page.get_by_test_id(CUST_APELLIDO1).first
            await campo_ap1.click()
            await campo_ap1.fill("")
            await campo_ap1.fill(apellido1)

            # La búsqueda es reactiva al teclear: esperar la tabla, no un sleep.
            await tabla.first.wait_for(state="visible", timeout=15_000)
            logger.info("[CP13] Tabla de resultados visible.")
            return True
        except Exception as e:
            logger.warning("[CP13] La tabla no apareció (intento %d/%d): %s",
                           intento, intentos, str(e)[:100])
            await page.wait_for_timeout(1_500)
    return False


# ── Paso 3: seleccionar el primer cliente ────────────────────────────────────
async def seleccionar_primer_cliente(page) -> bool:
    """Clic en la primera fila y espera a que carguen los campos de beneficiario."""
    logger.info("[CP13] Seleccionando el primer cliente de la tabla.")
    try:
        fila = page.locator(PRIMERA_FILA).first
        await fila.wait_for(state="visible", timeout=15_000)
        await fila.click()
        for testid in (BENEF_NOMBRE, BENEF_APELLIDO1, BENEF_APELLIDO2):
            await page.get_by_test_id(testid).first.wait_for(
                state="visible", timeout=15_000)
        logger.info("[CP13] Formulario cargado — campos de beneficiario visibles.")
        return True
    except Exception as e:
        logger.warning("[CP13] No se pudo seleccionar el cliente: %s", str(e)[:120])
        return False


# ── Paso 4: seleccionar beneficiario y validar ───────────────────────────────
async def seleccionar_beneficiario_y_validar(page, nombre: str, apellido1: str,
                                             apellido2: str = "",
                                             intentos: int = 3) -> bool:
    """Abre el dropdown del beneficiario, elige la opción y valida los valores.

    Tolerante: intenta por texto exacto (nombre completo, como el original) y,
    si no aparece, cae a coincidencia por el nombre dentro del dropdown."""
    completo = " ".join(p for p in (nombre, apellido1, apellido2) if p).strip()
    logger.info("[CP13] Seleccionando beneficiario '%s'.", completo)

    for intento in range(1, intentos + 1):
        try:
            await page.get_by_test_id(BENEF_NOMBRE).first.click()
            await page.wait_for_timeout(1_000)

            contenedor = page.locator(BENEF_DROPDOWN)
            # 1) intento exacto por nombre completo.
            opcion = contenedor.get_by_text(completo, exact=True)
            try:
                await opcion.first.wait_for(state="visible", timeout=6_000)
            except Exception:
                # 2) fallback: parcial por el primer nombre (case-insensitive).
                logger.info("[CP13] Texto exacto no visible — probando parcial.")
                opcion = contenedor.get_by_text(
                    re.compile(re.escape(nombre), re.I))
                await opcion.first.wait_for(state="visible", timeout=6_000)

            await opcion.first.click()
            await page.wait_for_timeout(1_000)

            # Validación de valores en los campos.
            from playwright.async_api import expect
            await expect(page.get_by_test_id(BENEF_NOMBRE).first).to_have_value(
                nombre, timeout=10_000)
            await expect(page.get_by_test_id(BENEF_APELLIDO1).first).to_have_value(
                apellido1, timeout=10_000)
            if apellido2:
                await expect(page.get_by_test_id(BENEF_APELLIDO2).first).to_have_value(
                    apellido2, timeout=10_000)
            logger.info("[CP13] Beneficiario validado — %s.", completo)
            return True
        except Exception as e:
            logger.warning("[CP13] Selección de beneficiario falló "
                           "(intento %d/%d): %s", intento, intentos, str(e)[:120])
            await page.wait_for_timeout(2_000)
    return False
