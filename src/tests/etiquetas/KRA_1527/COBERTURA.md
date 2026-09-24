# KRA-1527 · Cobertura de flujos del Hardware Agent

Inventario honesto de qué se cubre y qué no.
Guía de uso completa en [README.md](README.md).

---

## Los casos

| Caso | Flujo | Módulo (aislado en `flujos/`) | Limpieza |
|---|---|---|---|
| **CP01-EnvioMoneyTransfer** | Impresión de recibo de Money Transfer | `mt.py` | Cancela el envío |
| **CP02-FichaDeposito** | Impresión de ficha de depósito | `deposito.py` | No aplica |
| **CP03-EscaneoCheque** | Escaneo / procesamiento de cheque | `cheques.py` | Cancela el cheque |
| **CP04-FichaDepositoRedLenta** | Ficha de depósito enviada con la red frenada (para atrapar el HttpProxy) | `deposito.py` + `RedLenta` | No aplica |
| **CP05-ReimpresionRecibo** | Reimpresión de recibo (historial) | **`reimpresion.py`** | Nada que crear |

## Cobertura adicional

| Caso | Flujo | Por qué se incluye |
|---|---|---|
| **CP06-ImprimirBalanceCajero** | Imprimir reporte de balance por cajero | Otra ruta: un reporte, no un comprobante |
| **CP07-ImprimirMoneyOrder** | Imprimir un Money Order | Usa una impresora **distinta** («MO Printer») |

CP06 y CP07 nacieron de los CP12 y CP22 del sanity: mismo flujo probado, dos
usos — pero desde copias propias, no desde el sanity (ver el apartado de
aislamiento del README).

---

## Lo que se descartó

### Captura de firma digital — **fuera de la etiqueta**

Era el CP04 y se eliminó. No existe en **ningún** repositorio, el `test_CP04`
del sanity la marca pendiente (*Chronos Signature Hold*), y no se pudo
localizar en qué pantalla de la aplicación se captura. Mantener un caso que
solo podía hacer *skip* daba una falsa sensación de cobertura.

Si aparece el flujo, se agrega como CP08 (cobertura adicional) sin renumerar
nada. Y si se confirma que la firma **no pasa por el Hardware Agent**, la
etiqueta está completa sin ella: el criterio de aceptación es el token, no el
inventario de pantallas.

**La numeración se corrió** al quitarlo: CP05→CP04, CP06→CP05, CP07→CP06,
CP08→CP07. Y se corrió **una segunda vez** al eliminar la Inspección
Consolidada: CP07→CP06, CP08→CP07, CP09→CP08. Y una **tercera**, al sacar
el Control Negativo de la numeración —ahora es una compuerta del preflight,
no un caso—: CP07→CP06, CP08→CP07. Si QMetry conserva una numeración
anterior, hay que renumerar allí también.

Tras el tercer corrimiento **todos los CP son flujos reales de la
aplicación**: ninguno prueba la herramienta en vez del producto.

---

## Las seis rutas al agente que sí se cubren

El fix se valida en todas las familias de llamada al agente, que es lo que
importa — no en cada pantalla que existe:

| Familia | Caso |
|---|---|
| Impresión de comprobante de transacción | CP01 |
| Impresión de comprobante sin transacción (ficha) | CP02 · CP04 |
| Periférico de **entrada** (escáner) | CP03 |
| Reimpresión desde el historial (otro diálogo) | CP05 |
| Impresión de **reporte** | CP06 |
| **Segunda impresora** (MO Printer) | CP07 |

---

## Candidatos detectados, aún no automatizados

| Flujo | Estado | Nota |
|---|---|---|
| **Bill Payment con impresión** | `flujos/bill_payment.py` ya está copiado en la etiqueta, y `cancelaciones.cancelar_bill_payment` listo | Hoy el módulo **cancela** el error *«printer is not connected»*, y ese error prueba que **Hermes ya intenta imprimir solo** al pagar: la llamada al agente ocurre. El caso consiste en dejarla proceder. **Es el siguiente candidato.** |
| **Recargas (Top Ups)** | `recargas.py` existe en el sanity | El caso no completa la recarga a propósito (número real): sin completar no hay comprobante |
| **Pagos en Línea** | `pagos_linea.py` existe en el sanity | Falta confirmar si genera comprobante impreso |

Bill Payment sería una séptima variante de la primera familia, no una ruta
nueva. Vale agregarlo por completitud, no porque falte cobertura.

---

## Lo que puede invalidar la prueba

Tres reglas que separan esta suite del sanity. Si alguna se rompe, el resultado
es un **falso negativo** — verde sin haber probado nada:

- **No neutralizar `window.print`.** El sanity lo hace en todos sus tests.
- **Aceptar la impresión**, no declinarla.
- **Conservar los flags de Chromium** del `conftest` y correr con `PW_HEADLESS=0`.

Por eso cada caso llama a `exigir_comunicacion()` **antes** de dar un veredicto:
sin tráfico con el agente, el test falla en vez de aprobar en falso. Y por eso
el preflight distingue *«el agente no está corriendo»* (omitir: problema de
entorno) de *«el agente corre y no hubo tráfico»* (fallar: hallazgo real).
