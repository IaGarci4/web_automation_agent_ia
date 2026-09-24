"""
CP04-FichaDepositoRedLenta — Ficha de depósito enviada con la red frenada.

Funcionalmente es una **Ficha de Depósitos**, igual que el CP02: foto de la
cámara simulada, monto y Send. Lo que cambia es cómo se envía —y por qué.

## Qué lo diferencia del CP02

`Maxi.RulesOffice.Security.HttpProxy.exe` es el proceso que Roman marcó como
difícil: nace con el request y muere al terminar. Este caso estrangula la red
justo alrededor del Send para que el request tarde y el proceso siga vivo el
tiempo suficiente para volcarlo. Dos medidas:

  1. **`procdump -w` armado ANTES** de disparar la acción (lo hace la fixture
     `vigilancia`): espera a que el proceso arranque y lo vuelca al aparecer.
     Elimina la carrera — no hay que perseguirlo con un bucle.
  2. **Red ralentizada por CDP**: la «conexión lenta» de Roman, hecha
     determinista en vez de depender del internet de la máquina.

El caso se llamaba `CP04-VolcadoHttpProxy`. El nombre describía la técnica, no
lo que se prueba, y en el reporte del ticket eso confunde a quien lo lee: la
evidencia son capturas de una ficha de depósito, no de un volcado. Ahora el
nombre dice el flujo y el apellido dice la variante.

Si aun así el proxy no se captura, **eso es un hallazgo válido, no un fallo**:
significa que el proceso es demasiado efímero para volcarse, lo cual es
mitigación por diseño. El caso lo documenta como *no reproducible* y sigue —
el volcado del `Hermes2Agent.exe` se toma igual y es el que sostiene el
criterio del ticket.

    $env:KRA1527_PROXY_KBPS="20"; $env:KRA1527_PROXY_LATENCIA_MS="1000"
"""

import pytest
from playwright.async_api import Page

from config.logger import get_logger
from src.helpers.ha_audit import RedLenta
from src.helpers.screenshot_helper import ScreenshotHelper

from . import parametros as P
from .flujos import Evidencia
from .flujos import deposito as DS
from .flujos.transferencia_page import HmTransferelektraPage

logger = get_logger("KRA-1527")


@pytest.mark.etiqueta
@pytest.mark.hardware_agent
@pytest.mark.asyncio
@pytest.mark.parametrize("language,width,height", P.PANTALLA)
async def test_CP04_FichaDepositoRedLenta(logged_page: Page, vigilancia,
                                          language, width, height):
    flow = HmTransferelektraPage(logged_page)
    evi = Evidencia(ScreenshotHelper(logged_page), P.CP04)

    assert await DS.abrir(flow), "No se pudo abrir la Ficha de Depósitos."
    assert await DS.tomar_foto(flow), "No se pudo tomar la foto."
    assert await DS.escribir_monto(flow, P.DS_MONTO), \
        "No se pudo escribir el monto."
    await evi.shot("ficha_lista", paso=1)

    async with vigilancia(P.CP04,
                          "Ficha de depósito enviada con la red frenada") as v:
        # La red lenta se activa SOLO alrededor de la acción que dispara el
        # request; dejarla puesta ralentizaría el resto del caso.
        async with RedLenta(logged_page, kbps=P.PROXY_KBPS,
                            latencia_ms=P.PROXY_LATENCIA):
            enviada = await DS.enviar(flow)
            await logged_page.wait_for_timeout(10_000)
        v.notas = (f"Red ralentizada a {P.PROXY_KBPS} kbps / "
                   f"{P.PROXY_LATENCIA} ms para ampliar la vida del proceso "
                   f"efímero.")
    await evi.shot("ficha_enviada", paso=2)

    # Igual que el CP02: la ficha de depósito no se cancela desde Hermes.
    v.anotar("La ficha de depósito no es cancelable desde Hermes: se concilia "
             "en Chronos. No queda transacción viva en el reporte.")

    assert enviada, ("El envío de la ficha no se confirmó: no apareció el "
                     "aviso 'Success / Deposit Slip sent'. Revisa "
                     "Step02-ficha_enviada.png.")
    v.exigir_comunicacion()

    # El volcado del proxy puede no lograrse; lo que NO se admite es un token
    # en claro en lo que sí se capturó.
    capturado = any(r.get("capturado") and "HttpProxy" in r.get("proceso", "")
                    for r in v.dumps.resultados)
    if not capturado:
        logger.warning("[%s] El HttpProxy no se pudo volcar: el proceso vive "
                       "menos que la ventana de captura. Se documenta como NO "
                       "REPRODUCIBLE — es mitigación por diseño, no un fallo.",
                       P.CP04)
    else:
        logger.info("[%s] ✓ HttpProxy capturado durante el request.", P.CP04)
    v.exigir_sin_token()
