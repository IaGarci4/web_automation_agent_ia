# Brief para Metis — cómo aislar cada Errorcode de Lunex Notifications

> **Objetivo:** el CP09 provoca cada Errorcode del requerimiento a propósito.
> Cuatro no salen con el código esperado: la API responde **otro** código, de la
> familia de validación de agente/esquema. Necesitamos las **reglas de negocio**
> (orden de validación, datos de agente/esquema) para construir un request que
> aísle cada código. Sospecha: **no es bug de código, es interpretación de
> nuestro request.**
>
> **Documento técnico a investigar (léelo entero, incluida la sección
> «Error codes» y las páginas relacionadas):**
> https://maxims.atlassian.net/wiki/spaces/~62e05c2f3aaeedcae755fd4e/pages/2141585409/Lunex+Notifications+API+Integration+Guide
> Relacionadas que enlaza: «Transacciones Duplicadas Lunex», «[Eng] Processes
> Definition: Integration vs Certification», «KYC RULES ANALYSIS».

## Contexto mínimo

- API de notificaciones (Lunex → Maxi). Endpoint base:
  `https://zeus-services.maxilabs.net/api/v1/lunex/Payments/`
  (`RegisterTransaction`, `CancelTransaction`). Ambiente TEST.
- Identidad de nuestras pruebas: `Login=Lun3xProdUser`, `Entity=MX01D3643A`,
  `ExternalID=M120312738S13491` (= `M{IdAgent*IdUser}S{IdUser}`, IdAgent 8918,
  IdUser 13491), `CID=797dd3a85456df7f014efd19320eefdw`.
- Firma: `Md5 = MD5(Login+Password+Key)`, hex minúsculas.
- Un alta VÁLIDA con esa identidad responde `Errorcode 0` y persiste bien.
- Catálogo de Errorcodes del requerimiento: 0 éxito · 1 Request is null · 2
  Transaction already exists · 3 Action not recognized · 4 Session invalid · 5
  Validation error · 6 Key invalid · 7 ExternalID not recognized · 8 SKU Type
  not recognized · 9 Status not recognized · 10 Agent not configured · 12
  Transaction not cancellable · 15 Internal error.

## Lo que YA sale bien (para referencia de que el arnés funciona)

| Esperado | Cómo lo rompemos | Responde | ✔ |
|---|---|---|---|
| 2 | reenviar el mismo `TransactionID` | 2 | ✔ |
| 3 | `Action="no_lunex"` | 3 | ✔ |
| 4 | `Md5` inválido | 4 | ✔ |
| 6 | `Key=0` (con Md5 recalculado) | 6 | ✔ |
| 7 | `ExternalID="NOPARSE"` (no parseable) | 7 | ✔ |
| 12 | cancelar un `TransactionID` inexistente | 12 | ✔ |

## Lo que NO sale con el código esperado — necesitamos regla de negocio

| # | Esperado | Cómo lo rompemos hoy | Responde | Hipótesis nuestra |
|---|---|---|---|---|
| A | **1** Request is null | cuerpo JSON vacío `{}` | **5** | `{}` es JSON válido sin campos → se va a «Validation». ¿Qué cuerpo dispara 1? ¿Body HTTP totalmente vacío, `null`, o no-JSON? |
| B | **5** Validation error | quitar el campo `SKU` | **10** | quitar `SKU` rompe la resolución del esquema del agente antes que la validación de campos → 10. ¿Qué campo requerido se puede omitir para caer en 5 «limpio»? ¿Cuál es el ORDEN de validación? |
| C | **8** SKU Type not recognized | `SKUType="ZZZ"` | **10** | el esquema del agente se indexa por SKUType; uno desconocido hace fallar el lookup → 10. ¿Es alcanzable el 8? ¿Con qué SKUType? |
| D | **10** Agent not configured | `ExternalID` de agente 999999 (inexistente) | **15** | un agente que NO existe revienta a error interno (15) en vez de «no configurado» (10). Para un 10 limpio necesitamos un agente que EXISTA pero SIN esquema de comisión. |
| E | **9** Status not recognized | `Status="FAILT"` | **0 (ACEPTA)** | la API acepta un Status fuera de SUCCESS/VOID. ¿El requerimiento realmente exige rechazarlo con 9, o aceptarlo es comportamiento legacy a preservar? |

## Preguntas concretas para el skill

1. **Orden de validación** de `RegisterTransaction`: ¿en qué secuencia valida la
   API (autenticación → cuerpo → agente/esquema → campos → SKU/SKUType → Status)?
   Eso explica por qué B, C y D colapsan en 10/15.
2. **Código 1**: ¿qué forma exacta de cuerpo produce «Request is null»? (vacío
   real, `null`, malformado, sin `Content-Type`…).
3. **Código 5 aislado**: ¿qué campo requerido conviene omitir para obtener un
   `Validation error` sin tocar la resolución del agente?
4. **Código 8**: ¿es alcanzable? Si sí, ¿qué valor de `SKUType` lo dispara sin
   caer en el esquema del agente (10)?
5. **Código 10**: ¿existe un **agente/ExternalID de TEST real pero sin esquema
   de comisión** que devuelva 10 limpio en vez de 15? (dato de negocio/BD).
6. **Código 9 / Status=FAILT**: ¿el requerimiento manda rechazarlo (code 9) o la
   API debe aceptarlo? ¿Qué hacía el legacy Urano?
7. **Código 15**: ¿qué entradas provocan «Internal error» por diseño vs. cuáles
   deberían ser un error controlado del catálogo?

## Formato en el que quiero la respuesta (para poder aplicarla al código)

Markdown, **una sección por cada código (1, 5, 8, 9, 10, 15)**, con esta forma:

```
### Código N — <nombre>
- Alcanzable: sí / no / condicionado
- Campo(s) a enviar u omitir: <exacto>
- Valor exacto: <exacto>
- Por qué produce este código: <1-2 líneas>
- Regla de negocio / página de Confluence que lo respalda: <cita o enlace>
- Si NO es aislable: por qué, y qué código es el correcto a esperar
```

Con eso ajusto los escenarios del CP09 (`test_CP09_CatalogoErrores.py`) para que
cada uno espere el código correcto, o lo reclasifique si el requerimiento dice
otra cosa.
