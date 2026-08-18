# Consulta al código fuente de Hermes2 — Catálogo País × Pagador × Tipo de envío

> **Para:** el skill de análisis de código fuente (Big C / Little C) con acceso a Hermes 2 (frontend Angular) y su backend/API.
> **De:** equipo de automatización QA (AutomationAgent).
> **Objetivo:** extraer de la LÓGICA REAL del código —sin grabar flujos ni adivinar— un banco de datos que relacione, para la pantalla de **Money Transfer / Transfers**:
> **País destino → Pagadores disponibles → Tipos de envío disponibles (Cash / Deposit / Home-Domicilio / Mobile-Móvil / ATM) → campos del formulario de cada tipo.**
>
> Solo nos interesan **los datos, las combinaciones y qué está disponible y qué no**. NO nos interesa el cálculo de fees/tipo de cambio.

---

## 0. Contexto mínimo (lo que ya sabemos)

- Pantalla: `https://test-hermes.maxilabs.net/transfers` (Angular, "App version 6.6.2").
- La sección **Transfer** tiene 5 tabs de tipo de envío, con `data-testid` estable por índice:
  - `transfer-payers-0-tab-title-0` → **Cash / Efectivo**
  - `transfer-payers-0-tab-title-1` → **Deposit / Depósito**
  - `transfer-payers-0-tab-title-2` → **Home / Domicilio**
  - `transfer-payers-0-tab-title-3` → **Mobile / Móvil**
  - `transfer-payers-0-tab-title-4` → **ATM**
  - Algunos tabs aparecen con la clase CSS `disabled-tab` (deshabilitados) según el contexto.
- Los campos del sub-formulario de **Cash** que ya tenemos mapeados llevan el segmento `cash` en su `data-testid`, p. ej.:
  - `transfer-payers-money-info-city-0-cash-dropdown-input`
  - `transfer-payers-money-info-fee-type-0-cash-dropdown-input`
  - `transfer-payers-money-info-amount-0-cash-amount-input`
  - `transfer-payers-money-info-payer-0-cash-input`
- Observación de negocio: **al seleccionar el País del beneficiario cambia todo** (qué pagadores hay y qué tipos de envío se habilitan). Queremos entender exactamente esa lógica.

---

## 1. Modelo de dominio y relaciones

1.1. Identifica las entidades/modelos/DTOs que representan:
   - **País destino** (Country/Destination).
   - **Pagador** (Payer / Payee / PayerBranch).
   - **Tipo de envío / método de entrega** (PaymentType / DeliveryMethod / PaymentMethod: Cash, Deposit, Home, Mobile, ATM).
   - **Moneda** (Currency) y **producto**, si intervienen.

1.2. ¿Cómo se **relacionan** entre sí? En concreto: la disponibilidad de un tipo de envío ¿depende de…?
   - solo el **país**,
   - solo el **pagador**,
   - la combinación **país + pagador**,
   - o además de **moneda / producto / corredor (corridor)**.

1.3. Da los **nombres reales** de las clases/DTOs/interfaces y sus **campos clave** (IDs, códigos, y flags de habilitación tipo `isEnabled`, `available`, `active`).

---

## 2. Origen de los datos (lo más importante)

2.1. Cuando el usuario **selecciona el país del beneficiario**, ¿qué **llamadas** dispara el frontend? Lista la **secuencia de endpoints** (orden).

2.2. Para cada endpoint relevante (p. ej. "payers por país", "tipos de pago por país/pagador", "catálogo de métodos"):
   - **Método** y **URL** (con path params / query params).
   - **Esquema del request** (campos).
   - **Esquema del response** (JSON) con un **ejemplo real** representativo.
   - Qué campo del response indica **disponibilidad** de cada tipo (¿vienen todos con un flag `enabled`, o solo vienen los habilitados?).

2.3. ¿Los pagadores y sus tipos disponibles vienen de **API**, de **config estática**, o de **BD**? Si es BD, indica **tablas** y columnas relevantes. Si es config, indica el **archivo**.

---

## 3. Algoritmo de disponibilidad (qué habilita/deshabilita cada tab)

3.1. Regla EXACTA que habilita o deshabilita cada tab de tipo de envío (Cash/Deposit/Home/Mobile/ATM). ¿Qué campo/flag del modelo controla la clase `disabled-tab` en el DOM?

3.2. ¿La lista de tabs es **fija** (siempre 5) y solo se habilitan/deshabilitan, o es **dinámica** (solo se renderizan los soportados)?

3.3. Escribe el **pseudocódigo** del algoritmo actual: dado (país, pagador, [moneda]) → devuelve el conjunto de tipos de envío disponibles. Indica el **archivo/clase/método** donde vive esa lógica (frontend y/o backend).

---

## 4. Enumeraciones e IDs

4.1. Tabla de **tipos de envío**: para cada uno, su **id numérico**, su **key** interno (el que usan los `data-testid`, p. ej. `cash`), su **índice de tab** (0..4) y sus **labels** ES/EN.

4.2. Lista de **países** soportados: id interno / código ISO / nombre visible / moneda. (Si son muchos, dame el catálogo completo o cómo obtenerlo.)

4.3. Cualquier otro catálogo estático relevante (tipos de cuenta para Deposit, tipos de documento, etc.).

---

## 5. Campos del formulario por tipo de envío

Para **cada** tipo (Cash, Deposit, Home, Mobile, ATM), dame la tabla de campos del sub-formulario **Transfer**:

| Campo (label ES/EN) | `data-testid` | `formControlName` | Tipo de control (input / dropdown / typeahead / date) | ¿Requerido? | Validaciones | Opciones (si aplica) |

5.1. **CLAVE — patrón de los `data-testid`:** ¿cómo se **generan** los `data-testid` de estos campos según el tipo de pago? Los de Cash son `transfer-payers-money-info-<campo>-0-cash-<sufijo>`.
   - ¿El segmento `cash` se **reemplaza** por `deposit` / `home` / `mobile` / `atm` (mismo patrón, distinto key)?
   - ¿O cada tipo tiene su **propio set** de testids distinto?
   - Dame el **patrón/plantilla exacto** (con el nombre de la variable que inyecta ese key) **o** la tabla completa de testids por tipo. Esto es lo que nos permite predecir los selectores sin grabar.

5.2. Campos **condicionales** o específicos por tipo (ejemplos que esperamos):
   - **Deposit**: "Type" (tipo de cuenta) + "Account number".
   - **ATM**: número de tarjeta / datos de tarjeta.
   - **Mobile**: teléfono / wallet.
   - **Home**: dirección de entrega.
   Confírmalos con sus testids/formControlName reales y sus reglas.

5.3. ¿Qué campos del **cliente** y del **beneficiario** (parte superior del formulario) **cambian según el país** (requeridos/ocultos/validación distinta)? Indica la regla.

---

## 6. Reglas especiales / excepciones

6.1. **Sucursal (branch):** ¿qué tipos y/o pagadores la exigen? ¿Cómo se determina que es obligatoria (el front muestra "Field required")?

6.2. Cualquier regla de negocio que active/desactive campos o cambie validaciones por país/pagador/tipo (límites, obligatoriedad, formato).

6.3. Casos donde un pagador aparece pero un tipo está **deshabilitado** aunque exista el tab (y por qué).

---

## 7. Ejemplos concretos (para validar)

Dame el detalle completo de **2–3 países** con variedad, incluyendo por cada pagador qué tipos están disponibles y cuáles no:
- **México** (tenemos activos: Elektra, BanCoppel, Soriana, Walmart, Aurrera, Bancomer, A Waldos, Farmacias del Ahorro, Chedraui Efectivo, Banorte).
- **1–2 países adicionales** con combinaciones distintas (p. ej. uno que tenga Deposit/ATM pero no Cash, o Bangladesh si existe), para ver los contrastes.

---

## 8. Formato de la respuesta que necesito

Por favor responde con: (a) una **explicación en prosa** breve del modelo y del algoritmo (§1–§3), citando **archivos/clases/métodos**; y (b) un **JSON consumible** con esta forma (para cargarlo directo como banco de datos):

```json
{
  "payment_types": [
    { "key": "cash", "id": 1, "tab_index": 0, "label_es": "Efectivo", "label_en": "Cash" }
  ],
  "countries": [
    { "id": 10, "iso": "MX", "name": "MEXICO", "currency": "MXN" }
  ],
  "payers": [
    { "code": "BANORTE", "country_iso": "MX", "search": "BANORTE", "needs_branch": false }
  ],
  "availability": [
    { "country_iso": "MX", "payer_code": "BANORTE", "types_available": ["cash", "deposit"], "types_disabled": ["home", "mobile", "atm"] }
  ],
  "fields_by_type": {
    "deposit": [
      { "label_en": "Account number", "testid": "transfer-payers-money-info-...-deposit-...", "form_control": "accountNumber", "control": "input", "required": true, "validation": "numeric, 10-18 dígitos" }
    ]
  },
  "testid_pattern": "transfer-payers-money-info-{field}-0-{typeKey}-{suffix}   // {typeKey} ∈ cash|deposit|home|mobile|atm ?",
  "availability_algorithm": "pseudocódigo o resumen del método y su archivo",
  "source_refs": ["ruta/archivo.ts#Clase.metodo", "ruta/Controller.cs#Endpoint"]
}
```

Notas para el análisis:
- Prioriza **exactitud** sobre completitud: si algo no está claro en el código, dilo explícitamente en vez de inferir.
- Cita siempre **dónde** (archivo/clase/método/endpoint) vive cada regla o dato.
- Si el catálogo de países/pagadores es demasiado grande para volcarlo entero, explica **cómo obtenerlo** (endpoint o tabla) y da una muestra representativa.
