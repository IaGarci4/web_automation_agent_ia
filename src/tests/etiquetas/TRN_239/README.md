# TRN-239 · API Lunex — pruebas de migración

Migración de riesgo: el back end de notificaciones de recargas pasa de **Urano**
(.NET, WCF/SOAP) a una **API FastAPI** publicada en `zeus-services`
— **no** bajo el gateway Argo, aunque la documentación lo diga (ver abajo).

Lo que hay que demostrar no es que la API «funciona», sino que **no hay
diferencias de datos** con el legacy. Por eso el caso central no es un 200: es
comparar lo enviado contra lo persistido en `lunex.TransferLN`.

---

## Esta etiqueta no abre navegador

Las pruebas van **directo a la API**. La notificación es servidor-a-servidor:
hacer la recarga por la interfaz de Hermes cuesta dinero real y ni siquiera
captura lo que se quiere medir.

---

## La URL

```
base_url = https://zeus-services.maxilabs.net/api/v1/lunex/
```

| Endpoint | Para qué |
|---|---|
| `Payments/RegisterTransaction` | Alta de transacción — JSON y SOAP |
| `Payments/CancelTransaction` | Cancelación — JSON y SOAP |
| `healthcheck` | Estado del servicio y de su BD (TRN-569) |

### Cómo se eligió mal la primera vez

Había dos candidatas. `docs/TRN-239_Postman_Guia_y_Casos.md` afirmaba
`https://test-apps.maxilabs.net/Argo/` y lo daba por *«verificado en campo:
Argo/Payments/RegisterTransaction responde»*. La colección Postman y el
runner apuntaban a `zeus-services`. Se creyó al documento por la palabra
«verificado».

Estaba mal: Argo devuelve **404 en todas las rutas de Payments**, con el host
contestando — luego no era la VPN. Lo que «respondía» era el servidor
diciendo que ahí no hay nada.

**Una afirmación escrita no es una comprobación.** La colección tenía razón
porque salía del entorno; el documento se equivocaba porque salía de la
memoria de alguien. Cuando dos fuentes se contradigan, gana la que se pueda
ejecutar.

Argo sí es el gateway del back end de Hermes —ahí viven `Argo/auth` y
`Argo/api/MoneyTransfer/*`— pero la API Lunex no está montada bajo él.

El legacy .NET sigue en `https://test-uranus.maxilabs.net/Payments/LunexService.svc`,
en la cabecera SOAP `a:To` de la colección original. **No es la API migrada**;
queda como referencia de paridad.

Para apuntar a otra base sin tocar código:

```powershell
$env:TRN239_BASE_URL="https://otro-host/ruta/"
```

---

## Los 8 casos

| Caso | Qué prueba | Subticket |
|---|---|---|
| **CP01-Healthcheck** | El servicio responde y distingue el estado de su BD | TRN-569 |
| **CP02-AltaRegisterTransaction** | Alta JSON, alta SOAP y **paridad** entre formatos | TRN-239 |
| **CP03-CancelacionTransaccion** | Cancelar en JSON y SOAP; qué `Status` queda en BD | TRN-239 |
| **CP04-NegativoAutenticacion** | Rechaza MD5 inválido **sin filtrar trazas** | TRN-293 |
| **CP05-NegativosValidacion** | Campos faltantes, `Amount` negativo, cancelar inexistente | TRN-294 · TRN-300 |
| **CP06-ComisionesDtuItu** | Las tres variantes de comisión se aceptan y persisten | TRN-295 · TRN-296 |
| **CP07-StatusFailt** | Un Status fuera de requerimiento (FAILT) **debe ser rechazado** (code 9) | TRN-239 |
| **CP08-IntegridadDatos** | Enviado = persistido, coherencia vs producción, y un reenvío no duplica | TRN-239 |
| **CP09-CatalogoErrores** | Reproduce cada Errorcode del requerimiento: **pasa cuando la API rechaza** | TRN-239 |

Los 14 de la guía consolidados, más el **CP09** (regresión negativa): manda
basura a propósito para garantizar que las validaciones (firma, esquema,
unicidad, estados…) siguen disparando tras el cambio de desarrollo.

---

## Dos veredictos: OK o FALLA

| | Significa |
|---|---|
| **OK** | Se comprobó y está bien |
| **FALLA** | Se comprobó y está mal — el detalle dice **por qué**, y eso es lo que se revisa |

Antes había un tercer estado, «NO VERIFICADO», y confundía más de lo que
ayudaba. Ahora todo es OK o FALLA. Lo que antes quedaba «sin verificar» se
resuelve:

- **Sin conexión a BD → FALLA.** Los casos de integridad SON la validación
  contra base; sin ella no hay nada que aprobar. Corre con la VPN.
- **Falta un dato de DEV** (p. ej. el mensaje de error no nombra el campo,
  TRN-294) → **FALLA** con el motivo, para llevarlo al ticket.
- **Coherencia contra producción** → cada alta se compara con las reglas que
  se cumplen al 100 % en prod; un campo que no cuadra es **FALLA** con el valor.

Y la regla de una llamada correcta son tres condiciones, no una:

```
HTTP 200   Y   Errorcode == 0   Y   Error_text contiene 'Success'
```

Un 200 con `Errorcode: 15` es un rechazo con buena cara.

### Ninguna comprobación se cumple por ausencia

La primera corrida contra un entorno sin la API desplegada dejó esto:

```
CP04  La API rechaza la firma inválida ............. PASS — HTTP 404
CP05  Rechaza el alta con campos faltantes ......... PASS — HTTP 404
CP02  Paridad SOAP vs JSON ....................... PASS — ambas rechazadas
```

Tres verdes sobre un endpoint que no existe. El patrón es siempre el mismo:
**una afirmación en negativo se cumple sola cuando no hay nadie al otro
lado.** «Rechaza» lo cumple un 404; «no trae Fault» lo cumple una página de
error; «los dos formatos se comportan igual» lo cumplen dos ausencias.

La regla que lo corrige: *un caso negativo solo prueba algo si el
destinatario existe para decir que no.*

- `Respuesta.endpoint_existe` — falso ante 404, 405, 5xx y sin respuesta.
- `rechazada` exige que el endpoint exista **y** que la API diga que no.
- `veredicto_negativo()` devuelve **NO VERIFICADO** —nunca PASS— cuando no
  hay endpoint.
- El preflight sondea `Payments/*` con **GET**: un `405 Method Not Allowed`
  prueba que la ruta existe sin dar de alta nada; un `404` prueba que no. Si
  ninguna está publicada, la corrida se omite entera con el motivo.

---

## Cómo correrlo

**Todo de una vez** — preflight, los 8 casos, el happy path y los dos
reportes abiertos en el navegador:

```powershell
.\tools\trn239_correr_todo.ps1
```

```powershell
.\tools\trn239_correr_todo.ps1 -SinBD          # fuera de la VPN
.\tools\trn239_correr_todo.ps1 -Sku 8456       # forzar un producto
.\tools\trn239_correr_todo.ps1 -SinHappyPath   # solo los casos
```

Por partes:

```powershell
python -m src.tests.etiquetas.TRN_239.preflight   # ¿hay API? (2 segundos)
pytest src/tests/etiquetas/TRN_239 -v -s          # los 8 casos
pytest src/tests/etiquetas/TRN_239 -k CP08 -v -s  # solo integridad

# El happy path es un SCRIPT, no un test: con pytest recolecta 0 items.
python src\tests\etiquetas\TRN_239\trn239_happy_path.py
```

Requiere `requests` (ya está) y, para validar en BD, `pyodbc` más un driver
ODBC de SQL Server:

```powershell
pip install pyodbc
```

### Variables

| Variable | Defecto | Para qué |
|---|---|---|
| `TRN239_BASE_URL` | `https://zeus-services.maxilabs.net/api/v1/lunex/` | Base de la API |
| `TRN239_ALTAS` | `2` | Cuántas altas por corrida |
| `TRN239_VALIDAR_BD` | `1` | `0` desactiva la validación en BD |
| `TRN239_CANCEL_STATUS` | `VOID` | `Cancelled` para probar la otra variante |
| `TRN239_PASSWORD` | (en parámetros) | Confirmar con DEV |

La conexión a SQL sale del `.env` (`SERVIDOR_SQL`, `NAME_BD`, `AUTENTICATION`,
`USER_SQL`, `PASSWORD_SQL`) — ver `src/helpers/sql_helper.py`.

---

## Cada alta escribe datos reales

Una alta exitosa **inserta en `lunex.TransferLN`** del ambiente TEST. Por eso
`TRN239_ALTAS` viene en 2 y no en 50: súbelo solo cuando quieras volumen a
propósito. `Key` y `TransactionID` son incrementales y se guardan en
`reports/trn239_contadores.json`, porque el requerimiento dice que `Key` es único e
irreutilizable y reiniciarlos haría chocar la segunda corrida del día contra la
primera.

---

## Evidencia

```
reports/evidence/TRN-239/
├── reporte_TRN-239.html          ← ESTO es lo que se adjunta a QMetry
├── resultados.json                acumulado entre corridas
└── CP0X-Nombre/
    ├── Step01-*.json              par petición/respuesta de cada llamada
    └── Step02-*.txt               sobres SOAP
```

No hay PNG: aquí la evidencia es el **par petición/respuesta**, que es lo que
alguien va a querer comparar contra el legacy dentro de seis meses.

El acumulado no se borra entre corridas, para poder estabilizar un caso a la
vez. Para la corrida que se entrega: `python tools/trn239_reset.py`.

---

## Qué hay en esta carpeta

| Archivo | Para qué |
|---|---|
| `test_CP01…CP08` | Los ocho casos |
| `flujos/lunex_api.py` | El POM de la API: un método por endpoint |
| `flujos/bodies.py` | Cuerpos, firma MD5 y sobre SOAP |
| `flujos/bd.py` | Integridad contra `lunex.TransferLN` |
| `parametros.py` · `conftest.py` · `preflight.py` | Configuración y andamiaje |
| `consultas_bd.sql` | Lo que la etiqueta NO hace sola: el comparativo contra PROD |
| `consultas_produccion.sql` | Las 10 consultas **sin datos sensibles** que se pidieron a producción |
| `ConsultasSQLProd/` | Sus resultados. Cuatro preguntas del brief se cerraron aquí |
| `trn239_happy_path.py` | Script suelto: un alta, una cancelación, un HTML |
| `PREGUNTAS_ABIERTAS.md` | Lo que falta que conteste desarrollo, y dónde se aplica cada respuesta |

### Lo que dijeron los datos de producción

Siete millones de filas de `lunex.TransferLN` corrigieron cuatro cosas que la
etiqueta estaba haciendo mal, y ninguna se habría notado en la ejecución:

| Se enviaba | Producción dice | Dónde se corrigió |
|---|---|---|
| `Phone == TopupPhone` siempre | Distintos en ITU (99.94 %), iguales en DTU | `flujos/bodies.py` |
| `ExRate 21.0025` y `HNL` fijos | Uno por SKU, y **NULL** en DTU | `parametros.PERFIL_SKU` |
| `AmountInMN 252.03` fijo | `Amount × ExRate`, al centavo | `flujos/bodies.py` |
| Un reenvío duplicado = FALLA | El `TransactionID` **no es único**; uno se repite 14 veces | `test_CP08` → NO VERIFICADO |

Cuatro SKU del catálogo tampoco existían con ese número. Todo eso pasaba las
pruebas: la API aceptaba los cuerpos igual. Es el tipo de error que solo
aparece comparando contra el mundo real.

La colección Postman se retiró: la etiqueta cubre todo lo que hacía y además
valida en base de datos y genera el reporte. Si hace falta toquetear un
endpoint a mano, `curl` o Postman con la URL de arriba bastan — pero la
evidencia del ticket sale de aquí.

---

## Lo que todavía NO se puede afirmar

Tres preguntas del brief siguen abiertas, y los casos lo dicen en vez de
inventarse el resultado:

1. **Mapeo campo→columna** en `lunex.TransferLN`. Las comparaciones prueban
   varios nombres candidatos (`flujos/bd.py::CANDIDATOS`); un campo cuya
   columna no se encuentra sale como NO VERIFICADO, nunca como coincidente.
2. **Fórmula de comisión DTU vs ITU**. El CP06 envía las tres variantes y deja
   la evidencia, pero **no verifica el importe calculado**. Lo que sí exige ya
   es la invariante que se vio en producción: dos altas del mismo SKU y monto
   tienen que repartir la misma comisión total.
3. **Idempotencia**. Si llega un `TransactionID` repetido, ¿la API debe
   rechazar, ignorar o insertar? En producción se insertan duplicados, así que
   reproducirlos no demuestra un defecto.

`VOID vs Cancelled` ya está cerrado: `Cancelled` no aparece ni una vez en 7 M
de filas. Es **VOID**.

Todo el detalle, con los números y la consulta que lo respalda, en
`PREGUNTAS_ABIERTAS.md`.
