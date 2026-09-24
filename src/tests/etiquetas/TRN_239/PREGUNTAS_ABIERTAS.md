# TRN-239 · Estado de la investigación

> Dueño del ticket: Sergio Ulises García Balandrán
> Actualizado: 11-sep-2026, tras cruzar los datos de PRODUCCIÓN contra TEST.

Sustituye a `BRIEF_v2_para_Skill_Codigo.md` y a
`docs/TRN-239_Brief_para_Skill_Codigo.md` (obsoleto: aún da por buena la URL
de Argo). **Ese se puede borrar.**

**Big C solo tiene acceso a Hermes, no a Zeus.** Resultó importar menos de lo
esperado: cuatro de las siete preguntas se contestaron **cruzando las dos
bases de datos**, y esa respuesta vale más que leer el código, porque compara
los dos mundos que la migración tiene que igualar.

---

## ✅ Resuelto

| Qué | Respuesta | Cómo |
|---|---|---|
| **URL base** | `https://zeus-services.maxilabs.net/api/v1/lunex/` | Argo daba 404 en todo Payments |
| **`IdAgent`** | **8918** (no 1242) | `ExternalID` real `M120312738S13491` ÷ 13491 |
| **Credenciales** | Correctas | MD5 malo da `4`; el nuestro no |
| **Esquema** | Correcto | Faltar campos da `5`; el nuestro no |
| **Errorcode 15** | `ExternalID` apuntando a un agente inexistente | Por eliminación |
| **VOID vs Cancelled** | **VOID** (IdStatus 22) | `Cancelled` no existe en 7 M de filas |
| **Comisión ITU** | `Commission = D1Discount`, siempre | 4 659 662 de 4 659 662 filas |
| **`CorpCommission` negativo** | **Normal**, no es defecto | ~5 % del histórico, en todos los tipos |
| **`Phone` vs `TopupPhone`** | **Distintos** en ITU/Pinless, **iguales** en DTU | Query 6 y Query 10, fila a fila |
| **`ExRate` / `AmountInMN`** | `AmountInMN = Amount × ExRate` al centavo; **NULL en DTU** | Query 10 |
| **Reparto agente/corporativo** | La **suma** es fija por SKU; el **reparto** lo decide `IdSchema` | Query 10 |

---

## 🔴 Hallazgos que hay que reportar

### 1. La fecha se guarda distinto que en el legacy

```
Producción (Urano)   TransactionDate ≈ DateOfCreation   desfase 0-1 h · 7 M filas
TEST (API migrada)   TransactionDate = DateOfCreation + 7 h
```

En producción **no hay desplazamiento horario**. La API nueva lo aplica. Es
una diferencia de datos entre legacy y migrado — exactamente lo que este
ticket existe para encontrar.

Ojo antes de escalarlo: nuestro cliente envía `TransactionDate` ya restado
8 h (`flujos/bodies.py::fecha_gmt8`), así que **parte del desfase puede ser
nuestro**. Los desfases negativos raros (−376, −6788) son cargas históricas de
2017 y 2021: ruido, no señal.

La Query 10 da el número exacto contra el que medir. Hoy, en producción:

```
DateOfCreation 2026-09-11 16:49:25.610
TransactionDate 2026-09-11 17:49:24.000     → +1 h, al segundo
```

Y cuadra con el reparto 0 h / 1 h de la Query 5: es el desfase de horario de
verano entre el reloj del servidor y el de quien envía. **El objetivo medible
es +1 h ahora, no +7 h.**

Además la cuenta cierra: si la API suma 8 h internamente —como dice el
requerimiento— y nosotros enviamos UTC−8, lo guardado sale en UTC, y el servidor
está en UTC−7. 0 + 7 = los 7 h que vemos. El experimento pendiente es **enviar
la hora local sin convertir y volver a medir**; si entonces sale +8 h, el que
sobra es el ajuste interno de la API.

### 2. Estados incoherentes en el histórico

| IdStatus | LNStatus | Filas |
|---|---|---|
| 30 | SUCCESS | 7 045 484 |
| 22 | **SUCCESS** | **12 510** ⚠ |
| 22 | VOID | 1 647 |
| 22 | **(vacío)** | **250** ⚠ |

**12 510 filas marcadas como canceladas (IdStatus 22) siguen diciendo
`SUCCESS`** — ocho veces más que las VOID correctas. Dos lecturas posibles y
hay que preguntar cuál es:

- Se canceló del lado de Maxi y Lunex reportó la recarga como exitosa: es un
  estado de negocio legítimo, y entonces la conciliación debe contemplarlo.
- Es una incoherencia de datos del legacy, y la migración no debe heredarla.

Y **250 filas con `LNStatus` vacío**. Sea cual sea la causa, la API nueva
tiene que decidir qué hace con esos casos.

### 3. La comisión DTU no cuadra en el 66 % de las filas

```
Commission = AgentCommission + CorpCommission
```

Se cumple al 100 % en ITU, Pinless, Unlimited, Egift y PinlessU.
En **DTU no cuadra en 1 236 793 de 1 871 512 filas**, con una diferencia
máxima de **4.50** — sospechosamente igual al `Fee` máximo (`FeeMedio` 2.49,
y DTU es el único tipo con Fee).

Ejemplos reales:

```
Metro PCS  Commission 1.76  Agent 0.70  Corp 1.06  Fee 4.00   → cuadra
Cricket    Commission 0.00  Agent 0.70  Corp 0.82  Fee 4.00   → NO cuadra
```

En los «fee based» el `Commission` se guarda en 0 y la comisión real vive en
`Agent + Corp`. **Es el punto más delicado de la migración y sigue sin
fórmula.**

### 4. Hay seis SKUType, no dos

`ITU · DTU · Pinless · Unlimited · Egift · PinlessU`

La etiqueta solo prueba **ITU y DTU**. `Pinless` mueve 492 158 transacciones
en producción y no se está probando. Hueco de cobertura.

### 5. `Phone` y `TopupPhone` no son el mismo campo

| SKUType | Distintos | Iguales |
|---|---|---|
| ITU | **4 656 668** | 2 994 |
| Pinless | 492 158 | 0 |
| DTU | 28 745 | **1 842 767** |

Uno es el teléfono del cliente y el otro el número que se recarga. **La
etiqueta mandaba el mismo número en los dos, siempre**, con lo que en ITU
reproducía un caso que ocurre en el 0.06 % de la producción: probaba la
excepción y no la regla. Corregido en `flujos/bodies.py::alta` — distintos en
ITU/Pinless/Unlimited, iguales en DTU.

### 6. El `TransactionID` **no es único** en producción

El `41695812` aparece **14 veces**, y varias de esas filas tienen dos estados
distintos entre sí. La unicidad no la garantiza la base.

Consecuencia directa: el CP08 daba por hecho que «exactamente una fila» era lo
correcto y marcaba FAIL si había dos. Eso era inventar un requisito. Ahora lo
reporta como **NO VERIFICADO** con la pregunta abierta C adjunta.

### 7. Un mismo SKU con varios nombres y varias monedas

- **24 SKU con más de un nombre.** El 8485 es «Honduras - PaqueTigo» y
  «Honduras - Paquetigo Super Recargas»; el 7963 tiene tres. Si la API nueva
  valida `SKUName` contra el catálogo, esas filas históricas no cuadran.
- **14 SKU con dos monedas distintas**, incluidos los de más volumen: 8456
  Guatemala Tigo Paqueton (984 696 filas) y 8485 (472 056).

### 8. En producción **no se cancela casi nada**, y nada falla

De los 100 SKU con más volumen (Query 1):

- `Fallidas = 0` en **todos**. El estado `FAILT` no aparece nunca en 7 M de
  filas. El **CP07 prueba un estado que la producción no produce** — no está
  mal probarlo, pero hay que saber que no tiene precedente real.
- `Canceladas = 0` en todos los ITU y DTU de alto volumen. Las cancelaciones
  se concentran en **Pinless** (1 564 en MEGA Minutos) y en los DTU **con
  PIN**, y casi todas son anteriores a 2023.

O sea que el CP03 cancela un ITU, que es justo lo que no se cancela en
producción. Vale la pena preguntarlo antes de dar por bueno el resultado.

---

## Lo que sigue abierto

### A. Fórmula de comisión DTU → **medio resuelta, falta el porqué**

La Query 10 avanzó bastante. Filas reales, mismo SKU, agentes distintos:

```
SKU 9511 Cricket   D1 1.50   Commission 0.00   Agent 0.70 + Corp 0.82 = 1.52   IdSchema 1305
SKU 9511 Cricket   D1 1.50   Commission 0.00   Agent 1.00 + Corp 0.52 = 1.52   IdSchema 1326
SKU 9851 MetroPCS  D1 1.76   Commission 0.00   Agent 0.84 + Corp 0.92 = 1.76   IdSchema 1317
SKU 9851 MetroPCS  D1 1.76   Commission 0.00   Agent 0.70 + Corp 1.06 = 1.76   IdSchema 1304
SKU 8510 Telcel    D1 3.50   Commission 3.50   Agent 0.50 + Corp 3.00 = 3.50   IdSchema 1230
SKU 8510 Telcel    D1 3.50   Commission 3.50   Agent 2.50 + Corp 1.00 = 3.50   IdSchema 1567
```

Se lee solo:

> **La suma `Agent + Corp` es constante para un SKU+monto. Lo que cambia entre
> agentes es el reparto, y lo decide el `IdSchema`.** En ITU esa suma se
> guarda además en `Commission`; en los DTU «fee based» `Commission` queda en
> **0** y la comisión real vive solo en el par agente/corporativo.

Eso explica la diferencia máxima de 4.50 de la Query 3: no es que la fórmula
falle en DTU, es que en DTU `Commission` **no participa**.

Lo que sigue haciendo falta de desarrollo:

- ¿Dónde vive la tabla de esquemas? `IdSchema` e `IdAgentPaymentSchema` no
  salen de nada que enviemos: los pone el back end.
- Cricket suma 1.52 con `D1Discount 1.50`: dos centavos de diferencia. ¿El
  `D1Discount` del cliente es indicativo y el importe bueno sale del esquema?
- ¿Coincide bit a bit con el legacy? ¿Dónde se redondea?

*Se aplica en:* `test_CP06_ComisionesDtuItu.py`, que hoy envía las tres
variantes y **no verifica el importe**. Con esto ya puede al menos comprobar
que `Agent + Corp` es igual para dos altas del mismo SKU y monto.

> ~~Revertir un cambio mío~~ — **hecho**. `trn239_happy_path.py` ya no mete el
> `Margin` en `CommissionPercentage`.

### B. Catálogo de errores → **casi cerrado (CP09 + Metis)**

Se provocan y salen bien: `2, 3, 4, 6, 7, 12` (exactos) y `1, 5` (tras el
ajuste de Metis: cuerpo crudo para el 1, TransactionDate malformado para el 5).
La raíz de por qué varios colapsaban: **la API resuelve el agente/esquema antes
que la validación de campos**, así que 8 y 10 caen en 10/15.

**Preguntas para DEV / Big C (Sergio):**

1. **Orden de validación** de `RegisterTransaction`, y si `SKUType` tiene un
   **catálogo global** y con qué valor se alcanza el **code 8** (hoy un SKUType
   raro cae en 10).
2. **Status=FAILT en Register**: ¿el requerimiento manda rechazarlo (code 9) o
   se preserva como legacy? ¿Qué hacía Urano? (CP07 lo deja como OK-a-investigar;
   el CP09 usa `Status='ZZZ'` para el 9 puro).
3. **ExternalID/Entity de un agente TEST real SIN esquema de comisión** para el
   **code 10** limpio (hoy un agente inexistente da 15). O los nombres de tabla
   para sacarlo por BD.
4. **Code 15**: qué entradas son «internas por diseño» vs. deberían ser un error
   controlado del catálogo (el 15 se usa como detector de errores no manejados).

### C. Duplicados e idempotencia

**Ya contestada a medias:** sí hay `TransactionID` repetidos en producción —
uno aparece 14 veces—, así que la unicidad no la garantiza la base. Lo que
falta es la regla de negocio: cuando llega un reenvío, ¿la API nueva debe
**rechazar, ignorar o insertar**?

*Se aplica en:* `test_CP08_IntegridadDatos.py`, que cuenta filas tras el
reenvío y ahora lo deja en NO VERIFICADO en vez de fallar.

### D. Mapeo campo → columna

Resuelto por observación salvo dos cosas:

- `CommissionPercentage` **no tiene columna**. Existen `Commission`,
  `AgentCommission` y `CorpCommission`. ¿Se descarta al recibirlo?
- `IdSchema` e `IdAgentPaymentSchema` los pone el back end y deciden el
  reparto de la comisión (ver A). `IdProductTransfer` sigue sin explicar.

`Status` se guarda en **`LNStatus`** — ya está en `flujos/bd.py::CANDIDATOS`.

### E. El `PIN` en DTU

En la Query 10, **todas** las filas DTU traen PIN y **ninguna** ITU lo trae.
La etiqueta manda `PIN: None` en las dos y no comprueba la respuesta. Si en
DTU el PIN es lo que el cliente se lleva —es dinero—, que la API migrada lo
devuelva es tan importante como el `Errorcode 0`, y hoy no se está mirando.

Falta confirmar si el PIN se envía o lo devuelve la API. Los datos no lo
distinguen: solo se ve la columna ya poblada.

---

## Las 10 consultas de producción: todas leídas

| Query | Qué contestó | Dónde quedó |
|---|---|---|
| 1 | Volumen por SKU · nadie falla · casi nadie cancela | Hallazgo 8 · catálogo `PRODUCTOS` |
| 2 | `Commission = D1Discount` en ITU · `CorpCommission` negativo es normal | Resuelto |
| 3 | La suma no cuadra solo en DTU, y por el `Fee` | Hallazgo 3 · pregunta A |
| 4 | 12 510 canceladas que dicen SUCCESS · 250 sin estado | Hallazgo 2 |
| 5 | Desfase horario legacy vs migrado | Hallazgo 1 |
| 6 | `Phone ≠ TopupPhone` según el tipo | Hallazgo 5 · **corregido en el código** |
| 7 | 24 SKU con varios nombres | Hallazgo 7 |
| 8 | 14 SKU con dos monedas | Hallazgo 7 |
| 9 | `TransactionID` no es único | Hallazgo 6 · **corregido el CP08** |
| 10 | Detalle fila a fila: monedas, tipos de cambio, esquemas, PIN | Pregunta A y E · **corregido `bodies.py`** |

---

## Método que está funcionando

No preguntar lo que se puede medir. Cuatro de siete preguntas se cerraron
cruzando `lunex.TransferLN` de producción contra la de TEST, sin acceso al
código de Zeus.

Lo que sí necesita a desarrollo es lo que **no está en los datos**: el
*porqué* de la fórmula DTU y el catálogo de errores que aún no hemos
provocado.
