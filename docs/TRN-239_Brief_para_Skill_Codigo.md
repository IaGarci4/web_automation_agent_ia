# BRIEF para el skill de código (Big C / acceso a fuente de Hermes) — TRN-239 API Lunex

> **Objetivo:** necesito armar una colección Postman y casos de prueba que peguen **directo a la
> API Lunex migrada** (TRN-239). Ya tengo la URL y sé calcular el auth. Lo que me falta es:
> (a) el **esquema exacto del body** de cada endpoint, y (b) **de dónde saco datos reales** para
> el body (qué tablas/columnas de BD), porque tengo acceso a la BD pero no sé qué consultar.
> Por favor analiza el código fuente y respóndeme las secciones de abajo de forma concreta.

---

## Contexto (lo que ya sé, no hace falta que lo re-investigues)

- API migrada (FastAPI, Python) que reemplaza al Urano legacy (`Payments/LunexService.svc`, .NET).
- **URL base confirmada:** `https://zeus-services.maxilabs.net/api/v1/lunex/`
  - Alta:        `POST {{base_url}}Payments/RegisterTransaction`  (verificado, responde)
  - Cancelación: `POST {{base_url}}Payments/CancelTransaction`
  - Healthcheck: `GET  {{base_url}}healthcheck` (por confirmar la ruta exacta)
- Acepta **SOAP (XML)** y **JSON**.
- **Auth:** el request trae `Login`, `Key` y `Md5`. Fórmula (de la colección): `Md5 = MD5(Login + Password + Key)`.
- Estados: `SUCCESS` (alta), `FAILT` (fallida), `VOID` (cancelación).
- El alta invoca el SP `Lunex.st_CreateTransferLN`.
- Repos probables: `HERMES2-*` / api-lunex / el servicio que expone `/api/v1/lunex` en `zeus-services`.

---

## Lo que necesito que extraigas del código (concreto)

### 1. Esquema del body — RegisterTransaction
Del modelo/DTO del request (Pydantic o equivalente) y del parser SOAP:
- **Lista completa de campos** con: nombre exacto (respetando mayúsculas), tipo, **obligatorio u opcional**, default si existe, y formato esperado (ej. `TransactionDate` = ISO `YYYY-MM-DDTHH:MM:SS`).
- Restricciones/validaciones por campo (rangos de `Amount`, longitud de `Phone`, valores válidos de `Status`, `SKUType`, `Action`, etc.).
- ¿El nombre de campo en JSON es idéntico al de SOAP (`max:Campo`)? ¿Hay alias/mapeos?
- ¿Qué namespace/estructura SOAP espera exactamente? (¿usa `<a:To>`? ¿lo ignora?)

### 2. Esquema del body — CancelTransaction
Lo mismo que arriba para cancelación (campos, obligatorios, `Status=VOID`, qué identifica la transacción a cancelar: ¿`TransactionID`? ¿`ExternalID`? ¿ambos?).

### 3. ★ Origen de datos en BD (lo más importante para mí)
Para poder construir un body con **datos reales**, dime **de qué tabla y columna sale cada valor**:
- `Login` / `Password` / credenciales Lunex → ¿en qué tabla están las credenciales válidas de TEST? (nombre de tabla y columnas)
- `Entity` (ej. `MX01D3643A`) → ¿qué es y de qué tabla/columna sale? ¿es el código de agente en Lunex?
- `SKU` / `SKUName` / `SKUType` (ej. 8485 / 8510) → ¿catálogo de productos? tabla y columnas.
- `CID`, `ExternalID`, `TransactionID` → ¿se generan del lado de Lunex o se validan contra alguna tabla? ¿qué formato/rango?
- `Phone` / `TopupPhone` → ¿deben existir en alguna tabla o son libres?
- `CommissionPercentage`, `D1Discount`, `D2Discount`, `R1Discount`, `R2Discount`, `Fee`, `ExRate`, `AmountInMN`, `CountryCurrency` → ¿de qué tabla sale el esquema de comisión/tipo de cambio del agente? (para CP de comisiones)
- **Consulta SQL sugerida**: si puedes, dame 1–2 `SELECT` de ejemplo que devuelvan un juego de datos válido y coherente para armar un RegisterTransaction que el SP `Lunex.st_CreateTransferLN` acepte.

### 4. El SP `Lunex.st_CreateTransferLN`
- Parámetros de entrada (orden, tipo) y de dónde los toma el endpoint.
- Qué inserta/actualiza y en qué tablas (para poder **verificar** la transacción después del alta).
- Cómo se refleja una transacción registrada para consultarla luego (tabla + columnas: TransactionID, estado, agente, monto, folio).

### 5. Autenticación y credenciales
- Confirmar la fórmula del `Md5` (¿es `Login+Password+Key`? ¿hay salt/orden distinto?).
- ¿Dónde valida el servicio el `Md5`? ¿contra qué tabla obtiene el `Password`?
- ¿Qué responde ante `Md5` inválido? (código HTTP + cuerpo) — lo necesito para el caso negativo.

### 6. Validaciones y catálogo de errores
- Reglas de validación del request (campos faltantes, tipos, rangos) y **qué HTTP/estructura** devuelve cada una.
- Catálogo de códigos de error (TRN-300): lista de códigos y mensajes, para los casos negativos.
- Manejo de **idempotencia**: ¿qué pasa si llega el mismo `TransactionID` dos veces? (¿rechaza? ¿ignora? ¿duplica?)

### 7. Healthcheck
- Ruta exacta y método. Esquema de respuesta (`status`, `parts.database`, etc.) y qué considera `DEGRADED`/`DOWN`.

---

## Formato de respuesta que me sirve
Por cada endpoint: una **tabla de campos** (nombre · tipo · obligatorio · origen BD tabla.columna · ejemplo válido), más los `SELECT` sugeridos y el catálogo de errores. Con eso yo:
1. Relleno la colección Postman (`TRN-239_LunexCollection_v2`) con bodies realistas y variables.
2. Reestructuro los casos QMetry con datos verificables contra BD.
3. Empezamos a probar.

*(Devuélveme el resultado y yo armo la colección final y el Excel de casos.)*
