"""
ANALIZER — reconocimiento de México (descubre y persiste el catálogo).

Corre UN envío de reconocimiento y registra en el banco de datos
(src/pagadores/catalogo_disponibilidad.json):
  - qué TIPOS de envío ofrece el país (cash/deposit/home/mobile/atm),
  - para Cash: las TARIFAS (fee types) y los PAGADORES disponibles.

CÓMO CORRER:
    pytest src/tests/test_analizar_mexico.py -v -s
    # o vía agente: "analiza los catálogos de méxico" / "analiza méxico"
"""
import random
import pytest
from playwright.async_api import Page

from config.logger import get_logger
from src.pages.hm_transferelektra_page import HmTransferelektraPage
from src.helpers.datos import Datos
from src.pagadores import flujo_mt as F
from src.pagadores import analizer as A

logger = get_logger("test_analizar_mexico")

PAYERS, CIUDADES = F.cargar_catalogo(modulo="mexico")


@pytest.mark.analisis
@pytest.mark.asyncio
async def test_analizar_mexico(logged_page: Page):
    """Analiza México: tipos disponibles + tarifas + pagadores (Cash)."""
    flow = HmTransferelektraPage(logged_page)
    datos = Datos()
    rng = random.Random()
    # Un pagador representativo solo sirve para llegar al formulario (payer_city).
    cfg = PAYERS[0] if PAYERS else {
        "code": "ELEKTRA", "country": "MEXICo", "search": "ELEKTRa",
        "row": "ELEKTRA DIRECTO", "payer_city": "GUADALAJARa",
    }
    pais, ciudad, estado = F.destino(cfg, CIUDADES, rng)
    logger.info(f"[Analizer] Analizando país={pais} (via {cfg['code']})...")
    res = await A.analizar(flow, datos, cfg, pais, ciudad, estado, logger)
    logger.info(f"[Analizer] Resumen: {res}")
