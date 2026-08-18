# HERMES2 Action Recorder — Extensión Chrome

Graba acciones del usuario en HERMES2 y sobrevive a navegaciones completas (login, redirects, recargas).

## Por qué funciona (a diferencia de los scripts de consola)

Los scripts anteriores morían al navegar porque vivían en el contexto de Página 1.  
Esta extensión usa `chrome.scripting.executeScript` con `world: 'MAIN'`, que:

- ✅ Se inyecta automáticamente en **cada página nueva**
- ✅ **No puede ser bloqueado por CSP** del sitio (bypasea completamente)
- ✅ Guarda el estado en `chrome.storage.local` (persiste entre navegaciones)
- ✅ Restaura la grabación automáticamente al cargar la nueva página

---

## Instalación (1 vez)

1. Abre Chrome y ve a `chrome://extensions`
2. Activa **"Modo de desarrollador"** (esquina superior derecha)
3. Haz click en **"Cargar descomprimida"**
4. Selecciona la carpeta: `ai_agent/scripts/chrome-extension/`
5. Verás el ícono de la extensión en la barra de Chrome ✓

> No se necesita compilar ni instalar nada. Es una extensión sin dependencias.

---

## Uso

### Opción A — Desde el popup (recomendada)

1. Click en el ícono de la extensión en la barra de Chrome
2. Escribe el nombre del flujo (ej: `login`, `transferencia_simple`)
3. Click **"🔴 Iniciar Grabación"**
4. Navega y haz tus acciones normalmente (incluyendo login)
5. Click **"⏹️ Detener y Exportar"** → se descarga el JSON automáticamente

### Opción B — Desde la consola (como antes)

```javascript
// Iniciar
recorder.start("login_flujo")

// Ver estado (útil después de navegar)
recorder.status()

// Detener y descargar JSON
recorder.stop()

// Ver JSON en consola sin detener
recorder.export()
```

---

## Flujo completo de ejemplo

```
1. Abrir HERMES2 en Chrome
2. recorder.start("login")          ← consola o popup
3. Escribir usuario/contraseña
4. Click "Iniciar Sesión"           ← navegación → página nueva
   [En la nueva página aparece:]
   ✅ GRABACIÓN RESTAURADA
   Flujo: login | Acciones: 3 (acumuladas)
5. Continuar navegando...
6. recorder.stop()                  ← descarga login_<timestamp>.json
```

---

## Estructura de archivos

```
chrome-extension/
├── manifest.json       ← Configuración de la extensión (MV3)
├── background.js       ← Service worker: inyecta scripts, gestiona storage
├── content.js          ← Bridge isolated↔main world (chrome.storage)
├── recorder-core.js    ← Lógica de grabación (se inyecta en MAIN world)
├── popup.html          ← UI del popup
├── popup.js            ← Lógica del popup
└── README.md           ← Este archivo
```

---

## Output JSON

```json
{
  "flujo": "login",
  "acciones": [
    {
      "tipo": "input",
      "nombre": "username",
      "selector": "input[name=\"username\"]",
      "valor": "ext.iagarcia@maxillc.com",
      "url": "https://hermes2.app/login",
      "timestamp": "2026-05-28T..."
    },
    {
      "tipo": "click",
      "nombre": "btn-login",
      "selector": "#btn-login",
      "texto": "Iniciar Sesión",
      "url": "https://hermes2.app/login",
      "timestamp": "..."
    }
  ],
  "elementos": { ... },
  "paginas": [
    { "url": "https://hermes2.app/login", "evento": "start" },
    { "url": "https://hermes2.app/dashboard", "evento": "navigation" }
  ],
  "metadata": {
    "total_acciones": 15,
    "total_elementos": 8,
    "total_paginas": 2,
    "duracion_segundos": 45.2
  }
}
```

---

## Troubleshooting

**El ícono de la extensión no aparece**  
→ Ve a `chrome://extensions` y verifica que esté activada.

**"No se pudo comunicar con la página" en el popup**  
→ Refresca la pestaña de HERMES2 y vuelve a abrir el popup.

**No se descarga el JSON**  
→ Verifica que Chrome no esté bloqueando descargas. Usa `recorder.export()` en consola como alternativa.

**Quiero recargar la extensión después de editar código**  
→ `chrome://extensions` → click en el ícono 🔄 de la extensión.
