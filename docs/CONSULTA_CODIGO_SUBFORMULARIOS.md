# Consulta #2 — Sub-formularios de Deposit / Home / Mobile / ATM (proyecto `transfers_`)

> **Para:** el skill de análisis de código (Big C / Little C).
> **Contexto resuelto:** ya confirmamos que la app desplegada en `test-hermes.maxilabs.net/transfers` es el proyecto Nx **`transfers_`** (el DOM real usa `transfer-payers-money-info-...-0-cash-...-input` y `transfer-payers-0-tab-title-N`, que según tu análisis previo solo existen en `transfers_`).
> **Objetivo:** obtener con exactitud los `data-testid`, `formControlName` y campos de los **4 sub-formularios NO-Cash**, para replicarlos sin grabar ni adivinar. Ya tenemos Cash 1:1.

## Referencia (lo confirmado para Cash)
`transfers_/src/app/components/organisms/transfers-money-info-cash-form/transfers-money-info-cash-form.component.html`
Patrón: `testId() + '-<campo>' + '-' + numberOfTab() + '-cash'`, campos: `city`, `city-guide`, `fee-type`, `amount`, `payer`, `branch-selected`, `additional-info`.
Ej. real en DOM: `transfer-payers-money-info-amount-0-cash-amount-input`.

## Lo que necesito (por cada uno de los 4 componentes)
Lee los **.html** (y el .ts si hace falta) de:
- `transfers-money-info-deposit-form`
- `transfers-money-info-home-form` (o el nombre real del de Domicilio)
- `transfers-money-info-mobile-form` (Móvil/Wallet)
- `transfers-money-info-atm-form`

Y para **cada uno** entrega:

1. **El segmento final del testid**: ¿es literalmente `-deposit` / `-home` / `-mobile` / `-atm` (mismo patrón que Cash con el string cambiado), o difiere? Dame el string exacto que produce cada template.
2. **Tabla de campos** con: label (ES/EN) · `data-testid` COMPLETO resultante (asumiendo `numberOfTab()=0`) · `formControlName` · tipo de control (input / dropdown / typeahead / date / checkbox) · ¿requerido? · validaciones · opciones si es dropdown.
3. **Campos propios** de cada tipo (los que NO están en Cash): p. ej. Deposit → `accountType` + `accountNumber`; ATM → tarjeta; Mobile → teléfono/wallet; Home → dirección de entrega.
4. Si algún tipo **no usa** ciertos campos de Cash (p. ej. sin `fee-type` o sin `branch-selected`), indícalo.

## Formato de respuesta
Un JSON así (uno por tipo), para cargarlo directo:
```json
{
  "deposit": {
    "testid_suffix": "-deposit",
    "fields": [
      { "field": "amount", "testid": "transfer-payers-money-info-amount-0-deposit-amount-input",
        "form_control": "amount", "control": "input", "required": true, "validation": "..." },
      { "field": "accountNumber", "testid": "...", "form_control": "accountNumber", "control": "input", "required": true, "validation": "numérico N dígitos" },
      { "field": "accountType", "testid": "...", "form_control": "accountType", "control": "dropdown", "required": true, "options": ["..."] }
    ]
  },
  "home":   { "...": "..." },
  "mobile": { "...": "..." },
  "atm":    { "...": "..." }
}
```
Cita el archivo/línea de cada dato. Si un template no existe o el nombre difiere, dilo.
