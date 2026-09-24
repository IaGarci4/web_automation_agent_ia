# web_automation_agent_ia

Agente de **automatización QA** para **HERMES2** (plataforma de transferencias de
Maxi) y su back-office **Chronos**, sobre **Python + Playwright + pytest**.
Incluye una **interfaz gráfica (Streamlit)**, un **agente en lenguaje natural** y
un motor genérico que **aprende** flujos grabados. Funciona **offline** (sin API
key); Claude es opcional para respuestas más ricas.

## Qué trae

- **Sanity General (CP01–CP07)** — rescate del sanity manual a un motor estable,
  con Información Adicional/KYC, cuestionarios de compliance, OFAC Hold, pago con
  tarjeta de débito (POS), Bill Payment y Recargas (Top Ups). Cada caso deja
  **evidencias numeradas** con resaltado.
- **Etiquetas de deploy** — validaciones ligadas a tickets Jira (p.ej. **KRA-1125**:
  regla del teléfono `573` para Uniteller Colombia en depósito), con casos
  positivo y negativo.
- **Envíos por pagador** (data-driven) — catálogo `src/pagadores/<pais>/payers.json`
  (México activo); un envío a un pagador, a varios o a todos.
- **GUI Streamlit** — login con banco de usuarios Maxi, dashboard, ejecución con
  **log en vivo**, **botón Detener**, **historial**, **reporte HTML**, ambientes
  **Test/Producción** y **bilingüe (ES/EN)**.
- **Agente en lenguaje natural** — "ejecuta el sanity general", "corre el CP05",
  "corre la etiqueta KRA-1125 negativas 3 veces", "haz un envío a Banorte con
  customer Genaro Garcia Luna".

## Instalación

```powershell
mkdir C:\Repositorios -Force; cd C:\Repositorios
git clone https://github.com/IaGarci4/web_automation_agent_ia   # crea la carpeta
cd web_automation_agent_ia
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium        # el navegador; no lo trae pip
Copy-Item .env.example .env        # edita con tus credenciales
```

### Si al activar el `venv` sale «la ejecución de scripts está deshabilitada»

```
.\venv\Scripts\activate : No se puede cargar el archivo ...\Activate.ps1 porque
la ejecución de scripts está deshabilitada en este sistema.
    + CategoryInfo : SecurityError: (:) [], PSSecurityException
    + FullyQualifiedErrorId : UnauthorizedAccess
```

Es la política de seguridad de PowerShell, no un problema del proyecto:
`Activate.ps1` es un script y Windows los bloquea por defecto. Se arregla **una
sola vez por usuario** y no pide permisos de administrador.

**Paso 1** — ejecuta esto y confirma con `S`:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**Paso 2** — vuelve a activar el entorno:

```powershell
.\venv\Scripts\activate
```

La línea debe quedar empezando con `(venv)`.

> ⚠️ Son **dos comandos separados**: ejecuta el primero, pulsa Enter, y recién
> entonces el segundo. Si los pegas juntos y se pierde el salto de línea,
> PowerShell los interpreta como uno solo y falla con
> `No se puede enlazar el parámetro 'ExecutionPolicy'`.

`RemoteSigned` permite scripts locales pero sigue exigiendo firma a los
descargados de internet, y `-Scope CurrentUser` no toca la configuración de toda
la máquina.

<details>
<summary>Si tu equipo de IT tiene la política bloqueada y el comando falla</summary>

Dos salidas que no cambian nada permanente. **Opción A** — solo para la terminal
abierta (hay que repetirla en cada terminal nueva); de nuevo, un comando y
después el otro:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

```powershell
.\venv\Scripts\activate
```

**Opción B** — el activador de CMD, que no es un script de PowerShell y por
tanto no está sujeto a la política:

```powershell
.\venv\Scripts\activate.bat
```

</details>

> ¿Primera vez con el proyecto? La guía paso a paso —requisitos, activación del
> `venv`, qué carpetas se crean solas y errores frecuentes— está en
> **[docs/INSTALACION.md](docs/INSTALACION.md)**.

## Configuración (`.env`)

Copia `.env.example` a `.env` y completa al menos:

- `APP_URL` — URL de la app (preset: `https://test-hermes.maxilabs.net/transfers`).
- `PORTAL_USER` / `PORTAL_PASS` — usuario mono-agencia de Hermes.
- `PORTAL_USER_MULTI` / `PORTAL_PASS_MULTI` / `AGENCY_CODE` — para CP04 (multi-agencia).
- `AGENT_ADMIN_PASSWORD` — contraseña para entrar a la GUI (no es de ningún portal).
- `ANTHROPIC_API_KEY` — **opcional** (vacío = modo offline).

El `.env` **no se sube a git**. `.env.example` documenta toda la estructura
(URLs, usuarios, secretos, timeouts, pausas y overrides por caso).

## Uso — Interfaz gráfica (recomendado)

```powershell
python run_gui.py            # abre el navegador en http://localhost:8502
```

Desde el dashboard: **Sanity General** (todo o un CP, en Test/Producción),
**Transacciones por pagador** (solo pagadores con flujo aprendido) y
**Automatización web** (agente en lenguaje natural). Arriba a la izquierda se
elige el idioma (ES/EN), que también define en qué idioma se navega Hermes.

## Uso — Línea de comandos

```powershell
# Todo el sanity (en paralelo) con reporte HTML
python -m pytest src/tests/sanity_general -m sanity_general -n 3 `
    --html=report_sanity_general.html --self-contained-html

# Un caso puntual
pytest src/tests/sanity_general -k CP05 -v -s --headed

# Una etiqueta (positivo/negativo)
pytest src/tests/etiquetas -k KRA_1125 -v -s --headed

# Un envío por pagador (México)
pytest src/tests/test_envio_normal_mexico.py -k banorte -v -s --headed
```

Cambia de ambiente con `HERMES_ENV`:

```powershell
$env:HERMES_ENV="prod"; pytest src/tests/sanity_general -k CP05 -v -s
```

## Evidencias en QMetry (Test Management for Jira)

Las capturas del sanity se pueden subir **automáticamente** al Test Cycle
correspondiente, incrustadas en el campo *Actual Result* del paso — igual que si
se pegaran a mano.

> **APAGADO por defecto.** La lógica está integrada en **todos** los casos del
> sanity, pero no se sube nada mientras `QMETRY_UPLOAD` valga `0`. Se enciende
> por corrida (`$env:QMETRY_UPLOAD="1"`), de forma permanente (en el `.env`) o
> con la casilla del módulo *Sanity General* en la GUI.
> Si el caso **falla**, no se sube nada aunque esté encendido: las evidencias
> quedan en `reports/evidence/` y el ciclo no se ensucia con corridas
> incompletas.

```powershell
# Correr un caso y subir sus evidencias
$env:QMETRY_UPLOAD="1"; pytest src/tests/sanity_general -k CP01 -v -s

# …y además escribir el resultado (Pass/Fail/NA) de los pasos
$env:QMETRY_UPLOAD="1"; $env:QMETRY_RESULTADO="1"; pytest src/tests/sanity_general -k CP01 -v -s

# Revisar el reparto ANTES de subir (no toca QMetry)
python tools/ver_evidencias.py CP01

# Subir evidencias de una corrida anterior (idempotente)
python tools/qmetry_subir.py CP01
```

En la GUI hay dos casillas equivalentes en el módulo *Sanity General*.

**Configuración** (`.env`): `QMETRY_API_KEY` (Jira → QMetry → Configuration →
Open API), `QMETRY_PROJECT_ID`, y si el tenant lo exige `QMETRY_JIRA_EMAIL` +
`QMETRY_JIRA_TOKEN`. El Test Cycle se resuelve por ambiente
(`BM-TR-1370` en test · `BM-TR-1412` en producción).

**A qué paso va cada imagen** — por orden de prioridad:

1. **El nombre del archivo**: `evi.shot("cliente_beneficiario", paso=2)` genera
   `Step02-cliente_beneficiario.png` → paso 2. Varias imágenes pueden compartir
   paso. Es la forma recomendada: no requiere mapeo.
2. **Regla de cancelación**: toda evidencia de cancelación va al **último paso**
   del caso (en el sanity todos los casos cierran cancelando).
3. **`config/qmetry_mapeo.json`**: mapeo `fragmento → paso` por CP, con la key
   del Test Case. Lo que no mapea se adjunta a la ejecución del caso.

**Resultados**: `QMETRY_RESULTADO=1` escribe el veredicto **real** de pytest —
prueba exitosa → pasos con evidencia en *Pass* y el resto en *NA*; prueba
fallida → *Pass* hasta el punto de corte, *Fail* en el paso donde se detuvo y
*NA* en los siguientes. Tener una captura no marca *Pass* por sí solo.

Utilidades de diagnóstico: `tools/qmetry_probe.py` (flujo completo paso a paso),
`tools/qmetry_diag.py` (dónde quedaron los adjuntos),
`tools/qmetry_resultados.py` (ids de Pass/Fail/NA),
`tools/qmetry_ver_paso.py` (contenido crudo de un paso).

## Agente en lenguaje natural

```powershell
python agent/agente.py "ejecuta el sanity general en producción"
python agent/agente.py "corre el CP02 y CP03 del sanity general"
python agent/agente.py "corre la etiqueta KRA-1125 pruebas negativas por 2 minutos"
```

El agente entiende cantidad ("5 veces") y tiempo ("por 2 minutos"), pagador,
tipo de envío, monto, cliente y beneficiario. Aprende cada instrucción exitosa
en `agent/memoria.json`.

## Catálogo del Sanity General

| CP   | Caso                                             |
|------|--------------------------------------------------|
| CP01 | Money Transfer Cash + KYC + cancelación          |
| CP02 | Money Transfer con OFAC hit + cancelación        |
| CP03 | Money Transfer Depósito + Tarjeta de débito (POS)|
| CP04 | Doméstico ATM multi-agente + doble OFAC          |
| CP05 | Bill Payment nacional — Fidelity Express y Fiserv|
| CP06 | Recargas (Top Ups) — Lunex/DTOne                 |
| CP07 | Cheque individual (scan) + rechazo en Chronos    |
| CP09 | Pagos en Línea — depósito, cargo y pago          |
| CP10 | Ficha de Depósitos — happy path y caso alternativo|
| CP11 | Fax de entrada y salida (multi-agencia)          |
| CP12 | Reportes de Balance — continuo y por cajero      |
| CP22 | Money Order + Info Adicional — imprime y anula   |

> **CP06** valida los formularios de recarga pero **no completa el envío** (usa
> un número real; se detiene cuando el botón "Send/Enviar" es visible).
> **CP10** usa una **cámara simulada** (el conftest levanta Chromium con una
> webcam falsa), así que corre en máquinas sin cámara y en headless; ambas
> pruebas borran el recibo que crean en Chronos.
> Pendientes: CP11–CP22 y la fase Chronos (KYC/OFAC/Deposit Hold).

## Estructura

```
web_automation_agent_ia/
├── agent/              Agente NL (registry · brain · executor) + memoria local
├── config/             settings.py (env) · logger.py
├── gui/                GUI Streamlit: app.py · runner.py · i18n.py · auth.py · conocimiento.py
├── src/
│   ├── helpers/        base_page-tools · session_helper · datos (Faker+overrides) · screenshots
│   ├── pages/          base_page + Page Objects (smart_click, etc.)
│   ├── pagadores/      Envíos por país (flujo_mt) + catálogos payers.json
│   ├── sanity_general/ Capa estable: info_adicional · cuestionario · bill_payment · recargas · cancelacion
│   └── tests/          sanity_general/ · etiquetas/ · test_envio_normal_*.py
├── tools/              json_to_pom.py (transpiler) · run_repeat.py (repetición)
├── conftest.py         Fixtures logged_page / logged_page_multi (sesión persistente + idioma)
├── run_gui.py · requirements.txt · .env.example · pytest.ini
```

## Notas

- **Sesión persistente**: el login se guarda en `session_state/` (gitignoreado) y
  se reutiliza; si expira, la siguiente corrida la renueva sola.
- **Bilingüe**: los locators por texto visible contemplan ES/EN; los `data-testid`
  únicos son agnósticos al idioma. El Sanity General se ejecuta en inglés por
  precaución (configurable en `conftest.py`).
- **Seguridad**: contraseñas y secretos van solo en tu `.env` local (nunca en git).
  El banco de usuarios de la GUI (`gui/usuarios.json`) también está gitignoreado.
