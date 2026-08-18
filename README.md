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
git clone https://github.com/IaGarci4/web_automation_agent_ia
cd web_automation_agent_ia
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
copy .env.example .env        # edita con tus credenciales de Hermes
```

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
| CP05 | Bill Payment nacional — Fidelity Express         |
| CP06 | Bill Payment nacional — Fiserv                   |
| CP07 | Recargas (Top Ups) — Lunex/DTOne                 |

> **CP07** valida los formularios de recarga pero **no completa el envío** (usa
> un número real; se detiene cuando el botón "Send/Enviar" es visible).
> Pendientes: CP09–CP22 y la fase Chronos (KYC/OFAC/Deposit Hold).

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
