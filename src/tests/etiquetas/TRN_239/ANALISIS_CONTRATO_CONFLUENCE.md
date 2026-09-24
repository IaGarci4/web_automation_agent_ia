# TRN-239 · Requerimiento oficial vs implementación vs producción

> Fuente: **Lunex Notifications API — Integration Guide** (Confluence, por Sergio
> Ulises García Balandrán, act. 19-ago-2026). Leída directamente.
> Cruzada contra el código de la etiqueta y contra los 7 M de filas de prod.

## Lo primero, porque cambia cómo se lee todo: qué ES esta API

> «The Lunex Notifications API allows **Lunex to notify Maxi** about transaction
> lifecycle events. RegisterTransaction: *Notifies Maxi that a top-up
> transaction was executed*.»

**La API no ejecuta recargas. Las notifica.** En producción, quien llama es
**Lunex** (el proveedor), y Maxi es quien **recibe** y registra. Nuestro script
hace de Lunex: manda notificaciones a la API migrada de Maxi.

Consecuencia directa para tu preocupación: **nuestras altas de prueba NO
disparan recargas reales.** Registran una notificación en `lunex.TransferLN`.
Los teléfonos aleatorios son solo carga del mensaje, no números que se recarguen.

Y el propio documento define el ambiente:

| Ambiente | Base URL |
|---|---|
| **Development / Testing** | `https://zeus-services.maxilabs.net/api/v1/lunex/Payments/` |
| Production | *To define* |

O sea que `zeus-services` **es** el ambiente de pruebas de la API de
notificaciones («test credentials and test agent mappings»). Lo que no tiene
ambiente de pruebas es la ejecución real de la recarga (lado Lunex/Megarecargas)
— pero eso no lo tocamos nosotros. **Conviene que lo confirmes**, porque tú
mencionaste que no hay ambiente de test; puede que te refirieras al lado de la
recarga, no al de la notificación.

---

## Hallazgos que ya cambié en el código

### 1. Cancelación: el requerimiento manda `Status: "Cancelled"`, no `"VOID"`

> CancelTransaction · Status · **"Cancelled"**

Enviábamos `VOID` (funcionaba, pero era conjetura). Producción-Lunex enviará
`"Cancelled"`, así que para replicar producción hay que mandar eso. **Cambiado**
a `Cancelled` (override: `$env:TRN239_CANCEL_STATUS="VOID"`).

Lo persistido sigue siendo `LNStatus=VOID` / `IdStatus=22` — eso se valida
aparte con `cancelacion_confirmada`. Si al enviar `Cancelled` la cancelación
**falla**, es un hallazgo grande: la API no acepta lo que su requerimiento define.
Es lo primero a vigilar en la próxima corrida.

### 2. `FAILT` no es un estado válido — debe rechazarse

> RegisterTransaction · Status · **"SUCCESS or VOID — Other values are rejected"**

`FAILT` no está en el requerimiento. Y producción lo respalda: `Fallidas = 0` en 7 M
de filas. **En la 1ª corrida la API aceptó el FAILT** (Errorcode 0) y lo guardó
con `IdStatus=30`, idéntico a un éxito. Dos problemas: la API no aplica su
propia restricción, y si un FAILT entrara sería indistinguible de un SUCCESS.

**CP07 reencuadrado**: ahora manda `FAILT` y espera el **rechazo**. Si la API lo
acepta → FALLA, con la constancia de cómo quedó en BD.

---

## Lo que el requerimiento CONFIRMA (ya estaba bien)

| Punto | Requerimiento | Nuestro código |
|---|---|---|
| Fecha en GMT-8, API suma 8 h | «must be sent in GMT-8. The API converts by adding 8 hours» | `bodies.fecha_gmt8` ✅ correcto |
| Firma MD5 | `MD5(Login+Password+Key)` hex minúsculas UTF-8 | `bodies.md5_firma` ✅ |
| ExternalID | `M{IdAgent*IdUser}S{IdUser}` | `bodies.external_id` ✅ |
| `Reponse_timestamp` (una sola s) | «intentionally spelled with a single s… must not be renamed» | no lo renombramos ✅ |
| Estructura del cuerpo (30 campos) | ejemplo del doc | `bodies.alta` coincide campo a campo ✅ |
| DTU ejemplo del doc (9851 MetroPCS) | `ExRate/AmountInMN/CountryCurrency = null`, `Phone==TopupPhone`, `Fee 4.0` | nuestro DTU: nulls ✅, Phone==Topup ✅ |

**Sobre la fecha (+5 h vs +1 h de prod):** ya no es «quizá culpa nuestra». El
requerimiento confirma que enviar GMT-8 y que la API sume 8 h es lo correcto. El
desfase que se ve en BD es el offset horario del servidor, no un defecto. Baja
de prioridad; si acaso, medir una vez con la hora local para cerrarlo del todo.

---

## Observaciones menores

- **`Fee` y `CommissionPercentage` en el alta genérica**: mandamos `Fee=0` y
  `CommissionPercentage=9.00` fijos. Para DTU el requerimiento dice que ambos entran
  en el cálculo de comisión. No es problema: la API los recalcula del lado
  servidor (el DTU 9925 volvió con `Fee=1.50` aunque enviamos 0). Pero si
  quisiéramos cuerpos DTU más realistas, habría que mandar el `Fee` del SKU.
- **`Status` en el alta admite también `VOID`** (no solo SUCCESS). No lo usamos
  en el alta; solo SUCCESS. Sin acción.

---

## Páginas relacionadas que conviene leer (siguiente paso)

El documento enlaza a otras que tocan puntos abiertos:

- **«Transacciones Duplicadas Lunex»** — directamente relevante al CP08: qué
  hace el sistema con TransactionID repetidos (recordar: en prod NO es único).
- **«[Eng] Processes Definition: Integration vs Certification»** — define qué
  cuenta como certificación vs integración; útil para saber qué exige el cierre.
- **«KYC RULES ANALYSIS»** — por si la notificación arrastra validaciones KYC.

Puedo leerlas con el navegador (tengo tu sesión de Confluence abierta) si
quieres que profundice en alguna.

---

## Qué me sería útil de tu lado

No necesito que hagas una recarga real (y menos si toca producción). Lo que
más ayuda a la validación vs producción es:

1. **Confirmar el ambiente**: ¿`zeus-services` es de verdad test para las
   notificaciones, o también impacta producción? El doc dice que es test; tú
   mencionaste que no hay test. Cerrar esa duda es lo más importante.
2. **Una fila real de producción** de un SKU que probamos, con todas sus
   columnas, para comparar campo a campo (ya diste varias; con una más por SKU
   de alto volumen basta).
3. Que revises los 2 hallazgos de arriba (Cancelled y FAILT) y me digas si los
   llevo a DEV como tickets o si hay contexto que me falta.
