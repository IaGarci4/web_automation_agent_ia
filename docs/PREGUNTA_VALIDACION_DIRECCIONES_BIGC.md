# Pregunta para Big C — ¿Cómo validar el campo de Dirección (address) en Hermes 2?

> **Para:** el skill de código (Big C / Little C), con acceso al **código fuente
> del frontend de Hermes 2** (Angular) y su BFF.
> **De:** automatización QA (KRA-1527 · Money Transfer).
> **Objetivo:** entender EXACTAMENTE cómo el front decide que una dirección está
> "verificada" para poder llenar ese campo de forma determinista en Playwright y
> que **la validación de direcciones no detenga el flujo**.
> **Usa Codebase Memory MCP** (`mcp__codebase-memory-mcp__*`) sobre el repo del
> frontend de Hermes 2; si no está indexado, indícalo y reindexa antes de confiar
> en el grafo.

---

## 1. Contexto (qué hacemos y dónde se atora)

En Money Transfer, al llenar el domicilio del cliente, el campo de dirección usa
un **autocomplete con PostGrid**. Nuestra automatización teclea una dirección
real y a veces el campo queda marcado como **"Dirección no verificada"**, lo que
frena el envío. Necesitamos saber, desde el código, qué condición EXACTA marca
verificada / no verificada, para dejar el control en estado válido sin adivinar.

## 2. Lo que YA sabemos del lado QA (confírmalo o corrígelo con el código)

- Campo (data-testid): `transfer-customer-address-0-input`.
- Endpoint de sugerencias:
  `POST https://test-hermes-api-containers.maxilabs.net/api/bff/address/suggestions`
  · body `{"address":"<texto>"}`
  · respuesta `{status,message,data:[{id,mainText,secondaryText,provider:"postgrid"}]}`
  (`mainText`=calle, `secondaryText`=`CIUDAD ZIP`).
- `.fill()` (set directo del value) **no** dispara el autocomplete; solo se
  dispara con pulsaciones reales (keydown/keyup por carácter).
- El ZIP autocompleta ciudad/estado.
- Hipótesis actual (a confirmar): la dirección solo cuenta como válida si se
  **selecciona una sugerencia** de PostGrid; el texto libre o un auto-commit al
  perder foco (blur) la dejan "no verificada".
- Mensaje visible aproximado: **"Dirección no verificada. Revisa los datos y
  elige otra."**

## 3. Preguntas concretas (esto es lo que necesito)

1. **Ubicación**: ¿en qué componente/módulo/plantilla vive el campo de dirección
   del cliente de Money Transfer? (ruta de archivo, nombre de la clase del
   componente, el `FormControl`/`FormGroup` y el nombre del control).
2. **Regla de verificación**: ¿qué valida el "no verificada"? ¿Es un `Validator`
   (síncrono o asíncrono) de Angular, un flag de estado, o lógica en el
   componente? ¿Cuál es la **condición exacta** que lo pone en error?
3. **Estado "verificada"**: al **seleccionar una sugerencia** de PostGrid, ¿qué
   se setea? (¿el `FormControl` guarda el **objeto** de la sugerencia con su
   `id`/`placeId`, un flag `verified=true`, lat/long, un objeto address
   completo?). ¿Qué propiedad/valor es la que hace que el validador pase?
4. **Comparación**: ¿el validador exige que el texto **coincida con una
   sugerencia seleccionada** (un objeto), o basta un formato (número+calle)?
   ¿Compara contra el último `data[]` devuelto por `/address/suggestions`?
5. **Eventos**: ¿qué pasa en `blur`/`change` y al **teclear después** de haber
   seleccionado? ¿Se auto-confirma la primera sugerencia? ¿Se **invalida** el
   estado verificado si el usuario edita el texto tras seleccionar?
6. **Interacción con ZIP**: al cambiar el ZIP (o al autocompletar ciudad/estado),
   ¿se **resetea** o re-dispara la validación de la dirección?
7. **Backend/submit**: ¿hay validación de dirección en el **envío** (BFF/API) o
   solo en el front? ¿Qué **campos del payload** de la transacción representan la
   dirección verificada (p. ej. `addressId`, `postgridId`, `verified`,
   `latitude/longitude`, objeto `address`)? ¿Cuáles son obligatorios?
8. **Forma mínima determinista (lo más importante para automatizar)**: ¿cuál es
   la manera MÍNIMA y estable de dejar el control en estado "verificado" sin UI
   frágil? Por ejemplo:
   - ¿Se puede setear el `FormControl` con el **objeto sugerencia completo**
     (`patchValue({...})`) y marcarlo `markAsTouched()`/`updateValueAndValidity()`
     para que pase el validador?, o
   - ¿hay que emitir un **evento/onSelect** específico del componente de
     autocomplete?, o
   - ¿basta con elegir por teclado la fila cuyo `id` viene en `data[]`?
   Indica la ruta exacta (método/servicio) que commitea la selección.
9. **Detección del error (para el reporte)**: el **texto exacto** del mensaje y
   el **nodo DOM** (clase/`data-testid`/`aria`) que lo renderiza, para
   detectarlo con precisión en la automatización.

## 4. Consultas sugeridas al Codebase Memory MCP (para que las corras)

En el repo del **frontend de Hermes 2** (Angular):

```
# ¿está indexado y al día?
check_index_coverage / index_status
# si hace falta:
index_repository {"repo_path": "<ruta del repo del front de Hermes 2>"}

# localizar el campo y su validación
search_code  "transfer-customer-address"        # el testid del input
search_code  "address/suggestions"              # llamada al BFF de PostGrid
search_code  "postgrid"                          # proveedor
search_code  "no verificad"                      # texto del error (ES)
search_code  "not verified" / "verified"         # flag/estado
search_code  "AddressValidator" / "addressValidator" / "verifiedAddress"

# arquitectura y llamadas
get_architecture                                 # módulo del formulario de cliente/MT
search_graph  "address" / "suggestion" / "autocomplete"
trace_path    <función que llama a /address/suggestions>   # qué setea el estado verificado
trace_path    <validator o control de dirección>          # quién lo invalida/valida
```

Si el front no está en el grafo, usa **Little C** para extraer los fragmentos
del componente de autocomplete de dirección, el validador y el servicio que
llama a `/address/suggestions`, y pásalos a **Big C** para el análisis.

## 5. Formato de respuesta que necesito de vuelta

Para poder aplicarlo directo a los scripts de Playwright, respóndeme con:

1. **Archivo(s) y símbolo(s)** relevantes (ruta + clase/método).
2. **Condición exacta** que marca verificada vs no verificada (en palabras y, si
   puedes, el fragmento de código).
3. **La forma mínima determinista** para dejar la dirección válida (opción por
   modelo `patchValue`+evento, o la secuencia de selección correcta), con el
   nombre exacto del método/evento a disparar.
4. **Campos del payload** de la transacción que deben ir poblados para que el
   envío no rechace la dirección.
5. **Selector/texto** exacto del mensaje de error para detectarlo.
6. Cualquier **efecto colateral** (blur, cambio de ZIP, edición posterior) que
   invalide el estado, para evitarlo en el script.

> Con esto ajustaremos `resolver_direccion_cliente` (en
> `src/pages/hm_transferelektra_page.py` y en
> `src/tests/etiquetas/KRA_1527/flujos/transferencia_page.py`) para que llene la
> dirección de forma 100% determinista y la validación no detenga el flujo.
