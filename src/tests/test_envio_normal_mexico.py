"""
ENVÍOS NORMALES — MÉXICO (data-driven, UN TEST POR PAGADOR).

Reusa el flujo ESTABLE (HmTransferelektraPage) para CUALQUIER pagador activo
de src/pagadores/mexico/payers.json — sin grabar un script por pagador. Para
cada pagador activo se genera DINÁMICAMENTE su propio test:

    test_envio_normal_elektra, test_envio_normal_banorte, ...

Al pedir un pagador concreto, pytest ejecuta SOLO ese test (no monta el
navegador para los demás). El agente lo hace con `-k <pagador>`; para "todos
los pagadores" corre el archivo entero (sin -k).

ENFOQUE: automatización + auditoría + captura de errores. El objetivo es
EJERCITAR el flujo (llenar → elegir pagador → continuar/enviar). No se validan
cálculos. Si durante la corrida ocurre un error de backend (500), de consola o
una excepción JS, la fixture `logged_page` lo captura y vuelca un reporte de
diagnóstico (consola + HTTP con payload/respuesta/cURL) en reports/diag/.

El test PASA si el flujo corre sin excepción; los errores capturados quedan en
el reporte, no hacen fallar el test por sí solos.

Datos de cada envío: el PAGADOR es fijo (es lo que se rota), el PAÍS es el del
catálogo (MEXICo) y la CIUDAD DEL PAGADOR (payer_city) es fija. La ciudad/estado
del BENEFICIARIO se elige al azar del pool de México. El resto (nombre,
apellidos, teléfono, dirección, email, monto…) es aleatorio vía Faker, salvo
que la instrucción en lenguaje natural fije alguno (FLOW_OVERRIDES).

CÓMO CORRER:
    pytest src/tests/test_envio_normal_mexico.py -k banorte -v -s   # solo Banorte
    pytest src/tests/test_envio_normal_mexico.py -v -s              # todos los activos

CONTROLES (variables de entorno):
  FLOW_CANCEL=1      → cancela la transacción (default: no, queda activa).
  COMPLETAR_ENVIO=1  → completa el envío (default 1). 0 = solo llenar/elegir.
"""

import os
import random
import pytest
from playwright.async_api import Page

from config.logger import get_logger
from src.pages.hm_transferelektra_page import HmTransferelektraPage
from src.helpers.screenshot_helper import ScreenshotHelper
from src.helpers.datos import Datos
from src.pagadores import flujo_mt as F
from src.pagadores import catalogo as CAT

logger = get_logger("test_envio_normal_mexico")

PAYERS, CIUDADES = F.cargar_catalogo(modulo="mexico")

COMPLETAR = os.getenv("COMPLETAR_ENVIO", "1").strip().lower() in ("1", "true", "si", "yes")
CANCELAR = os.getenv("FLOW_CANCEL", "0").strip().lower() in ("1", "true", "si", "yes")
TIPO = os.getenv("FLOW_TYPE", "cash").strip().lower()   # cash|deposit|home|mobile|atm

EVIDENCE_FOLDER = "envio_normal_mexico"


def _evidence_dir():
    d = os.path.join(os.path.dirname(__file__), "..", "..", "reports", "evidence", EVIDENCE_FOLDER)
    os.makedirs(d, exist_ok=True)
    return d


async def _run_envio(logged_page, cfg):
    """Cuerpo común del envío normal para un pagador `cfg`.

    Ejercita el flujo completo. No valida cálculos: registra evidencia y deja
    que la fixture capture cualquier error (500/consola/JS) en el diagnóstico.
    """
    flow = HmTransferelektraPage(logged_page)
    datos = Datos()
    screenshot = ScreenshotHelper(logged_page)
    rng = random.Random()
    ev = lambda n: os.path.join(_evidence_dir(), n)

    pais, ciudad, estado = F.destino(cfg, CIUDADES, rng)
    logger.info(f"Envío normal · pagador={cfg['code']} · destino={ciudad}/{estado} ({pais})")

    # 1) Llenar cliente + beneficiario + tarifa + monto (llenado ROBUSTO de
    #    ai_agent) + seleccionar el TIPO de envío (tab). Cash llena su sub-form;
    #    los otros tipos dejan el tab seleccionado (campos pendientes de mapear).
    monto = await F.llenar_formulario_completo(flow, datos, cfg, pais, ciudad, estado,
                                               monto=int(float(datos.monto())), tipo=TIPO)

    # ── Banco de datos: DESCUBRIR y persistir qué tipos de envío ofrece este
    #    país (leyendo 'disabled-tab' del DOM). Así el catálogo crece solo y el
    #    agente podrá responder "¿tiene depósito <país>?" sin adivinar.
    try:
        disp = await flow.tipos_envio_disponibles()
        if disp:
            CAT.registrar_disponibilidad(pais, disp, pagador=cfg["code"])
            habilitados = [k for k, v in disp.items() if v]
            logger.info(f"[Catálogo] {pais}: tipos disponibles = {habilitados or 'ninguno'}")
    except Exception as e:
        logger.warning(f"[Catálogo] No se pudo registrar disponibilidad: {e}")

    # Los pasos siguientes (pagador, sucursal, envío, cancelación) usan los
    # data-testid del sub-formulario CASH. Para otros tipos, el tab ya quedó
    # seleccionado; se corta aquí hasta mapear sus campos (evita fallar con
    # selectores 'cash' que no aplican).
    if TIPO != "cash":
        logger.warning(f"[{cfg['code']}] Tipo '{TIPO}': tab seleccionado. El resto del "
                       f"flujo (pagador/envío/cancelación) está mapeado solo para Cash — "
                       f"pendiente de los data-testid de los campos de '{TIPO}'.")
        try:
            await screenshot.screenshot_only(screenshot_path=ev(f"tab_{TIPO}_{cfg['code']}.png"))
        except Exception:
            pass
        return

    # 2) Seleccionar el pagador (y sucursal si la app la exige) — CASH
    await F.seleccionar_pagador(flow, cfg, logger)

    # Evidencia del envío ya armado
    try:
        await screenshot.screenshot_only(screenshot_path=ev(f"armado_{cfg['code']}.png"))
    except Exception:
        pass

    # 3) Cerrar el flujo según configuración
    if CANCELAR:
        # Cancelar = ENVIAR primero y DESPUÉS cancelar en Reportes. Secuencia
        # portada del flujo grabado que funciona (test_HM_TransferElektra de
        # ai_agent): tras YES,Send hay que CERRAR el modal de éxito (NO), navegar
        # a Reportes > Transacciones (confirmando 'YES, Leave' al salir) y recién
        # ahí buscar la transacción y cancelarla. Sin esos pasos, la búsqueda se
        # queda en la pantalla de Transfers y se congela (bug anterior).
        cliente = datos.nombre_cliente()
        logger.info(f"Cancelación solicitada → enviar y luego cancelar (cliente '{cliente}').")
        try:
            # Enviar con el motor ROBUSTO: maneja el mensaje OFAC/compliance de
            # forma PERSISTENTE y BILINGÜE ('Back to Transfer'/'Regresar a Envío')
            # y cierra el modal de éxito con NO. Evita el cuelgue de ~90 s que
            # ocurría al esperar el botón 'YES, Send' cuando en realidad salía el
            # mensaje de OFAC (p.ej. beneficiario sancionado).
            enviado = await F.completar_envio(flow, completar=True, logger=logger)
            if not enviado:
                logger.warning(f"[{cfg['code']}] Envío no confirmado (posible OFAC "
                               f"persistente) — intento cancelar de todos modos.")
            try:
                await screenshot.screenshot_only(screenshot_path=ev(f"enviado_{cfg['code']}.png"))
            except Exception:
                pass
            # Navegar a Reportes > Transacciones
            await flow.click_reports()
            await flow.wait_for_no_blocking_overlays()
            await flow.click_transactions()
            await flow.wait_for_no_blocking_overlays()
            try:
                await flow.click_yes_leave()   # confirma salir de la pantalla
            except Exception:
                pass
            await flow.wait_for_no_blocking_overlays()
            # Buscar la transacción recién creada y cancelarla
            try:
                await flow.buscar_transaccion_por_nombre(cliente)
            except Exception:
                logger.info("Búsqueda por nombre no disponible — se cancela la más reciente.")
            await flow.cancelar_transaccion(reason_index=0, notes="Automation")
            logger.info(f"[{cfg['code']}] Transacción ENVIADA y luego CANCELADA.")
        except Exception as e:
            logger.warning(f"[{cfg['code']}] No se pudo completar la cancelación: {e}")
    elif COMPLETAR:
        enviado = await F.completar_envio(flow, completar=True, logger=logger,
                                          tipo_envio=TIPO)
        logger.info(f"[{cfg['code']}] Envío {'completado' if enviado else 'NO completado'}.")
    else:
        logger.info(f"[{cfg['code']}] COMPLETAR_ENVIO=0 — solo se llenó y eligió pagador.")

    # Evidencia final
    try:
        await screenshot.screenshot_only(screenshot_path=ev(f"fin_{cfg['code']}.png"))
    except Exception:
        pass
    logger.info(f"[{cfg['code']}] Envío normal (monto {monto}) finalizado.")


def _make_test(cfg):
    @pytest.mark.money_transfer
    @pytest.mark.asyncio
    async def _t(logged_page: Page):
        await _run_envio(logged_page, cfg)
    _t.__doc__ = f"Envío normal a {cfg['code']} — México (flujo estable parametrizado)."
    return _t


# ── Generar UN test por pagador activo: test_envio_normal_<code> ─────────────
for _cfg in PAYERS:
    _suf = _cfg["code"].lower().replace(" ", "_")
    globals()[f"test_envio_normal_{_suf}"] = _make_test(_cfg)
