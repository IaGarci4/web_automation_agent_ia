# KRA-1527 · El token no debe quedar ni viajar en texto plano

Automatización de la validación del fix de **KRA-1527** (Done · Highest ·
épico KRA-1531), que responde al hallazgo **5.2.1** del pentest de ioSENTRIX
(mayo 2026, severidad **Alta**).

---

## Qué se está validando

**El hallazgo.** `Hermes2Agent.exe` guardaba el JWT de autenticación **en texto
plano** en la memoria del proceso. Con *Administrador de tareas → Crear archivo
de volcado de memoria* —sin privilegios elevados— se extraía el token activo y
se reutilizaba para suplantar la sesión, **evadiendo el device-binding por
hardware ID**.

**El fix.** El token viaja cifrado entre los dos procesos:

```
  Front End (Hermes 2.0 web)
        │  mensaje
        ▼
  Hermes2Agent.exe ──── token ENCRIPTADO ────► Maxi.RulesOffice.Security.HttpProxy.exe
        ▲                                              │ desencripta y ejecuta el request
        └──────────── respuesta ◄──────────────────────┘
```

`Hermes2Agent.exe` nunca maneja el token en claro. `HttpProxy.exe` es
**efímero**: se abre al iniciar el request y se cierra al terminar — esa vida
corta es en sí una mitigación. La remediación declara además cifrado en memoria,
**DPAPI** y **zeroize** de los datos sensibles.

**Criterio de aceptación.** En **ningún** volcado de estos dos procesos debe
aparecer un JWT completo y decodificable.

---

## Qué sustituye esta automatización

El procedimiento manual que se venía haciendo:

1. Iniciar sesión en <https://test-hermes.maxilabs.net>.
2. Abrir el Administrador de tareas de Windows.
3. Seleccionar `Hermes2Agent`, botón derecho → *Crear archivo de volcado*.
4. Buscar el `.DMP` en `%TEMP%`.
5. `findstr /i /c:"eyJ" "Hermes2Agent (2).DMP"` desde CMD.
6. Copiar la salida a Notepad++ y revisarla a ojo.
7. Anotar el resultado en el reporte.

La automatización hace lo mismo **por cada flujo**, con dos mejoras que importan:

- **`findstr` solo busca la cadena `eyJ`.** El inspector la busca, la
  **decodifica** y valida los claims (`exp, iat, iss, sub, azp,
  preferred_username`). Así distingue un JWT de autenticación real de cualquier
  cadena que casualmente empiece con `eyJ` — menos falsos positivos, y un
  hallazgo defendible ante el pentester.
- **Audita también el tráfico** Front End ↔ agente. El volcado prueba que el
  token no se *almacena* en claro; la auditoría prueba que no se *transmite* en
  claro, y de paso demuestra que la comunicación **ocurrió**.

---

## Casos

Un archivo por caso, nombrado como en QMetry (`CP0X-NombreDelCaso`). Ese mismo
nombre es la carpeta de evidencias y la clave del reporte.

| Caso | Archivo | Proceso volcado | Limpieza |
|---|---|---|---|
| **CP01-EnvioMoneyTransfer** | `test_CP01_EnvioMoneyTransfer.py` | Hermes2Agent | Cancela el envío |
| **CP02-FichaDeposito** | `test_CP02_FichaDeposito.py` | Hermes2Agent | No aplica (ver abajo) |
| **CP03-EscaneoCheque** | `test_CP03_EscaneoCheque.py` | Hermes2Agent | Cancela el cheque |
| **CP04-FichaDepositoRedLenta** | `test_CP04_FichaDepositoRedLenta.py` | HttpProxy (+ Hermes2Agent) | No aplica |
| **CP05-ReimpresionRecibo** | `test_CP05_ReimpresionRecibo.py` | Hermes2Agent | Nada que limpiar |

Cobertura **adicional**, que también invoca al agente:

| Caso | Archivo | Por qué se incluye | Limpieza |
|---|---|---|---|
| **CP06-ImprimirBalanceCajero** | `test_CP06_…` | Otra ruta de impresión (un reporte, no un comprobante) | Nada que limpiar |
| **CP07-ImprimirMoneyOrder** | `test_CP07_…` | Usa una impresora **distinta** («MO Printer») | Invalida los MO |

> **La numeración se ha corrido tres veces.** Si QMetry conserva una versión
> anterior, esta es la equivalencia acumulada:
>
> | Corrimiento | Motivo | Equivalencia |
> |---|---|---|
> | 1º | La captura de firma digital era el CP04 y se descartó: no existe en la aplicación | CP05→CP04, CP06→CP05, CP07→CP06, CP08→CP07 |
> | 2º | Se eliminó la Inspección Consolidada (ver «La política de los `.DMP`») | CP07→CP06, CP08→CP07, CP09→CP08 |
> | 3º | El Control Negativo dejó de ser un caso: ahora es una compuerta del preflight | CP07→CP06, CP08→CP07 |
>
> Tras el tercero, **todos los CP son flujos reales de la aplicación**: no
> queda ninguno que pruebe la herramienta en vez del producto.

### La compuerta del inspector

Antes de cualquier caso, el preflight planta un JWT en un archivo de 4 KB y
exige que `dump_token_inspector.py` lo encuentre. Si no lo encuentra, **la
corrida se aborta**.

Es la respuesta a «¿cómo sabes que tu detector detecta?». Sin ella, un
inspector con una regresión diría *«sin token en claro»* en los siete
flujos, el reporte diría que el fix cumple, y nadie se enteraría.

Vivía como `CP06-ControlNegativo` y estaba mal por partida doble: no
validaba el criterio del ticket (prueba la herramienta, no el producto) y
**su fallo no detenía nada** — sin `-x` en `pytest.ini`, los demás casos
corrían igual y podían reportar PASS. Como compuerta sí manda.

```
$env:KRA1527_SIN_CONTROL="1"   # saltarla (solo para depurar el inspector)
```

El orden de los casos ya no importa: los siete son independientes.

---

## Todo lo que se crea, se cancela

Cada caso hace transacciones **reales** en TEST para que la aplicación invoque
al agente. Si no se cancelan, quedan vivas: ensucian los reportes del ambiente,
descuadran los balances, y el siguiente que abra el reporte no sabe qué es
basura de automatización.

| Lo que se crea | Cómo se limpia |
|---|---|
| Money Transfer | `cancelaciones.cancelar_money_transfer` — menú «···» → *Cancel* → motivo + notas |
| Cheque | `cancelaciones.cancelar_cheque` — mismo menú, confirmación simple |
| Bill Payment | `cancelaciones.cancelar_bill_payment` — listo para cuando se agregue el caso |
| Money Order | `money_order.anular_money_orders` — la app lo **invalida** (*Void*), no lo cancela |
| Ficha de depósito | **No es cancelable desde Hermes**: se concilia en Chronos. Queda anotado en el reporte para que no se lea como un olvido |

Dos decisiones que importan:

**La limpieza va ANTES del veredicto.** En la primera corrida el CP01 hizo el
envío, imprimió, y falló en `exigir_comunicacion()` — dejando la transacción
viva. Ahora se cancela primero y se juzga después: un fallo del veredicto ya no
ensucia el ambiente.

**El módulo no pregunta por tipo si «lleva notas o no».** Pulsa *Cancel* y
espera lo que aparezca: el modal de notas (Money Transfer) o la confirmación
simple (cheques, Bill Payment). Así un cambio de la app en un tipo concreto no
rompe el módulo, y no hay una tabla de excepciones que envejezca.

Para dejar las transacciones vivas y verlas en la app: `KRA1527_CANCELAR=0`.

---

## Esta etiqueta está AISLADA del sanity

Todos los flujos que usa viven en `flujos/`, como **copias**. No hay un solo
import a `src/sanity_general`, `src/pages`, `src/pagadores` ni `src/locators`.

El motivo es práctico: el sanity se mueve todos los días — se ajusta un timeout
para el CP11 y se cae el CP01. Esta suite no puede vivir con eso, porque es la
evidencia de un hallazgo de pentest con severidad Alta y tiene que poder
correrse tal cual dentro de seis meses. Al revés también aplica: un ajuste que
se haga aquí para atrapar al agente no puede romper el sanity.

| Módulo de la etiqueta | Copiado de |
|---|---|
| `flujos/base_page.py` | `src/pages/base_page.py` |
| `flujos/transferencia_page.py` | `src/pages/hm_transferelektra_page.py` |
| `flujos/locators.py` | `src/locators/hm_transferelektra_locators.py` |
| `flujos/mt.py` · `flujos/catalogo.py` | `src/pagadores/…` |
| `flujos/deposito.py` | `src/sanity_general/deposit_slip.py` |
| `flujos/cheques.py` · `money_order.py` · `balance.py` | `src/sanity_general/…` |
| `flujos/transacciones.py` | `src/sanity_general/cancelacion.py` |
| `flujos/info_adicional.py` · `cuestionario.py` · `firma_digital.py` | `src/sanity_general/…` |
| **`flujos/reimpresion.py`** | **propio — no existe en el sanity** |

**Lo único compartido** es la infraestructura, que no es lógica de flujo:
`config/` y `src/helpers/` (sesión, screenshots, datos, auditoría HA, volcados,
reporte). Romper eso rompería el proyecto entero de todas formas.

El precio del aislamiento es que las mejoras no se propagan solas: si un flujo
del sanity mejora y conviene traerlo, se copia el archivo **a mano y a
propósito**. Es exactamente el punto.

---

## CP05 — cómo funciona la reimpresión

El flujo, tal como se hace a mano:

```
Reportes > Transacciones
  → Buscar                       (los filtros por defecto ya listan el día)
  → menú «Más Acciones» (···) de una fila cualquiera
  → «Imprimir Recibo» / «Print Receipt»      ← el MISMO menú de Cancelar
  → modal «Imprimir Recibo»:
        Seleccione Tipo de Impresión → WINDOWS PRINTER
        Seleccione su Impresora      → la que traiga por defecto
  → «Imprimir»
```

Tres decisiones de diseño que conviene conocer antes de tocar
`flujos/reimpresion.py`:

- **El menú se monta en `<body>`**, no en la fila: es un
  `<p-menu appendto="body">`, así que sus opciones no están dentro del `<tr>`.
  Y como Angular deja los menús anteriores en el DOM, `.first` cae en uno
  oculto — se recorren todas las coincidencias comprobando visibilidad.
- **El texto del menú es «Imprimir Recibo»; el del botón, «Imprimir».** Buscar
  solo «Imprimir» encontraría el botón del modal. Las dos expresiones regulares
  están ancladas a propósito.
- **Los dos combos del modal comparten `id="dropdown"`**, igual que el «MO
  Printer» de los money orders. Se localizan por su etiqueta
  («Seleccione Tipo de Impresión»), con el enésimo `p-dropdown` como respaldo.

**El error al final es esperado y NO invalida el caso.** Aparece *después* de
que la petición salió hacia el Hardware Agent, que es lo único que esta etiqueta
audita. Se captura como evidencia, se anota en el reporte y se cierra el aviso
(si queda abierto, sus overlays bloquean al siguiente caso).

El tipo de impresión y la impresora se pueden forzar sin tocar código:

```powershell
$env:KRA1527_TIPO_IMPRESION="WINDOWS PRINTER"
$env:KRA1527_IMPRESORA="MICROSOFT PRINT TO PDF (PREDETERMINADO)"   # vacío = la del ambiente
```

---

## Antes de correr: el preflight

La primera corrida del CP01 tardó **1 minuto 54 en fallar**, y falló por algo
que se sabía en el segundo cero: en esa máquina no estaba `procdump` y el
navegador nunca habló con el agente. Se hizo un envío real y se ensució el
ambiente para llegar a una conclusión de entorno.

Ahora `preflight.py` mira la máquina **antes** de tocar la aplicación:

| Comprobación | Si falta |
|---|---|
| `Hermes2Agent.exe` corriendo | Los casos se **omiten** con el motivo, en el segundo cero |
| `procdump` en `PROCDUMP_PATH` | Avisa y corre **solo** la auditoría de tráfico |

La distinción es deliberada:

- **El agente no corre** → problema de entorno. Omitir es lo honesto: la
  etiqueta no puede opinar sobre el fix si el proceso auditado no existe.
- **El agente SÍ corre y no hubo tráfico** → hallazgo real, y el caso **falla**.
  Ese es el falso negativo del que habla el brief.

```powershell
$env:KRA1527_SIN_AGENTE="fallar"    # ejecutar igual y ver el fallo real
```

### Dos hallazgos de las primeras corridas

**1. El modal de éxito no pregunta si imprimir.** Dice *«Transaction
Successful! Please give the receipt to the customer»* y a continuación **«Do you
want to make another transaction?»**. El código pulsaba su botón afirmativo
creyendo que aceptaba la impresión: no imprimía nada y dejaba la app arrancando
otro envío. Ahora siempre se cierra con **NO**, sondeando el botón cada 150 ms
para no tardar (antes tardaba segundos y a veces acertaba el YES de al lado).

**2. La impresión es automática, pero solo si hay impresora configurada.** Los
money orders y los cheques sí llegaban al agente, y sus flujos empiezan por
configurar su periférico en **Configuración > Dispositivos**. El recibo del
money transfer no configuraba nada, así que la app no tenía a quién mandar el
trabajo y **no llamaba al agente** — sin error, simplemente no llamaba. El
diálogo de reimpresión (CP05) confirma el modelo: pide *Tipo de Impresión* e
*Impresora* antes de imprimir.

`flujos/impresora.py` lo resuelve, y los casos que imprimen lo llaman como
prerrequisito. La impresora concreta se puede fijar:

```powershell
$env:KRA1527_IMPRESORA_RECIBO="MICROSOFT PRINT TO PDF"   # vacío = la primera real
```

### Si sale «SIN COMUNICACIÓN» con el agente corriendo

El fallo ahora incluye el **censo de hosts** con los que sí habló el navegador,
separando los candidatos (ni la app ni CDNs conocidos). Sirve para el caso más
probable: que el agente publique su servicio en un dominio propio que resuelve
a `127.0.0.1` —práctica habitual para tener certificado TLS válido en local— y
que por tanto no case con un patrón de «localhost».

El patrón por defecto ya cubre `localhost`, `127.0.0.1`, `[::1]`,
`maxiagentes`, `hermes-agent`, `agent2hermes`. Si en tu máquina aparece otro,
el propio fallo lo lista y basta con ponerlo en el `.env`:

```ini
HW_AGENT_URL_PATTERN=localhost|127\.0\.0\.1|mi-host-del-agente
```

---

## Por qué el control negativo no es opcional

Es el **control negativo**: fabrica un archivo con un JWT de autenticación
plantado a propósito y exige que el inspector devuelva **FAIL**.

Sin él, un inspector roto daría "limpio" en los demás casos y ningún PASS sería
defendible. Es la prueba del instrumento, no del producto — y es lo primero que
preguntaría un auditor.

```powershell
```

---

## Tres reglas que pueden invalidar todo

Esta suite se aparta del sanity a propósito. Si alguna se rompe, el resultado es
un **falso negativo**: verde sin haber probado nada.

- **No se neutraliza `window.print`.** El sanity ejecuta
  `window.print = () => {}` en todos sus tests; aquí está prohibido, porque sin
  impresión no se invoca al agente.
- **Se imprime en físico.** En el diálogo del recibo digital se pulsa
  *NO, Print* (ver la sección siguiente); el *YES, Send* lo mandaría por
  SMS/correo y no invocaría al agente. Ojo con el otro modal: el de éxito
  pregunta «¿otra transacción?», así que ahí el afirmativo abre un envío nuevo
  y siempre se cierra con *NO*.
- **Se conservan los flags de Chromium** del `conftest`
  (`--ignore-certificate-errors`, `--allow-insecure-localhost`,
  `--disable-web-security`, `--allow-running-insecure-content`) y se corre con
  `PW_HEADLESS=0`. Sin ellos el navegador bloquea la llamada al agente local.

Por eso cada caso llama a **`exigir_comunicacion()` antes de dar un veredicto**:
si no hubo tráfico con el agente, el test **falla** en lugar de aprobar en falso.

---

## Datos: qué se aleatoriza y qué NO

Se aleatoriza lo que da igual. **La geografía no.**

| Dato | Cómo se genera |
|---|---|
| Nombres, apellidos, direcciones, ZIP, fecha de nacimiento | Faker, distinto en cada corrida |
| **Ciudad y estado de destino** | **Del catálogo del pagador** (`payer_city`) |
| Sucursal | Al azar entre las del modal |

El motivo es un fallo real: **no todos los pagadores operan en todas las
ciudades**. ELEKTRA tiene sucursales en Guadalajara; cuando el azar elegía
Mérida, el modal de sucursales salía vacío, el formulario quedaba inválido y
Continue no avanzaba nunca. Parecía un fallo del script y era del dato.

`destino_del_pagador()` toma la pareja pagador/ciudad que el módulo de pagadores
declara buena —la misma que usa el agente cuando le pides «haz un envío a
Elektra»—. `destino()` sigue existiendo para pruebas que quieran barrer
destinos, pero un happy path no debe usarlo.

## Teléfonos y correos: la regla de producción

Estas pruebas también se correrán **en producción**, donde la transacción es
real y Hermes ofrece mandar el recibo por SMS. Un número aleatorio tiene dueño:
si acierta con uno activo, una persona ajena recibe el recibo de una prueba.
Es una fuga de datos de un cliente real y no se puede deshacer.

```
Ambiente TEST/STAGE  →  cualquier número
Ambiente PRODUCCIÓN  →  número IMPOSIBLE, sin destinatario
```

Lo aplica **el generador de datos**, no el flujo. Esa decisión es deliberada:
una protección que hay que acordarse de activar es una protección que algún día
no se activa.

Los rangos no son inventados:

| Dato | En producción | Por qué no llega a nadie |
|---|---|---|
| Teléfono EE.UU. | `210-555-01NN` | El NANP reserva `555-0100`–`555-0199` para uso ficticio, en cualquier área |
| Teléfono México | `555-XXX-XXXX` | La LADA `555` no es asignable (CDMX es `55`, de dos dígitos) |
| Teléfono Colombia | `573-000-XXXX` | Se conserva el prefijo que exige la validación, y el abonado arranca con `0`: los móviles colombianos empiezan por `3` |
| Correo | `qa.kraNNNN@example.com` | `example.com` está reservado por la RFC 2606 y no tiene buzones |

Se pueden ajustar sin tocar código: `TEL_FICTICIO_US_AREA`, `TEL_FICTICIO_MX`.

> ⚠️ **Antes de la primera corrida en producción**: el rango de EE.UU. y el
> correo tienen respaldo normativo; el de México lo elegí por análisis del plan
> de numeración, no por una reserva oficial —no existe una. Conviene que
> Cumplimiento lo confirme.

---

## El modal del recibo digital (`flujos/modales.py`)

Tras *Sí, Enviar*, Hermes interpone un diálogo: **«Does the customer want to
receive the digital receipt?»**, con dos botones — *YES, Send* y *NO, Print*.

Se pulsa **«NO, Print»**, y la elección no es de estilo:

| Botón       | Qué hace                        | ¿Invoca al Hardware Agent? |
|-------------|---------------------------------|----------------------------|
| `YES, Send` | Manda el recibo por SMS/correo  | **No**                     |
| `NO, Print` | Imprime en físico               | **Sí**                     |

Elegir el otro botón dejaría el caso pasando sin haber probado el fix — el mismo
falso negativo del que avisa la sección anterior, por una vía distinta.

**Qué pasaba mientras nadie lo cerraba:** el flujo no fallaba, se *colgaba*. El
modal de éxito no montaba (15 s), el cierre con NO sondeaba en vano (8 s), la
navegación a Reportes chocaba con el overlay y la búsqueda para cancelar volvía
vacía (20 s). Por fuera parecía lentitud —«tarda muchísimo y luego sí funciona»—
cuando era un botón sin pulsar.

La regla del módulo es **si está, lo cierro; si no está, sigo**. Preguntar
cuesta milisegundos, así que se pregunta en todos los puntos donde el flujo
podría toparse con él: al enviar (`mt`), al cerrar el modal de éxito, al navegar
a Reportes (`transacciones`), antes de cancelar, al reimprimir, en la ficha de
depósito y en los cheques. Añadir un diálogo nuevo es añadirlo a
`atender_bloqueantes` — un solo sitio.

---

## El caso difícil: capturar el HttpProxy (CP04-FichaDepositoRedLenta)

El caso se llamaba `CP04-VolcadoHttpProxy`. El nombre describía la **técnica**
en vez del caso, y eso confundía a quien abría el reporte: la evidencia son
capturas de una ficha de depósito, no de un volcado. Funcionalmente es el
mismo flujo que el CP02 —foto, monto, Send—; lo que cambia es que aquí el
envío va con la red frenada. El nombre nuevo dice el flujo y el apellido dice
la variante.

Roman Arce lo advirtió: *«la app de HttpProxy se abre y se cierra, solo está
abierta cuando se hace un request»*. Dos medidas, en este orden:

1. **`procdump -w` armado ANTES de disparar la acción.** El flag `-w` espera a
   que el proceso arranque y lo vuelca en cuanto aparece. Eso elimina la carrera
   — no hay que perseguirlo con un bucle.
2. **Red ralentizada por CDP** (`Network.emulateNetworkConditions`), a 50 kbps
   y 500 ms de latencia por defecto. Es la idea de la «conexión lenta» que
   propuso Roman, hecha determinista en vez de depender del internet de la
   máquina. Se activa **solo** alrededor de la acción.

Si aun así no se captura, **eso es un hallazgo válido, no un fallo**: significa
que el proceso es demasiado efímero para volcarse, lo cual es mitigación por
diseño. El caso lo documenta como *no reproducible* y sigue.

```powershell
# Ampliar más la ventana si hace falta
$env:KRA1527_PROXY_KBPS="20"; $env:KRA1527_PROXY_LATENCIA_MS="1000"
```

---

## Requisitos en la máquina

| Requisito | Necesario para | Si falta |
|---|---|---|
| **Maxitransfer Hardware Agent** corriendo | CP01–CP07 (todos) | El preflight **omite** esos casos en el segundo cero, con el motivo |
| **procdump** (Sysinternals) en `PROCDUMP_PATH` | Los volcados de memoria | La auditoría de tráfico corre igual; el volcado se reporta *no realizado*, **nunca** como aprobado |
| `PW_HEADLESS=0` | Que la impresión se dispare | El navegador puede no invocar al agente |
| Impresora / escáner configurados | CP02, CP03, CP06, CP07 | El caso concreto falla en su propio paso |

Descarga de procdump:
<https://learn.microsoft.com/sysinternals/downloads/procdump>

```ini
# .env
PROCDUMP_PATH=C:\Tools\Sysinternals\procdump.exe
DUMP_OUT_DIR=%TEMP%
KRA1527_DUMP=1        # 0 = solo auditar el tráfico, sin volcar memoria
```

Sin procdump la etiqueta sigue sirviendo, pero **prueba la mitad**: demuestra
que el token no *viaja* en claro, no que no se *almacena* en claro. Y el
criterio de aceptación del hallazgo es el almacenamiento, así que para la
evidencia final procdump no es opcional.

---

## Cómo ejecutar

```powershell
# Empezar de cero (borra evidencias, reporte y .DMP)
python tools/kra1527_reset.py

# Solo el control negativo — empieza por aquí (no toca la app ni el agente)

# Todo, en el orden correcto (lo fija el conftest)
$env:PW_HEADLESS="0"; pytest src/tests/etiquetas/KRA_1527 -v -s

# Un caso suelto — recomendado mientras se estabiliza
pytest src/tests/etiquetas/KRA_1527/test_CP05_ReimpresionRecibo.py -v -s

# Sin volcados de memoria: solo auditoría de tráfico
$env:KRA1527_DUMP="0"; pytest src/tests/etiquetas/KRA_1527 -v -s

# Dejar las transacciones vivas para verlas en la app
$env:KRA1527_CANCELAR="0"; pytest src/tests/etiquetas/KRA_1527 -k CP01 -v -s
```

Correr la suite completa se reordena sola (control negativo primero, inspección
consolidada al final).

**El reporte se acumula entre corridas, a propósito**: así se puede estabilizar
un caso a la vez sin perder los resultados de los otros. Para la corrida que se
va a entregar como evidencia, primero `python tools/kra1527_reset.py`.

Al correr casos sueltos no hay dependencias entre ellos: cada uno captura e
inspecciona su propio volcado y escribe su veredicto en el reporte.

---

## Evidencia

```
reports/evidence/KRA-1527/
├── reporte_KRA-1527.html                    ← ESTO es lo que se comparte
├── resultados.json                           acumulado entre corridas
├── CP01-EnvioMoneyTransfer/                  capturas + reportes del inspector
├── CP05-ReimpresionRecibo/                   Step01…Step03 + el PDF impreso
└── VolcadoMemoriaDMP/                        los .DMP (git los ignora)
```

Las capturas se nombran `StepNN-<que_muestra>.png`, con NN = el paso del caso
en QMetry. Así se suben al paso correcto sin mapeo intermedio, y varias
imágenes pueden compartir un paso.

El reporte consolidado muestra, por flujo: el veredicto, las llamadas al agente
con su análisis, y el resultado de cada volcado con enlace al detalle.

**El reporte nunca contiene tokens.** De cualquier hallazgo se muestran solo sus
*claims* y su longitud; el valor se sustituye por
`«JWT-AUTH redactado · N caracteres»` **al capturar**, así que tampoco llega al
`resultados.json`. La evidencia debe demostrar la fuga, no convertirse en una.

### La política de los `.DMP`

Una sola regla, y el caso que la complicaba ya no está:

```
cada caso  →  captura + inspecciona (su veredicto) + CONSERVA el .DMP
purga      →  a mano, al cerrar el ticket:  python tools/kra1527_volcar.py --purgar
```

Los volcados **no se borran solos**. Viven en
`reports/evidence/KRA-1527/VolcadoMemoriaDMP/`, y tanto `borrar_volcados()`
como `kra1527_reset.py` se niegan a tocar esa carpeta: es la evidencia que
sostiene el hallazgo, y un volcado cuesta una transacción real más medio giga.
Pesan, sí — de ahí que la purga sea un acto deliberado y no un efecto
secundario.

> **Hubo un CP06-InspeccionConsolidada y se eliminó.** Su trabajo era releer
> todos los volcados en una pasada y luego borrarlos. Las dos mitades se
> quedaron sin sentido: cada caso ya inspecciona el suyo con vector y
> vigencia —más información de la que daba la pasada consolidada— y el
> borrado está desactivado desde que la carpeta es la evidencia. Peor aún,
> por defecto no releía nada: agregaba lo que ya había en el reporte,
> **incluida su propia entrada anterior**, así que duplicaba los hallazgos en
> cada corrida (2 → 4 → 6…) y aparecía en el resumen como un caso «con token
> en claro» sin haber tocado la aplicación.

Para depurar un volcado a mano: `KRA1527_CONSERVAR_DMP=1` — y bórralos después,
que pesan cientos de MB y llevan datos sensibles. Están en `.gitignore` y
**nunca** deben subirse a QMetry: a QMetry va el HTML.

---

## Veredictos

| Veredicto | Significa |
|---|---|
| **PASS** | No apareció ningún token en claro |
| **FAIL** | JWT de autenticación completo y decodificable → **hay un hallazgo** |
| **WARN** | Cadenas `eyJ…` que no decodifican: posible dato cifrado. Revisar |
| **SIN COMUNICACIÓN** | El flujo no ejercitó al agente → **no prueba nada** |
| **NO CAPTURADO** | No se pudo volcar (proceso efímero o sin procdump) |

`SIN COMUNICACIÓN` no es un aprobado. Es la señal de que el caso no hizo su
trabajo.

### Un hallazgo NO pone el CP en rojo

Estos veredictos son del **reporte**, no de pytest. Son dos preguntas
distintas y las contesta cada uno la suya:

| | Pregunta | Dónde se lee |
|---|---|---|
| **pytest** | ¿La automatización hizo su trabajo? | verde / rojo en la consola |
| **Reporte** | ¿Hay un token expuesto? | `reporte_KRA-1527.html` |

Un CP en verde con veredicto FAIL en el reporte es un resultado normal y
correcto: el flujo corrió entero *y* encontró lo que venía a buscar.

Se llegó aquí por dos motivos. Uno, un hallazgo real se veía igual que un
selector roto —rojo, entre trazas de pytest—, y lo que hay que llevarle a
desarrollo se perdía en el ruido. Dos, mientras el bug siguiera abierto la
suite no podía cerrar en verde nunca, que es justo cuando más falta hace
correrla entera para ver si algo *más* se rompió.

El hallazgo no se diluye: sale en WARNING en el log con su vector y su
vigencia, en el resumen de cierre, en el HTML del ticket, y el `.DMP` que lo
prueba se conserva en disco.

**Lo que sí deja el CP en rojo:** que el flujo funcional se rompa (no escaneó,
no imprimió), que el volcado se capture pero **no se pueda leer** —eso no es
un hallazgo, es una comprobación que no se hizo—, o que no haya ni tráfico ni
volcado, o sea, un caso que no midió nada.

---

## Archivos

| Archivo | Qué hace |
|---|---|
| `test_CP01_… test_CP07_…` | Un archivo por caso |
| `control_negativo.py` | La compuerta del inspector (la corre el preflight) |
| `conftest.py` | La fixture `vigilancia`, la política de `.DMP` y el orden de ejecución |
| `preflight.py` | Estado de la máquina antes de tocar la aplicación |
| `parametros.py` | Nombres de los casos y datos de entrada (todo por variable de entorno) |
| `flujos/` | **Copias aisladas** de los flujos + `reimpresion.py` y `cancelaciones.py`, propios |
| `COBERTURA.md` | Inventario de flujos cubiertos y pendientes |
| `tools/kra1527_reset.py` | Borra evidencias, reporte y `.DMP` para empezar de cero |
| `src/helpers/ha_audit.py` | Auditoría del tráfico, censo de hosts y red lenta (CDP) |
| `src/helpers/memdump_helper.py` | Orquesta procdump y el inspector |
| `src/helpers/reporte_kra1527.py` | Reporte HTML consolidado |
| `tools/dump_token_inspector.py` | Detecta y decodifica JWT en los `.DMP` |

### Variables de entorno de la etiqueta

| Variable | Defecto | Para qué |
|---|---|---|
| `KRA1527_DUMP` | `1` | Volcar memoria (necesita procdump) |
| `KRA1527_CONSERVAR_DMP` | `0` | No borrar los `.DMP` al final |
| `KRA1527_CANCELAR` | `1` | Cancelar las transacciones que crea la etiqueta |
| `KRA1527_SIN_AGENTE` | `omitir` | `fallar` para ejecutar aunque el agente no corra |
| `KRA1527_RESET` | `0` | Empezar el reporte de cero en esta corrida |
| `KRA1527_TIPO_IMPRESION` | `WINDOWS PRINTER` | Tipo de impresión del CP05 |
| `KRA1527_IMPRESORA_RECIBO` | *(vacío)* | Impresora a elegir en Dispositivos; vacío = la primera real |
| `KRA1527_PROXY_KBPS` · `_LATENCIA_MS` | `50` · `500` | Red lenta del CP04 |
| `HW_AGENT_URL_PATTERN` | ver `settings.py` | Qué URLs cuentan como llamada al agente |

---

## Referencias

- Ticket: <https://maxims.atlassian.net/browse/KRA-1527>
- Pentest: Google Drive · `Maxi_Send_Penetration_Test_May-2026` · §5.2.1
- Casos QMetry: `KRA-1527_QMetry_v2.xlsx`
- Ambiente: <https://test-hermes.maxilabs.net>
