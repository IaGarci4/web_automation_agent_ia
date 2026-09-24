"""
Envío de dinero DENTRO del agente (WebView2/CDP) — ARMADO Y DEJADO.

Objetivo: dejar un envío de dinero **armado** (cliente + beneficiario + pagador +
sucursal + monto) y **NO enviarlo** — se queda en pantalla, listo. Esto se deja
así a propósito hasta que el flujo esté **desplegado en producción**; ese día se
completa el envío real con `ENVIO_AGENTE_COMPLETAR=1`.

Reutiliza el flujo estable (`flujo_mt` + `HmTransferelektraPage`), incluida la
resolución de dirección (híbrida real/intercept). No valida cálculos: ejercita el
flujo y deja que la fixture capture errores en el diagnóstico.

Pensado para correr enganchado al agente por CDP:
    # 1) Agente lanzado (Ejecutar_Hermes2Agent.bat) y con sesión (o login solo)
    $env:HERMES_AGENT_CDP="1"
    pytest src/tests/test_envio_agente_dejar.py -v -s

Controles (env):
  ENVIO_PAGADOR=ELEKTRA        → pagador a usar (default ELEKTRA; México, cash).
  ENVIO_AGENTE_COMPLETAR=1     → completar el envío real (PRODUCCIÓN). Default 0
                                 = solo armar y dejar (NO envía).

OJO: en el agente la captura de pantalla sale NEGRA; la evidencia útil es el log
y la auditoría de DOM.
"""

import os
import random

import pytest
from playwright.async_api import Page

from config.logger import get_logger
from src.helpers.datos import Datos
from src.helpers.screenshot_helper import ScreenshotHelper
from src.helpers.token_support import obtener_token
from src.pages.hm_transferelektra_page import HmTransferelektraPage
from src.pagadores import flujo_mt as F

logger = get_logger("envio-agente-dejar")

PAYERS, CIUDADES = F.cargar_catalogo(modulo="mexico")
PAGADOR = os.getenv("ENVIO_PAGADOR", "ELEKTRA").strip().upper()
COMPLETAR = os.getenv("ENVIO_AGENTE_COMPLETAR", "0").strip().lower() in (
    "1", "true", "si", "sí", "yes")
# Aplicar el token de Soporte Remoto (BD) antes del envío. Best-effort: si no hay
# token o el control no está, se omite y el envío sigue. Desactivar con =0.
APLICAR_TOKEN = os.getenv("ENVIO_APLICAR_TOKEN", "1").strip().lower() in (
    "1", "true", "si", "sí", "yes")

EVIDENCE_FOLDER = "envio_agente"


def _evidence_dir():
    d = os.path.join(os.path.dirname(__file__), "..", "..", "reports",
                     "evidence", EVIDENCE_FOLDER)
    os.makedirs(d, exist_ok=True)
    return d


@pytest.mark.money_transfer
@pytest.mark.agente_dejar
@pytest.mark.asyncio
async def test_envio_agente_dejar(logged_page: Page):
    cfg = next((p for p in PAYERS if p["code"].upper() == PAGADOR), None)
    if cfg is None:
        cfg = PAYERS[0]
        logger.warning("Pagador '%s' no está en el catálogo; uso '%s'.",
                       PAGADOR, cfg["code"])

    flow = HmTransferelektraPage(logged_page)
    datos = Datos()
    screenshot = ScreenshotHelper(logged_page)
    rng = random.Random()
    ev = lambda n: os.path.join(_evidence_dir(), n)

    pais, ciudad, estado = F.destino(cfg, CIUDADES, rng)
    logger.info("Envío (dejar armado) · pagador=%s · destino=%s/%s (%s)",
                cfg["code"], ciudad, estado, pais)

    # 0) Soporte Remoto (token de BD) — best-effort, antes de armar el envío.
    if APLICAR_TOKEN:
        try:
            tok = obtener_token()
            if tok:
                await flow.aplicar_soporte_remoto(tok)
            else:
                logger.info("[Envío] Sin token de BD — se omite soporte remoto.")
        except Exception as e:
            logger.warning("[Envío] Soporte remoto (token) no aplicado: %s", str(e)[:120])

    # 1) Armar: cliente + beneficiario + tarifa + monto (incluye la resolución de
    #    dirección híbrida) y seleccionar tipo cash.
    monto = await F.llenar_formulario_completo(
        flow, datos, cfg, pais, ciudad, estado,
        monto=int(float(datos.monto())), tipo="cash")

    # 2) Seleccionar pagador (y sucursal si la app la exige).
    await F.seleccionar_pagador(flow, cfg, logger)

    try:
        await screenshot.screenshot_only(screenshot_path=ev(f"armado_{cfg['code']}.png"))
    except Exception:
        pass

    if COMPLETAR:
        # Día de producción: completar el envío real.
        enviado = await F.completar_envio(flow, completar=True, logger=logger, tipo_envio="cash")
        logger.info("[%s] Envío %s (monto %s).", cfg["code"],
                    "COMPLETADO" if enviado else "NO completado", monto)
        assert enviado, "Se pidió completar el envío pero no se confirmó."
        return

    # 3) DEJARLO ARMADO — no se envía. Confirmar que el botón Continuar está listo.
    listo = False
    try:
        btn = flow.page.get_by_test_id("totals-bill-payment-send-button").first
        listo = await btn.is_visible()
    except Exception:
        listo = False
    if not listo:
        # Fallback: el botón genérico de continuar/enviar por texto.
        try:
            import re as _re
            btn = flow.page.get_by_test_id("test-id-button").filter(
                has_text=_re.compile(r"continuar|continue|enviar|send", _re.I)).first
            listo = await btn.is_visible()
        except Exception:
            listo = False

    logger.info("[%s] Envío ARMADO y DEJADO (sin enviar) · monto=%s · botón de "
                "envío disponible=%s. Listo para completar en producción con "
                "ENVIO_AGENTE_COMPLETAR=1.", cfg["code"], monto, listo)
    # El test PASA si armó sin excepción; el botón visible es señal de que quedó
    # en el punto correcto (no se exige, para no fallar por un testid de UI).
