# TRN-239 — Análisis del flujo real de recargas Lunex
### Sesión en vivo · 4 de septiembre de 2026 · agente 0020-TX / Lunex `0020-TX STAGE H1`

---

## 0. Resumen ejecutivo

Se ejecutaron **4 recargas reales** en el portal de Lunex desde la cuenta del agente.
Una resultó **EXITOSA** ($2.00 Telcel México) y tres fallaron con códigos de error distintos.

**Hallazgo crítico:** ninguna de las 4 transacciones — ni la exitosa — apareció en el
Back Office de Chronos TEST. El listado de Lunex sigue mostrando únicamente registros
de agosto. Esto sugiere que **la notificación de Lunex hacia la API migrada no está
llegando al ambiente TEST**, y es el punto que conviene aclarar con DEV antes de dar
por probado TRN-239.

---

## 1. Arquitectura real: la recarga NO ocurre en Maxi

"Mega Recargas" en Maxi Send es un `<iframe>` que carga el portal propio de Lunex vía SSO:

```
iframe.iframe-content
  src = https://sgso.lunextelecom.com/index/login/token/{TOKEN}/username/{ENTITY}
```

| Dato | Valor capturado |
|------|-----------------|
| Portal | `https://sgso.lunextelecom.com` |
| Token SSO (32 hex = MD5) | `b0383f01dc3eb6942e2bb52db0e5a971` |
| Username / Entity del agente | `MX01D0001AH` |
| Sesión | `/index/index/ssId/v0rg7eadui34pa3oglotqcmre5` |
| Cuenta Lunex | `0020-TX STAGE H1` |

> El `username` tiene el mismo formato que el campo **`Entity`** de la colección Postman
> (`MX01D3643A`). Es el identificador del agente dentro de Lunex.

```
  Navegador                          Servidores
  ─────────                          ──────────
  Maxi Send
     └─ iframe ──► portal Lunex (la recarga se procesa aquí)
                        │
                        ▼
                   Lunex backend ──── SOAP/JSON ────► API Lunex de Maxi
                                   (servidor a servidor)  RegisterTransaction
                                   NO pasa por el navegador      │
                                                                  ▼
                                                     SP Lunex.st_CreateTransferLN
```

**El `RegisterTransaction` no es capturable desde el navegador.** Para obtener un payload
real hay que pedir los logs de la API a DEV.

---

## 2. Rutas del portal

| Pestaña | id del enlace | URL |
|---|---|---|
| Conecta2 | `menu_megaNew1ClicDesc` | `/pinless/main` |
| Recargas Internacionales | `menu_topUpWorldDesc` | `/topup/top-up-account` → `/topup/auto-top-up-account` |
| Recargas Nacionales (USA) | `menu_topUpUsaDesc` | `/domestic` → `/domestic/v2` |

Captura del teléfono del cliente: `form#form_phone_number_us` → `input#phone_number_us`

---

## 3. Formulario NACIONAL (EE.UU.) — `/domestic/v2`

```
form#topupForm  →  POST https://sgso.lunextelecom.com/domestic/confirm   (27 campos)
```

| Campo | Valor de ejemplo | Nota |
|---|---|---|
| `topup_type` | `topup` / `data` | radio |
| `Mobile_Phone_Top_Up` | `214-916-9893` | número a recargar |
| `CountryCode` | `1` | EE.UU. |
| `Operator_Top_Up` | `214_0` | T-Mobile |
| `Amount_Top_Up` / `Amount_Top_Up2` | `10` | el 2º es monto libre |
| `convenience_fee` | `0` | |
| `total_amount` | `10` | |
| `topupname`, `subscriberpin`, `isFlexibleAmount`, `currency`, `timezone` | | |

Flujo: `/domestic/v2` → **Siguiente** → `/domestic/confirm` (verificación) → **Enviar** → `/domestic/result`

⚠️ Aviso en la pantalla de verificación:
*"Todas las Recargas Nacionales son Finales. La cancelación o reembolso no están disponibles."*

### Catálogo de operadores EE.UU. (`Operator_Top_Up`, 24 opciones)

Formato `{idProducto}_{tipo}`:

| Valor | Operador | | Valor | Operador |
|---|---|---|---|---|
| `323_0` | AT&T | | `620_0` | **Verizon** |
| `1205_0` | Boost Mobile (fee based) | | `621_1` | Access Wireless |
| `1208_0` | Cricket (fee based) | | `184_1` | AirVoice Wireless Unlimited |
| `1253_0` | Go Smart | | `182_1` | Airlink Mobile |
| `1251_0` | H2O - Bolt RTR | | `201_1` | Net10 - PayGo |
| `1252_0` | H2O - PayGo RTR | | `204_1` | Page Plus - Pay Go |
| `1250_0` | H2O - Unlimited RTR | | `206_1` | Page Plus - The Monthly |
| `1202_0` | Metropcs (fee based) | | `209_1` | Pure Prepaid |
| `1145_0` | Net10 - Unlimited RTR | | `210_1` | Ready Mobile |
| `341_0` | Simple Mobile | | `307_1` | Red Pocket - Unl |
| **`214_0`** | **T-Mobile** | | `217_1` | Tracfone |

**Montos mínimos observados:** T-Mobile `$10` (rango 10–150) · Verizon `$5` (rango 5–150).
Ambos son de **monto libre** dentro del rango.

---

## 4. Formulario INTERNACIONAL — `/topup/auto-top-up-account`

```
form#topupForm  →  POST /topup/auto-top-up-confirm/rand/{RAND}
```
`{RAND}` es un token por sesión (ej. `dd7226c2621461ec4daf1e61bb0670ae`).

Campos: `phone_us`, `textsms`, `Country_Top_Up`, `Operator_Top_Up`, `Mobile_Phone_Top_Up`,
`CountryCode`, `Amount_Top_Up`, `Amount_Top_Up2`, **`estimate_transfer`**,
**`federal_transfer_tax`**, `total_amount`, `topupname`, `currency`, `recipientEmail`,
`recipientPhone`, `sms-message-content`, `pay`, …

**125 países.** `Country_Top_Up`: **México = `52`**.
El operador **no se elige manualmente**: se autodetecta y se confirma en un modal con el
catálogo de productos agrupado (*Paquetes: Llamadas, Textos, Internet* / *Sólo Internet* /
*Recarga Solamente*).

### Montos Telcel Amigo Sin Limite (`Amount_Top_Up`)

El `value` interno es **10× el importe en USD**:

| value | muestra |
|---|---|
| `20.0` | **$2** ← mínimo |
| `30.0` | $3 |
| `50.0` | $5 |
| `100.0` | $10 |
| `150.0` | $15 |
| `200.0` | $20 |
| `300.0` | $30 |
| `500.0` | $50 |

Al elegir $2: `currency = MXN`, `estimate_transfer = MXN 20`, `total_amount = 2`.
Producto: *MXN 20 · válido 1 día · ilimitado SMS/minutos · 100MB + 200MB*.

**Existe `federal_transfer_tax` = Impuesto Federal de Envío (1%).** Visible a partir de
montos mayores (en $20 se cobró $0.20; en $2 redondea a 0).

⚠️ Mismo aviso: *"Todas las Recargas Internacionales son Finales."*

Flujo: `/auto-top-up-account` → **CONTINUAR** → `/auto-top-up-confirm/rand/{RAND}` →
**Enviar** → barra de progreso → `/auto-top-up-result/rand/{RAND}`

---

## 5. Transacciones ejecutadas en esta sesión

| # | Transacción | Resultado | Operador / número | Monto | Detalle |
|---|---|---|---|---|---|
| 1 | `1014307300` | **FALLIDO** | T-Mobile · 214-916-9893 | $10 | *Invalid Card Number* — **Error 78** |
| 2 | `1014307403` | **FALLIDO** | T-Mobile · 832-798-0382 | $10 | *La cuenta es inválida o es de pospago* — **Error 44** |
| 3 | `1014307432` | **FALLIDO** | Verizon · 469-254-8267 | $5 | *Ocurrió un error* — **Error 40** |
| 4 | **`1014307527`** | **EXITOSO** | Telcel Amigo Sin Limite · 011-52-18115554045 | **$2.00** | válido hasta 07:38 PM EST 09/05/2026 |

**Códigos de error del catálogo capturados en vivo (útiles para TRN-300):**

| Código | Mensaje |
|---|---|
| **40** | Ocurrió un error. Por favor póngase en contacto con Soporte al Agente para más detalles. |
| **44** | La cuenta es inválida o es de pospago. Por favor verifique el número e intente de nuevo. |
| **78** | Invalid Card Number. Please check the number and try again. |

> Las 3 fallidas **no generaron cargo**. Las recargas nacionales de EE.UU. fallaron las 3
> veces con errores distintos, incluso en líneas reportadas como conectadas — conviene
> revisar si la cuenta STAGE tiene habilitado el producto nacional.

---

## 6. ⚠️ Hallazgo abierto: la notificación no llega a TEST

Tras la recarga **exitosa** `1014307527`, se consultó:

```
Back Office Chronos → Search Other Products → Top UP → Provider: Lunex
Rango 09/01/2026 – 09/06/2026  →  0 resultados
Rango 08/04/2026 – 09/04/2026  →  4 resultados, todos de agosto
```

Registros preexistentes (referencia de correlación):

| Fecha | Agente | Cellular | Folio | Transaction ID | Carrier | Retail |
|---|---|---|---|---|---|---|
| 08/28/2026 | 13039-CA | (323) 408-0594 | 7765719 | 1014205125 | METRO PCS - RTR | $60.00 |
| 08/19/2026 | 10902-TX | (458) 105-4903 | 7765709 | 1769553214 | Telcel - Amigo Sin Limite | $25.00 |
| 08/19/2026 | 10902-TX | (458) 105-4903 | 7765708 | 1769553213 | Telcel - Amigo Sin Limite | $25.00 |
| 08/19/2026 | 10902-TX | (458) 105-4903 | 7765707 | 1769553212 | Telcel - Amigo Sin Limite | $25.00 |

**Preguntas a plantear a DEV (Sergio Ulises García Balandrán):**

1. ¿La cuenta Lunex `0020-TX STAGE H1` notifica al ambiente TEST o a producción?
2. ¿Cuál es el retardo esperado entre la recarga en Lunex y el alta en Maxi?
3. ¿La API Lunex migrada está desplegada y apuntada en TEST? ¿Cuál es su URL?
4. ¿Hay logs de la API donde se vea el `RegisterTransaction` de `1014307527`?

Nota: los registros de agosto llegaron, así que el canal **funcionó** en algún momento.

---

## 7. Filtros del Back Office (catálogo capturado)

Pestaña **Top UP** — `ProviderId`: `-1=All`, **`3=Lunex`**, `5=Regalii`, `2=TransferTo`
`IdStatus`: `0=All`, `22=Cancelled`, `30=Paid`, `21=Pending`

> **No existe un estado "Fallido"** en el filtro. Las recargas fallidas no se registran.
> Esto invalida el caso de prueba que buscaba verificar el estado de una recarga fallida
> en el Back Office.

Columnas: `Date of Top UP · Agent Code · Agent Name · Customer Number · Cellular Number ·
Folio · Transaction ID · Carrier · Wholesale Price · Retail Price · Country`

---

## 8. Pendiente para completar la colección de Postman

1. **URL desplegada de la API Lunex** — solicitar a DEV (subtarea TRN-524).
   La colección apunta a `http://localhost:8081`, entorno local del desarrollador.
2. **Environment de Postman** con las variables que la colección usa pero no define:
   `base_url`, `lunex_login`, `lunex_md5`, `lunex_key`, `lunex_cancel_key`,
   `lunex_transaction_id`, `lunex_cancel_tran_id`, `lunex_date_time`.
3. **Credenciales** (`Login` / `Md5` / `Key`) y la regla de construcción del hash.
4. **URL del healthcheck** — documentada en las capturas de TRN-569.

Referencia legacy: `https://test-uranus.maxilabs.net/Payments/LunexService.svc`

---

*Capturado el 4 de septiembre de 2026. 4 recargas reales ejecutadas (1 exitosa, $2.00).*
