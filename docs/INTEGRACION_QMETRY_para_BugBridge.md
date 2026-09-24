# Integración Agente de IA → QMetry / Jira

**Resumen técnico para el proyecto BugBridge**
Origen: `AutomationAgent` (Playwright + pytest) · QMetry Test Management for Jira **Cloud** (QTM4J)
Autor del código: pipeline de automatización QA de Maxi Remesas · Fecha: septiembre 2026

---

## 0. Para qué sirve este documento

En `AutomationAgent` conseguimos que una suite automatizada deje sus evidencias
—capturas de pantalla— **dentro del paso correcto de un Test Case, en el Test
Cycle correcto de QMetry**, y que además escriba el resultado (Pass/Fail/NA) de
cada paso. Todo sin intervención humana y sin que un fallo de la subida tumbe
una prueba que ya había pasado.

El camino tuvo varias trampas que no están documentadas en ningún sitio y que
costaron días de depuración. Este documento las deja escritas para que
BugBridge no las repita.

> **Nota de alcance.** No conozco la arquitectura interna de BugBridge. Lo que
> sigue describe con precisión lo que hicimos y por qué; la sección 6 traduce
> eso a recomendaciones concretas, marcando claramente cuáles son
> transferibles tal cual y cuáles habría que adaptar.

---

## 1. Arquitectura en cuatro capas

Separar estas capas fue lo que hizo el sistema depurable. Recomiendo
reproducir la separación aunque el destino sea Jira y no QMetry.

```
┌─────────────────────────────────────────────────────────────┐
│ 4. HOOK          conftest.py                                │
│    Fixture autouse: al terminar cada test, decide si sube   │
│    y con qué veredicto. NUNCA lanza excepción.              │
├─────────────────────────────────────────────────────────────┤
│ 3. ORQUESTACIÓN  src/helpers/qmetry_sync.py                 │
│    Empareja archivos de evidencia ↔ pasos del caso.         │
│    Idempotencia, agrupación, reglas de negocio.             │
├─────────────────────────────────────────────────────────────┤
│ 2. CLIENTE       src/helpers/qmetry_client.py               │
│    HTTP puro contra la API. Sin lógica de negocio.          │
│    Traduce rarezas del tenant (rutas, cuerpos, alias).      │
├─────────────────────────────────────────────────────────────┤
│ 1. CONFIG        config/settings.py + config/qmetry_mapeo.json │
│    Credenciales por .env · mapeo declarativo por caso.      │
└─────────────────────────────────────────────────────────────┘
        ↑
   HERRAMIENTAS DE DIAGNÓSTICO  tools/qmetry_*.py  (7 scripts)
   Cada una responde UNA pregunta. Ver sección 5.
```

**Por qué importa la separación:** cuando algo falla, la pregunta siempre es
«¿es la API, es el mapeo, o es el disparador?». Con las capas mezcladas esa
pregunta no tiene respuesta rápida. Con ellas separadas, cada herramienta de
diagnóstico ataca una capa.

---

## 2. El modelo de datos de QMetry (la cadena de IDs)

Esto es lo primero que hay que entender y no es obvio: **para adjuntar algo a
un paso hacen falta cuatro identificadores encadenados**, y solo el primero es
el que se ve en la interfaz.

```
Test Cycle key      BM-TR-1370        ← lo que ve el humano
   ↓ GET /testcycles/{key}
cycleId             (alfanumérico)    ← lo que piden todos los demás endpoints
   ↓ POST /testcycles/{cycleId}/testcases/search  {filter:{key:"BM-TC-4644"}}
testCaseExecutionId                   ← la EJECUCIÓN del caso en ESE ciclo
   ↓ GET .../testcase-executions/{execId}/teststeps
testStepExecutionId                   ← la ejecución de UN paso
```

Puntos críticos:

- **El caso tiene que estar ligado al ciclo.** Si `BM-TC-4644` no está dentro
  de `BM-TR-1370`, el `search` devuelve vacío. No es un error de permisos
  aunque lo parezca.
- **`testStepSeqNo` ≠ `testStepExecutionId`.** El primero es el número visible
  (1..N); el segundo es el id interno. Nosotros construimos un diccionario
  `{seqNo: stepExecutionId}` y trabajamos siempre con el seqNo, que es el
  único número que un humano puede verificar mirando la pantalla.
- **Un caso puede tener VARIAS ejecuciones en el mismo ciclo.** La interfaz
  muestra la última. Si subes a otra, la API te dice «éxito» y en pantalla no
  aparece nada. Este fue un día entero de depuración; ver `tools/qmetry_diag.py`.

---

## 3. La trampa grande: los adjuntos NO pasan por la API

Esta es la parte que nadie espera y la que más tiempo cuesta.

**La API de QMetry no recibe el archivo.** Entrega credenciales de un POST
pre-firmado a S3, y el binario se sube directo a Amazon. Son dos peticiones a
dos servidores distintos:

```python
# 1) Credenciales (a QMetry, con tu apiKey)
GET /rest/api/latest/testcycles/{cycleId}/teststep-executions/attachments/url
    ?projectId=10030&fileName=captura.png&testStepExecutionId=...&inline=false
→ { "endpoint_url": "https://s3...", "params": { ...campos firmados... } }

# 2) Subida (a S3, SIN cabeceras de QMetry)
POST {endpoint_url}
    multipart: todos los `params` + el binario
→ HTTP 201
```

Dos detalles que hacen fallar la subida en silencio:

1. **El binario va SIEMPRE al final del multipart.** Es requisito de las
   políticas POST de S3, no un capricho. Si va antes que los campos firmados,
   S3 rechaza o —peor— acepta un archivo vacío.
2. **No mandes cabeceras de QMetry al POST de S3.** Es S3 puro. La `apiKey` ahí
   sobra y puede romper la firma.

Implementación (`qmetry_client._subir_a_s3`):

```python
campos = [(k, (None, str(v))) for k, v in params.items()]
campos.append((campo_archivo, (ruta.name, ruta.read_bytes(), tipo)))  # ← al final
requests.post(endpoint, files=campos, timeout=60)
```

**Cómo verificar que llegó bien:** si el adjunto aparece listado con `size: 0`,
el archivo llegó vacío a S3 — casi siempre por el orden del multipart.

---

## 4. Las cinco rarezas que costaron depuración

Ninguna de estas está en la documentación oficial. Las dejo con el síntoma
primero, porque es lo que verá quien las sufra.

### 4.1 `inline` tiene default OPUESTO al pedir y al listar

**Síntoma:** subes la imagen, la API responde 201, y al listar los adjuntos la
lista sale vacía. Parece que la subida falló. No falló.

| Operación | Endpoint | Default de `inline` |
|---|---|---|
| Pedir credenciales | `GET .../attachments/url` | `false` (adjunto suelto) |
| Listar adjuntos | `GET .../attachments` | `true` (incrustados) |

Si no pasas `inline=false` explícito al **listar**, estás preguntando por una
categoría distinta de la que subiste. Nosotros listamos probando ambos valores
(`for en_linea in (False, True)`).

### 4.2 Imagen visible en «Actual Result» = subir + escribir el campo

**Síntoma:** la imagen está adjunta pero no se ve en el paso, como sí se ve
cuando un humano pega una captura.

QMetry no usa HTML: usa **wiki markup de Jira**. Y subirla no basta, hay que
referenciarla en el campo:

```
!{base_url}/app/inline-attachments/TESTCASE_EXECUTION?fileName={nombre}&token={token}|width=W,height=H!
```

- `{nombre}` **no es el nombre de tu archivo**: QMetry le añade un timestamp y
  te lo devuelve en `params["x-amz-Meta-file-name"]`.
- `{token}` viene en `params["x-amz-Meta-token"]`.
- Ambos solo aparecen si pediste las credenciales con `inline=true`.
- Luego: `PUT .../teststep-executions/{stepId}` con `{"actualResult": markup}`.

Cómo lo descubrimos: `tools/qmetry_ver_paso.py` vuelca el `actualResult` crudo
de un paso donde un humano pegó una imagen a mano. Copiamos el formato exacto.
**Esa técnica es generalizable: cuando una API no documenta un formato, haz la
acción a mano en la interfaz y lee el resultado por API.**

### 4.3 El indexado del adjunto es ASÍNCRONO

**Síntoma:** subes y consultas inmediatamente; no está. Un minuto después, sí.

Un evento de S3 dispara el indexado en QMetry. Un `GET` inmediato puede venir
vacío aunque todo haya ido bien. Solución: reintentos con backoff
(`esperar_adjunto`, 6 intentos, espera creciente). **No confundas «todavía no
indexado» con «falló».**

### 4.4 El catálogo de resultados cambia de ruta según el tenant

**Síntoma:** las imágenes suben pero el estatus del paso no cambia nunca.

Los ids de Pass/Fail/NA **son distintos en cada proyecto**, y el endpoint para
leerlos cambia entre despliegues. Probamos cuatro rutas en orden:

```python
"/projects/{pid}/execution-results"
"/projects/{pid}/executionresults"
"/execution-results"
"/executionresults"
```

Y resolvemos **por nombre, nunca por id hardcodeado**, con tabla de alias
porque cada tenant los escribe distinto:

```python
"pass": ("pass", "passed", "aprobado", "exitoso", "ok")
"fail": ("fail", "failed", "fallido", "error")
"na":   ("na", "n/a", "not applicable", "no aplica", "not executed", "blocked")
```

### 4.5 Los nombres de campo del PUT también varían

**Síntoma:** el `PUT` devuelve 400 por un campo, y pierdes el estatus entero.

Unos tenants aceptan `comment`, otros `comments`. Implementamos un
**PUT tolerante** que prueba varios cuerpos en orden de preferencia y se queda
con el primero que el servidor acepte:

```python
cuerpos = [{**base, "comment": txt}, {**base, "comments": txt}, base]
```

El orden importa: el último es el cuerpo **mínimo** (solo el resultado). Así,
si el comentario es el problema, el estatus —que es lo importante— se escribe
igual. *Degradación elegante en lugar de todo-o-nada.*

### 4.6 (bonus) La región del tenant invalida la API Key

**Síntoma:** `"API key is invalid"` con una key que sabes que es correcta.

QMetry Cloud tiene región US (`qtmcloud.qmetry.com`) y Australia
(`syd-qtmcloud.qmetry.com`). La misma key es «inválida» contra el servidor
equivocado. `tools/qmetry_auth_check.py` prueba la **matriz completa**:
región × (solo `apiKey` vs `apiKey` + Basic auth de Jira) × endpoint.

Autenticación que usamos:

```python
headers = {"apiKey": QMETRY_API_KEY, "Accept": "application/json"}
# Algunos tenants exigen ADEMÁS el Basic de Jira (correo + API token Atlassian)
if jira_email and jira_token:
    headers["Authorization"] = "Basic " + b64(f"{email}:{token}")
```

---

## 5. La escalera de diagnóstico

Siete herramientas pequeñas, **cada una responde una sola pregunta**. Esto es
lo que más recomiendo copiar: convierte «no funciona» en «falla en el paso 3».

| Herramienta | Pregunta que responde |
|---|---|
| `qmetry_auth_check.py` | ¿Mis credenciales son válidas, y contra qué región/headers? |
| `qmetry_probe.py --solo-leer` | ¿Qué ve la API del ciclo/caso/pasos? (no escribe nada) |
| `qmetry_probe.py` | ¿Puedo subir UNA imagen a UN paso, mostrando cada etapa? |
| `qmetry_diag.py` | ¿Dónde quedaron los adjuntos? ¿size=0? ¿varias ejecuciones? |
| `qmetry_ver_paso.py` | ¿Cuál es el formato CRUDO de un campo hecho a mano? |
| `qmetry_resultados.py` | ¿Cómo se llaman exactamente Pass/Fail/NA en este proyecto? |
| `qmetry_estatus.py` | Si el estatus no cambia: ¿es el catálogo o es el PUT? |

**El patrón:** `--solo-leer` por defecto en todo lo que pueda escribir. Un
diagnóstico que modifica el sistema que estás diagnosticando no sirve.

---

## 6. Decisiones de diseño que recomiendo copiar en BugBridge

Estas son independientes de QMetry — aplican igual si BugBridge escribe en Jira.

### 6.1 Switch maestro apagado por defecto

```python
QMETRY_UPLOAD = os.getenv("QMETRY_UPLOAD", "0") in ("1","true","si","yes")
```

La lógica está integrada en **todos** los casos, pero no escribe nada hasta que
alguien la enciende a propósito. Para BugBridge esto es más crítico todavía:
crear tickets es una acción con consecuencias sociales, no solo técnicas. Un
bucle mal configurado que abre 200 bugs es un incidente.

### 6.2 La integración NUNCA tumba la prueba

```python
except Exception as e:      # nunca tumbar un test por la subida
    logger.warning("[QMetry] No se pudieron subir las evidencias: %s", e)
```

Subir evidencias es **secundario**. Si la API está caída, la prueba que pasó
debe seguir marcada como pasada. Esto parece obvio y casi nadie lo hace.

### 6.3 El veredicto viene del ejecutor, no del artefacto

Error tentador: «hay captura del paso 5 → el paso 5 pasó». Falso. Una captura
puede ser justo la del error.

Usamos el hook de pytest para capturar el resultado real:

```python
@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    setattr(item, "rep_" + outcome.get_result().when, outcome.get_result())
```

Y luego `rep_call.passed` decide. **Para BugBridge:** la severidad o el estado
del bug debe salir del sistema que observó el fallo, no de heurísticas sobre
los artefactos.

### 6.4 Idempotencia por identidad del artefacto

Antes de subir, listamos lo que ya hay y comparamos por nombre. Reejecutar el
pipeline no duplica nada.

**Para BugBridge esto es EL problema central.** Un puente de bugs sin
idempotencia genera duplicados en cada corrida. Sugerencias de clave de
deduplicación, de más a menos robusta:

1. **Firma del fallo**: hash de (test id + tipo de excepción + frame más
   profundo del propio código, ignorando líneas de librerías). Sobrevive a
   cambios de mensaje y de timestamps.
2. **Campo custom en Jira** con esa firma → búsqueda JQL exacta antes de crear.
3. Si ya existe y está abierto: **comentar** con la nueva ocurrencia y subir la
   evidencia nueva, no crear otro.
4. Si existe y está cerrado: **reabrir** con etiqueta de regresión — que es
   información mucho más valiosa que un bug nuevo.

Evita deduplicar por el texto del mensaje de error: los timestamps, ids y rutas
lo hacen distinto en cada corrida.

### 6.5 Convención antes que configuración

El destino de cada evidencia sale **del propio nombre del archivo**:

```
Step02-cliente_beneficiario.png   → paso 2
```

```python
_RE_PASO_EN_NOMBRE = re.compile(r"(?:^|[_\-])(?:step|paso|p|s)[ _\-]?0*(\d{1,2})(?:[_\-]|$)", re.I)
```

El mapeo JSON (`config/qmetry_mapeo.json`) quedó solo como **respaldo** para
módulos compartidos entre casos, que no pueden llevar un número fijo porque
cada caso los numera distinto. Resultado: el 90 % de las evidencias no
necesita configuración, y la que la necesita está declarada en un sitio.

### 6.6 Estados honestos y auditables

Los pasos fuera del alcance de la automatización (impresión física, edición
manual) se marcan **NA con un motivo escrito**, no Pass:

```json
"na": [5, 7, 8, 9],
"na_motivo": "No aplica en la ejecución automatizada: el proceso no usa
              impresora física, y la modificación manual queda fuera del alcance."
```

Un ciclo lleno de Pass falsos es peor que uno con NAs explicados. Cuando un
auditor pregunte «¿esto se probó?», la respuesta está escrita.

### 6.7 No ensuciar el registro oficial con corridas fallidas

Si el caso falla, **no subimos nada**. Las capturas quedan en `reports/` para
depurar, y se suben cuando el caso pase (o a la fuerza con
`tools/qmetry_subir.py CP02`). El ciclo de QMetry es el registro oficial;
llenarlo de evidencias de una corrida incompleta lo vuelve inútil.

*Para BugBridge la decisión probablemente sea la inversa* —el fallo **es** el
insumo— pero el principio se mantiene: define explícitamente qué merece llegar
al sistema de registro y qué se queda en local.

---

## 7. Si BugBridge va contra Jira directamente

Lo que cambia respecto de lo anterior:

| Aspecto | QMetry (QTM4J) | Jira REST v3 |
|---|---|---|
| Auth | Header `apiKey` (+ Basic opcional) | Basic: `email:API_TOKEN` en base64 |
| Adjuntos | 2 pasos vía S3 pre-firmado | 1 paso, pero exige `X-Atlassian-Token: no-check` |
| Texto enriquecido | Wiki markup `!img!` | **ADF** (JSON estructurado), no markdown |
| Búsqueda | `POST .../search` con filtro | JQL vía `POST /rest/api/3/search` |

Tres avisos concretos para Jira:

1. **`X-Atlassian-Token: no-check` es obligatorio** en `POST /issue/{key}/attachments`.
   Sin esa cabecera falla con un error de XSRF que no dice eso.
2. **ADF no es markdown.** El campo `description` de Jira Cloud v3 es un árbol
   JSON (Atlassian Document Format). Pegar markdown produce un ticket con el
   texto literal. Para adjuntar una imagen *dentro* del texto hay que subirla
   primero, tomar su `id`, e insertar un nodo `mediaSingle`.
3. **Los tokens de Atlassian se auto-revocan** si se detectan en un repositorio
   público. Deben ir en `.env` (gitignorado) y en `.env.example` solo como
   marcador de posición. Nosotros lo hacemos así.

---

## 8. Checklist de arranque para BugBridge

Sugerencia de orden. Cada punto es verificable antes de pasar al siguiente:

1. **Autenticación aislada.** Un script que solo pregunte «¿quién soy?»
   (`/myself` en Jira, `/projects` en QMetry). Si falla, prueba la matriz
   región × headers antes de tocar nada más.
2. **Lectura antes que escritura.** Localiza el ticket/ciclo/caso y muestra sus
   ids. Sin escribir nada. Aquí se detecta el 80 % de los problemas de
   configuración.
3. **Un adjunto, a mano, mostrando cada etapa.** Como `qmetry_probe.py`. Hasta
   que esto funcione, no automatices nada.
4. **Idempotencia.** Antes de la primera escritura automática. No después: la
   limpieza de duplicados es cara y manual.
5. **Switch apagado + no-lanza-nunca.** Antes de conectarlo al pipeline real.
6. **Estado y trazabilidad al final.** Es lo que más varía entre tenants y lo
   que menos daño hace si tarda.

---

## 9. Archivos de referencia en `AutomationAgent`

Todos comentados en castellano explicando el *porqué*, no solo el *qué*:

```
src/helpers/qmetry_client.py     Cliente HTTP. Empieza por el docstring de arriba:
                                 resume la cadena de IDs y el flujo S3.
src/helpers/qmetry_sync.py       Orquestación: mapeo evidencia↔paso, idempotencia,
                                 reglas de resultado (_marcar_resultados).
conftest.py (líneas 22-72)       El hook de pytest y la política de subida.
config/settings.py (223-246)     Credenciales, ciclos por ambiente, switches.
config/qmetry_mapeo.json         Mapeo declarativo por caso, con notas.
tools/qmetry_*.py                Las siete herramientas de diagnóstico.
```

---

## 10. Resumen en una frase

> La integración no fue difícil por la API, sino porque **tres de sus
> comportamientos son silenciosos**: los adjuntos van a S3 y no a QMetry, el
> parámetro `inline` significa lo contrario al leer que al escribir, y el
> indexado es asíncrono. Los tres producen el mismo síntoma —«la API dice que
> sí, la interfaz dice que no»— y ninguno se distingue sin herramientas que
> pregunten una cosa a la vez.
