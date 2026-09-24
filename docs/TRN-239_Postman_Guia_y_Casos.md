# TRN-239 — Guía de pruebas Postman (API Lunex) + casos QMetry
### 10 de septiembre de 2026 · Migración BE Urano → API Lunex (FastAPI)

---

## 1. Análisis de dónde estamos

**Cambio de enfoque confirmado:** las pruebas de TRN-239 apuntan **directo a la API Lunex desde
Postman**, NO desde el Front End de Hermes. Esto simplifica todo: la recarga real por UI (que
costaba dinero y no capturaba nada porque la notificación es server-to-server) queda fuera. Se
prueba la API que Lunex invoca para notificar a Maxi.

**Estado de la colección original (`LunexCollection.json` — "New Api notifications"):**

| Aspecto | Situación |
|---|---|
| Endpoints | RegisterTransaction (SOAP + JSON), CancelTransaction (SOAP + JSON) |
| Autenticación | ✅ Ya resuelta — el **pre-request calcula el MD5 solo**: `MD5(lunex_login + lunex_password + lunex_key)` |
| URLs | ❌ Apuntan a `http://localhost:8081` (entorno local del dev) — hay que cambiarlas |
| Variables | ❌ Usa `{{base_url}}`, `{{lunex_*}}` pero **no vienen definidas** (viven en el environment del dev) |
| Healthcheck | ❌ No estaba en la colección (existe: `GET {{base_url}}healthcheck`, TRN-569) |
| Tests | ❌ Sin `pm.test` — no era una suite ejecutable, solo requests sueltos |

**Lo que entrego lo corrige todo** (ver §3).

---

## 2. `base_url` — CONFIRMADO

La API Lunex migrada está montada **bajo el servicio Argo** del gateway:

```
base_url = https://test-apps.maxilabs.net/Argo/
```

Verificado en campo: `https://test-apps.maxilabs.net/Argo/Payments/RegisterTransaction` responde.
Endpoints completos:
- `https://test-apps.maxilabs.net/Argo/Payments/RegisterTransaction`
- `https://test-apps.maxilabs.net/Argo/Payments/CancelTransaction`
- `https://test-apps.maxilabs.net/Argo/healthcheck`

Ya está puesto en el environment y la colección que entrego. (El legacy Urano seguía en
`https://test-uranus.maxilabs.net/Payments/LunexService.svc`, .NET — NO es la API migrada.)

### El error "Faltan variables de entorno" — causa y arreglo

El pre-request **original** hace `if (!login || !password || !key) throw ...`. Ese error salta
cuando **no hay un Environment seleccionado**, o cuando alguna de las tres variables está vacía —
en particular **`lunex_key` no puede ir vacía**. Arréglalo así:
1. Importa `TRN-239_Lunex.postman_environment.json` y **selecciónalo** (esquina superior derecha).
2. Ese environment ya trae `lunex_login`, `lunex_password` y `lunex_key=1234567`.
3. O mejor: usa la **colección v2**, cuyo pre-request **genera `lunex_key` solo** (no depende de
   que la tengas cargada) y evita el error por completo.

**Healthcheck (confirmado en TRN-569):** `GET {{base_url}}healthcheck` devuelve
```json
{ "status": "UP|DEGRADED", "timestamp": "...", "version": "0.0.0", "uptime": 257,
  "parts": { "database": { "status": "OK|DOWN", "error": "timeout" } } }
```
(la captura "BD abajo" mostró `status: DEGRADED`, `database.status: DOWN` al desconectar la VPN).

---

## 3. Qué entrego (listo para importar)

**`TRN-239_LunexCollection_v2.postman_collection.json`** — colección corregida y ejecutable:

- Todas las URLs usan `{{base_url}}` (adiós localhost) y se arregló el host malformado del
  request "Copy".
- **Se agregó el Healthcheck** con sus asserts.
- **Pre-request mejorado**: genera `Key` y `TransactionID` **únicos por corrida** (timestamp) y
  calcula el MD5 — así no truena por key/transacción duplicada y se puede correr repetidamente.
- **Encadenado Register → Cancel**: al registrar con éxito, guarda el `TransactionID` en
  `lunex_cancel_tran_id`, y el Cancel lo toma automáticamente. Corres el flujo completo sin
  copiar/pegar IDs.
- **Cada request trae `pm.test`** (status, ausencia de Fault SOAP, esquema, sin stack trace) →
  se corre con **Collection Runner** o **Newman** y da PASS/FAIL.
- Organizada en carpetas: `0. Healthcheck`, `1. RegisterTransaction`, `2. CancelTransaction`,
  `3. Negativos`.

**`TRN-239_Lunex.postman_environment.json`** — environment con las 9 variables. Solo hay que
rellenar `base_url` (y confirmar credenciales de TEST con DEV).

### Cómo probar hoy mismo (3 pasos)
1. En Postman: **Import** → los dos archivos (colección + environment).
2. Selecciona el environment **"TRN-239 Lunex (TEST)"** y pega el `base_url` que te dé DEV.
3. Corre **`0. Healthcheck`** primero (valida conectividad); luego la carpeta completa con el
   **Runner**. Sin DEV para el `base_url`, no hay forma de que responda algo distinto a error de host.

---

## 4. Casos de prueba QMetry reestructurados (enfoque Postman/API)

Reemplazan a los de la versión UI. Todos **Ambiente TEST**, ejecución **manual desde Postman**
(la colección los cubre 1 a 1). Componente sugerido: `URANO`. Assignee/Reporter/Tester: tu UUID.

| CP | Título | Request de la colección | Resultado esperado |
|----|--------|-------------------------|--------------------|
| **CP01** | Healthcheck con BD arriba | `0. Healthcheck` (VPN conectada) | 200, `status: UP`, `database.status: OK` |
| **CP02** | Healthcheck con BD abajo | `0. Healthcheck` (VPN desconectada) | `status: DEGRADED`, `database.status: DOWN` (TRN-569) |
| **CP03** | Alta SOAP exitosa | `1. Register SOAP - SUCCESS` | 200, respuesta SOAP sin Fault, transacción registrada |
| **CP04** | Alta JSON exitosa | `1. Register JSON - SUCCESS` | 200, respuesta de éxito; guarda TransactionID |
| **CP05** | Paridad SOAP vs JSON | CP03 + CP04, comparar | Ambos formatos producen el mismo alta |
| **CP06** | Cancelación JSON (VOID) | `2. Cancel JSON - VOID` | 200, transacción anulada (usa la de CP04) |
| **CP07** | Cancelación SOAP (VOID) | `2. Cancel SOAP - VOID` | 200, sin Fault |
| **CP08** | Negativo auth: MD5 inválido | `3. Register - Md5 inválido` | Rechazo (401/403 o error), sin datos, sin stack trace (TRN-293) |
| **CP09** | Negativo validación: campos faltantes | `3. Register - campos faltantes` | Error de validación identificando faltantes (TRN-294) |
| **CP10** | Negativo validación: monto inválido | `3. Register - Amount inválido` | Rechazo por monto negativo |
| **CP11** | Negativo cancelación: TransactionID inexistente | `3. Cancel - TransactionID inexistente` | Error controlado del catálogo (TRN-300), sin excepción cruda |
| **CP12** | Comisiones: 3 variantes | `1. Register JSON` variando CommissionPercentage / D1-D2 / R1-R2 | El importe calculado corresponde a cada variante (TRN-295/296) |
| **CP13** | Status FAILT (recarga fallida) | `1. Register JSON` con `Status=FAILT` | Se registra como fallida, diferenciable de SUCCESS |
| **CP14** | Idempotencia: TransactionID duplicado | `1. Register JSON` reenviando el mismo TransactionID | No duplica; error de duplicado o resultado idempotente |

> **Nota:** el pre-request genera IDs únicos por corrida; para CP14 (idempotencia) hay que fijar
> `lunex_transaction_id` a un valor conocido y reenviar dos veces (se documenta en el paso).

---

## 5. Referencia técnica

| Dato | Valor |
|---|---|
| Fórmula de auth (pre-request) | `Md5 = MD5(lunex_login + lunex_password + lunex_key)` |
| Endpoints | `Payments/RegisterTransaction`, `Payments/CancelTransaction`, `healthcheck` |
| Formatos | SOAP (XML) y JSON — ambos soportados |
| Estados | `SUCCESS` (alta) · `FAILT` (fallida) · `VOID` (cancelación) |
| SKU ejemplo | `8485` Honduras Paquetigo · `8510` Mexico Telcel Amigo Sin Limite |
| Legacy (comparación de paridad) | `https://test-uranus.maxilabs.net/Payments/LunexService.svc` (.NET) |
| Deploy | OR-960 · 29 SEP 2026 |
| DEV / dueño | Sergio Ulises García Balandrán · TRN-239 |

---

## 6. Pendiente

- **`base_url` de DEV** → único bloqueante para ejecutar.
- **Excel QMetry** (`TRN-239_Postman_QMetry.xlsx`, 31 columnas) — el sandbox que genera el xlsx
  tuvo una caída de infraestructura durante esta sesión. Los 14 casos ya están definidos arriba;
  el archivo se genera en cuanto el sandbox se recupere (o se puede armar desde esta tabla).
