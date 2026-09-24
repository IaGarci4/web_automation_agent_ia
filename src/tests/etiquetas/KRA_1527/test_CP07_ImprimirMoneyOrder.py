"""
CP10-ImprimirMoneyOrder — COBERTURA ADICIONAL (fuera de la tabla de QMetry).

Money Order completo, con la vigilancia SOLO sobre la impresión.

Los money orders tienen su **propia impresora** («MO Printer» en Configuración
> Dispositivos), así que es una ruta distinta a la del recibo del CP01 y hay
que probarla aparte.

Reutiliza el módulo del CP22 del sanity, copiado en `flujos/money_order.py`.
Al final ANULA los money orders creados: no dejar basura en Open es parte del
caso.
"""

import pytest
from playwright.async_api import Page

from config.logger import get_logger
from src.helpers.screenshot_helper import ScreenshotHelper

from . import parametros as P
from .flujos import Evidencia
from .flujos import money_order as MO

logger = get_logger("KRA-1527")


@pytest.mark.etiqueta
@pytest.mark.hardware_agent
@pytest.mark.asyncio
@pytest.mark.parametrize("language,width,height", P.PANTALLA)
async def test_CP07_ImprimirMoneyOrder(logged_page: Page, vigilancia,
                                       language, width, height):
    from faker import Faker as _Faker
    fake = _Faker()
    evi = Evidencia(ScreenshotHelper(logged_page), P.CP07)

    nombre, ap1 = fake.first_name().upper(), fake.last_name().upper()
    cliente = {
        "telefono": fake.numerify("555010####"), "nombre": nombre,
        "apellido1": ap1, "apellido2": fake.last_name().upper(),
        "pay_to": f"{nombre} {ap1}", "num_id": fake.numerify("#########"),
        "tax_id": fake.numerify("478######"),
        "direccion": fake.street_address().upper(),
        "razon": fake.sentence(nb_words=4),
    }
    logger.info("[%s] Money Order de %s %s por $%s", P.CP07, nombre, ap1,
                P.MO_MONTO)

    # ── Preparación: NO se audita, es el armado del caso ────────────────────
    #
    # Aquí hubo un prerequisito que comprobaba `Get-Printer` y OMITÍA el caso
    # si «S SATO WS412-DT_sim» no estaba entre las impresoras de Windows. Se
    # quitó porque partía de una premisa falsa.
    #
    # El SATO no es una impresora del SPOOLER: es un periférico USB/IP al que
    # el Hardware Agent le habla directo en SBPL (SATO Barcode Printer
    # Language). Nunca aparece en `Get-Printer`, y aun así imprime — está
    # comprobado con el simulador renderizando Money Orders reales. La
    # comprobación miraba la cola de impresión, que es otra cosa, y acabó
    # omitiendo un caso perfectamente ejecutable.
    #
    # Quien sí sabe qué dispositivos hay es el propio agente, y su lista es la
    # que llena el combo de Configuración > Dispositivos. Así que se le
    # pregunta a la pantalla, y `seleccionar_impresora` ya distingue las tres
    # respuestas posibles: el combo no abrió, abrió vacío, o abrió con otras.
    assert await MO.preparar_impresora(logged_page), \
        "No se pudo preparar la impresora de Money Orders."
    assert await MO.abrir_money_order(logged_page), \
        "No se pudo abrir Services > Money Order."
    assert await MO.llenar_comprador(
        logged_page, cliente["telefono"], cliente["nombre"],
        cliente["apellido1"], cliente["apellido2"]), "Comprador no llenado."
    assert await MO.agregar_money_order(logged_page, cliente["pay_to"],
                                        P.MO_MONTO), \
        "No se pudo agregar el Money Order."
    if await MO.abrir_additional_info(logged_page):
        assert await MO.llenar_additional_info(
            logged_page, cliente["num_id"], cliente["tax_id"],
            cliente["direccion"], cliente["razon"]), \
            "No se pudo completar la Información Adicional."
    serie = await MO.numero_de_serie(logged_page)
    assert serie, "No se pudo leer el número de serie del Money Order."
    await evi.shot("money_order_listo", paso=1)

    # ── Lo auditado: SOLO la impresión ──────────────────────────────────────
    async with vigilancia(P.CP07, "Imprimir un Money Order") as v:
        v.notas = (f"Money Order #{serie} por ${P.MO_MONTO}. Impresora "
                   f"«{MO.IMPRESORA_MO}» (los MO usan una impresora distinta a "
                   f"la del recibo del CP01).")
        impreso = await MO.imprimir(logged_page, serie, evi=evi)
        await logged_page.wait_for_timeout(6_000)
    await evi.shot("money_order_impreso", paso=2)

    # ── Limpieza ANTES del veredicto ────────────────────────────────────────
    # Los money orders se INVALIDAN (Void) desde su propio reporte, no se
    # cancelan desde Transacciones. Va antes de los asserts: si el veredicto
    # falla, los MO se quedarían en Open y descuadran el balance del agente.
    if P.MO_ANULAR and P.CANCELAR:
        if await MO.ir_a_reportes_money_order(logged_page):
            await MO.buscar(logged_page)
            anulados = await MO.anular_money_orders(
                logged_page, cliente["apellido1"], maximo=P.MO_ESPERADOS,
                evi=evi)
            logger.info("[%s] %d money order(s) anulado(s).", P.CP07, anulados)
            v.anotar(f"Limpieza: {anulados} money order(s) invalidado(s).")
            if not anulados:
                logger.warning("[%s] ⚠ Quedaron money orders en Open para "
                               "'%s'.", P.CP07, cliente["apellido1"])

    assert impreso, f"No se pudo imprimir el Money Order #{serie}."
    v.exigir_comunicacion()
    v.exigir_sin_token()
