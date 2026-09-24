"""
Módulo `sanity_general` — motor REUTILIZABLE para rescatar el sanity manual de
HERMES2-qa (CP01…CP22) hacia el agente de IA.

Filosofía (igual que `src/pagadores`):
  • El llenado del FORMULARIO PRINCIPAL se REUTILIZA de `src/pagadores/flujo_mt.py`
    (la lógica que ya llena bien un envío normal — no se reinventa).
  • Lo que aquí se construye es la capa ESTABLE que en el sanity manual era
    inestable: Información Adicional, Cuestionario/Compliance y la interacción
    con Chronos (KYC Hold, etc.).

Fuente de verdad de locators: docs/sanity_general/CP01_info_adicional_DOM.md
(capturado en vivo del ambiente TEST).
"""

from config import settings

# Carpeta base de evidencias del SANITY (separada del resto del agente):
#   reports/evidence/sanity_general/<CP>/...
EVIDENCIAS_BASE = settings.EVIDENCE_DIR / "sanity_general"


def evidencia_dir(cp: str):
    """Devuelve (creando si no existe) la carpeta de evidencias de un CP:
    reports/evidence/sanity_general/<cp>/"""
    d = EVIDENCIAS_BASE / cp
    d.mkdir(parents=True, exist_ok=True)
    return d


def ev(cp: str, filename: str) -> str:
    """Ruta absoluta de un archivo de evidencia dentro de la carpeta del CP.

    Uso en un test:
        from src.sanity_general import ev
        await screenshot.screenshot_only(ev("CP01_money_transfer_cash_kyc", "01.png"))
    """
    return str(evidencia_dir(cp) / filename)


class Evidencia:
    """Capturador de evidencias con NUMERACIÓN AUTOMÁTICA y secuencial.

    Fuente ÚNICA de captura para test y métodos: se crea en el test y se pasa a
    los módulos (completar_envio, cancelar_por_cliente, cancelar_bill_payment…).
    Cada `shot()` incrementa un contador y guarda `NN_<nombre>.png` en la carpeta
    del CP. Así la numeración queda secuencial SIN huecos, sin importar si la foto
    se dispara en el test o dentro de un método (estados transitorios).

    Uso:
        evi = Evidencia(screenshot, "CP01_money_transfer_cash_kyc")
        await evi.shot("cliente_beneficiario", locators=[...])
        await F.completar_envio(flow, ..., evi=evi)   # el método sigue numerando
    """

    def __init__(self, screenshot, cp: str, start: int = 0):
        self.screenshot = screenshot   # ScreenshotHelper
        self.cp = cp
        self.n = start

    async def shot(self, nombre: str, *, locators=None, search_text=None,
                   selector=None, paso: int = None) -> str:
        """Captura la siguiente evidencia. Con `locators` o `search_text` usa
        resaltado verde; si no, captura simple. No lanza.

        `paso`: número del paso del caso en QMetry. Si se indica, el archivo se
        nombra **StepPP-<nombre>.png** (ej. `Step02-cliente_beneficiario.png`).
        Así la integración con QMetry lo sube al paso correcto SIN mapeo, y
        varias imágenes pueden compartir el mismo paso.
        Sin `paso`, se conserva el formato `NN_<nombre>.png`."""
        self.n += 1
        etiqueta = (f"Step{int(paso):02d}-{nombre}" if paso
                    else f"{self.n:02d}_{nombre}")
        path = ev(self.cp, f"{etiqueta}.png")
        try:
            if locators or search_text:
                await self.screenshot.screenshot_with_highlight(
                    path, locators=locators, search_text=search_text, selector=selector)
            else:
                await self.screenshot.screenshot_only(path)
        except Exception:
            pass
        return path

