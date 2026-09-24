# Instalación desde cero (Windows + VS Code + PowerShell)

Guía para alguien que **nunca** ha tenido el proyecto en su máquina.
Repositorio: <https://github.com/IaGarci4/web_automation_agent_ia>

> **¿Qué carpetas creo yo y cuáles se crean solas?**
>
> | Carpeta | ¿Quién la crea? |
> |---|---|
> | `C:\Repositorios` (o donde guardes tus proyectos) | **Tú**, una sola vez |
> | `web_automation_agent_ia` | **`git clone`**, automáticamente |
> | `venv\` | El comando `python -m venv venv` |
> | `reports\`, `session_state\` | El propio agente, en la primera corrida |
> | `.env` | **Tú**, copiando `.env.example` |
>
> Solo creas la carpeta contenedora. Todo lo demás aparece solo.

---

## 0. Requisitos previos

Instala esto **antes** de empezar (una sola vez por máquina):

| Programa | Dónde | Comprobación |
|---|---|---|
| **Python 3.11** | <https://www.python.org/downloads/> — marca *"Add Python to PATH"* | `python --version` |
| **Git** | <https://git-scm.com/download/win> | `git --version` |
| **VS Code** | <https://code.visualstudio.com/> | — |
| Extensión **Python** de Microsoft | Desde VS Code (`Ctrl+Shift+X` → "Python") | — |

Abre PowerShell y verifica:

```powershell
python --version   # debe decir 3.11.x
git --version
```

Si `python` no responde, cierra y vuelve a abrir la terminal (o reinicia) para
que tome el PATH.

---

## 1. Crear la carpeta contenedora y clonar

La carpeta del proyecto **NO la creas tú**: la crea `git clone`. Tú solo creas
la carpeta donde vivirán tus repositorios.

```powershell
# 1.1 Carpeta contenedora (solo si aún no existe)
mkdir C:\Repositorios -Force
cd C:\Repositorios

# 1.2 Clonar — esto CREA la carpeta 'web_automation_agent_ia'
git clone https://github.com/IaGarci4/web_automation_agent_ia

# 1.3 Entrar al proyecto
cd web_automation_agent_ia
```

Si el repositorio es privado, Git pedirá tus credenciales de GitHub. Usa tu
usuario y un **Personal Access Token** (no la contraseña de la cuenta):
GitHub → *Settings* → *Developer settings* → *Personal access tokens*.

### Abrir el proyecto en VS Code

```powershell
code .
```

Dentro de VS Code, abre la terminal integrada con **`Ctrl+ñ`** (o
*Terminal → New Terminal*) y asegúrate de que arriba a la derecha dice
**PowerShell**. Todos los comandos siguientes van ahí.

---

## 2. Crear el ambiente virtual

El ambiente virtual aísla las librerías de este proyecto de las del resto de tu
máquina. Se crea **dentro** de la carpeta del repo y está ignorado por Git.

```powershell
# 2.1 Crear (genera la carpeta venv\)
python -m venv venv

# 2.2 Activar
.\venv\Scripts\activate
```

Sabrás que está activo porque la línea de comandos empieza con `(venv)`:

```
(venv) PS C:\Repositorios\web_automation_agent_ia>
```

> **Si aparece el error "la ejecución de scripts está deshabilitada"**
> (`PSSecurityException` / `UnauthorizedAccess`), Windows está bloqueando la
> activación. Ejecuta esto **una sola vez** y confirma con `S`:
>
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```
>
> Después repite el paso 2.2 (`.\venv\Scripts\activate`) **como comando
> aparte**. Si pegas ambos juntos y se pierde el salto de línea, PowerShell los
> lee como uno solo y falla con
> `No se puede enlazar el parámetro 'ExecutionPolicy'`.
>
> ¿La política está bloqueada por IT? Alternativas sin cambios permanentes:
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` (solo esa
> terminal) o usar el activador de CMD, `.\venv\Scripts\activate.bat`.

> **Importante:** hay que activar el `venv` **cada vez** que abras una terminal
> nueva. Si ves un error tipo `ModuleNotFoundError`, casi siempre es que se te
> olvidó activarlo.

---

## 3. Instalar dependencias

```powershell
# 3.1 Actualizar pip (evita avisos y fallos de instalación)
python -m pip install --upgrade pip

# 3.2 Librerías del proyecto
pip install -r requirements.txt

# 3.3 Navegador que usa Playwright (~150 MB, solo la primera vez)
playwright install chromium
```

El paso 3.3 es fácil de olvidar: `pip install` trae la **librería** Playwright,
pero no el **navegador**. Sin él, cualquier prueba falla al arrancar.

---

## 4. Configurar el `.env` (credenciales)

El archivo `.env` guarda usuarios y contraseñas. **No está en Git** —
cada quien tiene el suyo. Se crea copiando la plantilla:

```powershell
Copy-Item .env.example .env
code .env          # lo abre en VS Code para editarlo
```

Lo **mínimo** que hay que llenar para correr el sanity:

```ini
HERMES_ENV=test                     # test | prod

PORTAL_USER=tu_usuario_hermes       # usuario mono-agencia
PORTAL_PASS=tu_password_hermes

PORTAL_USER_MULTI=tu_usuario_multi  # solo para CP04 y CP11 (multi-agencia)
PORTAL_PASS_MULTI=tu_password_multi

CHRONOS_USER=tu_usuario_chronos     # solo para los casos que tocan Chronos
CHRONOS_PASS=tu_password_chronos

AGENT_ADMIN_PASSWORD=lo_que_quieras # contraseña para ENTRAR A LA GUI
```

Notas:

- `AGENT_ADMIN_PASSWORD` **no** es de ningún portal: es la contraseña de la
  interfaz gráfica del agente. Elige la que quieras.
- `ANTHROPIC_API_KEY` es **opcional**. Vacío = el agente funciona en modo
  offline, sin perder funcionalidad de pruebas.
- El resto de variables ya viene con valores razonables; no las toques hasta
  que necesites cambiarlas.

Guarda con `Ctrl+S`.

---

## 5. Primera ejecución

### Opción A — Interfaz gráfica (recomendada para empezar)

```powershell
python run_gui.py
```

Abre el navegador en <http://localhost:8502>. Entra con el correo de tu
compañero y la `AGENT_ADMIN_PASSWORD` que pusiste en el `.env`.
Desde ahí eliges módulo, caso y ambiente sin escribir comandos.

Para detenerla: `Ctrl+C` en la terminal.

### Opción B — Línea de comandos

```powershell
# Un caso puntual, viendo el navegador
pytest src/tests/sanity_general -k CP02 -v -s

# Todo el sanity en paralelo, con reporte HTML
python -m pytest src/tests/sanity_general -m sanity_general -n 3 `
    --html=report_sanity.html --self-contained-html
```

La **primera** corrida hace login real y guarda la sesión en `session_state\`;
las siguientes ya no vuelven a loguearse.

**Chronos**: los casos que lo usan (CP07, CP09, CP10, CP11) inician sesión
solos. En producción el acceso es por Google y pedirá que **apruebes el 2FA en
tu celular** — tienes 2 minutos. Después queda guardado.

---

## 6. Comprobar que quedó bien

```powershell
# ¿El venv está activo y las librerías instaladas?
python -c "import playwright, pytest, streamlit; print('Dependencias OK')"

# ¿Playwright tiene su navegador?
playwright install --dry-run chromium

# ¿El proyecto compila?
python -c "from config import settings; print('Ambiente:', settings.HERMES_ENV)"
```

---

## 7. Problemas frecuentes

| Síntoma | Causa y solución |
|---|---|
| `no se reconoce python` | Python no está en el PATH. Reinstala marcando *"Add Python to PATH"*. |
| `la ejecución de scripts está deshabilitada` | Ejecuta el `Set-ExecutionPolicy` del paso 2. |
| `ModuleNotFoundError` | El `venv` no está activo: `.\venv\Scripts\activate`. |
| `Executable doesn't exist ... chromium` | Falta el paso 3.3: `playwright install chromium`. |
| El navegador no abre en las pruebas | `PW_HEADLESS=true` en tu `.env`. Ponlo en `false`. |
| Falla el login de Hermes | Revisa `PORTAL_USER` / `PORTAL_PASS`. Para forzar login limpio, borra la carpeta `session_state\`. |
| Chronos pide 2FA cada vez | Borra `session_state\chronos_cookies.json` y vuelve a entrar una vez. |

---

## 8. Trabajo diario (resumen)

Cada vez que te sientes a trabajar:

```powershell
cd C:\Repositorios\web_automation_agent_ia
.\venv\Scripts\activate
git pull                       # traer los últimos cambios
pip install -r requirements.txt  # solo si requirements.txt cambió
python run_gui.py
```

---

## 9. Qué NO se sube a Git

Estos archivos son **tuyos** y están ignorados a propósito. No los subas ni te
preocupes si no aparecen al clonar:

- `.env` — tus credenciales
- `venv\` — el ambiente virtual
- `session_state\` — cookies y tokens de sesión
- `reports\` — evidencias, reportes y descargas
- `gui\usuarios.json` — usuarios de la interfaz
