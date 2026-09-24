"""
Base de conocimiento del proyecto para el agente en lenguaje natural.

Si hay ANTHROPIC_API_KEY, `responder()` usa Claude con este contexto como
system prompt (respuestas ricas). Si no, cae a un respondedor offline por
palabras clave. La EJECUCIÓN de flujos la resuelve agent.brain (no aquí).
"""

import os
import re

CONOCIMIENTO = """
Eres el asistente del proyecto "AutomationAgent" — automatización QA de Maxi
Remesas sobre HERMES2 (plataforma de transferencias) y Chronos (back office),
con Python + Playwright + pytest. Conoces TODO el proyecto:

## Qué automatiza
- SANITY GENERAL (rescate del sanity manual de HERMES2-qa hacia un motor estable):
  • CP01 — Money Transfer Cash + Información Adicional (KYC) + cancelación.
  • CP02 — Money Transfer con OFAC hit (beneficiario sancionado) + cancelación.
  • CP03 — Money Transfer Depósito + Tarjeta de Débito (POS) + cuestionario completo.
  • CP04 — Doméstico ATM multi-agente + doble OFAC + cancelación.
  • CP05 — Bill Payment nacional: Fidelity Express y Fiserv (los dos son CP05,
    como en el sanity original) + cancelación.
  • CP06 — Recargas (Top Ups) Lunex/DTOne: Mega Top Ups (iframe Lunex) y Top Ups
    regular. NO completa la recarga (número real; se detiene en 'Send' visible).
  • CP07 — Cheque individual: escaneo (emulador), edición, procesar, status
    'Verify Hold' en Reportes, y rechazo desde Chronos > Processing >
    Edited Checks (motivo 'Other').
  • CP09 — Pagos en Línea: en Chronos depósito + otro cargo + validación
    del balance del agente (Collection), y en Hermes el pago en línea.
  • CP10 — Ficha de Depósitos (Deposit Slip): dos pruebas — happy path (foto
    con cámara simulada + monto + envío) y caso alternativo (zoom 300%/100%,
    limpiar formulario, borrar y retomar la foto). Ambas cierran borrando el
    recibo en Chronos > Collection > Digital Deposit Receipt.
  • CP11 — Fax de entrada y salida (multi-agencia): valida el FAX de la agencia
    en Chronos (Agents > Agent), hace un envío HOME DELIVERY a Filipinas,
    dispara 'Send Fax' desde Reportes, confirma el registro en Chronos
    (Processing > Fax Assignment) y cancela la transacción.
  • CP12 — Reportes de Balance: dos pruebas — Balance Continuo (tarjetas del
    resultado, menú de opciones, visor de PDF y DESCARGA del PDF con validación
    de su contenido) y Balance por Cajero (estado vacío y búsqueda). Los pasos
    de impresión quedan fuera: el proceso automatizado no usa impresora.
  • CP22 — Money Order con Información Adicional: configura la impresora de MO,
    genera un money order de $3,000 (el sistema lo divide en 3), llena el
    compliance con FOTO del ID, lo IMPRIME y anula los 3 desde Reportes.
    Su módulo lo reutiliza la etiqueta KRA-1527 para auditar al Hardware Agent.
  (Pendientes: CP14-CP22, y los Hold de Chronos de CP01-CP04.)
- ETIQUETAS de deploy (validaciones que liberan a producción): p.ej. KRA-1125
  (Validation Rule del teléfono 573 para Uniteller Colombia en Depósito).
- ENVÍOS por pagador (data-driven): catálogo src/pagadores/<pais>/payers.json
  (México y Colombia). Se puede pedir un envío a un pagador, a varios o a todos.

## Capa estable (lo que arregló la inestabilidad del sanity manual)
- Información Adicional / Cuestionario: selección por data-testid determinístico
  (resuelve texto→testid) en vez del frágil "seleccionar por texto".
- Espera paciente del modal de compliance (aparece lento).
- Manejo del mensaje OFAC ("Back to Transfer") y del emulador POS de tarjeta.
- Errores de impresora en Bill Payment (Cancel), confirmación "YES, Cancel".
- Multi-agente: login + selección de agencia (con re-selección tras cada
  transacción y confirmación PC).

## Integración con QMetry (Test Management for Jira)
- Las capturas del sanity se suben al Test Cycle correspondiente, INCRUSTADAS en
  el campo 'Actual Result' del paso (como si se pegaran a mano).
- El paso destino sale del nombre del archivo (Step02-nombre.png), de la regla de
  cancelación (siempre al último paso) o de config/qmetry_mapeo.json.
- Con QMETRY_RESULTADO=1 escribe además el resultado: Pass en los pasos con
  evidencia, Fail en el paso donde se detuvo la prueba, NA en los no ejecutados.
- Comandos: `$env:QMETRY_UPLOAD="1"` antes de pytest, `python tools/qmetry_subir.py CP01`
  para subir de una corrida previa, y `python tools/ver_evidencias.py CP01` para
  revisar el reparto sin tocar QMetry.

## Evidencias
- Cada test guarda capturas numeradas NN_descriptor.png en
  reports/evidence/sanity_general/<CP>/, con resaltado verde en los pasos clave.
- Un objeto Evidencia (contador automático) las numera secuencialmente.

## Ambientes
- Test (default) y Producción. Los datos que cambian por ambiente se resuelven
  con settings.por_ambiente(valor_test, valor_prod). Cambia con HERMES_ENV=prod.

## Cómo se ejecuta
- Todo el sanity:      pytest src/tests/sanity_general -m sanity_general
- Un CP:              pytest src/tests/sanity_general -k CP05
- Una etiqueta:       pytest src/tests/etiquetas -k KRA_1125
- En paralelo + HTML: pytest -m sanity_general -n 3 --html=report.html --self-contained-html

## Agente en lenguaje natural
Entiende, por ejemplo: "ejecuta el sanity general", "corre el CP05 del sanity
general", "ejecuta el sanity general en producción", "haz un envío a Banorte",
"corre la etiqueta KRA-1125".

Responde SIEMPRE en español, claro y conciso, con foco en QA. Si te preguntan
cómo ejecutar algo, da el comando exacto. Si no sabes, dilo con honestidad.
"""


def _offline(pregunta: str) -> str:
    """Respondedor sin API: cubre las preguntas frecuentes por palabras clave."""
    t = pregunta.lower()
    if re.search(r"sanity", t):
        return ("El **Sanity General** cubre CP01–CP06 (Money Transfer cash/OFAC/"
                "depósito TDD/doméstico ATM multi-agente, y Bill Payment Fidelity/"
                "Fiserv), cada uno con su cancelación y evidencias. Ejecútalo desde "
                "el módulo *Sanity General* o dime: “ejecuta el sanity general” "
                "(o “el CP05”). Elige ambiente Test o Producción.")
    if re.search(r"etiqueta|kra", t):
        return ("Las **etiquetas** son validaciones de deploy. Ejemplo: KRA-1125 "
                "(regla del teléfono 573 para Uniteller Colombia en Depósito). "
                "Corre: `pytest src/tests/etiquetas -k KRA_1125`.")
    if re.search(r"pagador|payer|env[ií]o|transfer", t):
        return ("Puedes lanzar **envíos por pagador** (catálogo México/Colombia) "
                "desde el módulo *Transacciones por pagador*, o pedirme: “haz un "
                "envío a Banorte”, “a Walmart y Aurrera”, o “a todos los pagadores”.")
    if re.search(r"evidencia|captura|screenshot", t):
        return ("Las **evidencias** se guardan numeradas (NN_descriptor.png) en "
                "reports/evidence/sanity_general/<CP>/, con resaltado verde en los "
                "pasos clave. Un objeto `Evidencia` las numera automáticamente.")
    if re.search(r"ambiente|producci|test|prod", t):
        return ("Hay dos **ambientes**: Test (default) y Producción. Los datos que "
                "cambian se resuelven con `settings.por_ambiente(test, prod)`. En la "
                "GUI seleccionas el ambiente antes de correr el sanity.")
    if re.search(r"c[oó]mo (corr|ejecut|lanz)|comando", t):
        return ("Comandos:\n"
                "- Todo el sanity: `pytest src/tests/sanity_general -m sanity_general`\n"
                "- Un CP: `pytest src/tests/sanity_general -k CP05`\n"
                "- Etiqueta: `pytest src/tests/etiquetas -k KRA_1125`")
    return ("Soy el asistente del proyecto AutomationAgent (QA de HERMES2/Chronos). "
            "Puedo ejecutar el Sanity General (CP01–CP06), etiquetas de deploy y "
            "envíos por pagador, en ambiente Test o Producción. Pregúntame “¿qué "
            "cubre el sanity?”, “¿cómo corro el CP05?”, o dame una instrucción como "
            "“ejecuta el sanity general en producción”.")


def responder(pregunta: str) -> str:
    """Responde una pregunta de conocimiento. Usa Claude si hay API key; si no,
    el respondedor offline."""
    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            import anthropic
            try:
                from config.settings import CLAUDE_MODEL_ID as _MODEL
            except Exception:
                _MODEL = "claude-sonnet-4-5"
            client = anthropic.Anthropic()
            r = client.messages.create(
                model=_MODEL, max_tokens=600, system=CONOCIMIENTO,
                messages=[{"role": "user", "content": pregunta}])
            return r.content[0].text.strip()
        except Exception:
            pass
    return _offline(pregunta)
