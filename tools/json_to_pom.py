"""
json_to_pom.py — Intérprete de grabaciones JSON → archivos POM

Convierte un JSON grabado por la extensión Chrome Recorder en 3 archivos:
  1. src/locators/{nombre}_locators.py   → clase con todos los selectores
  2. src/pages/{nombre}_page.py          → Page Object con métodos por acción
  3. src/tests/test_{nombre}.py          → Test ejecutable con steps + screenshots

Uso:
    python tools/json_to_pom.py ruta/al/flujo.json
    python tools/json_to_pom.py ruta/al/flujo.json --name mi_flujo
    python tools/json_to_pom.py ruta/al/flujo.json --dry-run   (previsualiza sin escribir)

El nombre del flujo se deduce del nombre del archivo JSON si no se especifica --name.
"""

import json
import os
import re
import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional


# ── Rutas del proyecto ────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
LOCATORS_DIR = PROJECT_ROOT / "src" / "locators"
PAGES_DIR    = PROJECT_ROOT / "src" / "pages"
TESTS_DIR    = PROJECT_ROOT / "src" / "tests"


# ── Selectores que no aportan y se deben ignorar ──────────────────────────────
SKIP_TAGS     = {"svg", "path"}
SKIP_NAMES    = {"not-read-indicator", "[object", "icon", "view-container", "path_",
                  "icon-container"}
# Prefijos de clases CSS que indican contenedores genéricos — no son elementos interactivos
SKIP_NAME_PREFIXES = ("col-", "row-", "container", "wrapper", "layout-", "ng-",
                      "flex-", "grid-")
SKIP_SELECTOR = {"span", "div", "path", "svg"}

# Acciones que pertenecen al modal 'Notificaciones Importantes'.
# Las maneja BasePage.handle_notifications_modal() (lee cada una y cierra con la X),
# por lo que NO deben generar métodos propios en el Page Object.
NOTIFICATION_MARKERS = (
    "not-read-indicator",
    "notifications-modal-intrusive",
    "notifications-intrusive",
    "icon-container",
)


# ════════════════════════════════════════════════════════════════════════════════
# PASO 1 — Parsear el JSON y extraer acciones relevantes
# ════════════════════════════════════════════════════════════════════════════════

def parse_json(json_path: str) -> dict:
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def extract_actions(data: dict) -> list[dict]:
    """
    Filtra las acciones relevantes del JSON:
      - Solo tipo 'click' o 'input' con valor
      - Ignora SVG, paths, elementos sin data-testid útil
      - Deduplica: si hay click + input en el mismo elemento, queda el input
    """
    raw = data.get("acciones", [])
    seen_keys = {}

    for accion in raw:
        tipo     = accion.get("tipo", "")
        tag      = accion.get("tag", "")
        nombre   = accion.get("nombre", "")
        selector = accion.get("selector", "")
        url      = accion.get("url", "")
        valor    = accion.get("valor", "")
        texto    = accion.get("texto", "")

        html_raw = accion.get("html", "")

        # Scroll: se conserva tal cual (rueda o barra lateral). Clave única por
        # posición+orden para no colapsar scrolls distintos.
        if tipo == "scroll":
            key = ("scroll", accion.get("scrollY"), len(seen_keys), url)
            seen_keys[key] = {
                "tipo": "scroll", "tag": "scroll", "nombre": "scroll",
                "selector": selector, "url": url,
                "scrollX": accion.get("scrollX", 0),
                "scrollY": accion.get("scrollY", 0),
                "valor": "", "texto": "", "html": "", "candidatos": {},
            }
            continue

        # Saltar svg/path SOLO si no tienen un data-testid válido. Los íconos
        # de acción (ej. transfer-beneficiary-clear-0-icon-svg = botón Borrar)
        # SÍ deben conservarse — antes se perdían por ser <svg>.
        if tag in SKIP_TAGS:
            cand = accion.get("candidatos") or {}
            m_t = re.search(r'data-testid=["\']([^"\']+)["\']', html_raw)
            tid = cand.get("testid") or (m_t.group(1) if m_t else "")
            if not testid_valido(tid):
                continue
        # Acciones dentro del modal de notificaciones — las maneja
        # handle_notifications_modal(), no deben generar pasos del test
        if any(m in html_raw or m in nombre or m in selector
               for m in NOTIFICATION_MARKERS):
            continue
        # Clicks en celdas/filas genéricas sin testid ni texto — ruido de grabación
        if (tipo == "click" and selector in ("td", "tr", "th")
                and "data-testid" not in html_raw and not texto):
            continue
        if any(nombre.startswith(p) for p in SKIP_NAMES):
            continue
        if tipo == "click" and any(nombre.startswith(p) for p in SKIP_NAME_PREFIXES):
            continue
        if tipo == "change":
            continue
        if tipo == "click" and selector in SKIP_SELECTOR and not nombre:
            continue

        # Para inputs: solo el tipo 'input' con valor
        if tag == "input" and tipo == "click" and nombre in seen_keys:
            continue

        # La clave incluye el SELECTOR: hay elementos distintos que comparten
        # nombre genérico (ej. id='id-button' en Search y en Options) y el
        # dedupe por nombre+url descartaba clicks legítimos
        key = (nombre, selector, url)
        if key not in seen_keys or tipo == "input":
            seen_keys[key] = {
                "tipo"      : tipo,
                "tag"       : tag,
                "nombre"    : nombre,
                "selector"  : selector,
                "url"       : url,
                "valor"     : valor,
                "texto"     : texto,
                "html"      : accion.get("html", ""),
                # Candidatos auditados por la extensión v2.2 — CRÍTICO para
                # que infer_best_selector elija el localizador más estable
                "candidatos": accion.get("candidatos") or {},
            }

    return list(seen_keys.values())


# Ids generados dinámicamente por Angular (dropdown_0, input_3, tab-12...)
# cambian entre renders — son la ÚLTIMA opción, no la primera.
DYNAMIC_ID_RE = re.compile(r'(?:^|_|-)\d+$|^\d')


def es_id_dinamico(id_val: str) -> bool:
    return bool(DYNAMIC_ID_RE.search(id_val or ""))


def semantica_campo(sel_val: str):
    """
    Mapea el testid de un input de FORMULARIO LIBRE a (clave_semantica, tipo)
    para que el test use Faker/override en vez del valor grabado fijo.
    Devuelve (None, None) para campos que NO se deben aleatorizar
    (geográficos/typeahead: país, ciudad, estado — y el nombre de beneficiario
    que es autocompletado de historial).
    """
    s = (sel_val or "").lower()
    # Geográficos → conservar valor grabado (catálogo real del país).
    # OJO: NO excluimos 'dropdown-input' en general, porque el NOMBRE del
    # beneficiario es un dropdown-input de autocompletado y SÍ debe ser random.
    if any(k in s for k in ("city", "state", "country")):
        return (None, None)
    pre = "beneficiary" if "beneficiary" in s else "customer"
    if "second-lastname" in s or "second_lastname" in s:
        return (f"{pre}_last2", "last_name")
    if "first-lastname" in s or "first_lastname" in s or "lastname" in s:
        return (f"{pre}_last1", "last_name")
    if "cellphone" in s or "phone" in s:
        return ("phone", "phone")
    if "address" in s:
        return ("address", "address")
    if "zip" in s:
        # Cliente (US) → zip REAL del banco (HERMES autocompleta city/state).
        # Beneficiario → zip genérico (el país destino acepta 5 dígitos).
        if pre == "beneficiary":
            return ("zip", "zip")
        return ("us_zip", "us_zip")
    if "email" in s:
        return ("email", "email")
    if "date-of-birth" in s or "dob" in s:
        return ("date", "date")
    if "name" in s:
        return (f"{pre}_name", "first_name")
    return (None, None)


def testid_valido(tid: str) -> bool:
    """
    ¿El data-testid es usable? HERMES a veces genera testids BASURA que son
    expresiones JS (ej. '()=>function yt(St){return O(St),St.value}(it)-branch-
    selected-0-cash-button'). Esos no sirven como localizador → se descartan
    para caer a texto/otros candidatos.
    """
    if not tid or len(tid) > 90:
        return False
    if any(bad in tid for bad in ("=>", "function", "{", "}", "(", ")")):
        return False
    return True


def infer_best_selector(accion: dict) -> tuple[str, str]:
    """
    Elige el mejor selector para una acción, AUDITANDO todos los candidatos
    que captura la extensión (v2.2+: campo 'candidatos') con fallback al
    HTML para grabaciones viejas.

    Ranking (estable e independiente del idioma primero):
      1. data-testid propio
      2. id ESTABLE (no dinámico tipo dropdown_0)
      3. data-testid del ancestro más cercano
      4. formcontrolname propio o del ancestro (forms Angular)
      5. name
      6. aria-label
      7. selector del JSON (si no es tag genérico)
      8. id dinámico (último recurso útil)
      9. texto visible (depende del idioma — evitarlo)
    """
    html     = accion.get("html", "")
    nombre   = accion.get("nombre", "")
    selector = accion.get("selector", "")
    texto    = accion.get("texto", "")
    cand     = accion.get("candidatos") or {}

    # ── 1. data-testid propio (candidatos o HTML) — solo si es VÁLIDO ─────────
    testid = cand.get("testid", "")
    if not testid:
        m = re.search(r'data-testid=["\']([^"\']+)["\']', html)
        testid = m.group(1) if m else ""
    if testid and testid_valido(testid):
        return ("testid", testid)
    # testid basura (ej. '()=>function...-branch-...') → seguir al texto/otros

    # ── 2. id ESTABLE ─────────────────────────────────────────────────────────
    id_val = cand.get("id", "")
    if not id_val:
        m = re.search(r'\bid=["\']([^"\']+)["\']', html)
        id_val = m.group(1) if m else ""
    if id_val and id_val not in ("typography", "id-button") and not es_id_dinamico(id_val):
        return ("css", f"#{id_val}")

    # ── 3. data-testid del ancestro (clicks en spans/divs internos) ──────────
    if cand.get("ancestorTestid"):
        return ("testid", cand["ancestorTestid"])

    # ── 4. formcontrolname propio o del ancestro ─────────────────────────────
    fc = cand.get("formcontrolname") or cand.get("ancestorFormcontrol", "")
    if not fc:
        m = re.search(r'formcontrolname=["\']([^"\']+)["\']', html)
        fc = m.group(1) if m else ""
    if fc:
        return ("css", f'[formcontrolname="{fc}"]')

    # ── 5. name ───────────────────────────────────────────────────────────────
    name = cand.get("name", "")
    if not name:
        m = re.search(r'\bname=["\']([^"\']+)["\']', html)
        name = m.group(1) if m else ""
    if name:
        tag = accion.get("tag", "")
        return ("css", f'{tag}[name="{name}"]' if tag else f'[name="{name}"]')

    # ── 6. aria-label ─────────────────────────────────────────────────────────
    aria = cand.get("ariaLabel", "")
    if not aria:
        m = re.search(r'aria-label=["\']([^"\']+)["\']', html)
        aria = m.group(1) if m else ""
    if aria:
        return ("aria", aria)

    # ── 7. Selector del JSON (si aporta) ──────────────────────────────────────
    # OJO: filas de modales (pagador/branch) llegan con [data-testid=""] VACÍO.
    # Ese selector no sirve → preferimos el TEXTO de la fila ('ELEKTRA DIRECTO',
    # nombre del branch, etc.) más abajo.
    selector_vacio_testid = selector.strip() in ('[data-testid=""]', "[data-testid='']")
    # Fila de modal (pagador/branch): testid vacío + tiene texto → se maneja
    # como selección de fila (por texto, o la primera visible si no existe).
    if selector_vacio_testid and texto:
        return ("fila", texto)
    if (selector and not selector_vacio_testid
            and selector not in ("span", "div", "path", "svg", "button")):
        if selector.startswith("[data-testid"):
            m = re.search(r'data-testid=["\']([^"\']+)["\']', selector)
            if m and testid_valido(m.group(1)):
                return ("testid", m.group(1))
        # Selector con id dinámico → seguir buscando antes de aceptarlo
        elif not (selector.startswith("#") and es_id_dinamico(selector[1:])):
            return ("css", selector)

    # ── 8. id dinámico — último recurso útil ─────────────────────────────────
    if id_val:
        return ("css", f"#{id_val}")

    # ── 9. Texto visible (depende del idioma) ────────────────────────────────
    if texto:
        return ("text", texto)

    return ("css", selector or nombre)


def classify_page(url: str, pages: list[dict]) -> str:
    """
    Deduce el nombre de la página a partir de la URL.
    IMPORTANTE: ignora el query string — las URLs de HERMES2 llevan
    '?iss=https%3A%2F%2Fsso.maxilabs.net...' y clasificaban mal.
    """
    base = url.split("?")[0].split("#")[0]
    if "sso.maxilabs.net" in base:
        return "login"
    if "reports/Transactions" in base:
        return "reports_transaction"
    if "transfers" in base:
        return "transfers"
    return "app"


def group_by_page(actions: list[dict], pages_data: list[dict]) -> dict[str, list]:
    """Agrupa acciones por página visitada."""
    # Construir mapa url → nombre_página
    url_to_page = {}
    page_order  = []
    for pdata in pages_data:
        url  = pdata.get("url", "")
        name = classify_page(url, pages_data)
        if name not in page_order:
            page_order.append(name)
        # Guardar prefijo de URL para matching
        key = url[:80]
        url_to_page[key] = name

    grouped = {p: [] for p in page_order}
    for accion in actions:
        # Clasificar directo por la URL de la acción — el matching por
        # prefijo fallaba cuando la página tenía query string distinto
        matched = classify_page(accion.get("url", ""), pages_data)
        if matched not in grouped:
            grouped[matched] = []
        grouped[matched].append(accion)

    # Grupos creados dinámicamente (ej. 'app') deben entrar a page_order,
    # si no sus acciones nunca se emiten en el page/test generado
    for name, accs in grouped.items():
        if accs and name not in page_order:
            page_order.append(name)

    return grouped, page_order


# ════════════════════════════════════════════════════════════════════════════════
# PASO 2 — Generar nombres limpios para Python
# ════════════════════════════════════════════════════════════════════════════════

def to_snake(text: str) -> str:
    """Convierte cualquier texto a snake_case limpio."""
    text = re.sub(r'[^a-zA-Z0-9_]', '_', text)
    text = re.sub(r'_+', '_', text)
    return text.strip('_').lower()


def to_pascal(text: str) -> str:
    """Convierte snake_case a PascalCase."""
    return ''.join(w.capitalize() for w in text.split('_') if w)


def const_name(nombre: str, tipo: str, selector_val: str) -> str:
    """Genera un nombre de constante VÁLIDO como identificador Python."""
    if selector_val and len(selector_val) > 5:
        base = selector_val.upper().replace("-", "_").replace(" ", "_")
        base = re.sub(r'[^A-Z0-9_]', '', base)
    else:
        base = to_snake(nombre).upper()
    base = base[:60] or "ELEMENT"
    # Un identificador Python no puede empezar con dígito ni estar vacío
    # (ej. texto '47,099,104.57' → '4709910457' rompía la constante).
    if not base or base[0].isdigit():
        base = "EL_" + base
    return base


# Nombres genéricos que Angular repite en muchos elementos — no sirven
# para nombrar métodos (se prefiere el selector real)
GENERIC_NAMES = {"id-button", "typography", "id-input", "id-label"}


def method_name(accion: dict, selector_val: str) -> str:
    """Genera un nombre de método descriptivo para la acción."""
    tipo   = accion.get("tipo", "click")
    if tipo == "scroll":
        return f"scroll_{int(accion.get('scrollY', 0))}px"
    # Tomar solo la primera línea del texto — evita que texto multilinea del DOM
    # (e.g. container con todos los labels del form) contamine el nombre del método
    texto  = (accion.get("texto", "") or "").split("\n")[0].strip()
    nombre = accion.get("nombre", "")
    # Nombres genéricos o ids dinámicos → mejor usar el selector real
    if nombre in GENERIC_NAMES or es_id_dinamico(nombre):
        nombre = ""

    if tipo == "input" and accion.get("valor"):
        return f"fill_{to_snake(nombre or selector_val)}"
    if texto:
        clean = to_snake(texto)[:30]
        return f"click_{clean}"
    if nombre:
        clean = to_snake(nombre)[:30]
        return f"click_{clean}"
    return f"click_{to_snake(selector_val)[:30]}"


def build_fallbacks(accion: dict, primary_type: str, primary_val: str) -> list:
    """
    Construye selectores CSS alternativos a partir de los candidatos
    auditados por la extensión — smart_click los usa si el primario falla.
    """
    cand = accion.get("candidatos") or {}
    fbs = []

    def add(css):
        if css and css not in fbs:
            fbs.append(css)

    def is_primary(kind, val):
        return primary_type == kind and primary_val == val

    if cand.get("testid") and not is_primary("testid", cand["testid"]):
        add(f'[data-testid="{cand["testid"]}"]')
    cid = cand.get("id", "")
    if cid and cid not in ("typography", "id-button") and not es_id_dinamico(cid):
        if not is_primary("css", f"#{cid}"):
            add(f"#{cid}")
    if cand.get("ancestorTestid") and not is_primary("testid", cand["ancestorTestid"]):
        add(f'[data-testid="{cand["ancestorTestid"]}"]')
    fc = cand.get("formcontrolname") or cand.get("ancestorFormcontrol", "")
    if fc and not is_primary("css", f'[formcontrolname="{fc}"]'):
        add(f'[formcontrolname="{fc}"]')
    if cand.get("name"):
        tag = accion.get("tag", "")
        add(f'{tag}[name="{cand["name"]}"]')
    if cand.get("ariaLabel") and not is_primary("aria", cand["ariaLabel"]):
        add(f'[aria-label="{cand["ariaLabel"]}"]')
    if cid and es_id_dinamico(cid) and not is_primary("css", f"#{cid}"):
        add(f"#{cid}")  # id dinámico: último recurso
    return fbs


# ════════════════════════════════════════════════════════════════════════════════
# AUTO-INJECT — Helpers de BasePage que el intérprete inserta automáticamente
# ════════════════════════════════════════════════════════════════════════════════

def auto_inject_after(accion: dict, all_actions: list[dict], idx: int) -> list[str]:
    """
    Analiza el contexto de una acción y retorna líneas de código extra
    que BasePage debe ejecutar automáticamente después de ella.

    Patrones detectados:
      - Login submit  → handle_notifications_modal()
      - Navbar click  → wait_for_no_blocking_overlays()
      - Modal confirm → wait_for_no_blocking_overlays()
      - URL change    → wait_for_load_state("networkidle") (si la URL siguiente difiere)
    """
    nombre   = (accion.get("nombre")    or "").lower()
    sel_val  = (accion.get("_sel_val")  or "").lower()
    texto    = (accion.get("texto")     or "").lower()
    tipo     = accion.get("tipo", "")
    url_now  = accion.get("url", "")

    lines = []

    # ── 1. Login submit → cerrar notificaciones ───────────────────────────────
    is_login_submit = (
        "submit" in nombre
        or "submit" in sel_val
        or "login-form-submit" in sel_val
        or ("login" in sel_val and tipo == "click")
    )
    if is_login_submit:
        lines.append(
            "    await flow.handle_notifications_modal()"
            "  # BasePage: lee y cierra 0..N notificaciones (ya espera la app)"
        )
        lines.append(
            "    await flow.save_session()"
            "  # Guarda la sesión — CP02+ entran directo sin login"
        )
        return lines  # No agregar nada más después de login

    # ── 2. Navbar / menú → esperar que desaparezcan overlays ─────────────────
    is_navbar = (
        "navbar" in nombre
        or "navbar" in sel_val
        or "dropdown" in sel_val
        or "menu" in nombre
    )
    if is_navbar and tipo == "click":
        lines.append(
            "    await flow.wait_for_no_blocking_overlays()"
            "  # BasePage: espera loaders/overlays"
        )
        return lines

    # ── 3. Modal confirm/deny → esperar carga ────────────────────────────────
    is_modal = (
        "modal-confirmation" in sel_val
        or "confirm" in nombre
        or "deny" in nombre
    )
    if is_modal and tipo == "click":
        lines.append(
            "    await flow.wait_for_no_blocking_overlays()"
            "  # BasePage: espera cierre de modal"
        )
        return lines

    # ── 4. Cambio de URL → networkidle ───────────────────────────────────────
    if idx + 1 < len(all_actions):
        url_next = all_actions[idx + 1].get("url", "")
        if url_next and url_next != url_now:
            lines.append("    try:  # URL cambia en siguiente accion")
            lines.append(
                "        await flow.page.wait_for_load_state"
                '("domcontentloaded", timeout=10000)'
            )
            lines.append("    except Exception:")
            lines.append(
                "        pass  # la espera real la hace el expect de la siguiente accion"
            )

    return lines


# ════════════════════════════════════════════════════════════════════════════════
# PASO 3 — Generar código
# ════════════════════════════════════════════════════════════════════════════════

def generate_locators_file(flujo_name: str, actions: list[dict]) -> str:
    """Genera el archivo de locators."""
    class_name = f"{to_pascal(flujo_name)}Locators"
    lines = [
        f'"""',
        f'Locators para el flujo: {flujo_name}',
        f'Generado automáticamente por json_to_pom.py — {datetime.now().strftime("%Y-%m-%d")}',
        f'"""',
        f'',
        f'',
        f'class {class_name}:',
        f'    """Selectores del flujo {flujo_name}."""',
        f'',
    ]

    # Tags HTML genéricos sin valor como selector de click — se descartan
    USELESS_SELECTORS = {"div", "span", "p", "li", "ul", "ol",
                         "section", "article", "aside", "main", "header", "footer"}

    seen_consts = set()
    for accion in actions:
        # Las acciones de scroll no tienen localizador propio → sin constante
        if accion.get("tipo") == "scroll":
            continue

        sel_type, sel_val = infer_best_selector(accion)

        # Sanear el valor del selector: nunca debe llevar saltos de línea
        # (un texto multilínea, ej. header de tabla, rompía el string Python).
        # Para selectores por texto, quedarse con la primera línea y acotar.
        sel_val = re.sub(r"\s+", " ", (sel_val or "").replace("\n", " ").replace("\r", " ")).strip()
        if sel_type == "text":
            sel_val = sel_val[:60]

        # Marcar y saltar clicks cuyo único selector es un tag genérico
        if accion.get("tipo") == "click" and sel_val in USELESS_SELECTORS:
            accion["_skip"] = True
            accion["_const_name"] = ""
            accion["_sel_type"]   = "css"
            accion["_sel_val"]    = sel_val
            continue

        cname = const_name(accion["nombre"], accion["tipo"], sel_val)

        if cname in seen_consts:
            cname = f"{cname}_{to_snake(accion['tipo'])}"
        seen_consts.add(cname)

        accion["_const_name"] = cname
        accion["_sel_type"]   = sel_type
        accion["_sel_val"]    = sel_val

        # Comentario con contexto — SOLO la primera línea del texto
        # (texto multilinea derramaba líneas sin '#' → SyntaxError)
        pagina = classify_page(accion.get("url", ""), [])
        comment_txt = (
            (accion.get("texto") or accion.get("nombre") or "")
            .split("\n")[0].strip()
        )
        linea_comentario = f"    # [{pagina}] {comment_txt}"
        if len(linea_comentario) > 90:
            linea_comentario = linea_comentario[:90]

        if sel_type == "testid":
            value_str = f'"{sel_val}"  # data-testid'
        elif sel_type == "aria":
            value_str = f'"[aria-label=\\"{sel_val}\\"]"'
        else:
            # Escapar comillas — un selector como [data-testid="x"] rompería
            # la string generada si no se escapa
            sel_escaped = sel_val.replace('"', '\\"')
            value_str = f'"{sel_escaped}"'

        lines.append(linea_comentario)
        lines.append(f'    {cname:<55} = {value_str}')
        lines.append('')

    return '\n'.join(lines)


def generate_page_file(flujo_name: str, actions: list[dict], grouped: dict, page_order: list) -> str:
    """
    Genera el Page Object con:
      - @property locators para campos de texto (usables en locators=[...] del screenshot)
      - Métodos que reciben value como parámetro (no hardcodeado)
      - Métodos de click limpios con expect().to_be_visible()
      - navigate() auto-inyectado si el flujo comienza en login
    """
    class_name     = f"{to_pascal(flujo_name)}Page"
    locators_class = f"{to_pascal(flujo_name)}Locators"
    features       = detect_features(actions)
    is_login_flow  = features.get("login") or (page_order and page_order[0] == "login")

    settings_imports = "TIMEOUT_ELEMENT"
    if is_login_flow:
        settings_imports = "TIMEOUT_ELEMENT, SSO_URL"

    lines = [
        f'"""',
        f'{class_name} — Page Object para el flujo: {flujo_name}',
        f'Generado automáticamente por json_to_pom.py — {datetime.now().strftime("%Y-%m-%d")}',
        f'',
        f'PATRON: Los métodos aceptan los valores como parámetros.',
        f'        Las constantes se definen en el test, no aquí.',
        f'"""',
        f'',
        f'from playwright.async_api import expect',
        f'from config.logger import get_logger',
        f'from config.settings import {settings_imports}',
        f'from src.locators.{flujo_name}_locators import {locators_class}',
        f'from src.pages.base_page import BasePage',
        f'',
        f'logger = get_logger("{flujo_name}_page")',
        f'',
        f'',
        f'class {class_name}(BasePage):',
        f'    """Page Object para el flujo {flujo_name}."""',
        f'',
    ]

    # ── Bloque de @property locators (campos de texto solamente) ──────────────
    input_actions = [a for a in actions if a.get("tipo") == "input" and a.get("_const_name")]
    if input_actions:
        lines.append('    # ── Locators (para usar en screenshot locators=[...]) ──────────────')
        lines.append('')
        seen_props = set()
        for accion in input_actions:
            cname    = accion["_const_name"]
            sel_type = accion["_sel_type"]
            sel_val  = accion["_sel_val"]
            nombre   = accion.get("nombre", "")
            prop_name = f"{to_snake(nombre or sel_val)}_input"
            if prop_name in seen_props:
                continue
            seen_props.add(prop_name)
            lines.append(f'    @property')
            if sel_type == "testid":
                lines.append(f'    def {prop_name}(self):')
                lines.append(f'        return self.page.get_by_test_id({locators_class}.{cname})')
            else:
                lines.append(f'    def {prop_name}(self):')
                lines.append(f'        return self.page.locator({locators_class}.{cname})')
            lines.append('')
        lines.append('')

    # ── navigate() ────────────────────────────────────────────────────────────
    if is_login_flow:
        lines += [
            '    # ── NAVEGACIÓN ──────────────────────────────────────────────────────',
            '',
            '    async def navigate(self) -> None:',
            '        """Navega a la URL de login SSO."""',
            '        logger.info("navigate: SSO login URL")',
            '        await self.page.goto(SSO_URL, wait_until="domcontentloaded", timeout=60000)',
            '',
        ]
    else:
        # Flujo SIN login grabado → corre con la fixture logged_page
        # (sesión ya iniciada). navigate() va a la URL inicial del flujo
        # SIN recargar si ya está ahí (una recarga reabre las notificaciones).
        first_url = ""
        for a in actions:
            if a.get("url"):
                first_url = a["url"].split("?")[0].split("#")[0]
                break
        lines += [
            '    # ── NAVEGACIÓN (sesión ya iniciada por logged_page) ─────────────────',
            '',
            '    async def navigate(self) -> None:',
            f'        """Va a la URL inicial del flujo — sin recargar si ya está ahí."""',
            f'        target = "{first_url}"',
            '        if self.page.url.split("?")[0].rstrip("/") == target.rstrip("/"):',
            '            logger.info("navigate: ya en la URL inicial — sin recargar")',
            '            await self.wait_for_no_blocking_overlays()',
            '            return',
            '        logger.info(f"navigate: {target}")',
            '        await self.goto(target)',
            '        # Una recarga completa puede reabrir el modal de notificaciones',
            '        await self.handle_notifications_modal()',
            '        await self.wait_for_no_blocking_overlays()',
            '',
        ]

    # ── Detectar pares trigger+opción de dropdowns (PrimeNG) ──────────────────
    # Dos clicks consecutivos que resuelven al MISMO selector = abrir el
    # dropdown y elegir una opción. Clickear dos veces el mismo elemento lo
    # abriría y CERRARÍA — se fusionan en una sola selección por texto.
    prev = None
    for accion in actions:
        if accion.get("_skip"):
            continue
        if (prev is not None
                and accion.get("tipo") == "click" and prev.get("tipo") == "click"
                and accion.get("_sel_val") and accion.get("_sel_val") == prev.get("_sel_val")
                and (accion.get("texto") or "").strip()):
            prev["_skip"] = True
            accion["_dropdown_option"] = True
        prev = accion

    # ── Métodos por página ────────────────────────────────────────────────────
    seen_methods = set()
    for page_name in page_order:
        page_actions = grouped.get(page_name, [])
        if not page_actions:
            continue

        separator = '─' * max(0, 50 - len(page_name))
        lines.append(f'    # ── {page_name.upper()} ──{separator}')
        lines.append('')

        for accion in page_actions:
            # Saltar acciones marcadas como sin selector útil
            if accion.get("_skip"):
                continue

            cname    = accion.get("_const_name", "ELEMENT")
            sel_type = accion.get("_sel_type", "css")
            sel_val  = accion.get("_sel_val", "")
            mname    = method_name(accion, sel_val)
            tipo     = accion.get("tipo", "click")
            valor    = accion.get("valor", "")
            # Solo primera línea + escape de comillas — texto multilinea o
            # con comillas rompía el has_text="..." generado
            texto    = (
                (accion.get("texto", "") or "")
                .split("\n")[0].strip().replace('"', '\\"')
            )
            doc      = texto or sel_val or cname

            # Evitar métodos duplicados en el mismo archivo
            if mname in seen_methods:
                mname = f"{mname}_2"
            seen_methods.add(mname)

            if tipo == "scroll":
                sx = int(accion.get("scrollX", 0) or 0)
                sy = int(accion.get("scrollY", 0) or 0)
                sv = accion.get("selector", "") or ""
                lines.append(f'    async def {mname}(self) -> None:')
                lines.append(f'        """Scroll para visualizar contenido (rueda o barra)."""')
                if sv:
                    lines.append(f'        await self.scroll_to({sy}, {sx}, selector="{sv}")')
                else:
                    lines.append(f'        await self.scroll_to({sy}, {sx})')
                lines.append('')
                continue
            elif tipo == "input" and valor:
                # Campo de texto: el método recibe `value` como parámetro
                param_name = to_snake(accion.get("nombre", "") or sel_val) or "value"
                # Campos de AUTOCOMPLETADO dinámico (país, estado, ciudad y los
                # *-dropdown-input): el dropdown solo aparece tecleando despacio
                # y hay que SELECCIONAR la opción → usar select_typeahead.
                # 'name' se deja como fill normal (su dropdown es historial de
                # beneficiarios y no se debe autoseleccionar).
                sv = (sel_val or "").lower()
                es_typeahead = sel_type == "testid" and (
                    "city" in sv or "country" in sv or "state" in sv
                    or "dropdown-input" in sv)
                lines.append(f'    async def {mname}(self, {param_name}: str) -> None:')
                lines.append(f'        """Ingresa texto en: {doc[:60]}"""')
                lines.append(f'        logger.info(f"{mname}: {{{param_name}}}")')
                if es_typeahead:
                    lines.append(f'        await self.select_typeahead({locators_class}.{cname}, {param_name})')
                elif sel_type == "testid":
                    lines.append(f'        await self.fill_input_by_testid(')
                    lines.append(f'            {locators_class}.{cname}, {param_name}')
                    lines.append(f'        )')
                else:
                    lines.append(f'        await self.fill({locators_class}.{cname}, {param_name})')
            elif accion.get("_dropdown_option"):
                # Selección de opción en dropdown (trigger + opción fusionados)
                lines.append(f'    async def {mname}(self) -> None:')
                lines.append(f'        """Selecciona la opción \'{texto[:40]}\' del dropdown."""')
                lines.append(f'        logger.info("{mname}...")')
                if sel_type == "testid":
                    lines.append(f'        await self.select_option_by_text(')
                    lines.append(f'            self.format_testid_selector({locators_class}.{cname}),')
                else:
                    lines.append(f'        await self.select_option_by_text(')
                    lines.append(f'            {locators_class}.{cname},')
                lines.append(f'            "li[role=\'option\'], .p-dropdown-item",')
                lines.append(f'            "{texto}",')
                lines.append(f'        )')
            else:
                # Click — delegado a smart_click (ADAPTATIVO):
                #   - desambigua testids genéricos repetidos por texto
                #   - si el texto no matchea (cambio de idioma), usa el
                #     primer match visible en vez de fallar
                #   - espera overlays/loaders y reintenta
                #   - usa los candidatos auditados como fallback

                # Caso especial: click en un INPUT DE MONTO grabado sin valor.
                # Se convierte en un FILL parametrizado para escribir el monto
                # (el test pasa la variable `amount`). Evita el 'Required field'.
                es_amount_input = (sel_type == "testid"
                                   and "amount" in sel_val and sel_val.endswith("input"))
                if es_amount_input:
                    accion["_amount_fill"] = True
                    lines.append(f'    async def {mname}(self, monto) -> None:')
                    lines.append(f'        """Escribe el monto (limpia + teclea) en: {doc[:50]}"""')
                    lines.append(f'        logger.info(f"{mname}: {{monto}}")')
                    lines.append(f'        await self.fill_monto({locators_class}.{cname}, monto)')
                    lines.append('')
                    continue

                # FILA de modal (pagador/branch): click por texto o, si no
                # existe (ej. branch grabado ausente), la primera fila visible.
                if sel_type == "fila":
                    txt_l = (texto or "").lower()
                    # 'Close Table' = tabla de COINCIDENCIA (solo sale si el
                    # teléfono/nombre coincide). Cierre rápido y OPCIONAL.
                    if "close table" in txt_l or "cerrar tabla" in txt_l:
                        lines.append(f'    async def {mname}(self) -> None:')
                        lines.append('        """Cierra tabla de coincidencia (OPCIONAL, solo si apareció)."""')
                        lines.append(f'        logger.info("{mname} (opcional)...")')
                        lines.append('        await self._cerrar_autofill()')
                        lines.append('')
                        continue
                    # Branch/sucursal: la tabla no siempre aparece → OPCIONAL.
                    es_opcional = any(k in txt_l for k in ("branch", "sucursal")) or \
                                  any(k in (sel_val or "").lower() for k in ("branch", "sucursal"))
                    lines.append(f'    async def {mname}(self) -> None:')
                    lines.append(f'        """Selecciona fila de modal: {texto[:40]}"""')
                    lines.append(f'        logger.info("{mname}...")')
                    if es_opcional:
                        lines.append(f'        await self.click_fila_modal("{texto}", optional=True)')
                    else:
                        lines.append(f'        await self.click_fila_modal("{texto}")')
                    lines.append('')
                    continue

                lines.append(f'    async def {mname}(self) -> None:')
                lines.append(f'        """Click en: {doc[:60]}"""')
                lines.append(f'        logger.info("{mname}...")')

                import re as _re
                m_dd = (_re.match(r'([a-z]+)-\d+-navbar-dropdown-item', sel_val)
                        if sel_type == "testid" else None)
                if m_dd:
                    opener = f"{m_dd.group(1)}-navbar-item"
                    lines.append(f'        item = self.page.get_by_test_id({locators_class}.{cname})')
                    lines.append(f'        if not await item.is_visible():')
                    lines.append(f'            # Abrir el dropdown del navbar solo si el item no está visible')
                    lines.append(f'            await self.smart_click(testid="{opener}")')

                fallbacks = build_fallbacks(accion, sel_type, sel_val)
                if sel_type == "testid":
                    args = [f'testid={locators_class}.{cname}']
                elif sel_type == "text":
                    args = [f'css="text=" + {locators_class}.{cname}']
                else:
                    args = [f'css={locators_class}.{cname}']
                if texto:
                    args.append(f'texto="{texto}"')
                if fallbacks:
                    args.append(f'fallbacks={fallbacks!r}')
                # Elementos CONDICIONALES (branch, sucursal): solo aparecen a
                # veces (cuando son requeridos) → click opcional, no falla si
                # no está. Crece: agrega aquí otras palabras condicionales.
                blob = (sel_val + " " + (texto or "")).lower()
                if any(k in blob for k in ("branch", "sucursal")):
                    args.append("optional=True")
                lines.append(f'        await self.smart_click({", ".join(args)})')

            lines.append('')

    return '\n'.join(lines)


def detect_features(actions: list[dict]) -> dict:
    """
    Analiza las acciones del flujo y detecta qué features necesita el test:
      - faker        → hay campos de nombre, teléfono, dirección
      - random_amount → hay campos de monto
      - login        → hay campos de usuario/contraseña
      - printer      → hay selección de impresora
      - modal_confirm → hay confirmaciones de modal
    """
    features = {
        "faker"        : False,
        "random_amount": False,
        "login"        : False,
        "printer"      : False,
        "modal_confirm": False,
        "logout"       : False,
    }
    faker_keywords  = {"name", "phone", "address", "zip", "city", "beneficiary",
                       "customer", "cellphone", "first", "last", "nombre"}
    amount_keywords = {"amount", "monto", "fee", "price", "cost"}

    for a in actions:
        nombre = (a.get("nombre") or "").lower()
        val    = (a.get("valor")  or "").lower()
        sel    = (a.get("_sel_val") or "").lower()

        if "username" in nombre or "password" in nombre:
            features["login"] = True
        if any(k in nombre or k in sel for k in faker_keywords):
            features["faker"] = True
        if any(k in nombre or k in sel for k in amount_keywords):
            features["random_amount"] = True
        if "printer" in sel or "ticket" in sel or "windows printer" in (a.get("texto") or "").lower():
            features["printer"] = True
        if "modal-confirmation" in sel:
            features["modal_confirm"] = True
        if "cerrar-sesi" in sel or "logout" in sel or "user-3-navbar" in sel:
            features["logout"] = True

    return features


def generate_test_file(flujo_name: str, actions: list[dict], page_order: list,
                       label: str = None) -> str:
    """
    Genera el test. `label` = nomenclatura tal cual (HM-Login, CR-KYC-0020-Soriana)
    para la carpeta de evidencias; flujo_name = versión Python.
    """
    class_name = f"{to_pascal(flujo_name)}Page"
    test_name  = f"test_{flujo_name}"
    label      = label or flujo_name

    # Agrupar métodos por página para organizar steps
    steps_by_page = {}
    for accion in actions:
        page = classify_page(accion.get("url", ""), [])
        if page not in steps_by_page:
            steps_by_page[page] = []
        steps_by_page[page].append(accion)

    features = detect_features(actions)

    # Selección de fixture (genérico):
    #   flujo con login grabado → browser_page (login explícito paso a paso)
    #   flujo sin login         → logged_page  (sesión persistente del portal)
    is_login_flow = features.get("login") or (page_order and page_order[0] == "login")
    if is_login_flow:
        fixture_name = "browser_page"
    else:
        fixture_name = "logged_page"

    prereqs = ["  - Variables: HERMES2_USER, HERMES2_PSWD (o defaults en config/settings.py)"]
    if not is_login_flow:
        prereqs.append(
            "  - Sesion: fixture logged_page — login automatico solo si expiro "
            "(session_state/)"
        )
    if features["printer"]:
        prereqs.append("  - Hardware Agent (Agent2Hermes) corriendo")

    imports = [
        "import os",
        "import pytest",
        "from playwright.async_api import Page",
        "",
        "from config.logger import get_logger",
        "from config.settings import PORTAL_USER, PORTAL_PASS",
        f"from src.pages.{flujo_name}_page import {class_name}",
        "from src.helpers.screenshot_helper import ScreenshotHelper",
        "from src.helpers.datos import Datos",
    ]
    if features["faker"]:
        imports.insert(2, "from faker import Faker")
    if features["random_amount"]:
        imports.insert(2, "import random")

    # ── Docstring ──────────────────────────────────────────────────────────────
    lines = [
        f'"""',
        f'TEST — {flujo_name.replace("_", " ").title()}',
        f'Generado automáticamente por json_to_pom.py — {datetime.now().strftime("%Y-%m-%d")}',
        f'',
        f'Flujo grabado:',
    ]
    for i, page in enumerate(page_order, 1):
        lines.append(f'  Step {i} — {page}')
    lines += [
        f'',
        f'PREREQUISITOS:',
    ] + prereqs + [
        f'',
        f'EJECUTAR:',
        f'    pytest src/tests/{test_name}.py -v -s',
        f'"""',
        f'',
    ] + imports + [
        f'',
        f'logger = get_logger("{test_name}")',
        f'',
        f'',
        f'# ── Constantes del caso de prueba ────────────────────────────────────────────',
    ]

    # Extraer valores registrados en el JSON como constantes
    recorded_inputs = [a for a in actions if a.get("tipo") == "input" and a.get("valor")]
    if recorded_inputs:
        for accion in recorded_inputs:
            nombre = accion.get("nombre", "")
            valor  = accion.get("valor", "")
            # Skip credenciales — van desde config/settings.py
            if "username" in nombre.lower() or "password" in nombre.lower():
                continue
            const = to_snake(nombre or accion.get("_const_name", "field")).upper()
            lines.append(f'{const:<40} = "{valor}"')

    if features["random_amount"]:
        lines += [
            f'AMOUNT_MIN                               = 10.00',
            f'AMOUNT_MAX                               = 500.00',
        ]
    if features["printer"]:
        lines.append(f'TARGET_PRINTER                           = "WINDOWS PRINTER"')

    lines += [
        f'',
        f'EVIDENCE_FOLDER = "{label}"',
        f'',
        f'',
    ]

    # ── Markers + función ─────────────────────────────────────────────────────
    lines += [
        f'@pytest.mark.sanity_general',
        f'@pytest.mark.parametrize("language,width,height", [',
        f'    ("English", 1366, 768)',
        f'])',
        f'@pytest.mark.asyncio',
        f'async def {test_name}(',
        f'    {fixture_name}: Page,',
        f'    language: str,',
        f'    width: int,',
        f'    height: int,',
        f'):',
        f'    """',
        f'    {flujo_name.replace("_", " ").title()}',
        f'',
    ]
    for i, page in enumerate(page_order, 1):
        lines.append(f'    Step {i} — {page}')
    lines += [
        f'    """',
        f'    # ── Setup ────────────────────────────────────────────────────────────',
        f'    flow       = {class_name}({fixture_name})',
        f'    screenshot = ScreenshotHelper({fixture_name})',
        f'    # Datos: overrides del lenguaje natural (FLOW_OVERRIDES) + Faker',
        f'    datos      = Datos()',
    ]

    if features["faker"]:
        lines += [
            f'    fake       = Faker()',
            f'',
            f'    # ── Datos aleatorios ─────────────────────────────────────────────',
            f'    customer_phone = fake.numerify("555#######")',
            f'    customer_zip   = fake.zipcode()[:5]',
            f'    # Agrega más campos de Faker según necesites',
        ]
    if features["random_amount"]:
        lines += [
            f'    amount = round(random.uniform(AMOUNT_MIN + 0.01, AMOUNT_MAX), 2)',
            f'    logger.info(f"Monto generado: {{amount}}")',
        ]

    lines += [
        f'',
        f'    # ── Carpeta de evidencias ────────────────────────────────────────────',
        f'    # Todos los reportes bajo reports/ (evidencia por flujo)',
        f'    evidence_dir = os.path.join(',
        f'        os.path.dirname(__file__), "..", "..", "reports", "evidence", EVIDENCE_FOLDER',
        f'    )',
        f'    os.makedirs(evidence_dir, exist_ok=True)',
        f'',
        f'    def evidence(filename: str) -> str:',
        f'        return os.path.join(evidence_dir, filename)',
        f'',
    ]

    # ── Palabras clave para highlight ─────────────────────────────────────────
    HIGHLIGHT_KEYWORDS = {
        "buscar", "search", "imprimir", "print", "ingresar", "submit",
        "confirmar", "confirm", "resultado", "result", "transaccion", "transaction",
        "recibo", "receipt", "monto", "amount", "pagador", "payer", "login",
    }

    step_num = 1
    seen_method_calls = set()
    cap_seq = 0  # contador de capturas de evidencia (una por transición)

    for page_name in page_order:
        page_actions = steps_by_page.get(page_name, [])
        if not page_actions:
            continue

        step_label = page_name.replace("_", " ").upper()
        lines += [
            f'    # ── Step {step_num}: {step_label} {"─" * max(0, 50 - len(step_label))}',
            f'    logger.info("Step {step_num} — {step_label}")',
            f'',
        ]

        # Auto-inyectar navigate() al inicio del flujo
        if step_num == 1:
            if is_login_flow:
                lines.append(f'    await flow.navigate()               # Navega a SSO login')
            else:
                lines.append(
                    f'    await flow.navigate()               '
                    f'# Sesión ya iniciada (logged_page) — va directo al flujo'
                )
            # Evidencia de la pantalla inicial
            lines.append(
                '    await screenshot.screenshot_only('
                'screenshot_path=evidence("step00_inicio.png"))'
            )

        # Recolectar locators de inputs en este step para el screenshot
        step_input_locators = []
        for accion in page_actions:
            if accion.get("tipo") == "input":
                nombre = accion.get("nombre", "")
                sel_val = accion.get("_sel_val", "")
                prop_name = f"{to_snake(nombre or sel_val)}_input"
                step_input_locators.append(prop_name)

        # Índice global de cada acción para auto_inject_after
        global_actions = actions  # referencia a la lista completa

        for local_idx, accion in enumerate(page_actions):
            # Saltar acciones sin selector útil
            if accion.get("_skip"):
                continue

            mname  = method_name(accion, accion.get("_sel_val", ""))
            tipo   = accion.get("tipo", "click")
            valor  = accion.get("valor", "")
            # Usar solo la primera línea del texto para evitar comentarios multilinea
            texto_raw = accion.get("texto") or accion.get("nombre") or mname
            texto  = (texto_raw or "").split("\n")[0].strip() or mname
            nombre = accion.get("nombre", "")

            # Índice global para detectar cambio de URL
            try:
                global_idx = global_actions.index(accion)
            except ValueError:
                global_idx = 0

            # (Versión genérica: sin módulo de cancelación específico. Un botón
            # 'Cancel'/'Cancelar' se trata como un clic normal del flujo.)

            # Evitar llamadas duplicadas
            call_key = mname
            if call_key in seen_method_calls:
                call_key = f"{mname}_2"
            seen_method_calls.add(call_key)

            if accion.get("_amount_fill"):
                # Monto: override 'monto' o aleatorio
                lines.append(f'    await flow.{mname}(datos.monto())  # monto del envío')
            elif tipo == "input" and valor:
                if "username" in nombre.lower() or "user" in nombre.lower():
                    lines.append(f"    await flow.{mname}(PORTAL_USER)  # {texto[:40]}")
                elif "password" in nombre.lower() or "pass" in nombre.lower():
                    lines.append(f"    await flow.{mname}(PORTAL_PASS)  # {texto[:40]}")
                else:
                    # Campo libre → Faker/override por semántica; typeahead/geo
                    # (país, ciudad, estado) conserva el valor grabado.
                    sem, t_campo = semantica_campo(accion.get("_sel_val", ""))
                    if sem:
                        lines.append(f'    await flow.{mname}(datos.valor("{sem}", "{t_campo}"))  # {texto[:30]}')
                        # Tras el zip del cliente, HERMES autocompleta City/State
                        # (a veces tarda) → esperar antes de seguir.
                        if sem == "us_zip":
                            lines.append('    await flow.esperar_autocomplete_cp()  # espera autocompletado de City/State')
                    else:
                        const = to_snake(nombre or accion.get("_const_name", "field")).upper()
                        lines.append(f"    await flow.{mname}({const})  # {texto[:40]}")
            else:
                lines.append(f"    await flow.{mname}()  # {texto[:40]}")

            # ── Auto-inyectar helpers de BasePage según contexto ──────────────
            injected = auto_inject_after(accion, global_actions, global_idx)
            lines.extend(injected)

            # ── Evidencia SOLO en transiciones reales ─────────────────────────
            # Capturar en cada llenado de campo genera demasiadas imágenes.
            # Se captura solo tras CLICKS y selecciones de dropdown (que
            # disparan navegación, modales o cambios de pantalla), no tras
            # cada input de texto ni cada scroll.
            es_transicion = (tipo == "click") or accion.get("_dropdown_option")
            if es_transicion:
                cap_seq += 1
                cap_mname = re.sub(r"[^a-z0-9_]", "", mname.lower())[:30]
                lines.append(
                    f'    await screenshot.screenshot_only('
                    f'screenshot_path=evidence("t{cap_seq:02d}_{cap_mname}.png"))'
                )

        pad = str(step_num).zfill(2)
        lines.append("")

        # Screenshot con highlight
        # Si el step incluye el submit de login, la página ya navegó y los
        # campos del form no existen — capturar sin resaltado (evita timeouts)
        step_has_login_submit = any(
            "login-form-submit" in (a.get("_sel_val") or "")
            for a in page_actions
        )
        if step_has_login_submit:
            lines.append(
                f"    await screenshot.screenshot_only("
                f"screenshot_path=evidence(\"step{pad}_{page_name}.png\"))"
            )
        elif step_input_locators:
            locator_args = ", ".join(f"flow.{p}" for p in step_input_locators[:3])
            lines += [
                f"    await screenshot.screenshot_with_highlight(",
                f"        screenshot_path=evidence(\"step{pad}_{page_name}.png\"),",
                f"        locators=[{locator_args}],",
                f"    )",
            ]
        else:
            highlight_text = None
            for accion in page_actions:
                texto_kw = (accion.get("texto") or "").lower()
                if any(kw in texto_kw for kw in HIGHLIGHT_KEYWORDS):
                    # Primera línea + escape — multilinea rompía el search_text="..."
                    highlight_text = (
                        (accion.get("texto") or "")
                        .split("\n")[0].strip().replace('"', '\\"')
                    )
                    break
            if highlight_text:
                lines += [
                    f"    await screenshot.screenshot_with_highlight(",
                    f"        screenshot_path=evidence(\"step{pad}_{page_name}.png\"),",
                    f"        search_text=\"{highlight_text}\",",
                    f"    )",
                ]
            else:
                lines.append(
                    f"    await screenshot.screenshot_only("
                    f"screenshot_path=evidence(\"step{pad}_{page_name}.png\"))"
                )

        lines += [
            f"    logger.info(\"Step {step_num} completado.\")",
            "",
        ]
        step_num += 1

    lines += [
        "    # -- Fin ---------------------------------------------------------------",
        f"    logger.info(\"{test_name} finalizado exitosamente.\")",
    ]

    return "\n".join(lines)


# ================================================================================
# MAIN
# ================================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Convierte un JSON grabado por Chrome Recorder en archivos POM."
    )
    parser.add_argument("json_path", help="Ruta al archivo JSON grabado")
    parser.add_argument(
        "--name", "-n",
        help="Nombre del flujo (snake_case). Por defecto se deduce del nombre del archivo.",
        default=None,
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Previsualiza los archivos generados sin escribirlos.",
    )
    args = parser.parse_args()

    json_path  = args.json_path
    dry_run    = args.dry_run
    flujo_name = args.name

    # Deducir nombre desde el archivo si no se especifica
    # Soporta formatos:
    #   CP01_login_1780712149126.json  -> cp01_login
    #   test_print_report_1780435766604.json -> test_print_report
    #   mi_flujo.json -> mi_flujo
    # LABEL = nomenclatura tal cual (HM-Login, CR-KYC-0020-Soriana) para
    # carpetas de evidencia/reportes. flujo_name = versión Python (snake).
    stem = Path(json_path).stem
    label = re.sub(r"[_-]\d{10,13}$", "", stem)  # quitar timestamp si lo hay
    if not flujo_name:
        flujo_name = re.sub(r"[^a-zA-Z0-9_]", "_", label).lower().strip("_")
        flujo_name = re.sub(r"_+", "_", flujo_name)
        print(f"  Nombre deducido del archivo: '{flujo_name}'  ·  label: '{label}'")

    print(f"\n  Flujo: {flujo_name}")
    print(f"  JSON:  {json_path}")
    print()

    # Parsear y extraer acciones
    data    = parse_json(json_path)
    actions = extract_actions(data)
    print(f"  Acciones filtradas: {len(actions)}")

    if not actions:
        print("  [!] Sin acciones utiles en el JSON.")
        return

    # Clasificar acciones por pagina
    pages_data = data.get("paginas", [])
    if not pages_data:
        seen_urls = {}
        for a in actions:
            u = a.get("url", "")
            if u and u not in seen_urls:
                seen_urls[u] = True
        pages_data = [{"url": u} for u in seen_urls]
    grouped, page_order = group_by_page(actions, pages_data)
    print(f"  Paginas detectadas: {page_order}")

    # Generar codigo
    locators_code = generate_locators_file(flujo_name, actions)
    page_code     = generate_page_file(flujo_name, actions, grouped, page_order)
    test_code     = generate_test_file(flujo_name, actions, page_order, label)

    # Rutas de salida
    locators_path = LOCATORS_DIR / f"{flujo_name}_locators.py"
    page_path     = PAGES_DIR    / f"{flujo_name}_page.py"
    test_path     = TESTS_DIR    / f"test_{flujo_name}.py"

    if dry_run:
        print("\n" + "=" * 70)
        print("DRY RUN -- Archivos que se generarian:")
        print("=" * 70)
        for label, path, code in [
            ("LOCATORS", locators_path, locators_code),
            ("PAGE",     page_path,     page_code),
            ("TEST",     test_path,     test_code),
        ]:
            print(f"\n{'--' * 35}")
            print(f"  {label}: {path}")
            print(f"{'--' * 35}")
            print(code[:2500])
            if len(code) > 2500:
                print(f"  ... ({len(code) - 2500} chars more)")
        return

    # Escribir archivos
    for path, code in [
        (locators_path, locators_code),
        (page_path,     page_code),
        (test_path,     test_code),
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(code, encoding="utf-8")
        print(f"  Generado: {path}")

    print()
    print("  LISTO. Proximos pasos:")
    print(f"    1. Revisar selectores en: {locators_path.name}")
    print(f"    2. Revisar metodos en:    {page_path.name}")
    print(f"    3. Ejecutar:")
    print(f"       pytest src/tests/test_{flujo_name}.py -v -s")


if __name__ == "__main__":
    main()
