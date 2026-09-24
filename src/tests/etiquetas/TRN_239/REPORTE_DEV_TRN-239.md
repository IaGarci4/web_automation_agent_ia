# TRN-239 · Hallazgos para Desarrollo (auditoría previa a producción)

> Migración BE Urano → API Lunex (FastAPI). Esta API sale a **producción** y la
> usan a diario todas las agencias de Maxi en EE. UU.: nada puede salir con un
> defecto silencioso. Fuentes de verdad: **Integration Guide** (Confluence),
> **código C# del legado** (Prometeo: `RESPUESTA_ERRORCODES` y
> `DTU_ITU_COMISIONES`) y **7 M de filas de producción** (`ConsultasSQLProd`).
>
> Regla de la etiqueta: el reporte muestra **OK solo si de verdad lo está** (sin
> hardcode). Lo que se desvía del comportamiento del legado se marca **FALLA** y
> se reporta aquí.

---

## 1. Defectos a confirmar/corregir con DEV

El código C# del legado (`LunexService.svc`) valida en este orden:
`r1(body=1) → r3(Action=3) → r9(Status=9) → r4(Md5=4) → Amount>0 → r5(modelo=5)
→ r6(Key=6) → r7(ExternalID=7) → r8(SKUType=8) → esquema de comisión (10)`.
Cada Errorcode tiene dueño en ese flujo. Si la API nueva no lo respeta, es un
cambio de comportamiento respecto al legado = riesgo en producción.

### D1 · La API ACEPTA un `Status` inválido (debería rechazar con 9)  🔴
- **Regla:** el legado valida `Status ∈ (SUCCESS, VOID)` en **r9** (antes incluso
  del Md5). Cualquier otro valor debe dar **Errorcode 9**.
- **Observado:** con `Status="FAILT"` la API responde **Errorcode 0 (Success)** y
  **persiste** la fila (LNStatus=FAILT, IdStatus=30 — indistinguible de un éxito).
- **Riesgo:** entran a `lunex.TransferLN` estados que en producción **no existen**
  (`Fallidas=0` en 7 M filas). Una conciliación por IdStatus no los separa.
- **Reproducir:** `POST …/Payments/RegisterTransaction` con un body válido y
  `Status="FAILT"` (o `"ZZZ"`). Casos: **CP07** y **CP09 code 9**.
- **Pregunta a DEV:** ¿se refuerza la validación r9 en la API nueva, o `FAILT` es
  un estado legacy que se preserva a propósito? (definir requerimiento).

### D2 · `SKUType` inválido da 10 en vez de 8  🟠
- **Regla:** el legado valida `SKUType ∈ (ITU, DTU)` en **r8**, *antes* de
  resolver el esquema del agente. Un SKUType no soportado debe dar **Errorcode 8**.
- **Observado:** con `SKUType="ZZZ"` la API responde **Errorcode 10** (Agent not
  configured) — se saltó r8 y falló en la resolución del esquema.
- **Riesgo:** el mensaje al cliente cambia; un integrador que espere 8 recibe 10.
- **Reproducir:** body válido con `SKUType="ZZZ"`. Caso: **CP09 code 8**.
- **Pregunta a DEV:** ¿la API nueva conserva la validación r8? ¿Existe un catálogo
  global de SKUType y en qué punto se valida?

### D3 · Agente inexistente da 15 (error interno no controlado)  🟠
- **Regla:** **Errorcode 10** = «Agent has no commission schema» → agente que
  **existe pero sin esquema** (confirmado en el C#: `GetOtherProductsCommission`
  devuelve null → `GetResponse(10)`). Un agente que **no existe** debería dar un
  error controlado (7 «ExternalID not recognized» o 10), **no 15**.
- **Observado:** con un ExternalID de agente inexistente (999999) la API responde
  **Errorcode 15 (Internal error)**.
- **Riesgo:** 15 es «unexpected server error»; dispararlo con una entrada de
  usuario es un error controlado faltante.
- **Reproducir:** body válido con `ExternalID` de un agente inexistente. Caso:
  **CP09 code 10**.
- **Pregunta a DEV:** ¿qué entradas de usuario deberían dar 15 (por diseño) vs.
  un error del catálogo? Y **necesitamos un agente REAL de TEST sin esquema de
  comisión** para probar el 10 limpio (query en `DTU_ITU_COMISIONES`, sección 4).

### D4 · Falta validación cruzada SKU ↔ SKUType ↔ País  🟡 (recomendación)
- **Hallazgo (Prometeo, DTU_ITU_COMISIONES §5):** la API solo valida
  `SKUType ∈ (ITU, DTU)` (r8), **no** que el SKUType corresponda al país real del
  SKU (`lunex.Product.IdCountry`). Se puede mandar un SKU internacional con
  `SKUType=DTU` (o viceversa) y la API lo aceptaría.
- **Riesgo:** combinaciones imposibles entran a la base.
- **Acción:** confirmar con DEV si debe validarse; si sí, agregar un CP que envíe
  un SKU con SKUType incoherente y espere rechazo.

---

## 2. DTU / ITU — VALIDADO contra 407 productos + `lunex.TransferLN`

Se cruzó `lunex.Product ⋈ Country` (por `IdCountry`) contra el `SKUType` real de
producción (`consultasBD-TRN-239.xlsx`). Resultado:

### D5 · `lunex.Product.IdCountry` NO corresponde al país real  🔴 (dato)
- **0 de 407** productos tienen el país de su nombre igual al del `JOIN`. Todos
  los productos de EE. UU. (AT&T, Cricket, T-Mobile, MetroPCS…) apuntan a
  **IdCountry 110 = KYRGYZSTAN**; «Afghanistan» → Argentina; «Russia» → Congo.
- **Consecuencia:** el `SKUType` **no se puede derivar del país** con esa tabla.
  Reportar a DEV: el FK `Product.IdCountry` está roto o apunta a otra tabla.

### La regla real (confirmada por datos, no por el país)
- **DTU = doméstico EE. UU.**: los **54 SKUType=DTU son TODOS 9xxx** (carriers de
  EE. UU.), sin excepción. `ITU` = internacional (7xxx/8xxx).
- Prometeo decía «DTU=México», que **contradice los datos**: DTU es EE. UU. Se
  descartó su regla de país.
- **Corrección en el repo:** `bd.productos_activos` ahora toma el `SKUType` **real
  de `lunex.TransferLN`** por SKU (dato de verdad); el prefijo (9xxx=DTU) queda
  solo como respaldo para SKUs sin ventas. Así el `SKUType` que manda el script
  coincide con lo que producción usó — sin adivinar ni depender del país roto.

### D6 · Existe `SKUType = "Pinless"` (y otros) fuera de (ITU, DTU)  🟠
- Producción tiene `SKUType` = **Pinless** (y en Query1: Unlimited, Egift,
  PinlessU). El código C# valida `SKUType ∈ (ITU, DTU)` (r8) → **debería
  rechazar Pinless**, pero producción lo tiene. Reportar: ¿r8 acepta más tipos?

### D7 · Un mismo SKU con varios `SKUType`  🟡
- SKU **8485 (Honduras)** aparece como **DTU, Pinless e ITU** a la vez; **9881
  (Telcel America)** como ITU y DTU. El mismo producto notificado con tipos
  distintos — inconsistencia de datos a revisar con DEV.

---

## 3. Sin hardcode — cómo lee el veredicto el CP09

- El veredicto de cada errorcode se decide con el **Errorcode real** que devuelve
  la API (`r.errorcode`), comparado contra el código que el **flujo C#** asigna a
  ese punto. **No hay resultados fijados a mano.**
- Se eliminó el enmascaramiento anterior (`PENDIENTES` y «aceptado = OK») que
  hacía pasar en verde desviaciones reales. Ahora:
  - código exacto → **OK**;
  - aceptó algo inválido, o devolvió otro código documentado → **FALLA (defecto,
    reportar a DEV)**;
  - fuera de catálogo / 5xx → **FALLA (flujo roto)**.
- Cada paso lleva la línea `REPRODUCIR → POST … · se rompe: <campo>` y el
  marcador `_MODIFICADO` al inicio del JSON de evidencia.

---

## 4. Lo que está correcto (sin hardcode)

- **CP01** healthcheck (status/DB UP) · **CP02** alta JSON+SOAP y paridad ·
  **CP03** cancelación (VOID/IdStatus 22) · **CP04** MD5 inválido (code 4) ·
  **CP05** validación/negativos (codes 5, 12) · **CP06** comisiones DTU/ITU
  coherentes con producción · **CP08** integridad e idempotencia (code 2).
- **CP09 — errorcodes que salen exactos:** 1 (body vacío), 2 (dup), 3 (Action),
  4 (Md5), 5 (TransactionDate malformado), 6 (Key), 7 (ExternalID), 12 (cancelar
  inexistente). *(1 y 5 pendientes de confirmar en la próxima corrida tras el
  ajuste de request.)*

---

## 5. Preguntas abiertas a DEV (resumen)

1. **r9/Status:** ¿la API nueva rechaza `Status` inválido con 9, o preserva
   `FAILT` legacy? (D1)
2. **r8/SKUType:** ¿se conserva la validación de SKUType (code 8) antes del
   esquema? ¿Catálogo global de SKUType? (D2)
3. **Agente sin esquema:** ExternalID/Entity de un agente **real de TEST sin
   esquema** para probar el 10 limpio; y qué entradas deben dar 15 vs. catálogo. (D3)
4. **SKU↔SKUType↔País:** ¿debe validarse la coherencia? (D4)
5. **DTU/ITU:** confirmar la definición real (producción dice DTU=EE.UU.). (§2)

> Nota de mantenimiento: hay dos carpetas, `TRN_239` (guion bajo, la etiqueta y
> el código) y `TRN-239` (guion, donde están los .md de Prometeo). Conviene
> consolidarlas en `TRN_239` para no duplicar.
