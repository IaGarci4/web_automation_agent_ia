# Comisiones DTU / ITU Lunex — relación Producto · SKU · SKUType · País

> Fuente: Confluence — **"Notificaciones lunex"** (diagrama de flujo de `LunexService.svc`, David Velasco)
> y **"Calculadora Lunex"** (David Velasco). Código C# y SQL citados textualmente de esas páginas.

## 1. Qué son DTU e ITU

El campo `SKUType` que manda el request solo acepta dos valores (validación `r8` del servicio):

```
valida SKUType in ('ITU', 'DTU')
```

| SKUType | Significado | Confirmado en |
|---|---|---|
| **DTU** | **TopUp Doméstico** — recarga a un SKU/Carrier de **México** | Cita textual: *"se utiliza si el FEE es mayor a 0 y el SKUType es DTU (TopUp Domestico)"* |
| **ITU** | **International TopUp** — recarga a un SKU/Carrier fuera de México | Por exclusión: es el único otro valor válido junto a DTU en la validación `r8` |

Es decir: **DTU/ITU no es un dato libre — depende de si el país real del SKU es México o no.** Esto es clave para tu prueba: el `SKUType` que mandes debe ser coherente con el `IdCountry` real del producto en `lunex.Product`, o vas a estar probando una combinación que la API nunca vería en producción.

## 2. Cómo se calcula la comisión (flujo completo de `LunexService.svc`)

Orden real (del diagrama Mermaid de "Notificaciones lunex"):

1. `RegisterTransaction`: valida body no-nulo (r1) → `Action=lunex` (r3) → `Status in (SUCCESS,VOID)` (r9) → sesión/Md5 (r4) → `Amount>0`.
2. `LunexApplication`: valida decoradores (r5) → key no duplicada (r6) → usuario/agente (r7) → `SKUType in (ITU,DTU)` (r8).
3. Desde ahí se **bifurca en dos rutas de comisión, en paralelo**:
   - **Ruta normal (Top Up):** `[Lunex].[st_GetAgentSchemaForService]` — obtiene el schema por **Carrier, País o Global** (la tabla de preponderancia de abajo) → decide entre **Cálculo 1** o **Cálculo 2**.
   - **Ruta "otros productos"** (`IdOtherProduct`, ej. tarjetas de regalo): `[Lunex].[st_GetAgentSchemaOtherProductsForService]` → **Cálculo 3**.
4. Ambas rutas terminan registrando con `Lunex.st_CreateTransferLN`.

### Cálculo 1 — se usa si `Fee>0`, `CommissionPercentage>0` **y** `SKUType=="DTU"`
```csharp
decimal reqFee = request.Fee ?? 0;
decimal reqCommissionP = request.CommissionPercentage ?? 0;
decimal percent = decimal.Round(reqCommissionP / 100, 2);
decimal tempFee = reqFee * percent;
providerCommission = reqFee - tempFee;
corpCommission = reqFee - providerCommission - commission.Commission;
model.Commission = 0;
model.CorpCommission = corpCommission;
model.AgentCommission = commission.Commission;
```

### Cálculo 2 — si NO se cumple la condición del Cálculo 1 (incluye todo lo que es `SKUType=="ITU"`)
```csharp
providerCommission = decimal.Round((request.D1Discount) * 100 / request.Amount, 2);
corpCommission = Math.Truncate((((providerCommission - commission.Commission) * request.Amount) / 100) * 100) / 100;
model.Commission = request.D1Discount;
model.CorpCommission = corpCommission;
model.AgentCommission = request.D1Discount - corpCommission;
```
⚠️ Riesgo ya documentado en "Calculadora Lunex": **Lunex a veces manda `D1Discount = 0`**, lo que produce comisión en negativo para Maxi. Vale la pena que tu CP incluya un caso con `D1Discount=0` para confirmar que la migración no reproduce ese defecto legacy.

### Cálculo 3 — solo para "otros productos" (no aplica a Top Up normal DTU/ITU)
```csharp
var commission = GetOtherProductsCommission(model.IdAgent, model.SKUType, model.Amount, model.SKU);
if (commission == null) return PaymentResposeMessage.GetResponse(10, false, 0); // <- esto es un origen real de Errorcode 10
providerCommission = decimal.Round((request.D1Discount) * 100 / request.Amount, 2);
corpCommission = (Math.Truncate((((providerCommission - commission.AgentPercentage) * request.Amount) / 100) * 100) / 100) - commission.ExtraAmount;
```
**Dato importante para tu brief de errorcodes (código 10):** aquí está confirmado en código que **10 se dispara cuando `GetOtherProductsCommission` devuelve `null`**, es decir, cuando el agente no tiene un esquema de comisión configurado para ese producto/SKUType/monto. Esto es exactamente lo que necesitabas para aislar el código 10 — el "agente real sin esquema" que buscabas.

## 3. Preponderancia del schema (Carrier / País / Global)

Tabla textual de "Calculadora Lunex":

| Schema | Preponderancia | Descripción |
|---|---|---|
| `schemaCarrier` | 5 (más alta) | comisión de un agente específico para un Carrier específico |
| `schemaCarrierDefault` | 4 | comisión default para un Carrier |
| `schemaCountry` | 3 | comisión de un agente específico para un país específico |
| `schemaCountryDefault` | 2 | comisión default para un país |
| `schemaGlobal` | 1 (más baja) | comisión global si ninguna de las anteriores existe |

El sistema toma la de **mayor preponderancia** que aplique al agente/carrier/país de la transacción.

## 4. JOIN correcto: Producto ↔ País ↔ Carrier

**Confirmado literalmente en el código SQL de "Calculadora Lunex":**
```sql
SELECT @IdCountry = IdCountry, @IdCarrier = IdCarrier
FROM lunex.product WITH(NOLOCK)
WHERE sku = @Sku
```
y en la resolución del schema:
```sql
FROM [TransFerTo].[Schema] s WITH(NOLOCK)
LEFT JOIN operation.country c  WITH(NOLOCK) ON s.IdCountry = c.idcountry
LEFT JOIN operation.carrier ca WITH(NOLOCK) ON s.idcarrier = ca.idcarrier
```

Con eso, la consulta que necesitas para tu script — **relación real Producto · SKU · País · Carrier**, para poder armar un request donde `SKUType` sea coherente con el país real del SKU:

```sql
-- Relación real SKU / Producto / País / Carrier (para elegir SKUType correcto en tu script)
SELECT
    p.SKU,
    p.Product,
    p.IdCountry,
    c.CountryName,
    p.IdCarrier,
    car.CarrierName,
    p.IdGenericstatus,
    p.Margin,
    CASE
        WHEN c.CountryName LIKE 'MEXIC%' THEN 'DTU'   -- doméstico
        ELSE 'ITU'                                     -- internacional
    END AS SKUType_Correcto
FROM lunex.Product AS p WITH(NOLOCK)
INNER JOIN operation.country AS c   WITH(NOLOCK) ON p.IdCountry = c.IdCountry
INNER JOIN operation.carrier AS car WITH(NOLOCK) ON p.IdCarrier = car.IdCarrier
WHERE p.IdGenericstatus = 1          -- solo productos activos
ORDER BY p.SKU;
```

Con tu ejemplo (`SKU=9800`, `Product=Xtreme Mobile`, `IdCountry=110` → `CountryName=KYRGYZSTAN`), esta consulta te devolvería `SKUType_Correcto = 'ITU'` — porque no es México. Así tu script, antes de armar el body, resuelve `SKUType` a partir del país real del producto en vez de fijarlo a mano, evitando mandar combinaciones imposibles (ej. un SKU de Kirguistán con `SKUType=DTU`).

⚠️ **Un solo dato que no puedo confirmar sin acceso a la BD:** el spelling exacto de México en `operation.country.CountryName` (podría ser `"MEXICO"`, `"MÉXICO"` o `"Mexico"`, con o sin acento). Antes de usar el `CASE` de arriba en producción, corre:
```sql
SELECT IdCountry, CountryName FROM operation.country WHERE CountryName LIKE '%MEXIC%';
```
y ajusta el `LIKE` con el valor exacto que te devuelva.

## 5. Punto clave para tu prueba (y posible caso de prueba adicional)

`SKUType` y `SKUName` **no viven como columnas fijas en `lunex.Product`** — llegan en el **request** (los defines tú/Lunex al armar el body) y se **persisten después** en `lunex.TransferLN` (columnas `SKUType`, `SKUName`, confirmadas en la consulta de `Calculadora Lunex`: `bill.SKUName, bill.SKUType ... FROM lunex.TransferLN AS bill`).

Esto significa que, hasta donde muestra el flujo documentado, **la API no necesariamente valida que el `SKUType` que mandas corresponda al país real del SKU** — solo valida que `SKUType` esté en `('ITU','DTU')` (r8) y que el agente tenga un esquema configurado para ese producto. Vale la pena agregar un caso de prueba explícito:

- **Caso nuevo sugerido:** enviar un SKU cuyo país real (según el JOIN de arriba) sea internacional, pero con `SKUType="DTU"` (o viceversa). Si la API lo acepta con `Errorcode 0`, es un hallazgo para reportar a DEV (falta de validación cruzada SKU↔SKUType↔País), relevante para el objetivo de "cero problemas" de esta migración.

## 6. Tablas confirmadas para tu script/consultas

| Tabla | Columnas confirmadas | Rol |
|---|---|---|
| `lunex.Product` | `SKU`, `Product`, `IdCountry`, `IdCarrier`, `IdGenericstatus`, `EnteredByIdUser`, `Margin` | Catálogo de productos (SKU → país/carrier reales) |
| `operation.country` | `IdCountry`, `CountryName` | Nombre real del país |
| `operation.carrier` | `IdCarrier`, `CarrierName` | Nombre real del carrier |
| `lunex.TransferLN` | `TransactionID`, `IdAgent`, `Sku`, `SKUName`, `SKUType`, `Fee`, `Amount`, `D1Discount`, `IdProductTransfer` | Transacción persistida (lo que realmente se envió y se guardó) |
| `TransFerTo.Schema` | `IdSchema`, `SchemaName`, `IdCountry`, `IdCarrier`, `IdProduct`, `BeginValue`, `EndValue`, `Commission`, `IsDefault`, `IdGenericStatus`, `IdOtherProduct` | Configuración de esquemas de comisión |
| `TransFerTo.AgentSchema` | `IdAgent`, `IdSchema` | Qué schema tiene asignado cada agente |
| `Operation.ProductTransfer` | `IdProductTransfer`, `IdOtherProduct`, `IdAgent`, `IdAgentPaymentSchema`, `Amount`, `Commission`, `AgentCommission`, `CorpCommission`, `Fee`, `TransactionFee` | Registro de la operación (para validar comisión post-transacción) |
| `Lunex.ServiceLogLunex` | `Request` (XML crudo) | Log del request tal como llegó de Lunex (útil para comparar enviado vs. persistido) |
