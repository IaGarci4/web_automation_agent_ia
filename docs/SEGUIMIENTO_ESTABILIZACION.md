# Seguimiento a la estabilización del proyecto

Guía y bitácora para llevar un portal nuevo de "recién automatizado" a "estable".
Copia la tabla de seguimiento por cada flujo y ve marcando el avance.

---

## Fases de estabilización

### Fase 0 — Alta del portal
- [ ] `.env` configurado (APP_URL, credenciales, selectores de login).
- [ ] Login manual exitoso en el navegador.
- [ ] Primera corrida: sesión guardada en `session_state/`.

### Fase 1 — Primer flujo grabado
- [ ] Flujo grabado con la extensión (JSON en `tools/grabaciones/`).
- [ ] Test generado con `json_to_pom.py`.
- [ ] Revisión de selectores generados (que sean estables: testid/id).
- [ ] Primera ejecución manual (`pytest ... --headed`).

### Fase 2 — Estabilidad del flujo
- [ ] El flujo pasa 3 corridas seguidas sin intervención.
- [ ] Elementos opcionales identificados (los que no siempre aparecen) y marcados.
- [ ] Tiempos de espera razonables (sin cuelgues largos).
- [ ] El agente aprende la instrucción en lenguaje natural.

### Fase 3 — Robustez
- [ ] Reporte de auditoría revisado (testids débiles reportados a desarrollo).
- [ ] Sin errores 500/4xx en `reports/diag/` (o documentados).
- [ ] Corrida en `--headless` para CI/CD.

---

## Tabla de seguimiento por flujo

| Flujo | Grabado | Generado | Pasa 1× | Pasa 3× | Aprendido | Estable | Notas |
|---|:--:|:--:|:--:|:--:|:--:|:--:|---|
| login | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | |
| <flujo_2> | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | |
| <flujo_3> | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | |

---

## Registro de incidencias

| Fecha | Flujo | Síntoma | Causa | Solución | Estado |
|---|---|---|---|---|---|
| | | | | | |

---

## Criterios de "estable"

Un flujo se considera **estable** cuando:
1. Pasa 3 ejecuciones consecutivas sin intervención manual.
2. Sus localizadores no dependen de texto frágil ni de índices que cambian.
3. Los pasos opcionales (modales/tablas que a veces salen) no rompen la corrida.
4. La auditoría no reporta `testid` duplicados/genéricos en los elementos del flujo.
5. El agente lo ejecuta por instrucción en lenguaje natural.

## Buenas prácticas

- Graba flujos **cortos y con propósito** (un objetivo por grabación).
- Pide a desarrollo `data-testid` semánticos en los elementos que automatizas
  (la auditoría te dice cuáles faltan).
- Versiona el proyecto en Git; no subas `.env` ni `session_state/`.
- Repite con `corre <flujo> N veces` para detectar inestabilidad temprano.
