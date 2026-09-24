# Respuesta — Aislar cada Errorcode de Lunex Notifications (CP09) · TRN-239

> Resuelve por qué 5 códigos no salían como se esperaba y da la acción concreta por cada uno.
> Fuente: **tabla oficial «Error codes» del Integration Guide** (leída en Confluence) + regla de
> duplicados (HRMS-3281) + razonamiento de QA sobre el orden de validación. Lo que aún requiere el
> código fuente / un dato de BD queda marcado.

## Catálogo oficial de Errorcodes (Integration Guide → «Error codes»)

| Code | Meaning | Notes (oficial) |
|---|---|---|
| 0 | Success | Transaction was processed and saved |
| 1 | Request is null | **Body is empty or malformed** |
| 2 | Transaction already exists | Key or TransactionID has been used before |
| 3 | Action is not recognized | Action must be `lunex` |
| 4 | Session is invalid | authentication failed (MD5) |
| 5 | Validation error | Required fields are missing or invalid |
| 6 | Key is invalid | Key is duplicated or invalid |
| 7 | ExternalID is not recognized | Agent/user could not be parsed from ExternalID |
| 8 | Type is not recognized (SKU) | **SKUType value is not supported** |
| 9 | Status is not recognized | **Status value is not valid for the operation** |
| 10 | Agent is not configured | **Agent has no commission schema; contact Maxi team** |
| 12 | Transaction not cancellable | does not exist or cannot be cancelled |
| 15 | Internal error | Unexpected server error; contact Maxi technical support |

## Diagnóstico raíz (confirmado)

**No es bug del arnés: es el ORDEN de validación.** La API resuelve el **agente y su esquema de
comisión** (por ExternalID/Entity + SKU/SKUType) y esa resolución puede fallar **antes** que la
validación de campos. Por eso B/C/D caían en 10/15. La regla: para aislar 1/5/8 hay que fallar
**sin romper** la resolución del agente.

---

## Por código

### Código 1 — Request is null  ✅ resoluble en el arnés
- **Antes:** `{}` → daba **5** (porque `{}` es JSON válido con campos faltantes).
- **Ahora:** la nota oficial dice **«Body is empty or malformed»** → enviar:
  - **cuerpo vacío** (sin body, con `Content-Type: application/json`), o
  - **JSON malformado** (ej. `{ "Login":` sin cerrar).
- **Por qué:** 1 se dispara en la deserialización (cuerpo nulo/roto), no en la validación de campos.
- **En el test:** cambiar `{}` por cuerpo vacío o `{` malformado.

### Código 5 — Validation error  ✅ resoluble en el arnés
- **Antes:** quitar `SKU` → daba **10** (SKU alimenta la resolución del esquema, que falla primero).
- **Ahora:** romper un campo **requerido por el modelo que NO entre a la resolución del agente**:
  `TransactionDate` malformado (ej. `"fecha-invalida"`) manteniendo Entity/ExternalID/SKU/SKUType válidos.
  Alternativas: `Amount` no numérico, u omitir `Login`.
- **Por qué:** 5 = «Required fields are missing or invalid», validación pura de modelo.
- **En el test:** dejar de omitir SKU; malformar `TransactionDate`.

### Código 8 — SKU Type not recognized  ⚠️ reachable pero depende del orden — requiere código
- **Antes:** `SKUType="ZZZ"` → daba **10** (el esquema se indexa por SKUType; uno desconocido rompe el lookup → 10).
- **El catálogo confirma que 8 EXISTE** para «SKUType value is not supported», así que **sí es un
  código válido esperado** — el problema es el orden: hay que llegar al chequeo de SKUType **sin**
  reventar antes la resolución del esquema del agente.
- **Qué falta:** confirmar con código si existe un **catálogo global de SKUType** y en qué punto se
  valida. Con eso sabremos el valor exacto que da 8 (probable: un SKUType con formato válido pero
  fuera del catálogo global, con Entity/ExternalID/SKU que sí resuelvan agente). **→ pregunta 1 a DEV/código.**
- **Mientras tanto:** dejar CP08 como *pendiente de confirmar* (no marcarlo fallido).

### Código 9 — Status not recognized  ⚠️ candidato a defecto — requiere decisión
- **Antes:** `Status="FAILT"` → la API **ACEPTA** (código 0).
- **La nota oficial dice «Status value is not valid for the operation»** → la validez de Status es
  **por operación**: en Register debería aceptar solo SUCCESS/VOID; `FAILT` debería dar **9**.
  Como la API lo acepta, hay dos lecturas:
  - **(a) Defecto:** la API no está rechazando un Status inválido para Register (no cumple el catálogo).
  - **(b) Legacy preservado:** `FAILT` era un estado real del legacy (la colección original lo usaba)
    y se mantiene a propósito.
- **Acción inmediata:** probar `Status="ZZZ"` (basura pura). Si `ZZZ` → 9 pero `FAILT` → 0, entonces
  `FAILT` es legacy-aceptado (usar `ZZZ` en el CP para el 9). Si `ZZZ` → 0 también, es **defecto**.
- **En el test:** cambiar `FAILT` por `ZZZ`; si sigue en 0, levantar defecto. **→ pregunta 2 (requerimiento vs legacy).**

### Código 10 — Agent not configured  ⚠️ requiere dato de BD
- **Antes:** ExternalID de agente **999999 inexistente** → daba **15**.
- **La nota oficial:** «Agent has **no commission schema**» → 10 = agente que **EXISTE pero sin esquema**.
  Un agente inexistente no es 10: según parseo del ExternalID da **7** (no parseable) o **15** (parsea
  pero no existe → excepción).
- **Qué falta:** un `ExternalID`/`Entity` de un **agente REAL de TEST sin esquema de comisión Lunex**.
  Consulta conceptual (pedir a DEV los nombres reales de tabla):
  ```sql
  SELECT TOP 5 a.IdAgent, a.Entity
  FROM <tabla_agentes> a
  LEFT JOIN <tabla_esquema_comision_lunex> e ON e.IdAgent = a.IdAgent
  WHERE e.IdAgent IS NULL;
  ```
- **En el test:** reemplazar el agente 999999 por ese agente real sin esquema. **→ pregunta 3 (dato BD/DEV).**

### Código 15 — Internal error  ⚠️ usar como detector de defectos
- La nota: «Unexpected server error». **Por diseño no debería dispararse por entradas de usuario.**
- Todo lo que hoy cae en 15 desde una entrada de usuario (ej. agente inexistente) es un **error
  controlado faltante** → documentarlo como defecto candidato. En el CP, dejar 15 solo para el
  escenario que DEV confirme como interno-por-diseño. **→ pregunta 4 a DEV/código.**

---

## Cambios YA en `test_CP09_CatalogoErrores.py`
| Code | Antes | Ahora | Estado |
|---|---|---|---|
| 1 | `{}` → 5 | **cuerpo vacío o JSON malformado** | ✅ resuelto |
| 5 | quitar SKU → 10 | **malformar `TransactionDate`** (no tocar SKU) | ✅ resuelto |
| 8 | `SKUType="ZZZ"` → 10 | pendiente: confirmar catálogo global de SKUType | ⚠️ DEV |
| 9 | `Status="FAILT"` → 0 | probar `Status="ZZZ"`; si sigue 0 = defecto | ⚠️ decisión |
| 10 | agente 999999 → 15 | **agente real sin esquema** (dato BD) | ⚠️ dato BD |
| 15 | — | detector de «error controlado faltante» | ⚠️ DEV |

Los que **ya salen bien** (2, 3, 4, 6, 7, 12) se dejan igual — el arnés es correcto.

## Lo que aún requiere código/DEV (corto, para Big C / Sergio)
1. **Orden de validación** de RegisterTransaction y **si `SKUType` tiene catálogo global** (para el código 8) y con qué valor se alcanza.
2. **Status=FAILT en Register:** ¿el requerimiento manda rechazarlo (9) o se preserva como legacy? (¿qué hacía Urano?)
3. **ExternalID/Entity de un agente TEST real SIN esquema de comisión** (para el 10 limpio), o los nombres de tabla para sacarlo por BD.
4. **Código 15:** qué entradas son «internas por diseño» vs. deberían ser error del catálogo.
