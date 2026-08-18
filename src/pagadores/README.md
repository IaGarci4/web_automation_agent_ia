# Módulo de pagadores

Catálogo **data-driven** de pagadores (payers) para el flujo de Money Transfer,
organizado **por país** para poder ir agregando mercados nuevos sin tocar el
motor. Hoy solo existe `mexico/`; el mismo patrón sirve para el siguiente país.

## Cómo está armado

```
src/pagadores/
├── flujo_mt.py          ← motor COMPARTIDO (no es de un país en particular).
│                          Llena el formulario, selecciona pagador/sucursal,
│                          captura y valida el cálculo. Lo reutilizan TODOS
│                          los países.
├── mexico/
│   └── payers.json      ← catálogo de pagadores de México (10 activos hoy:
│                          Elektra, BanCoppel, Soriana, Walmart, Aurrera,
│                          Bancomer, A Waldos, Farmacias del Ahorro, Chedraui
│                          Efectivo, Banorte) + inactivos listos para activar
│                          (BBVA, Banamex, Santander, HSBC, Scotiabank,
│                          Afirme, Banco Azteca) + el pool de ciudades/estados
│                          de México usado para el beneficiario.
└── <pais_nuevo>/
    └── payers.json      ← mismo esquema, otro país (ver abajo).
```

`flujo_mt.cargar_catalogo()` escanea automáticamente **todas** las carpetas
`src/pagadores/*/payers.json` y junta los pagadores `"activo": true` de todas
ellas (cada uno queda anotado con `_modulo` = nombre de la carpeta, para saber
a qué `test_envio_normal_<pais>.py` pertenece). No hace falta registrar nada
a mano en otro lado.

## Agregar un pagador de México (sin grabar nada)

Editar `mexico/payers.json` y agregar una entrada al array `payers`:

```json
{"code": "BBVA", "activo": true, "country": "MEXICo",
 "search": "BBVA", "row": "BBVA",
 "needs_branch": false, "branch": "", "payer_city": "GUADALAJARa",
 "id_payment_type": 1, "id_country_currency": 10,
 "is_enabled_scale_rounding": false, "id_scale_rounding": null}
```

Campos:

| Campo | Qué es |
|---|---|
| `code` | Nombre corto — se usa para el nombre del test (`test_envio_normal_bbva`) y para que el agente lo reconozca en lenguaje natural. |
| `country` | País destino tal como aparece en el typeahead de país del beneficiario. |
| `search` / `row` | Texto para buscar el pagador en el modal y texto de la fila a clickear (vacío = primera fila visible). |
| `needs_branch` / `branch` | Si el pagador exige elegir sucursal, y cuál (vacío = se elige una al azar cuando la app la marca "Field required"). |
| `payer_city` | Ciudad del pagador — **estática** (no se randomiza). |
| `id_payment_type`, `id_country_currency`, `is_enabled_scale_rounding`, `id_scale_rounding` | Contexto para el validador de cálculos (redondeo del monto destino). |

Con `"activo": true` ya alcanza — el test `test_envio_normal_<code>` se genera
solo, y el agente lo suma a "todos los pagadores" y al lenguaje natural.

En `Payers.txt` (si lo tenés a mano del proyecto de origen) hay un dump crudo
de pagadores reales de Hermes que sirve como fuente para ir completando más
entradas de México u otros países.

## Agregar un país nuevo

1. Crear `src/pagadores/<pais>/payers.json` con el mismo esquema (copiar
   `mexico/payers.json` como plantilla) y su propio bloque
   `ciudades_estado_por_pais`.
2. Crear `src/tests/test_envio_normal_<pais>.py` (copiar
   `test_envio_normal_mexico.py` y cambiar el nombre del módulo que carga).
3. Nada más — `flujo_mt.py`, `agent/brain.py` y el registry lo descubren solos.

## Cómo aprende el agente

`agent/brain.py` lee este catálogo para reconocer pagadores por nombre
("envío a Banorte", "manda a Walmart y Aurrera") y para la instrucción de
**todos los pagadores** ("haz envíos a todos los pagadores", "cada uno de los
payers", "los 10 payers"), que corre un envío por cada pagador activo con:

- **pagador**: fijo por iteración (es justamente lo que se está rotando).
- **país**: fijo — el `country` configurado en el payer.
- **ciudad del pagador** (`payer_city`): fija — la del catálogo.
- **ciudad/estado del beneficiario**: aleatoria dentro del pool del país
  (`ciudades_estado_por_pais`).
- **el resto de los datos** (nombre, apellidos, teléfono, dirección, email,
  monto…): aleatorios vía Faker, salvo que la instrucción fije alguno
  explícitamente (`FLOW_OVERRIDES`).

Cada corrida queda registrada en `reports/calculos/envio_normal_runs.jsonl` +
`resumen_envio_normal.html` (una fila por pagador, con veredicto) — esa es la
base de datos que crece con cada pagador nuevo para que el agente "aprenda"
más lenguaje natural y más variedad de casos.
