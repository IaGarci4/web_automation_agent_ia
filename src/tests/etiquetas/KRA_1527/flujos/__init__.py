"""
Flujos AISLADOS de la etiqueta KRA-1527.

## Por qué existe este paquete

Los módulos de `src/sanity_general` y `src/pagadores` los mueve el sanity todo el
tiempo: se ajusta un timeout para el CP11 y se cae el CP01. Esta etiqueta no
puede vivir con eso: es la evidencia de un hallazgo de pentest con severidad
Alta, y tiene que poder correrse tal cual dentro de seis meses.

Así que aquí hay **copias**, no imports. Un cambio en el sanity no puede romper
la etiqueta, y un ajuste que se haga aquí para atrapar al Hardware Agent no
puede romper el sanity.

| Módulo de la etiqueta | Copiado de |
|---|---|
| `base_page.py` | `src/pages/base_page.py` |
| `transferencia_page.py` | `src/pages/hm_transferelektra_page.py` |
| `locators.py` | `src/locators/hm_transferelektra_locators.py` |
| `mt.py` | `src/pagadores/flujo_mt.py` |
| `catalogo.py` | `src/pagadores/catalogo.py` |
| `deposito.py` | `src/sanity_general/deposit_slip.py` |
| `cheques.py` | `src/sanity_general/cheques.py` |
| `money_order.py` | `src/sanity_general/money_order.py` |
| `balance.py` | `src/sanity_general/balance.py` |
| `transacciones.py` | `src/sanity_general/cancelacion.py` |
| `info_adicional.py`, `cuestionario.py` | `src/sanity_general/…` |
| `firma_digital.py` | `src/sanity_general/firma_digital.py` |
| **`reimpresion.py`** | **propio de la etiqueta** (no existe en el sanity) |

**Lo único que se sigue compartiendo** es la infraestructura, que no es lógica
de flujo y romperla rompería el proyecto entero de todas formas:
`config/`, `src/helpers/` (sesión, screenshots, datos, auditoría, volcados).

Si un flujo del sanity mejora y conviene traer la mejora, se copia el archivo a
mano — deliberadamente, no por arrastre.

## Evidencias

`Evidencia` aquí escribe en `reports/evidence/KRA-1527/<CASO>/`, con el caso
nombrado como en QMetry (`CP01-EnvioMoneyTransfer`), no en la carpeta del
sanity.
"""

from config import settings

# Carpeta base de evidencias de la ETIQUETA (separada del sanity):
#   reports/evidence/KRA-1527/<CP0X-Nombre>/...
EVIDENCIAS_BASE = settings.EVIDENCE_DIR / "KRA-1527"


def evidencia_dir(caso: str):
    """Carpeta de evidencias del caso, creándola si no existe."""
    d = EVIDENCIAS_BASE / caso
    d.mkdir(parents=True, exist_ok=True)
    return d


def ev(caso: str, filename: str) -> str:
    """Ruta absoluta de un archivo de evidencia dentro de la carpeta del caso."""
    return str(evidencia_dir(caso) / filename)


class Evidencia:
    """Capturador de evidencias con numeración automática y secuencial.

    Misma API que la del sanity (`shot(nombre, paso=…)`), para que los módulos
    copiados sigan funcionando sin tocarlos, pero apuntando a la carpeta de la
    etiqueta.

        evi = Evidencia(ScreenshotHelper(page), "CP01-EnvioMoneyTransfer")
        await evi.shot("envio_armado", paso=1)
    """

    def __init__(self, screenshot, caso: str, start: int = 0):
        self.screenshot = screenshot        # ScreenshotHelper
        self.caso = caso
        self.cp = caso                      # alias: los módulos copiados usan .cp
        self.n = start

    async def shot(self, nombre: str, *, locators=None, search_text=None,
                   selector=None, paso: int = None) -> str:
        """Captura la siguiente evidencia. Con `locators` o `search_text`
        resalta en verde; si no, captura simple. Nunca lanza: una evidencia
        fallida no debe tumbar el caso que está probando el fix."""
        self.n += 1
        etiqueta = (f"Step{int(paso):02d}-{nombre}" if paso
                    else f"{self.n:02d}_{nombre}")
        path = ev(self.caso, f"{etiqueta}.png")
        try:
            if locators or search_text:
                await self.screenshot.screenshot_with_highlight(
                    path, locators=locators, search_text=search_text,
                    selector=selector)
            else:
                await self.screenshot.screenshot_only(path)
        except Exception:
            pass
        return path
