# CLAUDE.md — AutomationAgent

Instrucciones para Claude Code al trabajar en este repositorio.
Para el detalle del proyecto (estructura, cómo correr, dependencias) ver `README.md`.

---

## Codebase Memory MCP

Este proyecto usa **Codebase Memory MCP**: un grafo de conocimiento local del
código (funciones, clases, archivos, llamadas, dependencias) construido con
`tree-sitter`. No hace llamadas a ningún modelo ni servicio externo — todo vive
en el equipo del desarrollador. Se conecta a Claude Code vía MCP y expone
herramientas como `index_repository`, `search_graph`, `trace_path`,
`get_architecture`, `search_code`, `query_graph`, `check_index_coverage`,
`index_status` y `detect_changes`.

**Por qué importa:** una consulta estructural contra el grafo cuesta ~120x menos
tokens que leer archivo por archivo, y es exacta (basada en el parseo real del
código, no en texto).

### Instrucción para Claude Code (léelo si estás trabajando en este repo)

- Si el proyecto tiene un grafo indexado, **prefiere las herramientas
  `mcp__codebase-memory-mcp__*`** (o el agente `codebase-memory`) sobre
  `Grep` / `Glob` / lectura completa de archivos cuando la pregunta sea sobre
  arquitectura, quién llama a qué, dependencias, o impacto de un cambio.
- Si no hay índice o el índice parece desactualizado (`check_index_coverage`
  con huecos, o cambios recientes sin reindexar), indica al usuario que conviene
  reindexar antes de confiar en el grafo.
- Nunca se indexa lo que esté en `.gitignore` — no se necesita configuración
  extra para excluir secretos (`.env`, credenciales, etc.). Este repo ya tiene
  `.gitignore` cubriendo `.env`, `session_state/`, volcados de memoria y
  reportes, así que la indexación no los toca.

### Reindexar (cuando el código cambió)

Después de cambios grandes (nuevo módulo, refactor, muchos archivos) o si una
consulta al grafo ya no coincide con el código actual:

```powershell
codebase-memory-mcp cli index_repository '{"repo_path": "C:/Repositorios/AutomationAgent"}' --progress
```

O dentro de Claude Code, en la raíz del proyecto:

> "Reindexa este repositorio con Codebase Memory MCP"

### Consultar el grafo

Pide en lenguaje natural, por ejemplo:

- "Utilizando Codebase Memory MCP, describe la arquitectura principal: módulos, clases y dependencias relevantes."
- "Traza qué funciones llaman a `X` y qué depende de `Y` antes de modificarlo."
- "¿Hay código muerto (sin uso) en este proyecto?"

### Interfaz gráfica (opcional)

Con el repo ya indexado:

```powershell
& "$env:LOCALAPPDATA\Programs\codebase-memory-mcp\codebase-memory-mcp.exe" --ui=true --port=9749
```

(Ajusta la ruta del ejecutable a donde quedó instalado — revísalo con
`Get-Command codebase-memory-mcp`.) Luego abre `http://localhost:9749`.

### Problemas comunes

| Síntoma | Causa probable | Acción |
|---|---|---|
| `codebase-memory-mcp` no se reconoce en PowerShell | PATH no actualizado en esa sesión | Cierra todas las ventanas de PowerShell/Terminal y reábrelas, o usa la ruta completa al `.exe` |
| No aparece en `/mcp` dentro de Claude Code | La sesión se inició antes del registro, o el `.claude.json` quedó mal formado | Cierra y reabre Claude Code; valida el JSON con `Get-Content "$env:USERPROFILE\.claude.json" -Raw \| ConvertFrom-Json` |
| El grafo da respuestas desactualizadas | No se reindexó tras cambios de código | Reindexar (ver arriba) |

---
*Basado en el manual interno "Codebase Memory MCP en Claude Code" del Programa de
adopción de AI de Azzule Systems (Juan Carlos Infante Coronado, v1.2).*
