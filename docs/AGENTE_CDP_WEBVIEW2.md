# Automatización dentro del Hermes2Agent (WebView2) vía CDP

## Por qué

El **Hermes2Agent** (Hardware Agent) es **WPF .NET6 + Microsoft WebView2**
(Chromium embebido) que carga **la misma web app** de Hermes 2
(`test-hermes.maxilabs.net/transfers`). El login es **Kerberos** dentro de ese
navegador interno (por seguridad) y la ventana tiene **captura de pantalla
bloqueada** (se ve negra al grabar).

En vez de lanzar nuestro propio Chromium, la automatización se **engancha por
CDP** al WebView2 ya autenticado y **reutiliza el POM y los `data-testid` sin
cambios**. Como la web app es idéntica, no se toca ningún selector.

> Confirmado en el análisis: el enganche NO depende de Kerberos — una vez que el
> agente levantó su WebView2 y hay sesión, se ataca el mismo DOM. Solo aplica a
> builds **STAGE/QA** (en producción está el anti-debugging de KRA-860).

## Cómo se corre (máquina QA de agencia, Windows)

1. **Lanzar el agente con el puerto CDP abierto** — usa `Ejecutar_Hermes2Agent.bat`
   (Desktop, o `tools/Ejecutar_Hermes2Agent.bat` en el repo). Setea:
   ```bat
   set "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9222 --remote-allow-origins=*"
   start "" "C:\MaxiInstall\Maxi\HERMES2_agent.Installer\Hermes2Agent.exe"
   ```
   `--remote-allow-origins=*` es OBLIGATORIO (Chromium reciente rechaza el
   websocket CDP con 403 sin él).

2. **Iniciar sesión (Kerberos) y entrar a la app** (Envío de Dinero) en el agente.

3. **Verificar el puerto**:
   ```powershell
   python tools\agent_cdp_check.py
   ```
   Debe listar un target `page` con URL de `test-hermes … /transfers`.

4. **Correr la suite enganchada por CDP** — activa el modo con la variable y
   usa los tests existentes (la fixture `logged_page` se engancha sola):
   ```powershell
   $env:HERMES_AGENT_CDP="1"
   pytest src/tests/test_agent_cdp_smoke.py -v -s        # humo primero
   # luego cualquier caso del POM, p. ej.:
   pytest src/tests/test_envio_normal_mexico.py -k elektra -v -s
   ```

## Qué hace el framework en modo CDP

- `config/settings.py` → `AGENT_CDP` (de `HERMES_AGENT_CDP`) y `AGENT_CDP_URL`
  (default `http://127.0.0.1:9222`, o pásala directa en `HERMES_AGENT_CDP`).
- `conftest.py` → `logged_page`, cuando `AGENT_CDP` está activo:
  1. `chromium.connect_over_cdp(AGENT_CDP_URL)`, toma `contexts()[0]`.
  2. Localiza la página cuya URL casa con `test-hermes/transfers` (espera a que
     monte si hace falta).
  3. **OMITE el login** (ya autenticado por Kerberos); best-effort cierra
     notificaciones y fija idioma.
  4. Entrega ese `page` a los tests → el POM se usa **sin cambios**.
  5. Teardown: **solo desconecta la conexión CDP**, NO cierra la app ni la página.

Variables:

| Variable | Default | Para qué |
|---|---|---|
| `HERMES_AGENT_CDP` | *(vacío)* | `1`/`true` activa el modo; o pasa la URL CDP directa |
| `HERMES_AGENT_CDP_URL` | `http://127.0.0.1:9222` | endpoint CDP (debe coincidir con el `.bat`) |
| `HERMES_AGENT_PAGE_RE` | `test-hermes\.maxilabs\.net\|/transfers` | patrón de la página objetivo |

## Limitaciones y cuidados

- **Sin screenshots**: la captura del agente sale **negra**. En modo CDP la
  evidencia es **solo DOM** (auditoría de estructura + diagnóstico consola/red).
  No confíes en imágenes.
- **No cerrar la app**: el teardown NO cierra contexto/página; solo desconecta.
  Si algún flujo llama `context.close()`/`page.close()`, evítalo en este modo.
- **Un solo puerto**: mantén el mismo puerto en el `.bat` y en `AGENT_CDP_URL`.

## Soporte Remoto (token de BD)

Antes de operar, el agente puede pedir un **token de Soporte Remoto** que caduca
cada día a medianoche. Se consulta en BD y se aplica en la UI:

- **Token (BD)**: `src/helpers/token_support.py` → `obtener_token()` corre
  `SELECT * FROM corp.TokenSupport` (credenciales del `.env`: `SERVIDOR_SQL`,
  `NAME_BD`, `USER_SQL`, `PASSWORD_SQL`), elige la fila vigente y **cachea** el
  token en `reports/token_support.json` hasta su `ExpirationDate`.
- **Aplicarlo**: `HmTransferelektraPage.aplicar_soporte_remoto(token)` abre el
  dropdown de soporte remoto, elige 'Soporte Remoto'/'Remote Support', teclea el
  token en `input-field-input` y pulsa 'Continuar'/'Continue'.
- **Test**: `src/tests/test_soporte_remoto.py` (marker `soporte_remoto`).

```powershell
# con .env de BD y el agente enganchado por CDP:
$env:HERMES_AGENT_CDP="1"
pytest src/tests/test_soporte_remoto.py -v -s
# o consultar el token suelto:
python -m src.helpers.token_support
```

## Envío de dinero en el agente (armado, sin enviar)

`src/tests/test_envio_agente_dejar.py` (marker `agente_dejar`) arma un envío de
dinero dentro del agente (cliente + beneficiario + pagador + sucursal + monto,
reutilizando la resolución de dirección) y lo **deja SIN enviar**. Se queda así a
propósito hasta que el flujo esté **en producción**; ese día se completa el envío
real con `ENVIO_AGENTE_COMPLETAR=1`.

```powershell
$env:HERMES_AGENT_CDP="1"
pytest src/tests/test_envio_agente_dejar.py -v -s          # arma y deja (NO envía)
# en producción, para completar el envío real:
$env:ENVIO_AGENTE_COMPLETAR="1"; pytest src/tests/test_envio_agente_dejar.py -v -s
# cambiar de pagador:  $env:ENVIO_PAGADOR="BANORTE"
```

## Fallback (si el puerto NO abre)

`tools/agent_cdp_check.py` da exit 1: el agente **ignora la variable** porque fija
`AdditionalBrowserArguments` por código. Es un cambio de 1 línea del lado dev
(dueños del agente: Alejandro Cárdenas / Román Arce, epic **KRA-860**),
condicionado a **NO producción**:

```csharp
var options = new CoreWebView2EnvironmentOptions();
#if !PRODUCTION
    options.AdditionalBrowserArguments =
        "--remote-debugging-port=9222 --remote-allow-origins=*";
#endif
var env = await CoreWebView2Environment.CreateAsync(null, userDataFolder, options);
```

No afecta seguridad en producción (excluido por compilación/ambiente). Tras
aplicarlo, repetir desde el paso 3.

## Qué reportar tras el primer smoke

- Salida de `/json/version` y `/json` (targets).
- ¿Bastó la variable del `.bat` o hizo falta el Fallback?
- ¿El smoke pasó con el POM sin cambios? Si falló, qué selector/paso y el error.
- Comportamiento de la desconexión: ¿el agente siguió vivo tras el teardown?
