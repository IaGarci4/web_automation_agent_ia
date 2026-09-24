"""
CP07 — Procesamiento de cheque individual (scan) + rechazo desde Chronos.
(Rescate de `HERMES2-qa/.../test_CP07_check_individual_scan.py`.)

Flujo (9 steps):
  1. Sesión con usuario mono-agencia (la da la fixture logged_page).
  2. Cheques > Cheques individuales.
  3. Escanear un cheque (el escáner es un EMULADOR ya disponible).
  4. Editar la información del cheque (número, fecha +1 día, monto).
  5. Procesar.
  6. Finalizar.
  7. Reportes > Transacciones: el cheque debe quedar en status 'Verify Hold'.
  8. Chronos > Processing > Edited Checks.
  9. Filtrar por agencia, abrir la transacción, verificar el Check Number en la
     pestaña Issuer y rechazarla con el motivo 'Other'.

La agencia y las URLs salen del ambiente activo (HERMES_ENV): 0040-OK en test,
0020-TX en producción.

COMO CORRER:
    pytest src/tests/sanity_general -k CP07 -v -s --headed
"""
import os
import pytest
from playwright.async_api import Page

from config.logger import get_logger
from config import settings
from src.pages.hm_transferelektra_page import HmTransferelektraPage
from src.helpers.screenshot_helper import ScreenshotHelper
from src.sanity_general import cheques as CH
from src.sanity_general import chronos as CR
from src.sanity_general import Evidencia

logger = get_logger("CP07")

# ── Datos del caso ──────────────────────────────────────────────────────────
CHECK_AMOUNT     = os.getenv("CP07_AMOUNT", "5.00")
EXPECTED_STATUS  = os.getenv("CP07_STATUS", "Verify Hold")
REJECT_REASON    = os.getenv("CP07_REJECT_REASON", "Other")
AGENCY_CODE      = os.getenv("CP07_AGENCY", settings.AGENCY_CODE)

# Sub-fases activables (para depurar solo Hermes o solo Chronos).
HACER_CHRONOS = os.getenv("CP07_CHRONOS", "1").strip().lower() in ("1", "true", "si", "yes")
# Si el cheque cae en OFAC Hold, Chronos NO permite rechazarlo (regla de
# negocio). Con CP07_TOLERAR_OFAC=1 el caso no se marca como fallo.
TOLERAR_OFAC = os.getenv("CP07_TOLERAR_OFAC", "0").strip().lower() in ("1", "true", "si", "yes")

EVIDENCE = "CP07_check_individual_scan"


@pytest.mark.sanity_general
@pytest.mark.chronos
@pytest.mark.asyncio
@pytest.mark.parametrize("language,width,height", [("English", 1366, 768)])
async def test_CP07_check_individual_scan(logged_page: Page, language, width, height):
    flow = HmTransferelektraPage(logged_page)
    screenshot = ScreenshotHelper(logged_page)
    evi = Evidencia(screenshot, EVIDENCE)
    await logged_page.evaluate("window.print = () => {};")

    numero = CH.generar_numero_cheque()
    logger.info("[CP07] Número de cheque de esta corrida: %s | agencia=%s",
                numero, AGENCY_CODE)

    # ── Step 1: sesión lista (la hace la fixture) ────────────────────────────
    await evi.shot("sesion_mono_agente")

    # ── Prerequisito: escáner configurado (Configuración > Dispositivos) ─────
    # Va ANTES de Cheques: sin escáner seleccionado, 'Scan Check' no abre el
    # modal de escaneo (Hermes incluso redirige a esta pantalla).
    escaner_ok = await CH.configurar_escaner(flow, evi=evi)
    if not escaner_ok:
        logger.warning("[CP07] No se pudo confirmar el escáner — el escaneo "
                       "puede fallar. Revisa Configuración > Dispositivos.")

    # ── Step 2: Cheques > Individuales ───────────────────────────────────────
    await CH.ir_a_cheques_individuales(flow)
    await evi.shot("pantalla_cheques_individuales")

    # ── Step 3: escanear (emulador) ──────────────────────────────────────────
    escaneado = await CH.escanear(flow)
    await evi.shot("cheque_escaneado")
    assert escaneado, ("El escaneo no expuso los campos del cheque "
                       "(¿está corriendo el emulador del escáner?).")

    # ── Step 4: editar los datos del cheque ──────────────────────────────────
    datos = await CH.llenar_datos(flow, numero, amount=CHECK_AMOUNT)
    await evi.shot("datos_cheque_editados", locators=[
        logged_page.get_by_test_id(CH.CHECK_NUMBER_INPUT).locator("visible=true").first,
        logged_page.get_by_test_id(CH.ISSUED_DATE_INPUT).locator("visible=true").first,
    ])

    # ── Steps 5–6: procesar y finalizar ──────────────────────────────────────
    await CH.procesar(flow)
    await evi.shot("cheque_procesado")
    await CH.finalizar(flow)
    await evi.shot("proceso_finalizado")

    # ── Step 7: Reportes > Transacciones en 'Verify Hold' ────────────────────
    await flow.click_reports()
    await flow.wait_for_no_blocking_overlays()
    await flow.click_transactions()
    await flow.wait_for_no_blocking_overlays()
    try:
        await flow.click_yes_leave()
    except Exception:
        pass
    await CH.buscar_cheques_desde(flow, CH.fecha_ayer())

    status, folio, fila = await CH.status_y_folio(flow, datos["check_number"])
    # Evidencia ANTES del assert: si el status no es el esperado, queda registrado.
    await evi.shot("reporte_verify_hold",
                   locators=[fila] if fila is not None else None)
    assert status == EXPECTED_STATUS, (
        f"Se esperaba el status '{EXPECTED_STATUS}' para el cheque "
        f"{datos['check_number']}, se obtuvo '{status}'.")
    logger.info("[CP07] Steps 1–7 OK — cheque %s en '%s' (folio %s).",
                datos["check_number"], status, folio)

    if not HACER_CHRONOS:
        logger.info("[CP07] CP07_CHRONOS=0 — Steps 8–9 omitidos.")
        return

    # ── Steps 8–9: Chronos > Processing > Edited Checks ──────────────────────
    chronos_page = await logged_page.context.new_page()
    try:
        # Reutiliza la sesión guardada; si expiró, hace el login por SSO SOLO
        # (mismo comportamiento que Hermes) y la vuelve a guardar.
        dentro = await CR.abrir_chronos(chronos_page)
        assert dentro, ("No se pudo entrar a Chronos (ni con la sesión guardada "
                        "ni con el login por SSO). Revisa CHRONOS_USER/"
                        "CHRONOS_PASS y la aprobación del 2FA en el celular.")

        assert await CR.ir_a_edited_checks(chronos_page), \
            "No se pudo abrir Chronos > Processing > Edited Checks."
        evi_chronos = Evidencia(ScreenshotHelper(chronos_page), EVIDENCE, start=evi.n)
        await evi_chronos.shot("chronos_edited_checks")

        await CR.buscar_agencia(chronos_page, AGENCY_CODE)
        await evi_chronos.shot("chronos_filtro_agencia")

        fila_ch = await CR.buscar_fila(
            chronos_page, amount=datos["amount"], agency_code=AGENCY_CODE,
            folio=folio, movement_date=CH.fecha_hoy())
        assert fila_ch is not None, (
            f"La transacción de ${datos['amount']} (folio {folio}) no aparece en "
            f"Edited Checks para la agencia {AGENCY_CODE}.")
        await evi_chronos.shot("chronos_transaccion", locators=[fila_ch])

        await CR.abrir_fila(chronos_page, fila_ch)
        check_number_issuer = await CR.leer_check_number_issuer(chronos_page)
        await evi_chronos.shot("chronos_issuer_check_number")
        assert check_number_issuer == datos["check_number"], (
            f"El Check Number de Issuer no coincide: se esperaba "
            f"'{datos['check_number']}' y Chronos muestra '{check_number_issuer}'.")

        rechazado, motivo = await CR.rechazar(chronos_page, reason=REJECT_REASON)
        await evi_chronos.shot("chronos_rechazo")
        if not rechazado and motivo.startswith("OFAC_HOLD"):
            # REGLA DE NEGOCIO de Chronos (no es un fallo de automatización):
            # una transacción en OFAC Hold no se puede rechazar hasta resolver
            # ese hold. Con CP07_TOLERAR_OFAC=1 el caso no se marca como fallo.
            logger.warning("[CP07] La transacción quedó en OFAC HOLD: Chronos no "
                           "permite rechazarla. %s", motivo)
            if TOLERAR_OFAC:
                logger.warning("[CP07] CP07_TOLERAR_OFAC=1 → se cierra el caso "
                               "hasta el rechazo (pendiente resolver el OFAC Hold).")
                return
            pytest.fail(
                "La transacción está en OFAC Hold y Chronos no permite "
                "rechazarla (regla de negocio). Resuelve el OFAC Hold primero, "
                "o usa datos del cheque que no disparen OFAC. "
                f"Detalle: {motivo}")
        assert rechazado, (f"No se pudo rechazar la transacción con motivo "
                           f"'{REJECT_REASON}'. Detalle: {motivo}")
        await CR.cerrar_modal_exito(chronos_page)
        await evi_chronos.shot("chronos_rechazo_confirmado")
        logger.info("[CP07] Steps 8–9 OK — cheque rechazado en Chronos ('%s').",
                    REJECT_REASON)
    finally:
        try:
            await chronos_page.close()
        except Exception:
            pass
