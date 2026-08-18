"""
GUI del AutomationAgent (Streamlit) — bilingüe (ES/EN).

Módulos:
  • Login con banco de usuarios Maxi (gui/auth.py).
  • Dashboard: Sanity General · Transacciones por pagador · Automatización web.
  • Sanity General con ambientes Test / Producción y runner en vivo.
  • Automatización web: agente en lenguaje natural con el conocimiento del proyecto.

Correr:
    python run_gui.py         # recomendado (abre el navegador, puerto propio)
    streamlit run gui/app.py
"""

import json
import sys
from pathlib import Path

import streamlit as st

# Raíz del proyecto en el path (para importar agent/, config/, src/)
RAIZ = Path(__file__).parent.parent
sys.path.insert(0, str(RAIZ))

from gui import auth                                  # noqa: E402
from gui import conocimiento                          # noqa: E402
from gui import runner                                # noqa: E402
from gui import i18n                                  # noqa: E402
from gui.i18n import T                                # noqa: E402
from agent import brain                               # noqa: E402

# ── Estilo / colores Maxi Send (firmes, apegados al logo) ───────────────────
AZUL = "#173B8A"        # azul royal sólido del logo
AZUL_CLARO = "#1E4BB8"  # hover
VERDE = "#7BC143"       # verde vivo del swoosh
VERDE_OSC = "#5CA328"
TINTA = "#14213d"       # texto oscuro sólido

LOGO_SVG = f"""
<svg width="220" height="86" viewBox="0 0 220 86" xmlns="http://www.w3.org/2000/svg">
  <path d="M112 20 a26 26 0 0 1 44 0" fill="none" stroke="{VERDE}" stroke-width="12" stroke-linecap="round"/>
  <text x="8" y="60" font-family="Arial Black, Arial, sans-serif" font-weight="900"
        font-size="52" fill="{AZUL}">maxi</text>
  <text x="120" y="78" font-family="Arial, sans-serif" font-weight="700"
        font-size="22" letter-spacing="6" fill="{AZUL}">SEND</text>
</svg>
"""


def _lng() -> str:
    return i18n.lang()


def _css():
    st.markdown(f"""
    <style>
      .stApp {{ background: linear-gradient(180deg,#e8eefc 0%, #ffffff 55%);
                font-size: 17px; }}
      /* Tipografía un poco más grande en general */
      .stMarkdown, .stMarkdown p, .stCaption, .stText {{ font-size: 1.02rem; }}
      /* Sub-encabezados / labels de submenú: medianos */
      label, .stRadio label, .stCheckbox label, .stSelectbox label,
      div[data-testid="stWidgetLabel"] p {{ font-size: 1.08rem !important;
                                            font-weight: 600; }}
      h2.maxi-title {{ font-size: 2rem; }}
      section[data-testid="stSidebar"] .stButton>button {{ font-size: 1.02rem; }}
      .maxi-card {{
        background:#ffffff; border:1px solid #d7e0f5;
        border-top:5px solid {AZUL}; border-radius:16px;
        padding:22px; box-shadow:0 6px 20px rgba(23,59,138,.12); height:100%;
      }}
      .maxi-card h4 {{ color:{AZUL} !important; font-weight:800;
                       margin:0 0 8px; opacity:1 !important; }}
      .maxi-card p  {{ color:{TINTA} !important; font-weight:500;
                       margin:0; opacity:1 !important; }}
      .maxi-title {{ color:{AZUL} !important; font-weight:800; opacity:1 !important; }}
      .stButton>button {{
        background:{AZUL}; color:#ffffff !important; border:0; border-radius:10px;
        font-weight:800; padding:.55rem 1rem;
      }}
      .stButton>button:hover {{ background:{AZUL_CLARO}; color:#ffffff !important; }}
      .stButton>button[kind="primary"] {{ background:{VERDE}; color:{TINTA} !important; }}
      .stButton>button[kind="primary"]:hover {{ background:{VERDE_OSC}; color:#ffffff !important; }}
      .badge-ok {{ background:{VERDE}; color:#123314; padding:2px 10px;
                   border-radius:999px; font-weight:800; font-size:.8rem; }}
    </style>
    """, unsafe_allow_html=True)


def _logo(center=False, ancho=220):
    svg = LOGO_SVG.replace('width="220"', f'width="{ancho}"') if ancho != 220 else LOGO_SVG
    align = "center" if center else "left"
    st.markdown(f"<div style='text-align:{align}'>{svg}</div>", unsafe_allow_html=True)


def _card_html(acento: str, titulo: str, texto: str) -> str:
    """Tarjeta de módulo con acento de color vivo y texto sólido."""
    return (f"<div class='maxi-card' style='border-top-color:{acento}'>"
            f"<h4 style='color:{acento}!important'>{titulo}</h4>"
            f"<p>{texto}</p></div>")


def _selector_idioma(key: str):
    """Radio ES/EN. Guarda el idioma en session_state['lang']."""
    actual = i18n.lang()
    idx = 0 if actual == "es" else 1
    elegido = st.radio(T("language"), ["es", "en"], index=idx, horizontal=True,
                       key=key, format_func=lambda v: "Español" if v == "es" else "English",
                       label_visibility="collapsed")
    if elegido != actual:
        st.session_state.lang = elegido
        st.rerun()


# ── Ejecución en vivo (runner en background) ────────────────────────────────

def _iniciar(clave, label, args, *, ambiente="test", extra=None, casos=None,
             repeticiones=1, duracion_seg=0):
    """Lanza una corrida en background y guarda su handle en session_state.

    Inyecta FLOW_LANG según el idioma elegido en la GUI: así el sanity y los
    envíos NAVEGAN Hermes en ese idioma (inglés/español). Soporta repetición
    por cantidad (repeticiones) o por tiempo (duracion_seg)."""
    extra = dict(extra or {})
    extra.setdefault("FLOW_LANG", "en" if _lng() == "en" else "es")
    prev = st.session_state.get(clave)
    if prev is not None and prev.viva:
        prev.detener()
    st.session_state[clave] = runner.Ejecucion(
        label, args, ambiente=ambiente, extra_env=extra, casos=casos,
        repeticiones=repeticiones, duracion_seg=duracion_seg)
    st.rerun()


def _registrar_historial(modulo, ej):
    """Guarda la corrida terminada en el historial (una sola vez)."""
    if getattr(ej, "_registrado", False):
        return
    ej._registrado = True
    snap = ej.snapshot()
    st.session_state.setdefault("historial", [])
    st.session_state.historial.insert(0, {
        "modulo": modulo, "label": ej.label, "ambiente": ej.ambiente,
        "inicio": snap["inicio"], "duracion": ej.duracion(),
        "ok": snap["returncode"] == 0, "resumen": snap["resumen"],
        "por_caso": snap["por_caso"], "report": snap["report"],
        "log": runner.log_amigable(ej.leer_log()),
    })


def _mostrar_resultados(snap):
    """Métricas + detalle por caso (sin gráfica, por preferencia del usuario)."""
    r = snap["resumen"]
    fallaron = r["failed"] + r["error"]
    c1, c2, c3 = st.columns(3)
    c1.metric(T("m_passed"), r["passed"])
    c2.metric(T("m_failed"), fallaron)
    c3.metric(T("m_skipped"), r["skipped"])
    if snap["por_caso"]:
        st.markdown(T("per_case"))
        for nid, estado in snap["por_caso"].items():
            cp = runner.cp_en_curso(nid) or ""
            ic = "✅" if estado == "PASSED" else ("⏭" if estado == "SKIPPED" else "❌")
            nombre = runner.nombre_cp(cp, _lng()) if cp else nid
            st.markdown(f"{ic} {nombre} — `{estado}`")


def _boton_reporte(report_path, key):
    if not report_path:
        return
    try:
        data = Path(report_path).read_bytes()
        st.download_button(T("download_report"), data,
                           file_name=Path(report_path).name,
                           mime="text/html", key=key)
    except Exception:
        pass


def _panel_vivo_impl(clave, modulo):
    """Estado en vivo: caso en curso, log SIEMPRE visible, detener, y al
    terminar: veredicto + métricas + reporte."""
    ej = st.session_state.get(clave)
    if ej is None:
        return
    ej.refrescar()
    snap = ej.snapshot()
    if snap["viva"]:
        cp = snap["cp_en_curso"]
        if not cp and len(ej.casos) == 1 and str(ej.casos[0]).upper().startswith("CP"):
            cp = ej.casos[0]                      # muestra el CP elegido de una
        st.info(T("running", x=runner.nombre_cp(cp, _lng())) if cp else T("running_plain"))
        if st.button(T("stop"), key=f"stop_{clave}"):
            ej.detener()
            st.rerun()
    else:
        _registrar_historial(modulo, ej)
        ok = snap["returncode"] == 0
        (st.success if ok else st.error)(
            T("finished_ok", d=ej.duracion()) if ok
            else T("finished_fail", d=ej.duracion()))
        _mostrar_resultados(snap)
        _boton_reporte(snap["report"], key=f"rep_{clave}_{ej.id}")

    # Log colapsable con flecha propia (▸/▾) que PERSISTE entre refrescos del
    # panel (el expander nativo se recolapsaría solo con run_every). Se muestra
    # únicamente cuando el usuario lo despliega.
    key_open = f"logopen_{clave}"
    abierto = st.session_state.get(key_open, False)
    flecha = "▾" if abierto else "▸"
    titulo = T("log_live") if snap["viva"] else T("log_done")
    if st.button(f"{flecha} {titulo}", key=f"logtgl_{clave}"):
        st.session_state[key_open] = not abierto
        abierto = st.session_state[key_open]
    if abierto:
        tecnico = st.checkbox(T("tech_log"), key=f"tec_{clave}", help=T("tech_help"))
        st.code(runner.log_amigable(ej.leer_log(), incluir_tecnico=tecnico) or T("starting"))


# st.fragment(run_every=...) refresca el panel SIN recargar toda la app, así el
# botón Detener sigue respondiendo durante la corrida.
if hasattr(st, "fragment"):
    panel_vivo = st.fragment(run_every=2)(_panel_vivo_impl)
else:                                          # Streamlit < 1.37: refresco manual
    def panel_vivo(clave, modulo):
        _panel_vivo_impl(clave, modulo)
        ej = st.session_state.get(clave)
        if ej is not None and ej.viva:
            if st.button(T("refresh"), key=f"ref_{clave}"):
                st.rerun()


def vista_historial(modulo):
    """Historial de corridas de este módulo, con flecha desplegable por corrida."""
    hist = [h for h in st.session_state.get("historial", []) if h["modulo"] == modulo]
    if not hist:
        return
    st.divider()
    st.markdown("#### " + T("history"))
    for i, h in enumerate(hist[:15]):
        ic = "✅" if h["ok"] else "❌"
        with st.expander(f"{ic} {h['label']} · {h['ambiente']} · "
                         f"{h['inicio']} · {h['duracion']}"):
            r = h["resumen"]
            st.markdown(T("hist_summary", p=r["passed"],
                          f=r["failed"] + r["error"], s=r["skipped"]))
            for nid, estado in h["por_caso"].items():
                cp = runner.cp_en_curso(nid) or ""
                mic = "✅" if estado == "PASSED" else ("⏭" if estado == "SKIPPED" else "❌")
                st.markdown(f"{mic} {runner.nombre_cp(cp, _lng()) if cp else nid} — `{estado}`")
            _boton_reporte(h.get("report"), key=f"hrep_{modulo}_{i}")
            st.code(h["log"] or T("no_log"))


# ── Vistas ──────────────────────────────────────────────────────────────────

def vista_login():
    _logo(center=True)
    st.markdown(f"<h3 class='maxi-title' style='text-align:center'>{T('app_subtitle')}</h3>",
                unsafe_allow_html=True)
    st.markdown(f"<p style='text-align:center;color:#667'>{T('login_prompt')}</p>",
                unsafe_allow_html=True)
    # Formulario COMPACTO y centrado (columna central angosta).
    c1, c2, c3 = st.columns([2, 1.4, 2])
    with c2:
        _selector_idioma("lang_login")
        with st.form("login"):
            email = st.text_input(T("email_label"), placeholder="nombre@maxillc.com")
            pwd = st.text_input(T("pass_label"), type="password")
            ok = st.form_submit_button(T("login_btn"), use_container_width=True)
        if ok:
            if auth.verificar(email, pwd):
                st.session_state.auth = True
                st.session_state.email = email.strip().lower()
                st.session_state.vista = "dashboard"
                st.rerun()
            else:
                st.error(T("support_msg"))


def preparar_entorno():
    """Verifica el entorno (playwright/pytest) — 'preparado en background'."""
    if st.session_state.get("entorno_ok"):
        return
    with st.spinner(T("preparing_env")):
        try:
            import importlib
            importlib.import_module("playwright")
            importlib.import_module("pytest")
            st.session_state.entorno_ok = True
        except Exception:
            st.session_state.entorno_ok = False


def barra_lateral():
    with st.sidebar:
        _logo()
        _selector_idioma("lang_side")
        st.markdown(f"👤 **{st.session_state.email}**")
        estado = T("env_ready") if st.session_state.get("entorno_ok") else T("env_check")
        st.markdown(f"{T('environment')}: <span class='badge-ok'>{estado}</span>",
                    unsafe_allow_html=True)
        st.divider()
        if st.button(T("nav_home"), use_container_width=True):
            st.session_state.vista = "dashboard"; st.rerun()
        if st.button(T("nav_sanity"), use_container_width=True):
            st.session_state.vista = "sanity"; st.rerun()
        if st.button(T("nav_payers"), use_container_width=True):
            st.session_state.vista = "pagadores"; st.rerun()
        if st.button(T("nav_web"), use_container_width=True):
            st.session_state.vista = "agente"; st.rerun()
        st.divider()
        if st.button(T("nav_exit"), use_container_width=True):
            nombre = st.session_state.email.split("@")[0]
            lang = st.session_state.get("lang", "es")
            st.session_state.clear()
            st.session_state.lang = lang
            st.session_state.despedida = i18n.T("farewell", n=nombre)
            st.rerun()


def vista_dashboard():
    _logo()
    nombre = st.session_state.email.split("@")[0]
    st.markdown(f"<h2 class='maxi-title'>{T('hello', n=nombre)}</h2>", unsafe_allow_html=True)
    st.caption(T("welcome"))
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(_card_html(AZUL, T("nav_sanity"), T("card_sanity_desc")),
                    unsafe_allow_html=True)
        if st.button(T("open_sanity"), key="d1", use_container_width=True):
            st.session_state.vista = "sanity"; st.rerun()
    with col2:
        st.markdown(_card_html(VERDE, T("card_payers_title"), T("card_payers_desc")),
                    unsafe_allow_html=True)
        if st.button(T("open_payers"), key="d2", use_container_width=True):
            st.session_state.vista = "pagadores"; st.rerun()
    with col3:
        st.markdown(_card_html(AZUL_CLARO, T("card_web_title"), T("card_web_desc")),
                    unsafe_allow_html=True)
        if st.button(T("open_web"), key="d3", use_container_width=True):
            st.session_state.vista = "agente"; st.rerun()


CP_SANITY = ["CP01", "CP02", "CP03", "CP04", "CP05", "CP06", "CP07"]


def vista_sanity():
    st.markdown(f"<h2 class='maxi-title'>{T('sanity_title')}</h2>", unsafe_allow_html=True)
    amb = st.radio(T("environment"), ["test", "prod"], horizontal=True,
                   format_func=lambda v: T(v))
    # Opciones: (clave, etiqueta). clave='all' o 'CP0x'
    opciones = [("all", T("all_sanity"))] + [(cp, runner.nombre_cp(cp, _lng())) for cp in CP_SANITY]
    sel = st.selectbox(T("what_run"), opciones, format_func=lambda o: o[1])
    if st.button(T("run"), type="primary"):
        if sel[0] == "all":
            args = ["src/tests/sanity_general", "-m", "sanity_general"]
            casos, label = list(CP_SANITY), "Sanity General — TODOS"
        else:
            cp = sel[0]
            args = ["src/tests/sanity_general", "-k", cp]
            casos, label = [cp], f"Sanity General — {cp}"
        _iniciar("run_sanity", f"{label} ({T(amb)})", args, ambiente=amb, casos=casos)
    panel_vivo("run_sanity", "sanity")
    vista_historial("sanity")


def _modulos_con_envio() -> set:
    """Módulos (países) que YA tienen flujo de envío APRENDIDO por el agente,
    es decir, un test_envio_normal_<modulo>.py. Los pagadores de módulos sin ese
    test (p.ej. Colombia/Uniteller, exclusivos de la etiqueta KRA-1125) NO se
    ofrecen aquí — evita el error 'file not found' y no mezcla etiquetas."""
    base = RAIZ / "src" / "tests"
    try:
        return {p.stem[len("test_envio_normal_"):]
                for p in base.glob("test_envio_normal_*.py")}
    except Exception:
        return {"mexico"}


def _payers_activos():
    mods = _modulos_con_envio()
    return [p for p in brain._catalogo_payers()
            if p.get("activo") and p.get("_modulo") in mods]


def vista_pagadores():
    st.markdown(f"<h2 class='maxi-title'>{T('payers_title')}</h2>", unsafe_allow_html=True)
    payers = _payers_activos()
    if not payers:
        st.warning(T("no_payers"))
        return
    etiquetas = [f"{p['code']}  ·  {p['_modulo']}" for p in payers]
    idx = st.selectbox(T("payer"), range(len(payers)), format_func=lambda i: etiquetas[i])
    p = payers[idx]
    tipo = st.selectbox(T("send_type"), ["cash", "deposit", "atm"], index=0)
    col1, col2 = st.columns(2)
    monto = col1.text_input(T("amount_opt"), placeholder=T("amount_ph"))
    cancelar = col2.checkbox(T("cancel_end"), value=False)
    colc, cold = st.columns(2)
    cliente = colc.text_input(T("client_opt"), placeholder=T("client_ph"))
    beneficiario = cold.text_input(T("benef_opt"), placeholder=T("benef_ph"))
    if st.button(T("run_send"), type="primary"):
        modulo = p["_modulo"]
        kexpr = p["code"].lower().replace(" ", "_")
        args = [f"src/tests/test_envio_normal_{modulo}.py", "-k", kexpr]
        extra = {"FLOW_CANCEL": "1" if cancelar else "0", "FLOW_TYPE": tipo}
        ov = {}
        if monto.strip():
            ov["monto"] = monto.strip()
        if cliente.strip():
            ov["cliente"] = cliente.strip()
        if beneficiario.strip():
            ov["beneficiario"] = beneficiario.strip()
        if ov:
            extra["FLOW_OVERRIDES"] = json.dumps(ov)
        _iniciar("run_pagadores", f"Envío a {p['code']}", args,
                 ambiente="test", extra=extra, casos=[p["code"]])
    panel_vivo("run_pagadores", "pagadores")
    vista_historial("pagadores")


def vista_agente():
    st.markdown(f"<h2 class='maxi-title'>{T('web_title')}</h2>", unsafe_allow_html=True)
    st.caption(T("web_examples"))

    if "chat" not in st.session_state:
        st.session_state.chat = [{"rol": "assistant", "texto": T("web_greeting")}]

    for m in st.session_state.chat:
        with st.chat_message(m["rol"]):
            st.markdown(m["texto"])

    prompt = st.chat_input(T("web_input"))
    if prompt:
        st.session_state.chat.append({"rol": "user", "texto": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        catalogo = {"tests": {}, "pages": {}}
        try:
            from agent.registry import construir_catalogo
            catalogo = construir_catalogo()
        except Exception:
            pass
        plan = brain.interpretar(prompt, catalogo)
        with st.chat_message("assistant"):
            if plan.get("tipo") == "ejecutar_test":
                st.markdown(T("understood", t=plan["test"], r=plan.get("razon", "")))
                st.session_state.plan_pendiente = plan
                st.session_state.chat.append(
                    {"rol": "assistant", "texto": T("will_run", t=plan["test"])})
            else:
                if plan.get("tipo") == "respuesta":
                    resp = plan["mensaje"]
                else:
                    resp = conocimiento.responder(prompt)
                st.markdown(resp)
                st.session_state.chat.append({"rol": "assistant", "texto": resp})
                st.session_state.pop("plan_pendiente", None)

    plan = st.session_state.get("plan_pendiente")
    if plan:
        if st.button(T("run_named", t=plan["test"]), type="primary"):
            args = [plan["archivo"]]
            if plan.get("marker"):
                args += ["-m", plan["marker"]]
            if plan.get("kexpr"):
                args += ["-k", plan["kexpr"]]
            extra = {}
            if plan.get("cancelar"):
                extra["FLOW_CANCEL"] = "1"
            if plan.get("overrides"):
                extra["FLOW_OVERRIDES"] = json.dumps(plan["overrides"])
            if plan.get("tipo_envio"):
                extra["FLOW_TYPE"] = plan["tipo_envio"]
            _iniciar("run_agente", plan["test"], args,
                     ambiente=plan.get("ambiente", "test"),
                     extra=extra or None, casos=plan.get("casos"),
                     repeticiones=plan.get("veces", 1),
                     duracion_seg=plan.get("duracion_seg", 0))
            st.session_state.pop("plan_pendiente", None)

    panel_vivo("run_agente", "agente")
    vista_historial("agente")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(page_title="Maxi · QA", page_icon="🤖", layout="wide")
    _css()

    if st.session_state.get("despedida"):
        st.success(st.session_state.pop("despedida"))

    if not st.session_state.get("auth"):
        vista_login()
        return

    preparar_entorno()
    barra_lateral()

    vista = st.session_state.get("vista", "dashboard")
    if vista == "sanity":
        vista_sanity()
    elif vista == "pagadores":
        vista_pagadores()
    elif vista == "agente":
        vista_agente()
    else:
        vista_dashboard()


if __name__ == "__main__":
    main()
