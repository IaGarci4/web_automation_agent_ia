# Resumen de avance — módulo de pagadores (para retomar con Opus)

## Objetivo original

`AutomationAgent` es un motor genérico de automatización web (Playwright + POM
+ agente de lenguaje natural) que aprende flujos grabados con una extensión de
Chrome. Se pidió portar a este proyecto una parte concreta de otro repo más
maduro, `C:\Repositorios\ai_agent` (framework QA de producción para Hermes2),
que ya tenía resuelto:

1. Un **módulo de pagadores** (Money Transfer) — catálogo de pagadores
   mexicanos (Banorte, Elektra, Soriana, etc.) separado por país.
2. La lógica del **agente en lenguaje natural** para "haz envíos a todos los
   pagadores" (10 en total) — random en todo excepto país/ciudad/pagador.
3. Una estructura **extensible**: agregar pagadores o países nuevos sin tocar
   el motor, para que el agente vaya "aprendiendo" más lenguaje natural.

El objetivo final es probar la estabilidad real del framework corriendo este
flujo contra el ambiente de test real de Hermes2
(`https://test-hermes.maxilabs.net/transfers`).

## Qué se portó (ya está en el repo)

- `src/pagadores/mexico/payers.json` — 10 pagadores activos + 7 inactivos +
  pool de ciudades/estados de México.
- `src/pagadores/flujo_mt.py` — driver del envío (llenar formulario, elegir
  sucursal, validar cálculo), genérico por país.
- `src/tests/test_envio_normal_mexico.py` — un test pytest por pagador,
  generado desde el catálogo (no hace falta grabar nada por pagador).
- `agent/brain.py` — nueva lógica NLU: detecta "todos los pagadores" (corre
  los 10), un pagador puntual (`pytest -k <pagador>`, sin abrir navegador para
  los demás), varios pagadores, y avisa si se mezclan países.
- `src/helpers/datos.py` y `validador_calculos.py` — reemplazados por las
  versiones reales (Faker + reglas de redondeo por pagador; antes eran un
  stub que no validaba nada).
- `config/reglas_calculo.json`, `config/tipos_pago.json` — catálogos de
  soporte, portados.
- `src/pages/hm_transferelektra_page.py` + locators — Page Object real de la
  pantalla de Transfers de Hermes2.
- `src/pagadores/README.md` — cómo sumar un pagador (editar JSON) o un país
  nuevo (carpeta + test), para que el crecimiento futuro no requiera tocar
  código central.
- `.env` — preset apuntando al Hermes2 de test, con selectores de login reales
  documentados en el `CLAUDE.md` de `ai_agent`.

Todo esto fue **verificado que compila** (`py_compile` en cada archivo) antes
de entregarlo. Ese fue el límite de la verificación posible desde este entorno
de trabajo: no hay red/browser real hacia `test-hermes.maxilabs.net` desde
acá, así que la ejecución real end-to-end solo la puede correr el usuario en
su máquina.

## El problema real: dos bugs de estabilidad encontrados recién al correr en vivo

Cuando el usuario lo corrió localmente (`python agent/agente.py "manda un
envio a banorte"`), aparecieron **dos defectos reales del motor genérico**,
no del módulo de pagadores en sí — es decir, esto ya estaba roto en
`AutomationAgent` antes de este trabajo, y recién se manifestó al intentar un
flujo real contra un portal con login SSO:

### Bug 1 — `config/settings.py` no definía `STORAGE_STATE` / `SESSION_DIR`

`conftest.py` y `src/helpers/session_helper.py` ya referenciaban
`settings.STORAGE_STATE` y `settings.SESSION_DIR` (para guardar/reusar la
sesión de login entre corridas), pero `config/settings.py` nunca las definía
→ `AttributeError` en el fixture `logged_page`, rompiendo **cualquier** test
que dependa de sesión persistente (no solo los de pagadores).

**Fix aplicado:** se agregaron ambas al final de `config/settings.py`:
```python
SESSION_DIR   = PROJECT_ROOT / "session_state"
STORAGE_STATE = SESSION_DIR / f"{PORTAL_NAME}_storage_state.json"
```
Se validó con un barrido de `settings.<ATRIBUTO>` contra todo el repo que no
queda ningún otro atributo referenciado sin definir.

### Bug 2 — heurístico de "sesión activa" invertido para portales con SSO externo

`SessionHelper._sesion_activa()` tenía, como última instancia, este
heurístico: *"si la URL actual ya no es `APP_URL`, entonces ya estamos
dentro"*. Esto es correcto para portales donde login y app viven en el mismo
dominio. Pero Hermes2 usa **SSO externo** (Keycloak en `sso.maxilabs.net`): si
NO hay sesión válida, `test-hermes.maxilabs.net` te redirige a
`sso.maxilabs.net`. El heurístico viejo leía ese redirect (cambio de dominio)
como "sesión activa" — exactamente al revés — y el login se saltaba. El test
quedaba parado en la pantalla de SSO intentando llenar campos del formulario
de transferencia que no existen ahí, y fallaba por timeout (30s) en el primer
campo (`transfer-customer-cellphone-0-cellphone-input`).

**Fix aplicado:** ahora, si `READY_SELECTOR` está configurado (como en el
preset de Hermes2: `[data-testid="user-navbar-item"]`), es la señal
autoritativa — se espera unos segundos por si la SPA todavía está montando el
DOM, pero si no aparece, se concluye que NO hay sesión y sí se ejecuta el
login real. El heurístico de dominio solo se usa como último recurso cuando
NO hay `READY_SELECTOR` configurado.

### Efecto colateral detectado (no confirmado como bug de código)

En la segunda corrida del usuario, la app navegó a
`https://example.com/login` (el valor por defecto del código) en vez de la
URL real de Hermes2. Causa: el `.env` local del usuario tenía el **esquema de
variables de `ai_agent`** (`USERHERMES`, `PASSHERMES`, `USERCHRONOS`,
`PASSGMAILCR`) en vez del esquema que usa `AutomationAgent`
(`PORTAL_USER`, `PORTAL_PASS`, `APP_URL`, etc.) — probablemente se
sobrescribió el `.env` preparado. Se reescribió con el esquema correcto y las
credenciales de Hermes (`IGAgent005`). *Nota de seguridad: ese `.env` viejo
traía una contraseña de Gmail en texto plano (`PASSGMAILCR`) que no era de
este proyecto — se recomendó al usuario rotarla.*

## Estado actual

- Los dos bugs de sesión/login están corregidos y confirmados por
  `py_compile` + revisión manual línea por línea (el sandbox de este entorno
  tuvo un problema de sincronización de archivo intermitente en esta sesión —
  varios archivos mostraban contenido viejo/truncado en `bash` mientras que
  el canal de archivos real, autoritativo, siempre estuvo correcto; se
  confirmó copiando el contenido a un archivo nuevo y compilándolo de cero
  cada vez que hubo duda).
- **Todavía no se confirmó una corrida exitosa end-to-end** — el usuario
  estaba a punto de reintentar con los dos fixes aplicados cuando se pidió
  este resumen. Ese es el paso inmediato pendiente.
- Pendiente de la tarea original de modernización (no arrancado aún):
  `pyproject.toml`, `requirements.txt` pineado, CI (`.github/workflows`),
  `Dockerfile`, y tests unitarios de `agent/brain.py`.
- Pendiente: reforzar `dom_audit.py`/`diagnostics.py` con accesibilidad y
  métricas de performance.

## Qué necesita entender Opus para retomar

1. El módulo de pagadores en sí (catálogo, driver, test generado, NLU) está
   completo y no es sospechoso de causar las fallas vistas — las fallas son
   del **motor genérico de sesión/login**, que ya tenía estos huecos antes de
   portar el módulo, simplemente nunca se había ejercitado contra un portal
   con SSO externo real.
2. Si al reintentar aparece un tercer problema, lo más probable es que sea en
   la misma zona (`conftest.py` / `session_helper.py` / selectores de
   `.env`) — no en `src/pagadores/` — dado el patrón de los dos bugs ya
   encontrados.
3. Los selectores de login (`login-form-username-input`, `#password`,
   `login-form-submit-button`, `[data-testid="user-navbar-item"]`) vienen
   documentados como reales en el `CLAUDE.md` de `ai_agent`, así que si fallan
   ahí, revisar primero si Hermes2 cambió su UI de login antes de sospechar
   del código.
