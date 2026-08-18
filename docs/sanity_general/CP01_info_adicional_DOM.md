# CP01 — Mapa de DOM en vivo: capa "Información Adicional" (customer-id)

> Capturado en vivo desde `https://test-hermes.maxilabs.net/transfers`, ambiente TEST,
> agente `0020-TX`, App version 6.8.0. Fuente de verdad para construir la capa estable
> del sanity en AutomationAgent. Idioma de captura: Español (los textos de país/tipo de
> ID son idénticos en EN/ES, así que el mapeo texto→testid es language-agnostic).

## Diagnóstico de la inestabilidad

El código manual de `HERMES2-qa` (`additional_info_tab.py`, `additional_info_questionnaire_tab.py`)
falla por tres razones, TODAS evitables con lo capturado:

1. **Selección de dropdowns "por texto"** (`select_option_by_text` sobre `button.dropdown-item`):
   depende de que las opciones ya estén renderizadas. En carga lenta el scan cae en vacío.
   → **FIX:** cada opción tiene `data-testid` determinístico. Se resuelve texto→testid una vez
     (los items están en el DOM aunque el dropdown esté cerrado) y se hace click al testid exacto.
2. **Selectores frágiles** para tab y botón Aceptar (`#ngb-nav-1`, `button.footer-btn-accept`).
   → **FIX:** usar el tab por texto+rol y Aceptar por texto (`Aceptar|Accept`) con espera por estado.
3. **Esperas fijas** (`wait_for_timeout`) en vez de esperar la condición real de render.
   → **FIX:** `smart_click` + espera del input `...-dropdown-input` visible antes de operar.

---

## Botón que ABRE la Info Adicional (por tipo de envío)

`transfer-payers-money-info-additional-info-0-{tipo}-additional-info-button-button`
donde `{tipo}` ∈ `cash | deposit | mobile | home | atm`.
Ícono: `...-additional-info-button-icon-icon-svg`.

## Ficha "Información Adicional" (Identificación del Cliente)

| Campo | data-testid (ESTABLE) | Notas |
|---|---|---|
| Tab "Información Adicional" | `#ngb-nav-0` (frágil) | Preferir `button.compliance-btn-tab:has-text('Información Adicional'\|'Additional Info')`. Es el tab activo por defecto. |
| (i) ¿Por qué se requiere? | `compliance-why-is-this-info-required-icon-svg` | Modal: `compliance-why-is-this-info-required-modal` |
| Limpiar todo | `request-id-clear-fieldsicon-icon-svg` | Modal confirm: `compliance-modal-clear-info` |
| País de emisión (input) | `compliance-id-info-form-country-customer-id-dropdown-input` | placeholder "País de emisión" |
| País de emisión (opciones) | `compliance-id-info-form-country-customer-id-{N}-dropdown-item` | N=0..25, texto = país |
| Tipo de Identificación (input) | `compliance-id-info-form-id-type-customer-id-dropdown-input` | |
| Tipo de Identificación (opciones) | `compliance-id-info-form-id-type-customer-id-{N}-dropdown-item` | N=0.. , texto = tipo |
| Número de ID | `compliance-id-info-form-id-number-customer-id-input` | (NO estaba en el locator file actual) |
| Fecha de expiración | `compliance-id-info-form-expiration-date-customer-id-input` | placeholder mm/dd/yyyy (NUEVO) |
| Fecha de Nacimiento | `request-id-birth-date-input` | placeholder mm/dd/yyyy (NUEVO) |
| Foto Frente ID | `compliance-customer-id-form-carousel-element-container-0` | opcional en el flujo simple |
| Foto Otro | `compliance-customer-id-form-carousel-element-container-1` | |
| Carousel prev/next | `compliance-customer-id-form-carousel-prev-button` / `-next-button` | |
| Título ficha | `compliance-customer-id-form-title-h5-heading` | ancla de "modal cargado" |
| Aceptar | `button.footer-btn-accept` (sin testid) | usar texto `Aceptar\|Accept` |
| Regresar A Envío | (sin testid) | texto `Regresar A Envío\|Back to Transfer` |

### Opciones País de emisión (texto → índice)
ARGENTINA(0) BANGLADESH(1) BOLIVIA(2) BRAZIL(3) CHILE(4) COLOMBIA(5) COSTA RICA(6)
DOMINICAN REPUBLIC(7) ECUADOR(8) EL SALVADOR(9) GUATEMALA(10) HONDURAS(11) INDIA(12)
ISRAEL(13) MEXICO(14) NEPAL(15) NICARAGUA(16) PAKISTAN(17) PANAMA(18) PARAGUAY(19)
PERU(20) PHILIPPINES(21) UNITED STATES(22) URUGUAY(23) VENEZUELA(24) VIETNAM(25)

### Opciones Tipo de Identificación (dependen del país)
Para EL SALVADOR: MATRICULA CONSULAR(0), NON US PASSPORT(1), DUI: DOCUMENTO ÚNICO DE IDENTIDAD(2).
> El set cambia según país → NO cablear índices; resolver por texto→testid en runtime.

---

## Tab "Cuestionario" (compliance) — para CPs que lo requieran (no CP01 simple)
- Tab: `#ngb-nav-1` (frágil) → preferir `button.compliance-btn-tab:has-text('Cuestionario'|'Questionnaire')`
- Relationship input: `questionnaire-form-compliance-container-relationship-dropdown-input`
- Purpose input: `questionnaire-form-compliance-container-purpose-dropdown-input`
- Source of funds input: `questionnaire-form-compliance-containersource-of-funds-dropdown-input` (ojo: sin guion antes de "source")
- Opciones: mismo patrón `...-{N}-dropdown-item`

## Modal "Transacción de terceras personas" (third-party)
- Sí: `compliance-is-your-money-modal-yes-button`
- No: `compliance-is-your-money-modal-no-button`

---

## Diseño de la capa estable (AdditionalInfoMixin)

```
seleccionar_opcion_dropdown(campo_input_testid, item_prefix, texto):
    1. esperar input visible (compliance-customer-id-form-title-h5-heading como ancla del modal)
    2. click en input (abre dropdown)
    3. resolver: entre [data-testid^=item_prefix][data-testid$=-dropdown-item],
       encontrar el que innerText == texto (normalizado) → click a ESE testid
    4. verificar input.value == texto ; si no, reintentar 1x

llenar_info_adicional_simple(pais, tipo_id, num_id, exp, dob):
    - abrir con transfer-payers-money-info-additional-info-0-{tipo}-additional-info-button-button
    - esperar compliance-customer-id-form-title-h5-heading
    - país  → seleccionar_opcion_dropdown(country input, country item prefix, pais)
    - tipo  → seleccionar_opcion_dropdown(id-type input, id-type item prefix, tipo_id)
    - num   → fill compliance-id-info-form-id-number-customer-id-input
    - exp   → fill compliance-id-info-form-expiration-date-customer-id-input
    - dob   → fill request-id-birth-date-input
    - Aceptar (texto) con espera de cierre del modal
```

Ventaja: 0 dependencia de timing de opciones, language-agnostic, y sin selectores CSS frágiles.

---

# CP01 Step 7 — KYC Hold en Chronos (stack legacy)

> Capturado en vivo: `https://test-apps.maxilabs.net/Chronos/Frontend/compliance/kyc-hold`
> Título: "Know Your Customer Hold". Ambiente TEST.

## Realidad del DOM
- **0 `data-testid`** en toda la página. Stack legacy: Angular + PrimeNG `p-table` (`ui-table-scrollable-*`) + Angular Material (toolbar `mat-icon-button`).
- Por eso aquí NO aplicamos la estrategia testid; usamos anclas por rol/label/id-por-índice.

## Anclas estables encontradas
| Elemento | Selector estable |
|---|---|
| Buscador | `input.form-control[placeholder*="Agent Code"]` (placeholder: "(Agent Code, Agent Name, Claim Code, Folio, Sender Name)"). Sin id/name. |
| Tabla (header) | `table.ui-table-scrollable-header-table thead tr th` (ancla de "cargó") |
| Tabla (body) | `table.ui-table-scrollable-body-table` |
| Fila | `tr.handle.ng-star-inserted` ; resaltada = `tr.handle.row-cyan` (Agent Notification Automatic) |
| Fila por remitente | `tbody tr:has-text('<SENDER NAME>')` |
| Checkbox Review Kyc (fila N) | `#ReviewKycChkbx{N}` (ID estable por índice) |
| Checkbox Physical Copy (fila N) | `#PhysicalChkbx{N}` |
| Checkbox To KYC (fila N) | `#ToKYCChkbx{N}` |
| Refrescar / Email | botones verdes junto al buscador (mat-icon-button) |
| Menú / Logout / Agent Monitor | toolbar `button[title='Menu'|'Logout'|'Agent Monitor']` |

## Columnas de la grid (orden)
Review Kyc · Physical Copy · Date of Transfer · Detail(▸) · Agent Code · Folio · Amount · Sender Name · Beneficiary · Country · Aggregator. Paginación abajo.

## Interacción de liberación (según modelo actual `release_ofac_hold_transaction`, verificar en corrida real)
1. Click en la fila del remitente → `page.get_by_text(sender_name).first.click()` (abre diálogo de detalle).
2. `page.get_by_label("Release Reason:").select_option("1")`.
3. `page.get_by_role("button", name="Release").click()`.
4. `page.get_by_role("button", name="  Close").click()` (ojo: dos espacios).
> El DOM del diálogo de detalle/Release aún NO capturado (no se hizo click para no liberar una transacción real ajena). Capturar durante CP01 real con nuestra propia transacción.

## Navegación a la página (evitar depender del menú)
`go_to_kyc_hold_page` usa toolbar→Compliance→KYC Hold. Más estable: **navegar directo por URL**
`…/Chronos/Frontend/compliance/kyc-hold` (funciona con la sesión activa, como se validó aquí) y esperar
`table thead tr th` visible. La fila del remitente requiere **polling con reload** (la transacción tarda en caer en KYC Hold tras el envío).

## Estrategia de espera (matar flakiness de "la fila no aparece")
- Loop: buscar por sender → si no aparece, `reload` + esperar `networkidle` → reintentar (hasta ~20 intentos).
- Usar el buscador para filtrar por Folio (más único que el nombre) cuando se tenga el folio del envío.
