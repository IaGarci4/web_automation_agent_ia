# KRA-1526 — Análisis de endpoints IdUser / IdAgent y regla mono/multi-agente
### Sesión de investigación · 8 de septiembre de 2026 · Hermes 2 TEST (agente 0040-OK)

---

## 1. La regla real (confirmada por DEV y por el JWT)

Eduardo López (DEV) confirmó en el chat:

> "para multiagentes la validación por idAgent no aplica … solo aplica por IdUser"

**Esto NO es un bug — es el diseño.** Lo verifiqué decodificando el JWT del usuario multi-agente
`hermes2multi11`: el token **no contiene `IdUser` ni `IdAgent`**. Solo trae:

```
sub  = c818ee40-ea35-4ae7-85ed-46f78a859f0f   (UUID de Keycloak)
preferred_username = hermes2multi11
```

El middleware resuelve en el servidor, a partir del `sub`, **qué usuario y qué agentes** tiene
autorizados. Como un multi-agente está asociado a *varios* IdAgent, validar un IdAgent puntual
en el request no tiene sentido en ese modelo — por eso un multi-agente puede cambiar el IdAgent
y sigue recibiendo 200. Lo que **siempre** se valida es el IdUser, porque un usuario es único.

| Tipo de usuario | Validación IdUser | Validación IdAgent |
|---|---|---|
| **Mono-agente** | Sí → 403 si no coincide | **Sí → 403 si no coincide** |
| **Multi-agente** | Sí → 403 si no coincide | **NO aplica → 200 aunque cambie** |

> Confirmación de campo (chat de Ignacio): multi-agente cambió IdUser → 403 correcto;
> cambió IdAgent (1242→4525) → 200 con datos. Es el comportamiento esperado.

### El discriminante existe en el API: `isMonoAgent`

Al capturar el tráfico del reporte de Money Transfers apareció el flag en el body:

```
POST /api/transactions/reports/money_transfers
  body: { idAgent, isMonoAgent, beginDate, endDate }
```

`isMonoAgent` es la bandera que el front envía y que el middleware usa para decidir si valida o
no el IdAgent. **Este flag es la clave para diseñar los casos**: el resultado esperado depende de
él.

---

## 2. Inventario de endpoints que usan IdUser / IdAgent

Capturado en vivo interceptando `fetch`/`XHR` en Hermes 2 TEST, más las colecciones de cURL del
Desktop. **El bug de IDOR original NO era solo la búsqueda global** — varios endpoints reciben
estos identificadores y todos deben quedar cubiertos por el middleware.

| # | Endpoint | Método | IdUser | IdAgent | Dónde viajan | Módulo |
|---|----------|--------|:---:|:---:|---|--------|
| 1 | `/api/bff/customer/search` | GET | ✅ | ✅ | query | **Búsqueda global** (el del ticket) |
| 2 | `/api/reports/balance_by_cashier` | GET | ✅ | ✅ | query | **Balance por Cajero** ← ambos IDs |
| 3 | `/api/reports/balance` | GET | — | ✅ | query | Balance de agente |
| 4 | `/api/transactions/reports/money_transfers` | POST | — | ✅ | **body** + `isMonoAgent` | Reporte de transacciones |
| 5 | `/api/agents/{id}/users_by_agent` | GET | — | ✅ | query + path | Catálogo de cajeros del agente |
| 6 | `/api/bff/user/agents` | GET | (deriva del JWT) | — | — | Lista de agencias del usuario |
| 7 | `/api/checks/checks/agents/{id}/check_limit` | GET | — | ✅ | path | Cheques — límite |
| 8 | `/api/checks/checks/agents/{id}/transaction_limits` | GET | — | ✅ | path | Cheques — límites de transacción |
| 9 | `/api/checks/checks/fees/agent/{id}` | GET | — | ✅ | path | Cheques — comisiones |
| 10 | `/api/checks/checks/configuration/fees/agent/{id}` | GET | — | ✅ | path | Cheques — config comisiones |
| 11 | `/api/checks/checks/issuer/{id}/history` | GET | — | ✅ | path | Cheques — historial emisor |

**Observaciones para el diseño de pruebas:**

- **#1 y #2 son los más críticos**: llevan IdUser **e** IdAgent juntos, así que permiten probar
  las dos variables de forma independiente en el mismo request. #2 (Balance por Cajero) es un
  segundo caso de cobertura además de la búsqueda global.
- **#4 manda los IDs en el body, no en query** — y trae `isMonoAgent`. Cambia la mecánica de la
  prueba (hay que editar el `--data`/`-d` del curl, no la URL).
- **#7–#11 llevan el IdAgent en el path** (`/agents/{id}/…`), no en query. Un tercer patrón.
- El middleware debe cubrir los **tres patrones**: query param, body y path param.

---

## 3. Los dos ambientes / dominios

| Ambiente | Front | API BFF |
|---|---|---|
| TEST | `test-hermes.maxilabs.net` | `test-hermes-api-containers.maxilabs.net` |
| PROD | `hermes.maxiagentes.net` | `hermes2-api.maxiagentes.net` |

> El curl del multi-agente del chat usa PROD (`hermes2-api.maxiagentes.net`).
> Los casos anteriores usaban TEST. Documentar el ambiente por caso.

**El token JWT vive 20 minutos** (exp − iat = 1200s). Relevante para automatizar: hay que tomar un
token fresco en cada corrida.

---

## 4. Diagnóstico de los 7 casos actuales (testcases_1788902766796.xlsx)

| Caso | Estado | Problema |
|---|---|---|
| CP01 Happy Path IdUser+IdAgent propios → 200 | ✅ correcto | — |
| CP02 IdUser ajeno → 403 | ✅ correcto | núcleo de la prueba |
| CP03 IdAgent ajeno → 403 | ⚠️ **incompleto** | Solo válido para **mono-agente**. Falta decir explícitamente que es mono-agente. |
| CP04 Multi sin agencia, IdAgent varía → 200 | ✅ correcto | pero mezcla conceptos (ver abajo) |
| CP05 Multi con agencia, IdUser ajeno → 403 | ✅ correcto | — |
| **CP06 Multi con agencia, IdAgent ajeno → 403** | ❌ **INCORRECTO** | **Contradice la regla de DEV.** Para multi-agente el IdAgent NO se valida → responde **200**, no 403. Este caso haría fallar una prueba que en realidad pasa. |
| CP07 Happy Path PROD → 200 | ✅ correcto | — |

**Conclusión:** hay que rediseñar. El error grave es **CP06** (espera 403 donde el sistema
responde 200 por diseño). Además falta:
- Distinguir explícitamente mono-agente vs multi-agente en cada caso.
- Cubrir el **segundo endpoint con ambos IDs** (`balance_by_cashier`).
- Cubrir el patrón **body** (`money_transfers` con `isMonoAgent`).
- El caso de **regresión** que pediste: tras un 403, volver a los IDs correctos y confirmar que
  regresan las coincidencias (los clientes del teléfono `8118615244`).

---

## 5. Dato de negocio para los casos (del response real del chat)

Búsqueda del teléfono `8118615244` con IdUser+IdAgent correctos (IdAgent=1242) devuelve **11
clientes** (`totalRecords: 11`), todos con `idAgent: 1242`. Entre ellos:
ADRIANA LOPEZ, ANTONELA GALARDON, ANTONIO GALARZA, FERNANDA LOPEZ, GENARO ROBLES, GERMAN VALENTIN,
IGNACIO ANTONIO GARCIA, YULISA ROJAS, IGNACIO GARCIA, JOAQUIN GUZMAN, ANTONIO TEST.

Ese "11 registros / todos idAgent=1242" es el **criterio de regresión**: si tras restaurar los IDs
correctos la consulta devuelve esos registros, la prueba pasó.

---

*Fuente: captura de tráfico en vivo (fetch/XHR interceptor) en Hermes 2 TEST, decodificación del
JWT multi-agente, colecciones cURL del Desktop y el chat DEV (Eduardo López / Ignacio García).*
