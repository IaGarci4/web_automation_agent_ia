# TRN-239 · Análisis de la 1ª ejecución (14-sep-2026)

> 12 altas + 1 cancelación en `MaxiTest`, capturadas por `EnterByIdUser = 13491`.
> Pregunta a responder: **los datos son distintos de producción (aleatorios),
> ¿pero son COHERENTES — sin inconsistencias internas?**

Respuesta corta: **sí, coherentes.** Todas las reglas que sacamos de los 7 M de
filas de producción se cumplen en nuestros registros. Hay **5 diferencias que
explicar**, ninguna es una inconsistencia de datos; cuatro son esperadas y una
(la fecha) es el hallazgo abierto de siempre.

---

## Lo que quedó registrado

| TxnID | SKU | Tipo | Phone / Topup | Amount | D1 | Comm | Agent | Corp | Fee | ExRate | Moneda | Estado |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ...995 | 8511 Telcel Internet | ITU | 6453…/4150… | 25 | 2.75 | 2.75 | 6.25 | **-3.50** | 0 | 1.00 | USD | SUCCESS/30 |
| ...994 | 8513 Cuba Cubacel-2 | ITU | 7986…/5882… | 25 | 2.75 | 2.75 | 2.25 | 0.50 | 0 | 1.00 | USD | SUCCESS/30 |
| ...993 | 8513 Cuba Cubacel-2 | ITU | 8464…/2633… | 25 | 2.75 | 2.75 | 2.25 | 0.50 | 0 | 1.00 | USD | **FAILT/30** |
| ...992 | 8383 Chile Entel | ITU | 3308…/3897… | 20 | 2.20 | 2.20 | 1.60 | 0.60 | 0 | 1.00 | USD | SUCCESS/30 |
| ...991 | 8383 Chile Entel | ITU | 8826…/7382… | 20 | 2.20 | 2.20 | 1.60 | 0.60 | 0 | 1.00 | USD | SUCCESS/30 |
| ...990 | 8377 Burundi Econet | ITU | 9921…/8371… | 25 | 0.00 | 0.00 | 2.00 | **-2.00** | 0 | 1.00 | USD | SUCCESS/30 |
| ...989 | 8552 Paquetigo | ITU | 2786…/8048… | 25 | 1.08 | 1.08 | 2.50 | **-1.42** | 0 | 1.00 | USD | SUCCESS/30 |
| ...988 | 9925 Go Smart | **DTU** | 7222…/**7222…** | 25 | 0.00 | 0.00 | 1.50 | -1.365 | **1.50** | NULL | NULL | SUCCESS/30 |
| ...983 | 7511 Anguilla Lime | ITU | 2583…/4298… | 25 | 2.75 | 2.75 | 2.00 | 0.75 | 0 | 1.00 | USD | **VOID/22** |
| ...982 | 8402 Kenya Orange | ITU | 5253…/4083… | 25 | 2.75 | 2.75 | 2.00 | 0.75 | 0 | 1.00 | USD | SUCCESS/30 |
| ...981 | 7921 Liberia Lonestar | ITU | 2441…/6733… | 25 | 2.75 | 2.75 | 2.00 | 0.75 | 0 | 1.00 | USD | SUCCESS/30 |
| ...980 | 7551 Bangladesh Bl. | ITU | 3044…/9297… | 25 | 2.75 | 2.75 | 2.00 | 0.75 | 0 | 1.00 | USD | SUCCESS/30 |

(Falta una 13ª alta — la previa SOAP del CP03, TxnID ...984 — que la API rechazó
con **Errorcode 15** y por eso no persistió. Ver punto 5.)

---

## Reglas de producción: TODAS se cumplen ✓

| # | Regla (de producción) | En nuestros datos | ✓ |
|---|---|---|---|
| 1 | **Phone ≠ TopupPhone en ITU** (99.94 %) | Los 11 ITU: distintos | ✓ |
| 2 | **Phone = TopupPhone en DTU** (98.5 %) | 9925 Go Smart: 7222703349 = 7222703349 | ✓ |
| 3 | **Commission = D1Discount en ITU** (100 %) | Los 11 ITU cuadran al centavo | ✓ |
| 4 | **Commission = Agent + Corp** (salvo DTU) | Los 11 ITU cuadran; 9925 DTU no (esperado) | ✓ |
| 5 | **DTU fee-based: Commission=0, Fee>0, sin ExRate** | 9925: Comm 0, Fee 1.50, ExRate NULL, Moneda NULL | ✓ |
| 6 | **CorpCommission negativo existe y es normal** | 4 filas negativas, todas cuadran en la suma | ✓ |
| 7 | **Alta = 30/SUCCESS, cancelación = 22/VOID** | 11 en 30, la cancelada en 22/VOID | ✓ |
| 8 | **Identidad del agente** (IdAgent 8918) | Las 12: 8918, ExternalID M120312738S13491 | ✓ |
| 9 | **AmountInMN = Amount × ExRate** | Todas: 25×1.00=25, 20×1.00=20 | ✓ |

La conclusión importante: **la migración no introdujo ninguna incoherencia en
los datos que sabemos leer.** Lo enviado y lo persistido concuerdan, y las
relaciones internas (comisión, reparto, moneda) respetan lo que hace el legacy.

---

## Las 5 diferencias que hay que explicar (no son defectos de datos)

### 1. 🔴 La fecha va +5 h (producción va +1 h) — hallazgo abierto

```
DateOfCreation  2026-09-14 13:12:40      (hora del servidor)
TransactionDate 2026-09-14 18:12:40      (+5 h)
```

En producción (Query 10) el desfase es **+1 h**. El nuestro es **+5 h**. La
diferencia sale de dos sumas que se encadenan:

- Nuestro cliente envía la fecha ya restada 8 h (`bodies.fecha_gmt8`).
- La API le suma 8 h internamente (según el requerimiento) → guarda en UTC (18:12).
- `DateOfCreation` es hora local del servidor (UTC-5) → 13:12.
- 18:12 − 13:12 = **5 h**, que es el offset del servidor, no un error de la API.

**Es parte nuestra.** El experimento pendiente sigue igual: enviar la hora local
sin pre-restar 8 h y volver a medir. Es la única de las cinco que puede terminar
en un cambio de código o en un ticket a DEV.

### 2. 🟡 Todos los ITU salieron en USD con ExRate 1.00

Producción tiene monedas reales por SKU (MXN, GTQ, HNL…). Aquí **todo salió
USD/1.00** porque el sorteo cayó en SKUs (Cuba, Chile, Burundi, Kenya, Liberia,
Bangladesh…) que **no están en `PERFIL_SKU`**, así que tomaron el perfil por
defecto ITU = USD/1.00.

No es una inconsistencia —`AmountInMN = Amount × 1.00` cuadra— pero **no podemos
confirmar** que USD sea la moneda real de esos SKUs, porque no salieron en la
muestra de producción. La API aceptó lo que le mandamos sin corregirlo.

Acción: si queremos monedas realistas, hay que ampliar `PERFIL_SKU`, o forzar el
sorteo a SKUs de alto volumen (los que sí tienen perfil).

### 3. 🟡 FAILT se guarda con IdStatus = 30 (igual que SUCCESS)

La fila 8513 con `LNStatus = FAILT` quedó con `IdStatus = 30` — **el mismo id
que un SUCCESS**. Se distinguen solo por el texto `LNStatus`, no por el id.

No se puede comparar contra producción porque allá **FAILT no existe** (Query 1:
`Fallidas = 0` en todos los SKU). Es decir, el CP07 prueba un estado que la
producción nunca genera, y la API lo mapea al id de éxito. Pregunta para DEV:
¿debería FAILT tener su propio IdStatus, o directamente no aceptarse?

### 4. 🟢 CorpCommission negativo más seguido que en producción

4 de 12 filas (33 %) tienen Corp negativo; en producción es ~5 %. No es
inconsistencia —todas cuadran en `Agent + Corp = Commission`— sino efecto de
haber sorteado SKUs raros de bajo volumen con esquemas de reparto distintos.
Con SKUs de alto volumen el porcentaje se parecería más al de producción.

### 5. 🟡 Una alta SOAP falló con Errorcode 15

La alta previa SOAP del CP03 (TxnID ...984) devolvió `Errorcode 15 · Internal
error`. Las otras 12 altas (incluida la SOAP del CP02) pasaron, así que **no es
sistemático ni específico de SOAP** — parece intermitente del lado de la API.
Vale la pena repetir para ver si reaparece; si es constante en algún SKU, es
ticket para DEV.

---

## Sobre las 12 altas y 1 sola cancelación

Es **el diseño actual**, no un error: cada caso da de alta para tener qué
probar, y solo el **CP03** cancela. El desglose:

| Caso | Altas que persisten | Cancela |
|---|---|---|
| CP02 (alta + paridad) | 3 | — |
| CP03 (cancelación) | 1 (+1 SOAP que falló) | **1** |
| CP06 (comisiones) | 5 | — |
| CP07 (FAILT vs SUCCESS) | 2 | — |
| CP08 (integridad) | 1 | — |
| **Total** | **12** | **1** |

La consecuencia real: **cada corrida deja 11 altas SUCCESS sin cancelar en
TEST.** Si eso te molesta (ensucia la tabla), hay dos caminos y cualquiera es
fácil de agregar:

- **Limpieza al final**: cancelar automáticamente las SUCCESS que dejó la
  corrida (usando el mismo `EnterByIdUser`). La tabla queda como estaba.
- **Solo happy path**: si lo que quieres es la prueba mínima 1 alta + 1
  cancelación, ese es `trn239_happy_path.py`, que hace exactamente eso.

Dime cuál prefieres y lo dejo listo.

---

## Correcciones aplicadas al reporte tras esta corrida

| Qué salía mal | Causa | Corregido |
|---|---|---|
| **CP01 FALLA** («no trae parts.database») | La API devuelve `details.database`, no `parts.database`; y el valor es `UP`, no `OK` | CP01 ahora lee las dos formas → **OK**, con anotación de requerimiento para DEV |
| **CP03 / CP07 «no se encontró la transacción»** | La API responde antes de persistir; la lectura llegaba muy pronto | `buscar_transaccion` reintenta 4× con 1 s (las filas SÍ estaban) |
| «Errorcode=None» en el healthcheck | El healthcheck no es transacción | CP01 muestra `version` y `ms`, no Errorcode |
| «Amount(Amount)», «SKU(SKU)» | Se imprimía campo+columna aunque fueran iguales | Solo se muestra la columna cuando difiere (`Status→LNStatus`) |

Con estos cambios, la próxima corrida debería salir **CP01 OK · CP03 OK ·
CP07 con la comparación FAILT/SUCCESS hecha**, y el veredicto global dejar de ser
FALLA por los dos falsos negativos.
