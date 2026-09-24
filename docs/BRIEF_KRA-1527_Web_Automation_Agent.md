# BRIEF TÉCNICO — KRA-1527 · Token en memoria del Hardware Agent
### Destinatario: Web Automation Agent · Repo: `C:\Repositorios\AutomationAgent`

> **Objetivo de la automatización:** disparar desde el Front End **todos** los flujos que
> provocan comunicación entre Hermes 2.0 y el agente de hardware local, capturar el volcado
> de memoria de los procesos involucrados, y verificar que el **JWT no aparece en texto plano**.
> El fix de Roman Arce debe validarse sin falsos positivos ni falsos negativos.

---

## 1. Contexto del hallazgo y del fix

**Hallazgo (ioSENTRIX, Pentesting 2026 · 5.2.1 · Severidad Alta):**
El agente de escritorio `Hermes2Agent.exe` almacenaba el JWT de autenticación **en texto plano**
en su memoria de proceso. Con Administrador de tareas → *Crear archivo de volcado de memoria*
(sin privilegios elevados) se extraía el token activo y se reutilizaba para suplantar la sesión,
**evadiendo el device-binding por hardware ID**.

**Fix implementado (KRA-1527, Done, Highest, épico KRA-1531):**

```
  Front End (Hermes 2.0 web)
        │  mensaje
        ▼
  Hermes2Agent.exe ──── token ENCRIPTADO ────► Maxi.RulesOffice.Security.HttpProxy.exe
        ▲                                              │ desencripta y ejecuta el request
        └──────────── respuesta ◄──────────────────────┘
```

- `Hermes2Agent.exe` **nunca** maneja el token en claro; lo pasa cifrado.
- `Maxi.RulesOffice.Security.HttpProxy.exe` es un **proceso efímero**: se abre al iniciar el
  request y se cierra al terminar. Esa vida corta es, en sí misma, una mitigación adicional.
- Remediación declarada en el ticket: cifrado en memoria + **DPAPI** + **zeroize** de datos
  sensibles cuando dejan de necesitarse.

**Criterio de aceptación global:** en **ningún** volcado de memoria de estos dos procesos debe
aparecer un JWT completo y decodificable.

---

## 2. ⚠️ Tres bloqueadores críticos del repo actual

Estos tres puntos **invalidarían la prueba** si el agente reutiliza los patrones del sanity tal cual.

### 2.1 `window.print` está neutralizado en todo el sanity
Todos los tests de `src/tests/sanity_general/` ejecutan:
```python
await logged_page.evaluate("window.print = () => {};")
```
Esto **impide que se dispare la impresión real** y, por tanto, **no se invoca al Hardware Agent**.
→ **En los tests de KRA-1527 esta línea NO debe existir.** Si se neutraliza la impresión, el
volcado saldrá PASS trivialmente porque nunca hubo comunicación: **falso negativo**.

### 2.2 El recibo se **declina** en el flujo de transferencias
```python
transfers-container-modal-success-transfer-0-decline-button   # ← "NO" = NO imprimir recibo
```
El sanity siempre declina para no bloquearse con el diálogo de impresión.
→ **En KRA-1527 hay que ACEPTAR la impresión** (el botón afirmativo del mismo modal) para que
`Hermes2Agent.exe` reciba el mensaje. Confirmar el testid del botón afirmativo con `dom_audit`
antes de codificar.

### 2.3 Los launch args de Chromium ya contemplan el Hardware Agent
En `conftest.py → _launch_args()` existen flags documentados explícitamente para evitar el popup
*"Acceder a otras aplicaciones y servicios de este dispositivo"* que Hermes dispara al hablar con
el Hardware Agent local:
```
--ignore-certificate-errors  --allow-insecure-localhost
--disable-web-security       --allow-running-insecure-content
```
→ **Conservarlos.** Sin ellos el navegador bloquea la llamada al agente y no hay comunicación.
No ejecutar estos tests en modo headless sin validar que la impresión sigue disparándose
(`PW_HEADLESS=0` recomendado).

---

## 3. Diseño propuesto: híbrido Playwright + volcado a nivel SO

Playwright **no puede** crear un volcado de memoria: es una operación del sistema operativo.
El test debe orquestar tres fases.

```
FASE 1 — Playwright        FASE 2 — Subproceso Windows      FASE 3 — Inspección
─────────────────────      ───────────────────────────      ────────────────────
Driver del flujo FE   ──►  procdump captura el .DMP    ──►  dump_token_inspector.py
(imprimir, escanear…)      de Hermes2Agent / HttpProxy       veredicto PASS/WARN/FAIL
```

### 3.1 Captura del volcado — proceso estable (`Hermes2Agent.exe`)
Corre de forma permanente, así que se puede volcar **después** de la acción:

```python
subprocess.run([PROCDUMP, "-accepteula", "-ma", "Hermes2Agent.exe", str(dmp_path)],
               check=True, capture_output=True, timeout=120)
```
Alternativa nativa sin descargar Sysinternals (suele requerir consola elevada):
```
rundll32.exe comsvcs.dll, MiniDump <PID> <ruta.dmp> full
```

### 3.2 Captura del volcado — proceso efímero (`HttpProxy.exe`) ★ clave
Este es el punto que Roman marcó como difícil ("se abre y se cierra"). **No hay que perseguirlo
con un poll:** `procdump` tiene el flag `-w`, que **espera a que el proceso arranque** y lo vuelca
en cuanto aparece.

```python
# Lanzar ANTES de disparar la acción en el FE — queda esperando
proc = subprocess.Popen([PROCDUMP, "-accepteula", "-ma", "-w",
                         "Maxi.RulesOffice.Security.HttpProxy.exe", str(dmp_path)])
# ... aquí Playwright ejecuta la acción que dispara el request ...
proc.wait(timeout=60)
```
Esto elimina la carrera y hace la prueba **determinista**. Si aun así no se captura, ese resultado
se documenta como *"no reproducible — proceso demasiado efímero"*, que es un hallazgo válido
(mitigación por diseño), **no** un caso fallido.

> El truco de "conexión lenta para ampliar la ventana" que mencionó Roman queda como plan B.
> Se puede emular con `page.route()` + delay artificial, o con Chrome DevTools throttling.

### 3.3 Inspección
Herramienta ya construida y probada: **`tools/dump_token_inspector.py`** (sin dependencias externas).

```bash
python tools/dump_token_inspector.py "<ruta.dmp>" --caso "CP01" --proceso Hermes2Agent --out reporte.html
```
- Regex de JWT completo: `eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+`
- **Decodifica** header y payload y valida claims (`exp, iat, iss, sub, azp, preferred_username`).
  Esto distingue un JWT de autenticación real de una cadena que casualmente empieza con `eyJ`
  — más preciso que `findstr /i /c:"eyJ"`.
- Veredicto: **FAIL** (JWT de auth decodificable) · **WARN** (fragmentos no concluyentes) · **PASS**.
- Exit code `1` si hay FAIL → integrable directo en el assert de pytest.
- Genera reporte HTML autocontenido. Muestra: `tools/muestra/reporte_muestra_KRA-1527.html`.

**Assert sugerido:**
```python
r = subprocess.run([sys.executable, INSPECTOR, str(dmp), "--proceso", proceso,
                    "--out", str(html_out)], capture_output=True, text=True)
assert r.returncode == 0, f"TOKEN EXPUESTO en {dmp.name}\n{r.stdout}"
```

---

## 4. Flujos a automatizar (cobertura del Hardware Agent)

Prioridad por probabilidad de tocar el agente de hardware. Test IDs verificados en el repo.

| # | Flujo | Módulo repo | Test IDs clave | Estado |
|---|-------|-------------|----------------|--------|
| 1 | **Imprimir recibo de Money Transfer** | `hm_transferelektra_page.py` | `transfer-continue-button-0-button` → `transfers-container-modal-summary-0-send-button` → **botón afirmativo** del modal de éxito (NO el `-decline-button`) | POM existe |
| 2 | **Ficha de depósito** | `src/sanity_general/deposit_slip.py` | `footer-deposit-button`, `deposit-slip-form-amount-input`, `test-id-button` (Send) | Existe |
| 3 | **Escaneo / procesamiento de cheque** | `src/sanity_general/cheques.py` | `checks-navbar-item`, `checks-0-navbar-dropdown-item`, `pre-scan-check-process-button`, `issuer-check-form-checkNumber-input`, `check-amount-input`, `transaction-check-process-button`, `checks-page-success-process-check-modal-finish-process-button` | Existe (escáner **emulado**, se elige en Configuración > Dispositivos, `CP07_SCANNER=CANON`) |
| 4 | **Imprimir reporte por cajero / balance** | `src/sanity_general/balance.py` | `reports-navbar-item`, `reports-1-navbar-dropdown-item`, `reports-by-cashier-search-button`, `report-options-button` (**índice 1 = Imprimir**), `reports-by-cashier-print-button` | Existe |
| 5 | **Captura de firma digital** | — | — | ❌ **No implementado** (`test_CP04` lo marca PENDIENTE: *Chronos Signature Hold*). Requiere descubrimiento DOM previo. |
| 6 | **Money Orders** | — | — | ❌ **No existe nada** en el repo (grep sin resultados). Requiere exploración completa del módulo. |

**Recomendación de alcance:** automatizar **1–4** (base sólida, POMs ya existen) y dejar **5–6**
como exploración manual con `dom_audit` en una segunda iteración. No intentar money orders a
ciegas: es donde más riesgo hay de generar un test frágil.

---

## 5. Convenciones del repo a respetar

**Framework:** Playwright **async** (`playwright.async_api`) + pytest + `pytest-asyncio`
(`asyncio_mode = auto` en `pytest.ini`). Chromium. Sin package.json ni pyproject.

**Fixtures (`conftest.py`):**
- `logged_page` → sesión mono-agencia (`SessionHelper.ensure_logged_in()` + reuso de `session_state/`)
- `logged_page_multi` → multi-agencia (`PORTAL_USER_MULTI` + `seleccionar_agencia(AGENCY_CODE)`)
- Tras login: cierra modal de Notificaciones y fija idioma (`FLOW_LANG`)

**Esqueleto de test:**
```python
@pytest.mark.etiqueta
@pytest.mark.asyncio
@pytest.mark.parametrize("language,width,height", [("English", 1366, 768)])
async def test_KRA_1527_CP01_recibo_money_transfer(logged_page: Page, language, width, height):
    flow = HmTransferelektraPage(logged_page)
    screenshot = ScreenshotHelper(logged_page)
    evi = Evidencia(screenshot, EVIDENCE)
    # ⚠️ NO neutralizar window.print — se necesita la impresión real
```

**Selectores:** `page.get_by_test_id(...)` o el helper `flow.smart_click(testid=, texto=, fallbacks=[], optional=)`.
Convención `data-testid`: kebab-case con índice → `transfer-<seccion>-<campo>-<idx>-<tipo>`
(sufijos `-button`, `-input`, `-icon-svg`, `-dropdown-input`, `-navbar-item`, `-h5-heading`).
Hay testids genéricos repetidos (`test-id-button`, `typography`) → desambiguar por texto visible ES/EN.
Centralizar los nuevos en `src/locators/`.

**Timeouts** (`config/settings.py`, ms): `TIMEOUT_NAVIGATION=60000`, `TIMEOUT_ELEMENT=30000`,
`TIMEOUT_MODAL=30000`, `TIMEOUT_SHORT=5000`. Cheques usa `SCAN_TIMEOUT=180_000`.
Esperas: `expect(...).to_be_visible(timeout=)`, `flow.wait_for_no_blocking_overlays()`.

**Evidencia:** capturar **antes** del assert con `evi.shot(nombre, locators=, paso=)`
(numeración automática `NN_nombre.png` en `reports/evidence/<CP>/`).

**Entorno:** `HERMES_ENV=test|prod` con `settings.por_ambiente(test, prod)`. `PW_HEADLESS=0`
para estos tests. Ubicación sugerida del módulo: `src/tests/etiquetas/test_KRA_1527.py`.

---

## 6. Helper propuesto: `src/helpers/memdump_helper.py`

Encapsula la parte de SO para que los tests queden limpios:

```python
class MemDumpHelper:
    def __init__(self, procdump_path: str, out_dir: Path, caso: str): ...

    def arm_ephemeral(self, process_name: str) -> subprocess.Popen:
        """procdump -ma -w <proc>  — armar ANTES de disparar la acción (HttpProxy)."""

    def dump_now(self, process_name: str) -> Path:
        """procdump -ma <proc>  — para procesos estables (Hermes2Agent)."""

    def inspect(self, dmp: Path, proceso: str) -> tuple[bool, str, Path]:
        """Ejecuta dump_token_inspector.py. Devuelve (ok, stdout, ruta_reporte_html)."""

    def cleanup(self):
        """Borra los .DMP tras la inspección — pueden pesar cientos de MB
           y contienen datos sensibles. NO deben quedar en el repo ni en CI."""
```

**Config nueva sugerida en `.env`:**
```
PROCDUMP_PATH=C:\Tools\Sysinternals\procdump.exe
DUMP_OUT_DIR=%TEMP%
HW_AGENT_PROC=Hermes2Agent.exe
HW_PROXY_PROC=Maxi.RulesOffice.Security.HttpProxy.exe
```

---

## 7. Riesgos y salvaguardas

| Riesgo | Mitigación |
|--------|------------|
| **Falso negativo** por `window.print` neutralizado o recibo declinado | Prohibido en estos tests (§2.1, §2.2). Añadir un assert previo que confirme que la comunicación ocurrió (log del agente o cambio de estado en UI). |
| **Falso negativo** por método defectuoso | **CP08 (control negativo)**: correr el inspector contra un archivo con un JWT de ejemplo y verificar que da **FAIL**. Sin esto, ningún PASS es defendible ante el pentester. |
| `HttpProxy` no capturable | Usar `procdump -w` (§3.2). Si aun así falla, documentar como no reproducible, no como fallo. |
| Headless altera el comportamiento de impresión | `PW_HEADLESS=0` y validar en la primera corrida. |
| `.DMP` pesados con datos sensibles | Borrar tras inspeccionar (`cleanup()`); `*.DMP` al `.gitignore`; **nunca** subirlos como evidencia a QMetry — subir solo el **reporte HTML**. |
| Escáner emulado ≠ hardware real | El emulador vale para el flujo FE. Si se quiere certeza total sobre el periférico físico, una pasada manual con hardware real. |

---

## 8. Entregables esperados del Web Automation Agent

1. `src/tests/etiquetas/test_KRA_1527.py` — tests para los flujos 1–4 (§4).
2. `src/helpers/memdump_helper.py` — orquestación del volcado (§6).
3. Test IDs nuevos centralizados en `src/locators/`.
4. Reportes HTML del inspector en `reports/evidence/KRA-1527/`.
5. **CP08 control negativo** implementado como test independiente.
6. Nota de ejecución: qué flujos se automatizaron, cuáles quedaron manuales y por qué.

---

## 9. Referencias

| Recurso | Ruta |
|---------|------|
| Inspector de volcados | `tools/dump_token_inspector.py` |
| Reporte HTML de muestra | `tools/muestra/reporte_muestra_KRA-1527.html` |
| Casos QMetry (8 casos) | `KRA-1527_QMetry_v2.xlsx` |
| Ticket Jira | https://maxims.atlassian.net/browse/KRA-1527 (Done · Highest · épico KRA-1531) |
| Reporte de pentest | Google Drive · `Maxi_Send_Penetration_Test_May-2026` · §5.2.1 |
| Transpiler grabación→POM | `tools/json_to_pom.py` (ya detecta feature `printer` y exige *"Hardware Agent corriendo"*) |
| Procesos objetivo | `Hermes2Agent.exe` · `Maxi.RulesOffice.Security.HttpProxy.exe` |
| Ambiente | https://test-hermes.maxilabs.net |

---

**Resumen en una línea para el agente:** automatiza los flujos FE que invocan al Hardware Agent
**sin neutralizar la impresión**, arma `procdump -w` antes de disparar la acción para atrapar el
`HttpProxy` efímero, y falla el test si `dump_token_inspector.py` devuelve exit code 1.
