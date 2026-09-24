"""
Chronos — Agents > Agent y Processing > Fax Assignment (CP11).

Dos usos en el caso del fax:
  1. ANTES del envío: abrir la ficha de la agencia y comprobar que tiene el
     número de FAX configurado. Si no lo tiene, el resto del caso no tiene
     sentido, así que conviene fallar aquí con un mensaje claro.
  2. DESPUÉS de mandar el fax desde Hermes: comprobar que el registro apareció
     en Processing > Fax Assignment.

Chronos no usa data-testid: todo va por CSS/XPath e índices de columna.
"""

import re

from config import settings
from config.logger import get_logger
from src.sanity_general import chronos as CR
from src.sanity_general.chronos_cobranza import limpiar_modales

logger = get_logger("sanity.chronos.agentes")

TIMEOUT = 120_000

# ── Menú ────────────────────────────────────────────────────────────────────
AGENTS_OPTION = "//mat-panel-title[contains(text(),'Agents')]"
AGENT_SUB = "//div[normalize-space()='Agent']"
PROCESSING_OPTION = "//mat-panel-title[contains(text(),'Processing')]"
RE_FAX_ASSIGNMENT = re.compile(r"fax\s*assignment", re.I)

# ── Ficha del agente ────────────────────────────────────────────────────────
BUSCADOR = ".form-control"
# El FAX es el 2º input con máscara del grupo (el 1º es el teléfono).
FAX_INPUTS = "div.input-group > p-inputmask.form-control > input.ui-inputtext"
IDX_FAX = 1

# ── Tabla de Fax Assignment ─────────────────────────────────────────────────
PRIMERA_FILA = "//tbody/tr[1]/td[2]"


def fax_esperado() -> str:
    """Número de fax que debe tener la agencia, según el ambiente."""
    return settings.AGENCY_FAX


def _solo_digitos(texto: str) -> str:
    return "".join(c for c in (texto or "") if c.isdigit())


async def ir_a_agente(page, agency_code: str = None) -> bool:
    """Menu → Agents → Agent → buscar la agencia y abrir su ficha."""
    codigo = agency_code or settings.AGENCY_CODE
    try:
        await limpiar_modales(page)
        await CR._click_listo(page, page.locator(CR.TOOLBAR_MENU).first,
                              "Menu abierto", timeout=TIMEOUT)
        await page.wait_for_timeout(800)
        await CR._click_listo(page, page.locator(AGENTS_OPTION).first,
                              "Agents", timeout=TIMEOUT)
        await page.wait_for_timeout(800)
        await CR._click_listo(page, page.locator(AGENT_SUB).first,
                              "Agent (submenú)", timeout=TIMEOUT)
        await page.wait_for_timeout(1_500)

        buscador = page.locator(BUSCADOR).first
        await buscador.wait_for(state="visible", timeout=TIMEOUT)
        await buscador.click()
        await buscador.fill(codigo)
        await page.wait_for_timeout(3_500)

        fila = page.locator(f'td:has-text("{codigo}")').first
        await fila.wait_for(state="visible", timeout=TIMEOUT)
        await CR._click_listo(page, fila, f"Ficha de {codigo} abierta",
                              timeout=TIMEOUT)
        await page.wait_for_timeout(6_000)      # la ficha carga lento
        return True
    except Exception as e:
        logger.warning("[Agentes] No se pudo abrir la agencia %s: %s",
                       codigo, str(e)[:110])
        return False


async def leer_fax(page):
    """Devuelve (valor_del_campo, locator) del FAX de la ficha abierta."""
    try:
        campo = page.locator(FAX_INPUTS).nth(IDX_FAX)
        await campo.wait_for(state="visible", timeout=30_000)
        valor = (await campo.input_value() or "").strip()
        return valor, campo
    except Exception as e:
        logger.warning("[Agentes] No se pudo leer el FAX: %s", str(e)[:90])
        return "", None


async def validar_fax(page, esperado: str = None):
    """Comprueba el FAX de la agencia. Devuelve (ok, valor_leido, locator).

    Compara SOLO los dígitos: la máscara puede mostrar '(469) 729-3817' o
    '4697293817' según cómo se guardó, y ambos son el mismo número."""
    objetivo = esperado or fax_esperado()
    valor, campo = await leer_fax(page)
    ok = bool(valor) and _solo_digitos(valor) == _solo_digitos(objetivo)
    if ok:
        logger.info("[Agentes] ✓ FAX configurado: %s", valor)
    else:
        logger.warning("[Agentes] FAX distinto del esperado — leído '%s', "
                       "esperado '%s'.", valor or "(vacío)", objetivo)
    return ok, valor, campo


async def ir_a_fax_assignment(page) -> bool:
    """Menu → Processing → Fax Assignment."""
    try:
        await limpiar_modales(page)
        await CR._click_listo(page, page.locator(CR.TOOLBAR_MENU).first,
                              "Menu abierto", timeout=TIMEOUT)
        await page.wait_for_timeout(800)
        await CR._click_listo(page, page.locator(PROCESSING_OPTION).first,
                              "Processing", timeout=TIMEOUT)
        await page.wait_for_timeout(800)
        enlace = page.get_by_role("link", name=RE_FAX_ASSIGNMENT).first
        await enlace.wait_for(state="visible", timeout=30_000)
        await CR._click_listo(page, enlace, "Fax Assignment", timeout=TIMEOUT)
        await page.wait_for_timeout(6_000)      # la tabla tarda en poblarse
        return True
    except Exception as e:
        logger.warning("[Fax] No se pudo abrir Fax Assignment: %s", str(e)[:110])
        return False


async def hay_registro_de_fax(page, timeout_ms: int = 30_000):
    """Espera a que la tabla de Fax Assignment tenga al menos un registro.

    Devuelve (ok, locator_de_la_primera_celda) para poder resaltarlo en la
    evidencia."""
    celda = page.locator(PRIMERA_FILA).first
    espera = 0
    while espera <= timeout_ms:
        try:
            if await celda.is_visible():
                texto = (await celda.inner_text() or "").strip()
                logger.info("[Fax] ✓ Registro en Fax Assignment: '%s'", texto[:60])
                return True, celda
        except Exception:
            pass
        await page.wait_for_timeout(500)
        espera += 500
    logger.warning("[Fax] La tabla de Fax Assignment quedó vacía tras %.0f s.",
                   timeout_ms / 1000)
    return False, None
