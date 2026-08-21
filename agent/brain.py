"""
Brain — el cerebro del agente.

Interpreta instrucciones en lenguaje natural (español o inglés) y produce
un PLAN:
  {"tipo": "ejecutar_test",  "test": ..., "archivo": ..., "razon": ...}
  {"tipo": "respuesta",      "mensaje": ...}
  {"tipo": "sugerencia",     "mensaje": ...}

Modo actual: OFFLINE — matching por tokens contra el catálogo + memoria de
instrucciones aprendidas. Cuando haya ANTHROPIC_API_KEY disponible, la
función interpretar() puede delegar en Claude sin cambiar ninguna interfaz
(ver interpretar_con_claude más abajo — punto de extensión listo).
"""

import json
import os
import re
import time
import unicodedata
from pathlib import Path

MEMORIA_FILE = Path(__file__).parent / "memoria.json"

# Palabras vacías que no aportan a la intención
STOPWORDS = {
    "el", "la", "los", "las", "un", "una", "de", "del", "al", "a", "y", "o",
    "que", "en", "por", "para", "con", "me", "mi", "te", "se", "lo", "su",
    "haz", "hace", "hacer", "dame", "quiero", "necesito", "puedes", "podes",
    "favor", "porfa", "ahora", "luego", "the", "a", "an", "of", "to", "and",
    "or", "in", "on", "for", "with", "please", "run", "do",
    "corre", "correr", "ejecuta", "ejecutar", "lanza", "lanzar", "prueba",
    "test", "caso", "cp", "script", "flujo", "reporte", "report",
}

# Sinónimos → token canónico (amplía el matching)
SINONIMOS = {
    "login"        : ["sesion", "inicio", "ingresar", "loguear", "signin", "log"],
    "balance"      : ["saldo", "balances"],
    "agent"        : ["agente"],
    "reports"      : ["reportes", "informe", "informes"],
    "transfer"     : ["transfers", "envio", "envios", "enviar", "enviare", "envia",
                       "enviado", "mandar", "manda", "mande", "transferencia",
                       "transferencias", "dinero", "remesa", "remesas"],
    "transactions" : ["transacciones", "transaccion", "movimientos"],
}

# Palabras de DOMINIO que pueden venir PEGADAS en el nombre del flujo
# (ej. 'transferelektra' → 'transfer' + 'elektra', 'agentbalance' → 'agent' +
# 'balance'). Se usan para partir tokens compuestos y mejorar el matching.
DOMINIO = [
    "transfer", "elektra", "balance", "agent", "login", "reports", "report",
    "transactions", "transaction", "money", "cash", "deposit", "bill",
    "payment", "chronos", "kyc", "soriana",
]


def normalizar_texto_simple(texto: str) -> str:
    """
    Quita tildes/diacríticos SIN tokenizar (para regex de substring, no de
    tokens). Complementa a normalizar(): esa devuelve una lista de tokens
    filtrada por stopwords; esta devuelve el string completo, útil cuando
    una función necesita matchear frases con re.search en vez de comparar
    tokens sueltos (ej. detectar_cancelacion).
    """
    texto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def normalizar(texto: str) -> list[str]:
    """minúsculas, sin acentos, tokens sin stopwords, con sinónimos."""
    texto = unicodedata.normalize("NFD", texto.lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    tokens = re.findall(r"[a-z0-9]+", texto)
    resultado = []
    for t in tokens:
        if t in STOPWORDS:
            continue
        resultado.append(t)
        for canonico, sins in SINONIMOS.items():
            if t == canonico or t in sins:
                resultado.append(canonico)
        # Partir tokens compuestos: 'transferelektra' → 'transfer' + 'elektra'
        for d in DOMINIO:
            if d != t and len(t) > len(d) and d in t:
                resultado.append(d)
    return list(dict.fromkeys(resultado))  # únicos, orden preservado


def _tokens_ponderados(nombre: str, info: dict) -> dict:
    """
    Tokens del test con peso: los del NOMBRE del flujo pesan 2 (señal
    fuerte de intención), los de docstring/pasos pesan 1 (contexto débil).
    Evita falsos positivos tipo 'envío de dinero' → CP de reportes solo
    porque un paso menciona 'transfers'.
    """
    pesos = {}
    for t in normalizar(nombre.replace("test_", "").replace("_", " ")):
        pesos[t] = 2
    for t in normalizar(info.get("doc", "")):
        pesos.setdefault(t, 1)
    for paso in info.get("pasos", []):
        limpio = paso.replace("click_", "").replace("fill_", "").replace("_", " ")
        for t in normalizar(limpio):
            pesos.setdefault(t, 1)
    return pesos


UMBRAL_EJECUCION = 2  # puntaje mínimo para ejecutar sin preguntar


# ── Memoria (aprendizaje por refuerzo simple) ────────────────────────────────

def cargar_memoria() -> dict:
    if MEMORIA_FILE.exists():
        try:
            return json.loads(MEMORIA_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def recordar_exito(instruccion: str, test: str) -> None:
    """Guarda que esta instrucción → este test funcionó. La próxima vez
    el match es directo, sin scoring."""
    memoria = cargar_memoria()
    clave = " ".join(normalizar(instruccion))
    entrada = memoria.get(clave, {"test": test, "exitos": 0})
    entrada["test"] = test
    entrada["exitos"] = entrada.get("exitos", 0) + 1
    entrada["ultima_vez"] = time.strftime("%Y-%m-%d %H:%M")
    memoria[clave] = entrada
    MEMORIA_FILE.write_text(
        json.dumps(memoria, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ── Interpretación ───────────────────────────────────────────────────────────

META_CAPACIDADES = {"sabes", "puedes", "capacidades", "lista", "listar",
                    "ayuda", "help", "comandos", "aprendiste"}


NUM_PALABRA = {"una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
               "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10}


def extraer_veces(instruccion: str) -> int:
    """
    Detecta cuántas veces ejecutar: 'corre 5 veces', 'ejecuta dos veces',
    'repite 10x'. Default 1 si no se menciona repetición.
    """
    t = instruccion.lower()
    m = re.search(r"(\d+)\s*(?:veces|vez|x|iteraciones|repet)", t)
    if m:
        return max(1, int(m.group(1)))
    # 'dos/2 envíos/transacciones/transferencias/transfers'
    m = re.search(r"\b(\d+)\s*(?:env[ií]os?|transacc\w+|transferencias?|transfers?)\b", t)
    if m:
        return max(1, int(m.group(1)))
    for palabra, n in NUM_PALABRA.items():
        if re.search(rf"\b{palabra}\b\s*(?:veces|vez|env[ií]os?|transacc\w+|transferencias?|transfers?)", t):
            return n
    if re.search(r"\b(?:dos veces|de nuevo|otra vez|repite|repetir)\b", t):
        return 2
    # Si menciona varios montos ('125 y 345'), itera tantas veces como montos
    montos = extraer_montos(instruccion)
    if len(montos) > 1:
        return len(montos)
    return 1


def extraer_duracion(instruccion: str) -> int:
    """Duración pedida en SEGUNDOS: 'por 2 minutos', 'durante 30 segundos',
    'por 1 hora'. 0 si no se menciona (entonces manda la cantidad de veces)."""
    t = normalizar_texto_simple(instruccion.lower())
    # Frases sin número: 'media hora' = 30 min · 'hora y media' = 90 min.
    if re.search(r"\bhora\s+y\s+media\b", t):
        return 5400
    if re.search(r"\bmedia\s+hora\b", t):
        return 1800
    m = re.search(r"(\d+)\s*(?:horas?|hrs?|\bh\b)", t)
    if m:
        return int(m.group(1)) * 3600
    m = re.search(r"(\d+)\s*(?:minutos?|mins?)", t)
    if m:
        return int(m.group(1)) * 60
    m = re.search(r"(\d+)\s*(?:segundos?|segs?)", t)
    if m:
        return int(m.group(1))
    return 0


def extraer_montos(instruccion: str) -> list:
    """
    Extrae TODOS los montos mencionados, en orden. Soporta '125 usd', '$345',
    'monto 158.25'. Para envíos múltiples con distinto monto por iteración.
      'uno por 125 usd y el siguiente por 345 usd' → ['125', '345']
    """
    t = instruccion
    montos = []
    for m in re.finditer(
        r"\$\s*([\d]+(?:[.,]\d+)?)"
        r"|\b([\d]+(?:[.,]\d+)?)\s*(?:usd|dolar(?:es)?|d[oó]lar(?:es)?)\b"
        r"|\bmonto\s*\$?\s*([\d]+(?:[.,]\d+)?)",
        t, re.IGNORECASE):
        val = (m.group(1) or m.group(2) or m.group(3))
        if val:
            montos.append(val.replace(",", "."))
    return montos


def extraer_overrides(instruccion: str) -> dict:
    """
    Extrae los datos que el usuario fija en lenguaje natural, para que el
    test los use y el resto sea Faker. Ejemplos que entiende:
      'cliente Juan Valdez Robledo'   → {'cliente': 'Juan Valdez Robledo'}
      'beneficiario Ana Perez Lopez'  → {'beneficiario': 'Ana Perez Lopez'}
      'monto 158.25' / '$158.25'      → {'monto': '158.25'}
    """
    t = instruccion.strip()
    ov = {}
    # Monto: 'monto 158.25', '$125', '125 usd', '125 dólares', 'enviaré 125 usd'
    m = re.search(
        r"\bmonto\s*\$?\s*([\d]+(?:[.,]\d+)?)"
        r"|\$\s*([\d]+(?:[.,]\d+)?)"
        r"|\b([\d]+(?:[.,]\d+)?)\s*(?:usd|dolar(?:es)?|d[oó]lar(?:es)?)\b",
        t, re.IGNORECASE)
    if m:
        ov["monto"] = (m.group(1) or m.group(2) or m.group(3)).replace(",", ".")
    # nombre del cliente/beneficiario: palabras hasta coma o siguiente keyword
    # Corte del nombre: en la coma o en la siguiente palabra clave (ES/EN),
    # incluida 'cancel...' para 'customer Genaro Garcia Luna cancela el envío'.
    corte = (r"(?:,|\bmonto\b|\bamount\b|\bbeneficiario\b|\bbeneficiary\b|\bbenef\b|"
             r"\bcliente\b|\bcustomer\b|\bcancel\w*\b|\btodos\b|\bdemas\b|"
             r"\bdemás\b|\ben\s+ingl|$)")
    def _limpiar_nombre(s: str) -> str:
        # Normaliza espacios y quita una conjunción colgante ('... Lopez y').
        s = " ".join(s.split())
        return re.sub(r"\s+(?:y|e|and)$", "", s, flags=re.IGNORECASE).strip()

    # Cliente / customer (acepta ambos idiomas)
    m = re.search(rf"\b(?:cliente|customer)\s+([A-Za-zÁÉÍÓÚÑáéíóúñ.\s]+?)\s*{corte}",
                  t, re.IGNORECASE)
    if m and m.group(1).strip():
        ov["cliente"] = _limpiar_nombre(m.group(1))
    # Beneficiario / beneficiary
    m = re.search(rf"\b(?:beneficiario|beneficiary|benef)\s+([A-Za-zÁÉÍÓÚÑáéíóúñ.\s]+?)\s*{corte}",
                  t, re.IGNORECASE)
    if m and m.group(1).strip():
        ov["beneficiario"] = _limpiar_nombre(m.group(1))
    return ov


def detectar_cancelacion(instruccion: str) -> bool:
    """
    ¿La instrucción pide cancelar la transacción? El flujo NO cancela por
    defecto; solo si el usuario lo indica explícitamente. Reconoce frases
    afirmativas ('cancela', 'y cancélala', 'cancelar la transacción') y respeta
    negaciones ('no canceles', 'sin cancelar', 'déjala').

    NOTA (fix): se normalizan tildes antes de matchear. Antes, 'cancélala'
    (con tilde en la é) NO matcheaba el patrón 'cancel...' (sin tilde) y la
    función devolvía False para el propio ejemplo que documenta — bug real
    detectado por dogfooding de las pruebas unitarias del agente.
    """
    t = " " + normalizar_texto_simple(instruccion.lower()) + " "
    # Negaciones explícitas → NO cancelar
    if re.search(r"\bno\s+cancel|sin\s+cancel|no\s+la\s+cancel|dejal[ao]|dejar\s+activ", t):
        return False
    return bool(re.search(r"\bcancel(a|ar|ala|arla|alo|e|en|acion)\b|cancela", t))


def _catalogo_payers() -> list:
    """
    Lee los pagadores de TODOS los módulos de país bajo src/pagadores/
    (src/pagadores/<pais>/payers.json). Cada payer queda anotado con
    "_modulo" = nombre de la carpeta de país, para saber a qué
    test_envio_normal_<pais>.py enrutarlo.
    """
    payers = []
    try:
        base = Path(__file__).parent.parent / "src" / "pagadores"
        for cfg_path in sorted(base.glob("*/payers.json")):
            try:
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            modulo = cfg_path.parent.name
            for p in data.get("payers", []):
                p = dict(p)
                p["_modulo"] = modulo
                payers.append(p)
    except Exception:
        pass
    return payers


def _modulos_con_envio() -> set:
    """Módulos con flujo de envío APRENDIDO (test_envio_normal_<modulo>.py).
    Los pagadores de módulos sin ese test (ej. Colombia/Uniteller, exclusivos de
    la etiqueta KRA-1125) NO se enrutan como envío normal — evita el error de
    'archivo no encontrado' y no mezcla el flujo de etiquetas."""
    base = Path(__file__).parent.parent / "src" / "tests"
    try:
        return {p.stem[len("test_envio_normal_"):]
                for p in base.glob("test_envio_normal_*.py")}
    except Exception:
        return {"mexico"}


def detectar_payer(instruccion: str):
    """¿La instrucción menciona un pagador del catálogo? Devuelve su 'code' o None.
    Reconoce por palabras del code/search (ELEKTRA, BANCOPPEL, SORIANA, BANORTE…)."""
    toks = set(normalizar(instruccion))
    for p in _catalogo_payers():
        kws = set()
        for s in (p.get("code", ""), p.get("search", "")):
            for w in re.split(r"[^a-z0-9]+", s.lower()):
                if len(w) >= 4:
                    kws.add(w)
        if toks & kws:
            return p.get("code")
    return None


def detectar_payers(instruccion: str) -> list:
    """TODOS los pagadores del catálogo mencionados (en orden de catálogo).
    Permite 'envío a Walmart, Aurrera y Bancomer' → los tres. Devuelve la
    lista de dicts {"code":..., "_modulo":...} (no solo el code) para poder
    enrutar cada uno a su test_envio_normal_<pais>.py."""
    toks = set(normalizar(instruccion))
    found = []
    vistos = set()
    for p in _catalogo_payers():
        if not p.get("activo"):
            continue
        kws = set()
        for s in (p.get("code", ""), p.get("search", "")):
            for w in re.split(r"[^a-z0-9]+", s.lower()):
                if len(w) >= 4:
                    kws.add(w)
        code = p.get("code")
        if toks & kws and code not in vistos:
            found.append(p)
            vistos.add(code)
    return found


def detectar_todos_payers(instruccion: str) -> bool:
    """¿La instrucción pide UN ENVÍO A CADA PAGADOR (todos los activos)?
    'todos los pagadores', 'cada uno de los payers', 'los 10 payers', 'a cada uno'."""
    t = instruccion.lower()
    return bool(re.search(
        r"\btodos\b|\bcada\b|cada uno|de cada|\b\d+\s*(?:payers|pagadores)\b|"
        r"todos\s+los\s+(?:payers|pagadores)", t))


def detectar_envio_normal(instruccion: str) -> bool:
    """¿Es una petición de ENVÍO normal? (enviar/transferir/mandar/remesa/depósito)."""
    t = instruccion.lower()
    return bool(re.search(r"env[ií]|transfer|manda|mande|remes|dep[oó]sit|paga", t))


def detectar_idioma(instruccion: str) -> str:
    """
    Idioma de la INTERFAZ pedido en la instrucción.
      'en' → si menciona inglés/english ('manda un envío a banorte en inglés').
      'es' → default (español); la app arranca en español y no se toca.
    """
    t = normalizar_texto_simple(instruccion.lower())
    if re.search(r"\bingles\b|\benglish\b", t):
        return "en"
    return "es"


def detectar_tipo_envio(instruccion: str) -> str:
    """
    Tipo de envío pedido en la instrucción: cash | deposit | home | mobile | atm.
    Default 'cash' (es el tab activo por defecto en Hermes).
      'por depósito'/'deposit'/'a cuenta'      → deposit
      'a domicilio'/'home'                      → home
      'móvil'/'mobile'/'wallet'/'billetera'     → mobile
      'atm'/'cajero'                            → atm
      'efectivo'/'cash' o nada                  → cash
    """
    t = normalizar_texto_simple(instruccion.lower())
    reglas = [
        ("atm",     r"\batm\b|\bcajero\b"),
        ("mobile",  r"\bmovil\b|\bmobile\b|\bwallet\b|\bbilletera\b|\bmonedero\b"),
        ("home",    r"\bdomicilio\b|\bhome\b|a\s+domicilio"),
        ("deposit", r"\bdeposito\b|\bdeposit\b|\ba\s+cuenta\b"),
        ("cash",    r"\befectivo\b|\bcash\b"),
    ]
    for tipo, pat in reglas:
        if re.search(pat, t):
            return tipo
    return "cash"


def _pais_en_texto(instruccion: str, paises: list):
    """Devuelve el nombre de país (del catálogo) mencionado en la instrucción, o None."""
    t = normalizar_texto_simple(instruccion.lower())
    for p in paises:
        pn = normalizar_texto_simple((p or "").lower())
        if pn and re.search(rf"\b{re.escape(pn)}\b", t):
            return p
    return None


def _validar_tipo_disponible(pais: str, tipo: str):
    """
    Guardrail de tipo: (ok, mensaje). Consulta el catálogo descubierto.
      - cash o país sin datos → no bloquea (best effort).
      - tipo disponible → ok.
      - tipo NO disponible → ok=False + mensaje con los tipos que SÍ hay.
    """
    if tipo == "cash":
        return True, None
    try:
        from src.pagadores import catalogo as _CAT
        tipos = _CAT.tipos_de_pais(pais)
        if not tipos:
            return True, None
        if tipos.get(tipo) is True:
            return True, None
        hay = [k for k, v in tipos.items() if v]
        return False, (f"🚫 El tipo '{tipo}' NO está disponible para {str(pais).upper()} "
                       f"según el catálogo. Disponibles: {', '.join(hay) or 'ninguno'}. "
                       f"Pedí uno de esos o corré 'analiza {str(pais).lower()}' para refrescar.")
    except Exception:
        return True, None


def _extraer_pais_destino(instruccion: str):
    """
    Palabra-objetivo tras 'a '/'para ' cuando NO se identificó un pagador conocido
    (heurístico para envíos a un PAÍS por nombre, ej. 'haz un envío a Pakistán').
    Excluye modificadores (todos/cada/pagador/domicilio/cajero/cuenta). None si no aplica.
    """
    t = normalizar_texto_simple(instruccion.lower())
    # 1ª palabra (>=4 letras) tras 'a'/'para', + opcional 2ª palabra que NO sea
    # preposición (para no arrastrar 'por/en/de...': 'a pakistan por wallet' → 'pakistan').
    m = re.search(r"\b(?:a|para)\s+([a-z]{4,}(?:\s+(?!por|en|de|del|con|y|la|el|los)[a-z]{3,})?)", t)
    if not m:
        return None
    cand = m.group(1).strip()
    primera = cand.split()[0]
    stop = {"todos", "cada", "pagador", "pagadores", "payers", "cuenta",
            "domicilio", "cajero", "efectivo", "deposito", "movil", "mobile", "wallet"}
    if primera in stop:
        return None
    return cand


def detectar_sanity(instruccion: str) -> bool:
    """¿La instrucción pide correr el SANITY GENERAL?"""
    t = normalizar_texto_simple(instruccion.lower())
    return bool(re.search(r"\bsanity\b|\bsanidad\b", t))


def detectar_cp(instruccion: str):
    """Número de CP mencionado: 'CP05', 'cp 5', 'caso 5' → 'CP05'. None si no hay."""
    cps = detectar_cps(instruccion)
    return cps[0] if cps else None


def detectar_cps(instruccion: str) -> list:
    """TODOS los CP mencionados, únicos y en orden: 'ejecuta los CP02 y CP03'
    → ['CP02', 'CP03']. Permite correr varios casos con un solo -k."""
    t = instruccion.lower()
    nums = re.findall(r"\bcp[\s_\-]*0*(\d{1,2})\b", t)
    if not nums:
        nums = re.findall(r"\bcaso[s]?\s*0*(\d{1,2})\b", t)
    out = []
    for n in nums:
        cp = f"CP{int(n):02d}"
        if cp not in out:
            out.append(cp)
    return out


def detectar_ambiente(instruccion: str) -> str:
    """Ambiente pedido: 'producción'/'prod' → 'prod'; default 'test'."""
    t = normalizar_texto_simple(instruccion.lower())
    return "prod" if re.search(r"\bprod\w*\b|\bproduccion\b", t) else "test"


def interpretar(instruccion: str, catalogo: dict) -> dict:
    """Instrucción en lenguaje natural → plan de acción."""
    tokens = set(normalizar(instruccion))
    veces = extraer_veces(instruccion)
    duracion_seg = extraer_duracion(instruccion)
    overrides = extraer_overrides(instruccion)
    montos = extraer_montos(instruccion)   # lista para envíos múltiples con distinto monto
    cancelar = detectar_cancelacion(instruccion)
    tl = instruccion.lower()

    # IDs de ticket Jira detectados en la instrucción (KRA-1125, MAXI-42, etc.)
    # Se usan tanto en el branch de etiqueta explícita como en el de disparo por ID.
    _TICKET_IDS = re.findall(r"\b([A-Za-z]{2,}[-_]+\d+)\b", instruccion)

    # ── SANITY GENERAL ─────────────────────────────────────────────────────────
    #   "ejecuta el sanity general"            → corre TODOS los CP del sanity.
    #   "ejecuta el CP05 del sanity general"   → corre SOLO ese CP (por -k).
    #   "...en producción"                     → ambiente prod (default: test).
    if detectar_sanity(instruccion):
        cps = detectar_cps(instruccion)
        ambiente = detectar_ambiente(instruccion)
        if len(cps) >= 2:
            # Varios CP en una instrucción: 'ejecuta los CP02 y CP03' → -k "CP02 or CP03"
            kexpr = " or ".join(cps)
            etiqueta = ", ".join(cps)
            return {
                "tipo": "ejecutar_test",
                "test": f"Sanity General — {etiqueta} ({ambiente})",
                "archivo": "src/tests/sanity_general",
                "kexpr": kexpr, "ambiente": ambiente, "casos": cps,
                "veces": veces, "overrides": {}, "montos": [], "cancelar": False,
                "razon": f"Sanity General: {etiqueta} en ambiente {ambiente.upper()}",
            }
        if len(cps) == 1:
            cp = cps[0]
            return {
                "tipo": "ejecutar_test",
                "test": f"Sanity General — {cp} ({ambiente})",
                "archivo": "src/tests/sanity_general",
                "kexpr": cp, "ambiente": ambiente, "casos": [cp],
                "veces": veces, "overrides": {}, "montos": [], "cancelar": False,
                "razon": f"Sanity General: {cp} en ambiente {ambiente.upper()}",
            }
        return {
            "tipo": "ejecutar_test",
            "test": f"Sanity General — TODOS ({ambiente})",
            "archivo": "src/tests/sanity_general",
            "kexpr": None, "marker": "sanity_general", "ambiente": ambiente,
            "casos": ["CP01", "CP02", "CP03", "CP04", "CP05", "CP06"],
            "veces": 1, "overrides": {}, "montos": [], "cancelar": False,
            "razon": f"Sanity General COMPLETO en ambiente {ambiente.upper()}",
        }

    # ── Consulta al CATÁLOGO (no abre navegador): "¿qué tipos hay para X?",
    #    "¿tiene depósito Bangladesh?" → responde desde el banco de datos. ──
    if re.search(r"\bque tipos\b|tipos?\s+de\s+env|\bdisponible|"
                 r"\btiene\b.*\b(cash|efectivo|dep[oó]sit\w*|home|domicilio|m[oó]vil|mobile|atm|cajero)\b", tl):
        try:
            from src.pagadores import catalogo as _CAT
            conocidos = _CAT.paises_conocidos()
            pais = _pais_en_texto(instruccion, conocidos)
            if pais:
                return {"tipo": "respuesta", "mensaje": "📚 " + _CAT.resumen_pais(pais)}
            if conocidos:
                return {"tipo": "respuesta", "mensaje":
                        "📚 Países en el catálogo: " + ", ".join(conocidos) +
                        ". Preguntá por uno (ej. 'qué tipos hay para MEXICO')."}
            return {"tipo": "respuesta", "mensaje":
                    "📚 El catálogo está vacío. Corré 'analiza los catálogos de méxico' para poblarlo."}
        except Exception:
            pass

    # ── ETIQUETAS de deploy: "corre la etiqueta <id>" → src/tests/etiquetas ──
    #    Dispara con la palabra "etiqueta" O con un ID de ticket Jira (KRA-1125,
    #    MAXI-42, etc.) en cualquier parte de la instrucción. Va ANTES del envío
    #    normal porque el ID suele contener tokens que dispararían ese flujo.
    if re.search(r"\betiquetas?\b", tl) or _TICKET_IDS:
        # Prioridad 1: usar IDs de ticket detectados (KRA-1125 → KRA_1125).
        ids = _TICKET_IDS
        if ids:
            kexpr = " and ".join(re.sub(r"[-_]+", "_", i.upper()) for i in ids)
        else:
            # Sin ID explícito: tokens filtrados con stopwords extendidas.
            stop_ext = {
                "etiqueta", "etiquetas", "corre", "correr", "ejecuta", "ejecutar",
                "lanza", "lanzar", "prueba", "test", "de", "la", "el", "los", "las",
                "por", "id", "que", "un", "una",
                "envio", "envios", "transfer", "transferencia", "transferencias",
                "mandar", "manda", "mande", "haz", "hace", "hacer", "dinero",
                "remesa", "remesas",
            }
            toks = [t for t in normalizar(instruccion) if t not in stop_ext]
            kexpr = " and ".join(toks) if toks else None

        # Filtrar caso individual: "positivo" → valido/positivo; "negativo" → negativo/rechazado/sin
        if kexpr:
            if re.search(r"\bpositiv\w*\b", tl):
                kexpr = f"({kexpr}) and (positivo or valido)"
            elif re.search(r"\bnegativ\w*\b", tl):
                kexpr = f"({kexpr}) and (negativo or rechazado or sin)"

        # Filtrar pagadores específicos: "solo nequi y bancolombia" → and (NEQUI2 or ...)
        # Solo aplica cuando la instrucción menciona explícitamente pagadores conocidos.
        if kexpr and re.search(r"\bsolo\b|\bpagadores?\b|\bpayers?\b", tl):
            payers_solicitados = detectar_payers(instruccion)
            if payers_solicitados:
                codes = " or ".join(p["code"] for p in payers_solicitados)
                kexpr = f"({kexpr}) and ({codes})"

        # CANTIDAD de ejecuciones: si el usuario NO pidió cantidad ni tiempo,
        # se ejecuta UNA sola (la etiqueta está parametrizada por pagador y si no
        # se limita corre TODOS). Con 'N veces' → N casos. Con tiempo → hasta
        # cumplirlo (una ejecución por vuelta).
        max_casos = None
        if duracion_seg:
            max_casos = 1            # una por vuelta; el ciclo lo repite por tiempo
        elif veces > 1:
            max_casos = veces
        else:
            max_casos = 1
        # Etiqueta de test más legible cuando hay repetición.
        _rep = (f" · {veces}x" if veces > 1 else
                (f" · {duracion_seg}s" if duracion_seg else ""))
        return {
            "tipo": "ejecutar_test",
            "test": f"etiqueta ({kexpr or 'todas'}){_rep}",
            "archivo": "src/tests/etiquetas",
            "kexpr": kexpr,
            "veces": 1 if duracion_seg else 1,   # la repetición la da max_casos/tiempo
            "duracion_seg": duracion_seg,
            "max_casos": max_casos,
            "overrides": overrides, "montos": montos,
            "cancelar": cancelar,
            "razon": f"etiqueta(s) de deploy: {kexpr or 'todas'}"
                     + (f" — {veces} ejecución(es)" if veces > 1 else " — 1 ejecución")
                     + (f", repitiendo durante {duracion_seg}s" if duracion_seg else ""),
        }

    # ── Análisis / descubrimiento de catálogo (corre el analizer) ──
    if re.search(r"\banaliz|\bdescubr|\breconoc|cat[aá]log", tl):
        return {"tipo": "ejecutar_test", "test": "test_analizar_mexico",
                "archivo": "src/tests/test_analizar_mexico.py", "kexpr": None,
                "veces": 1, "overrides": {}, "montos": [], "cancelar": False,
                "razon": "análisis/descubrimiento de catálogo (tipos, tarifas, pagadores)"}

    # ── Envío NORMAL a pagador(es) (módulo data-driven de src/pagadores/) ──
    # Resuelve "envío a BanCoppel", "manda a Walmart y Aurrera" o "haz envíos
    # a todos los pagadores": rota por el catálogo data-driven en vez de
    # matchear contra el catálogo de tests genérico (que no sabe de pagadores).
    if detectar_envio_normal(instruccion):
        _mods_envio = _modulos_con_envio()
        # Solo pagadores de módulos con flujo de envío APRENDIDO (excluye los
        # exclusivos de etiquetas, ej. Colombia/Uniteller de KRA-1125).
        todos_activos = [p for p in _catalogo_payers()
                         if p.get("activo") and p.get("_modulo") in _mods_envio]
        modulos_activos = sorted({p["_modulo"] for p in todos_activos})

        if detectar_todos_payers(instruccion):
            if len(modulos_activos) == 1:
                modulo = modulos_activos[0]
                return {
                    "tipo": "ejecutar_test",
                    "test": f"test_envio_normal ({len(todos_activos)} pagadores de {modulo} — TODOS los activos)",
                    "archivo": f"src/tests/test_envio_normal_{modulo}.py",
                    "kexpr": None, "tipo_envio": detectar_tipo_envio(instruccion),
                    "casos": [p["code"] for p in todos_activos], "duracion_seg": duracion_seg,
                    "veces": veces, "overrides": overrides, "montos": montos, "cancelar": cancelar,
                    "razon": f"envío normal a TODOS los pagadores activos de {modulo} "
                             f"({len(todos_activos)}: {', '.join(p['code'] for p in todos_activos)})",
                }
            if not modulos_activos:
                return {"tipo": "sugerencia", "mensaje":
                        "No hay pagadores activos en src/pagadores/*/payers.json todavía."}
            return {
                "tipo": "sugerencia",
                "mensaje": ("Hay pagadores activos en varios países (" +
                            ", ".join(modulos_activos) + "). Decime de cuál país "
                            "querés el envío a todos (ej. 'todos los pagadores de México')."),
            }

        payers = detectar_payers(instruccion)
        # Descartar pagadores sin flujo de envío aprendido (p.ej. exclusivos de
        # la etiqueta KRA-1125). Si el usuario pidió uno de esos, avisar.
        _payers_no_envio = [p for p in payers if p.get("_modulo") not in _mods_envio]
        payers = [p for p in payers if p.get("_modulo") in _mods_envio]
        if _payers_no_envio and not payers:
            nombres = ", ".join(p["code"] for p in _payers_no_envio)
            return {"tipo": "sugerencia", "mensaje":
                    f"El pagador {nombres} es exclusivo de una etiqueta (aún no hay "
                    f"flujo de envío aprendido para su país). Para probarlo, corré su "
                    f"etiqueta (p.ej. 'corre la etiqueta KRA-1125'). En envíos por "
                    f"pagador solo están los pagadores ya aprendidos."}
        if payers:
            # Guardrail de TIPO: si se pidió un tipo (wallet/deposit/...) que el
            # catálogo marca como NO disponible para ese país → abortar y avisar.
            _tipo = detectar_tipo_envio(instruccion)
            _pais = payers[0].get("country") or "MEXICO"
            _ok, _msg = _validar_tipo_disponible(_pais, _tipo)
            if not _ok:
                return {"tipo": "sugerencia", "mensaje": _msg}
            modulos = {p["_modulo"] for p in payers}
            if len(modulos) > 1:
                return {
                    "tipo": "sugerencia",
                    "mensaje": ("Esos pagadores son de países distintos (" +
                                ", ".join(sorted(modulos)) + "); todavía no puedo "
                                "correrlos en una sola instrucción. Pedime uno por país."),
                }
            modulo = modulos.pop()
            sufs = [p["code"].lower().replace(" ", "_") for p in payers]
            kexpr = " or ".join(sufs)
            if len(payers) == 1:
                test_name = f"test_envio_normal_{sufs[0]}"
                razon = f"envío normal a {payers[0]['code']} (solo ese pagador, {modulo})"
            else:
                test_name = f"test_envio_normal ({len(payers)} pagadores de {modulo}: " \
                            f"{', '.join(p['code'] for p in payers)})"
                razon = f"envío normal a {len(payers)} pagadores de {modulo}: " \
                        f"{', '.join(p['code'] for p in payers)}"
            return {
                "tipo": "ejecutar_test",
                "test": test_name,
                "archivo": f"src/tests/test_envio_normal_{modulo}.py",
                "kexpr": kexpr, "tipo_envio": _tipo,
                "casos": [p["code"] for p in payers], "duracion_seg": duracion_seg,
                "veces": veces, "overrides": overrides, "montos": montos, "cancelar": cancelar,
                "razon": razon,
            }
        # Sin pagador conocido: ¿es un envío a un PAÍS por nombre (ej. Pakistán)?
        pais_obj = _extraer_pais_destino(instruccion)
        if pais_obj:
            from src.pagadores import catalogo as _CAT
            conocidos = _CAT.paises_conocidos()
            match = _pais_en_texto(instruccion, conocidos)
            if not match:
                # País NO conocido → NO enviar; pedir analizar primero.
                return {"tipo": "sugerencia", "mensaje":
                        f"🌎 No tengo datos de '{pais_obj.upper()}' en el catálogo todavía. "
                        f"Corré primero: 'analiza {pais_obj}' — descubro sus tipos/pagadores/"
                        f"tarifas y los guardo; después reintentá el envío."}
            # País conocido → validar el tipo pedido contra el catálogo.
            _tipo = detectar_tipo_envio(instruccion)
            _ok, _msg = _validar_tipo_disponible(match, _tipo)
            if not _ok:
                return {"tipo": "sugerencia", "mensaje": _msg}
            # País conocido + tipo válido, pero el ENVÍO ejecutable hoy solo está
            # cableado para México (payers.json). Para otros países ya sabemos la
            # combinación, falta el sub-flujo de envío genérico + campos no-cash.
            hay = [k for k, v in _CAT.tipos_de_pais(match).items() if v]
            return {"tipo": "sugerencia", "mensaje":
                    f"✅ {match.upper()}: combinación válida (tipo '{_tipo}'; disponibles: "
                    f"{', '.join(hay)}). Pero el envío EJECUTABLE hoy está cableado solo para "
                    f"México; para {match.upper()} ya tengo el catálogo, falta el sub-flujo de "
                    f"envío genérico (y, si el tipo es no-cash, sus campos)."}
        # "envío"/"manda" sin pagador identificable → seguir al flujo genérico
        # (podría ser un flujo grabado normal, ej. 'corre el envío de reportes').

    # 0. Si hay API key de Anthropic, delegar en Claude (punto de extensión).
    #    Si Claude devuelve un plan de ejecución, le INYECTAMOS los datos que ya
    #    parseamos localmente (overrides, cancelar, veces) para no perderlos.
    if os.getenv("ANTHROPIC_API_KEY"):
        plan = interpretar_con_claude(instruccion, catalogo)
        if plan:
            if plan.get("tipo") == "ejecutar_test":
                plan.setdefault("overrides", overrides)
                plan.setdefault("cancelar", cancelar)
                plan.setdefault("veces", veces)
            return plan

    # 1. Meta: ¿qué sabes hacer?
    if tokens & META_CAPACIDADES:
        from agent.registry import resumen_capacidades
        return {"tipo": "respuesta", "mensaje": resumen_capacidades(catalogo)}

    # 2. Memoria: ¿ya aprendí esta instrucción?
    memoria = cargar_memoria()
    clave = " ".join(normalizar(instruccion))
    if clave in memoria:
        test = memoria[clave]["test"]
        info = catalogo["tests"].get(test)
        if info:
            return {
                "tipo": "ejecutar_test", "test": test,
                "archivo": info["archivo"], "veces": veces, "overrides": overrides,
                "montos": montos, "cancelar": cancelar,
                "razon": f"aprendido (usado {memoria[clave]['exitos']}x antes)",
            }

    # 3. Scoring ponderado contra los tests del catálogo
    mejores = []
    for nombre, info in catalogo.get("tests", {}).items():
        pesos = _tokens_ponderados(nombre, info)
        score = sum(pesos[t] for t in tokens if t in pesos)
        if score > 0:
            mejores.append((score, nombre, info))
    mejores.sort(key=lambda x: -x[0])

    if mejores and mejores[0][0] >= UMBRAL_EJECUCION:
        score, nombre, info = mejores[0]
        # Match claro: único o con ventaja sobre el segundo
        if len(mejores) == 1 or score > mejores[1][0]:
            return {
                "tipo": "ejecutar_test", "test": nombre,
                "archivo": info["archivo"], "veces": veces, "overrides": overrides,
                "montos": montos, "cancelar": cancelar,
                "razon": f"match por {score} término(s)",
            }
        # Empate → preguntar
        opciones = "\n".join(f"  • {n}" for _, n, _ in mejores[:4])
        return {
            "tipo": "sugerencia",
            "mensaje": ("Tu instrucción matchea varios flujos:\n" + opciones +
                        "\nDecime cuál con más detalle (ej. el nombre del CP)."),
        }

    # 4. ¿Matchea métodos POM sueltos? → orientar
    acciones = []
    for cls, pinfo in catalogo.get("pages", {}).items():
        for m in pinfo["metodos"]:
            m_tokens = set(normalizar(m["nombre"].replace("_", " ")))
            if tokens & m_tokens:
                acciones.append(f"{cls}.{m['nombre']}()")
    if acciones:
        return {
            "tipo": "sugerencia",
            "mensaje": ("No tengo un flujo completo para eso, pero conozco "
                        "estas acciones relacionadas:\n  " + "\n  ".join(acciones[:8]) +
                        "\nSi necesitás el flujo completo: grabalo con la extensión "
                        "y generalo con json_to_pom — lo aprendo automáticamente."),
        }

    # 5. Sin match
    return {
        "tipo": "sugerencia",
        "mensaje": ("No reconozco esa tarea todavía. Escribí 'capacidades' para "
                    "ver lo que sé hacer, o grabá el flujo con la extensión "
                    "Chrome y generalo con json_to_pom para enseñármelo."),
    }


# ── Punto de extensión: Claude API (Fase 2b) ────────────────────────────────

def interpretar_con_claude(instruccion: str, catalogo: dict):
    """
    Cuando exista ANTHROPIC_API_KEY: envía la instrucción + catálogo a Claude
    y recibe el plan en JSON. Mismo contrato que interpretar() — conectar
    aquí no requiere tocar nada más del agente.
    """
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return None  # SDK no instalado → seguir en modo offline

    try:
        # Modelo seleccionable (haiku/sonnet/opus) desde settings/.env
        try:
            from config.settings import CLAUDE_MODEL_ID as _MODEL
        except Exception:
            _MODEL = "claude-sonnet-4-5"
        client = anthropic.Anthropic()
        catalogo_json = json.dumps(
            {k: {n: {kk: vv for kk, vv in i.items() if kk != "usa_sesion"}
                 for n, i in v.items()} if k == "tests" else
             {n: [m["nombre"] for m in i["metodos"]] for n, i in v.items()}
             for k, v in catalogo.items()},
            ensure_ascii=False,
        )
        respuesta = client.messages.create(
            model=_MODEL,
            max_tokens=500,
            system=(
                "Eres el cerebro de un agente de automatización QA (Playwright) "
                "para HERMES2. Recibes una instrucción y un catálogo de "
                "capacidades. Responde SOLO JSON válido con uno de estos "
                "formatos: {\"tipo\":\"ejecutar_test\",\"test\":\"...\","
                "\"archivo\":\"...\",\"razon\":\"...\"} si la instrucción "
                "corresponde a un test del catálogo, o "
                "{\"tipo\":\"respuesta\",\"mensaje\":\"...\"} para preguntas, o "
                "{\"tipo\":\"sugerencia\",\"mensaje\":\"...\"} si no hay match."
            ),
            messages=[{
                "role": "user",
                "content": f"Catálogo:\n{catalogo_json}\n\nInstrucción: {instruccion}",
            }],
        )
        texto = respuesta.content[0].text.strip()
        m = re.search(r"\{.*\}", texto, re.DOTALL)
        return json.loads(m.group(0)) if m else None
    except Exception:
        return None  # cualquier fallo → fallback offline silencioso
