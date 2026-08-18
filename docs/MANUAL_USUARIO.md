# Manual de usuario — WebAuto Agent

Automatiza **cualquier portal web**: graba un flujo con el mouse, el sistema
genera el test, lo ejecuta, **aprende** la instrucción y audita la página.
Funciona **sin API Key** (aprendizaje local). Ideal para login + operaciones
repetitivas en portales como Zeus, CRMs, paneles administrativos, etc.

---

## 1. Instalación

Requisitos: **Python 3.10+** y **Google Chrome**.

```powershell
# 1. Entrar a la carpeta del proyecto
cd webauto-agent

# 2. Crear entorno virtual e instalar dependencias
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt

# 3. Instalar el navegador de Playwright
playwright install chromium
```

## 2. Configurar tu portal

Copia la plantilla y edítala con los datos de TU portal:

```powershell
copy .env.example .env
```

En `.env` define al menos:

```
PORTAL_NAME=zeus
APP_URL=https://zeus.tu-dominio.com/login
PORTAL_USER=tu_usuario
PORTAL_PASS=tu_password
READY_SELECTOR=nav            # algo visible SOLO cuando ya entraste (opcional)
```

Si tu portal usa nombres de campo distintos, ajusta los selectores:

```
LOGIN_USER_SELECTOR=#email
LOGIN_PASS_SELECTOR=#password
LOGIN_SUBMIT_SELECTOR=button:has-text('Entrar')
```

## 3. Login y sesión (una sola vez)

La primera corrida hace login y **guarda la sesión** en `session_state/`. Las
siguientes la reutilizan (no vuelve a pedir usuario/contraseña). Si tu portal
pide 2FA, apruébalo en el navegador la primera vez — hay 3 minutos de espera.

## 4. Grabar un flujo nuevo

1. Carga la extensión en Chrome: `chrome://extensions` → Modo desarrollador →
   "Cargar descomprimida" → selecciona la carpeta `scripts/chrome-extension/`.
2. Abre tu portal, presiona **F12 → Console** y escribe:

   ```javascript
   recorder.start("mi_flujo")      // empieza a grabar
   // ... haz el flujo a mano (clics, llenar campos, navegar)
   recorder.stop()                 // descarga mi_flujo_<timestamp>.json
   ```
3. Mueve el `.json` descargado a `tools/grabaciones/`.

> La extensión **audita los localizadores** mientras grabas: prefiere
> `data-testid` > `id` > `aria-label` > CSS > texto, para que el test sea estable.

## 5. Generar el test

```powershell
python tools\json_to_pom.py tools\grabaciones\mi_flujo.json --name mi_flujo
```

Genera 3 archivos: `src/locators/mi_flujo_locators.py`,
`src/pages/mi_flujo_page.py` y `src/tests/test_mi_flujo.py`.

## 6. Ejecutar

```powershell
# Directo con pytest
pytest src\tests\test_mi_flujo.py -v -s --headed

# O con el agente en lenguaje natural (aprende la instrucción)
python agent\agente.py
tú> corre mi flujo
```

La primera vez el agente busca el flujo por coincidencia; cuando funciona,
**lo aprende** y la próxima vez la instrucción es directa (memoria local en
`agent/memoria.json`).

## 7. Qué genera cada corrida

| Carpeta | Contenido |
|---|---|
| `reports/evidence/<flujo>/` | Screenshots paso a paso |
| `reports/audit/` | Auditoría de estructura del DOM (testids, anidación, etc.) |
| `reports/diag/` | Errores de DevTools si los hubo (500/4xx, JS, consola) |

## 8. Comandos útiles del agente

- `capacidades` — qué sabe hacer (flujos detectados).
- `corre <flujo> N veces` — repite N veces (caza inestabilidad).
- `salir` — termina la sesión del agente.

> Nota: si editas código del agente (`agent/`), reinicia el `tú>` para que cargue
> los cambios. Los tests no necesitan reinicio.

## 9. Solución de problemas

- **No encuentra el login:** ajusta `LOGIN_*_SELECTOR` en `.env` (inspecciona el
  campo en el navegador con F12).
- **Sesión caducó:** borra `session_state/` y vuelve a correr (hace login limpio).
- **Un paso no aparece siempre:** es normal; el motor tolera elementos opcionales
  y continúa sin romperse.
