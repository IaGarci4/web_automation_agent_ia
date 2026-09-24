# KRA-1526 — Autorización IDOR (IdUser / IdAgent)

Prueba automatizada de la corrección del bug IDOR: la búsqueda global (y
endpoints relacionados) ya no debe devolver datos de otro usuario/agencia al
cambiar `IdUser` / `IdAgent` en el request.

Dos perfiles, **separados** en dos runners y dos reportes:

- **Mono-agente** (`.\kra1526.ps1`): el middleware valida IdUser Y IdAgent →
  cambiar cualquiera ⇒ 403. Casos CP01–CP07.
- **Multi-agente** (`.\kra1526_multi.ps1`, opt-in): valida IdUser (ajeno ⇒ 403)
  pero **no** el IdAgent (cambiarlo ⇒ 200 por diseño). Casos CP08–CP09, corre en
  la **agencia 0040**. Reporte aparte (`reporte_KRA-1526-multi.html`).

## Cómo se corre (sin intervención)

Desde la raíz del repo:

```powershell
# MONO (default)
.\kra1526.ps1            # CP01..CP07 + abre el reporte mono
.\kra1526.ps1 CP02       # un caso mono suelto

# MULTI-AGENTE (agencia 0040) — aparte, requiere credenciales multiagente
.\kra1526_multi.ps1      # CP08 + CP09 + abre el reporte multi
.\kra1526_multi.ps1 CP09 # un caso multi suelto
```

O con pytest directo:

```powershell
python -m pytest src/tests/etiquetas/KRA_1526 -m idor -v -s          # mono
$env:KRA1526_MULTI="1"; $env:KRA1526_AGENCY="0040"
python -m pytest src/tests/etiquetas/KRA_1526 -m idor_multi -v -s     # multi
```

No se pega ningún curl. La corrida:

1. Inicia sesión en Hermes 2 TEST sola (sesión persistente; login solo si expiró).
2. Teclea el teléfono de prueba y **captura en vivo** el request real de
   `/api/bff/customer/search` → de ahí salen el **token** y los **IdUser/IdAgent
   propios** y el body 200 de baseline.
3. Reproduce las variantes con `requests` (el token dura ~20 min) y valida.
4. Escribe `reports/evidence/KRA-1526/reporte_KRA-1526.html` (estilo TRN-239) y
   abre el reporte.

## Los casos

| CP | Qué prueba | Esperado |
|----|------------|----------|
| CP01 | Búsqueda global con IDs propios (baseline) | 200 con datos, todos del IdAgent propio |
| CP02 | IdUser ajeno | 403 y sin datos |
| CP03 | IdAgent ajeno (mono-agente) | 403 y sin datos |
| CP04 | Regresión: restaurar IDs propios | 200 con datos (mismo IdAgent) |
| CP05 | Balance por Cajero, IdUser ajeno | 403 (host lambdas + header `authorizer` con token fresco de sesión) |
| CP06 | Reporte de transacciones (body + `isMonoAgent`), IdAgent ajeno | 403 (endpoint capturado en vivo; fallback a ruta inferida) |
| CP07 | Regresión en PRODUCCIÓN | opt-in (`KRA1526_PROD=1`); ver abajo |
| CP08 | **Multi**: IdUser ajeno (agencia 0040) | 403 y sin datos (IdUser sí se valida) |
| CP09 | **Multi**: IdAgent distinto (agencia 0040) | **200** por diseño (IdAgent no se valida) |

CP08/CP09 solo corren con `KRA1526_MULTI=1` (runner `kra1526_multi.ps1`), en la
agencia 0040, y escriben su **propio** reporte. Si el multi está desactivado o la
captura multi falla, se omiten.

CP05 y CP06 llaman su endpoint **por API con el token fresco de la sesión**,
mismo flujo que la búsqueda global (happy path propios → cambiar un ID ajeno →
verificar rechazo). Detalles del contrato real (confirmados con DevTools):
- **CP05 Balance por Cajero** vive en el host de **lambdas**
  (`test-hermes-api-lambdas`) y su auth es el header **`authorizer`** (JWT sin
  `Bearer`) — no `authorization`. El token se deriva fresco de la sesión.
- **CP06 Reporte de transacciones** va en el host de `api-containers` con
  `authorization: Bearer` y el IdAgent en el body + `isMonoAgent`.

CP01–CP04 van sobre la búsqueda global capturada en vivo. Ningún token se
hardcodea: todo sale de la sesión de cada corrida.

## Producción (CP07)

Opt-in por seguridad. PROD entra por SSO de Google (correo Maxi + 2FA en el
celular), que exige un paso humano la primera vez: no se puede tomar un token
headless sin intervención. La automatización **desatendida cubre TEST**
(CP01–CP06). Para PROD: crear una sesión PROD una vez y correr con
`KRA1526_PROD=1`.

## Ajustes por entorno (env)

| Variable | Default | Para qué |
|---|---|---|
| `KRA1526_TELEFONO` | `8118615244` | teléfono de prueba para la búsqueda |
| `KRA1526_IDUSER_AJENO` | `99999` | IdUser ajeno a probar |
| `KRA1526_IDAGENT_AJENO` | `9999` | IdAgent ajeno a probar |
| `KRA1526_BALANCE_HOST` | `https://test-hermes-api-lambdas.maxilabs.net` | host del balance por cajero (lambdas, no api-containers) |
| `KRA1526_RUTA_BALANCE` | `/api/reports/balance_by_cashier` | ruta CP05 |
| `KRA1526_BALANCE_URL` | *(vacío)* | URL completa real del balance (host + IdUser/IdAgent/fechas). Fíjala una vez para ids/fechas exactos; el token igual se inyecta fresco |
| `KRA1526_RUTA_MT` | `/api/transactions/reports/money_transfers` | ruta CP06 |
| `KRA1526_PROD` | `0` | activa CP07 (producción) |
| `KRA1526_MULTI` | `0` | activa CP08/CP09 (multi-agente) |
| `KRA1526_AGENCY` | `0040` | agencia para el perfil multi-agente |
| `KRA1526_IDAGENT_DISTINTO` | `1242` | IdAgent distinto para CP09 (agente real ≠ 0040) |

## Reporte

`reports/evidence/KRA-1526/reporte_KRA-1526.html` — un caso por bloque, veredicto
PASS/FAIL, y por paso el enlace al `.json` con la petición/respuesta exactas (el
ID alterado va marcado con `_MODIFICADO`, para reproducir a mano si hace falta).
Solo hay OK o FALLA: un endpoint que no respondió sale FALLA (una prueba de
seguridad que no pudo ejecutarse no se da por buena), salvo las rutas inferidas
de CP05/CP06, que se omiten con nota.
