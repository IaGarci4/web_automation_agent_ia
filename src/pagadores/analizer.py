"""
Analizer — reconocimiento de un país: descubre qué OFRECE y lo persiste.

Corre un envío "de reconocimiento" (aunque tarde) y, para el país dado:
  1) Llena el formulario común hasta la sección Transfer (reutiliza el flujo
     estable de flujo_mt).
  2) Lee del DOM los TIPOS de envío disponibles (clase 'disabled-tab') → catálogo.
  3) Para CASH (único tipo con sub-formulario mapeado hoy): descubre las TARIFAS
     (fee types) y la lista de PAGADORES → catálogo.
  4) Anota qué tipos usan SUCURSAL (branch) según el backend (cash/deposit/atm).
     En el envío real, cuando el pagador la exige, la sucursal se elige
     ALEATORIA (flujo_mt.seleccionar_sucursal_si_aplica) — aquí no se fija.

Los tipos NO-Cash quedan registrados a nivel de disponibilidad; sus pagadores y
tarifas se agregarán cuando se mapeen sus sub-formularios
(ver docs/CONSULTA_CODIGO_SUBFORMULARIOS.md). El banco de datos vive en
src/pagadores/catalogo_disponibilidad.json y CRECE con cada análisis.
"""
from src.pagadores import flujo_mt as F
from src.pagadores import catalogo as CAT


async def analizar(flow, datos, cfg, pais, ciudad, estado, logger=None) -> dict:
    """Analiza un país y persiste lo descubierto. Devuelve un resumen dict."""
    resultado = {"pais": pais, "tipos_disponibles": {}, "cash": {}}

    # 1) Llenar común + sub-formulario CASH (ciudad/tarifa/monto). Esto deja la
    #    sección Transfer lista para leer tipos, tarifas y pagadores.
    await F.llenar_formulario_completo(
        flow, datos, cfg, pais, ciudad, estado, monto=100, tipo="cash")

    # 2) TIPOS disponibles (leídos del DOM: 'disabled-tab')
    disp = await flow.tipos_envio_disponibles()
    resultado["tipos_disponibles"] = disp
    CAT.registrar_disponibilidad(pais, disp, pagador=cfg.get("code"))
    if logger:
        hab = [k for k, v in (disp or {}).items() if v]
        logger.info(f"[Analizer] {pais} → tipos disponibles: {hab or 'ninguno'}")

    # 3) CASH: tarifas + pagadores (solo si cash está disponible)
    if (disp or {}).get("cash"):
        try:
            fee_types = await flow.listar_fee_types()
        except Exception:
            fee_types = []
        try:
            payers = await flow.listar_pagadores_disponibles()
        except Exception:
            payers = []
        CAT.registrar_detalle(pais, "cash", fee_types=fee_types, payers=payers)
        resultado["cash"] = {"fee_types": fee_types, "payers": payers}
        if logger:
            logger.info(f"[Analizer] {pais} cash → {len(fee_types)} tarifa(s), "
                        f"{len(payers)} pagador(es). Tarifas: {fee_types}")
    else:
        if logger:
            logger.info(f"[Analizer] {pais}: cash NO disponible — se omite detalle de cash.")

    ruta = CAT._CATALOGO
    if logger:
        logger.info(f"[Analizer] Banco de datos actualizado → {ruta}")
    resultado["catalogo"] = str(ruta)
    return resultado
