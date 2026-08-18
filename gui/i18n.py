"""
i18n — textos de la GUI en español e inglés.

Uso:
    from gui import i18n
    i18n.T("login_btn")                 # según el idioma activo
    i18n.T("hello", n="ignacio")        # con formato

El idioma vive en st.session_state["lang"] ('es' | 'en'), default 'es'.
"""

import streamlit as st

STR = {
    # ── Login ──
    "app_subtitle": {"es": "Agente de Automatización QA", "en": "QA Automation Agent"},
    "login_prompt": {"es": "Ingresa con tu correo Maxi", "en": "Sign in with your Maxi email"},
    "email_label": {"es": "Correo electrónico", "en": "Email"},
    "pass_label": {"es": "Contraseña", "en": "Password"},
    "login_btn": {"es": "Iniciar sesión", "en": "Sign in"},
    "language": {"es": "Idioma", "en": "Language"},
    "support_msg": {
        "es": "Por favor contacte a soporte a través del correo helpdesk@maxillc.com",
        "en": "Please contact support at helpdesk@maxillc.com"},

    # ── Sidebar / navegación ──
    "environment": {"es": "Entorno", "en": "Environment"},
    "env_ready": {"es": "listo", "en": "ready"},
    "env_check": {"es": "revisar", "en": "check"},
    "nav_home": {"es": "🏠 Inicio", "en": "🏠 Home"},
    "nav_sanity": {"es": "🧪 Sanity General", "en": "🧪 Sanity General"},
    "nav_payers": {"es": "💸 Transacciones por pagador", "en": "💸 Transactions by payer"},
    "nav_web": {"es": "🌐 Automatización web", "en": "🌐 Web automation"},
    "nav_exit": {"es": "🚪 Salir", "en": "🚪 Sign out"},
    "farewell": {
        "es": "¡Hasta pronto, {n}! 👋 Gracias por usar el agente de IA.",
        "en": "See you soon, {n}! 👋 Thanks for using the AI agent."},

    # ── Dashboard ──
    "hello": {"es": "¡Hola, {n}! 👋", "en": "Hi, {n}! 👋"},
    "welcome": {"es": "Bienvenido al Agente de Automatización QA de Maxi. Elige un módulo:",
                "en": "Welcome to Maxi's QA Automation Agent. Pick a module:"},
    "card_sanity_desc": {
        "es": "Ejecuta el sanity completo o un CP específico, en ambiente Test o Producción.",
        "en": "Run the full sanity or a specific CP, in Test or Production."},
    "card_payers_title": {"es": "💸 Transacciones por pagador", "en": "💸 Transactions by payer"},
    "card_payers_desc": {
        "es": "Lanza envíos data-driven a un pagador del catálogo (México / Colombia).",
        "en": "Launch data-driven transfers to a catalog payer (Mexico / Colombia)."},
    "card_web_title": {"es": "🌐 Automatización web", "en": "🌐 Web automation"},
    "card_web_desc": {
        "es": "Habla en lenguaje natural. Conoce todo el proyecto y ejecuta lo que le pidas.",
        "en": "Talk in natural language. It knows the whole project and runs what you ask."},
    "open_sanity": {"es": "Abrir Sanity", "en": "Open Sanity"},
    "open_payers": {"es": "Abrir Pagadores", "en": "Open Payers"},
    "open_web": {"es": "Abrir Automatización web", "en": "Open Web automation"},

    # ── Sanity ──
    "sanity_title": {"es": "🧪 Sanity General", "en": "🧪 Sanity General"},
    "test": {"es": "Test", "en": "Test"},
    "prod": {"es": "Producción", "en": "Production"},
    "what_run": {"es": "¿Qué ejecutar?", "en": "What to run?"},
    "all_sanity": {"es": "Todo el Sanity General", "en": "Whole Sanity General"},
    "run": {"es": "▶ Ejecutar", "en": "▶ Run"},

    # ── Pagadores ──
    "payers_title": {"es": "💸 Transacciones por pagador", "en": "💸 Transactions by payer"},
    "no_payers": {"es": "No hay pagadores activos en src/pagadores/*/payers.json.",
                  "en": "No active payers in src/pagadores/*/payers.json."},
    "payer": {"es": "Pagador", "en": "Payer"},
    "send_type": {"es": "Tipo de envío", "en": "Transfer type"},
    "amount_opt": {"es": "Monto (opcional)", "en": "Amount (optional)"},
    "amount_ph": {"es": "ej. 125", "en": "e.g. 125"},
    "cancel_end": {"es": "Cancelar al final", "en": "Cancel at the end"},
    "client_opt": {"es": "Cliente (opcional)", "en": "Customer (optional)"},
    "client_ph": {"es": "ej. Genaro Garcia Luna", "en": "e.g. Genaro Garcia Luna"},
    "benef_opt": {"es": "Beneficiario (opcional)", "en": "Beneficiary (optional)"},
    "benef_ph": {"es": "ej. Ana Perez Lopez", "en": "e.g. Ana Perez Lopez"},
    "run_send": {"es": "▶ Ejecutar envío", "en": "▶ Run transfer"},

    # ── Automatización web (agente NL) ──
    "web_title": {"es": "🌐 Automatización web — lenguaje natural",
                  "en": "🌐 Web automation — natural language"},
    "web_examples": {
        "es": "Ejemplos: “ejecuta el sanity general”, “corre el CP05 del sanity general”, "
              "“ejecuta el sanity general en producción”, “¿qué cubre el sanity?”, "
              "“haz un envío a Banorte”.",
        "en": "Examples: “run the sanity”, “run CP05 of the sanity”, "
              "“run the sanity in production”, “what does the sanity cover?”, "
              "“make a transfer to Banorte”."},
    "web_greeting": {
        "es": "¡Hola! Soy tu agente QA. Pídeme correr el sanity, una etiqueta o un "
              "envío, o pregúntame sobre el proyecto.",
        "en": "Hi! I'm your QA agent. Ask me to run the sanity, a tag or a transfer, "
              "or ask me about the project."},
    "web_input": {"es": "Escribe tu instrucción o pregunta…",
                  "en": "Type your instruction or question…"},
    "understood": {"es": "🧠 Entendido: **{t}** — {r}", "en": "🧠 Understood: **{t}** — {r}"},
    "will_run": {"es": "Voy a ejecutar **{t}**. Confirma abajo para lanzarlo.",
                 "en": "I'll run **{t}**. Confirm below to launch it."},
    "run_named": {"es": "▶ Ejecutar: {t}", "en": "▶ Run: {t}"},

    # ── Panel en vivo ──
    "running": {"es": "▶ Ejecutando… {x}", "en": "▶ Running… {x}"},
    "running_plain": {"es": "▶ Ejecutando…", "en": "▶ Running…"},
    "stop": {"es": "⏹ Detener ejecución", "en": "⏹ Stop execution"},
    "refresh": {"es": "🔄 Actualizar estado", "en": "🔄 Refresh status"},
    "finished_ok": {"es": "✅ Terminó · {d}", "en": "✅ Finished · {d}"},
    "finished_fail": {"es": "⚠ Terminó con fallos · {d}", "en": "⚠ Finished with failures · {d}"},
    "m_passed": {"es": "✅ Pasaron", "en": "✅ Passed"},
    "m_failed": {"es": "❌ Fallaron", "en": "❌ Failed"},
    "m_skipped": {"es": "⏭ Omitidos", "en": "⏭ Skipped"},
    "per_case": {"es": "**Detalle por caso:**", "en": "**Per-case detail:**"},
    "download_report": {"es": "📄 Descargar reporte HTML", "en": "📄 Download HTML report"},
    "tech_log": {"es": "Ver log técnico completo", "en": "Show full technical log"},
    "tech_help": {"es": "El log técnico completo también queda en el reporte.",
                  "en": "The full technical log is also saved in the report."},
    "log_live": {"es": "📋 Log de ejecución (en vivo)", "en": "📋 Execution log (live)"},
    "log_done": {"es": "📋 Log de ejecución", "en": "📋 Execution log"},
    "starting": {"es": "(iniciando…)", "en": "(starting…)"},
    "history": {"es": "🗂 Historial de ejecuciones", "en": "🗂 Execution history"},
    "hist_summary": {"es": "Pasaron **{p}** · Fallaron **{f}** · Omitidos **{s}**",
                     "en": "Passed **{p}** · Failed **{f}** · Skipped **{s}**"},
    "no_log": {"es": "(sin log)", "en": "(no log)"},
    "preparing_env": {"es": "Preparando el entorno virtual…", "en": "Preparing the virtual environment…"},
}


def lang() -> str:
    return st.session_state.get("lang", "es")


def T(key: str, **kw) -> str:
    d = STR.get(key, {})
    s = d.get(lang()) or d.get("es") or key
    return s.format(**kw) if kw else s
