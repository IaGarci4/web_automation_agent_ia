"""
Catálogo País × Tipo de envío — banco de datos DESCUBIERTO en vivo.

Basado en el análisis del código fuente de Hermes2
(ver docs/big-c_Hermes2_CatalogoPaisPagadorTipoEnvio.md):

- Los 5 tipos de envío son FIJOS (tabs Cash/Deposit/Home/Mobile/ATM). Su
  DISPONIBILIDAD la decide el backend legacy (API "H1") por país + esquema
  (moneda) + ciudad; el frontend la refleja en el DOM habilitando o no cada tab
  con la clase CSS 'disabled-tab' (transfers-payers.component.ts::checkPayerByCountry).
- El catálogo real NO está en el código fuente: vive en ese sistema legacy. Por
  eso NO lo hardcodeamos. Lo DESCUBRIMOS leyendo el DOM en cada corrida
  (HmTransferelektraPage.tipos_envio_disponibles) y lo PERSISTIMOS aquí. Así el
  banco de datos crece y es siempre fiel a la app real — sin adivinar.

- App desplegada en test-hermes = proyecto Nx 'transfers_' (confirmado porque el
  DOM real usa los testids con sufijo de tipo, p. ej.
  'transfer-payers-money-info-amount-0-cash-amount-input' y
  'transfer-payers-0-tab-title-0', que según el análisis solo existen en 'transfers_').
"""
from __future__ import annotations

import json
import time
from pathlib import Path

# ── Tipos de envío (id/key/tab confirmados: money-info.props.ts + backend) ────
PAYMENT_TYPES = [
    {"key": "cash",    "id": 1, "tab_index": 0, "label_es": "Efectivo",  "label_en": "Cash"},
    {"key": "deposit", "id": 2, "tab_index": 1, "label_es": "Depósito",  "label_en": "Deposit"},
    {"key": "home",    "id": 3, "tab_index": 2, "label_es": "Domicilio", "label_en": "Home Delivery"},
    {"key": "mobile",  "id": 5, "tab_index": 3, "label_es": "Móvil",     "label_en": "Mobile Wallet"},
    {"key": "atm",     "id": 6, "tab_index": 4, "label_es": "ATM",       "label_en": "ATM"},
]
KEYS = [p["key"] for p in PAYMENT_TYPES]
TAB_INDEX = {p["key"]: p["tab_index"] for p in PAYMENT_TYPES}
ID_BY_KEY = {p["key"]: p["id"] for p in PAYMENT_TYPES}

# testid del tab por índice
TAB_TESTID = "transfer-payers-0-tab-title-{index}"

# Patrón de testid de los CAMPOS por tipo en 'transfers_' (desplegado). El
# segmento {type_key} ∈ cash|deposit|home|mobile|atm. Confirmado 1:1 solo para
# 'cash'; para los demás se usa como plantilla derivada (a validar contra el DOM
# real de cada tipo — ver docs/CONSULTA_CODIGO_SUBFORMULARIOS.md).
FIELD_TESTID_PATTERN = "transfer-payers-money-info-{field}-{n}-{type_key}-{suffix}"

# Sucursal: el backend solo soporta branches para Cash(1)/Deposit(2)/ATM(6);
# Home(3) y Mobile(5) NO manejan sucursal (BranchesService.METHOD_MAPPER).
TIPOS_CON_SUCURSAL = {"cash", "deposit", "atm"}

# Campos propios de cada sub-formulario (data-testid CONFIRMADOS por inspección
# del DOM real). Se van completando por tipo a medida que se confirman.
# 'deposit' confirmado; el resto (home/mobile/atm) pendiente (Consulta #2).
FIELDS_BY_TYPE = {
    "deposit": {
        "city_dropdown": "transfer-payers-money-info-city-0-deposit-dropdown-input",
        "fee_type_dropdown": "transfer-payers-money-info-fee-type-0-deposit-dropdown-input",
        "amount_input": "transfer-payers-money-info-amount-0-deposit-amount-input",
        "payer_input": "transfer-payers-money-info-payer-0-deposit-input",
        "account_type_button": "transfer-payers-money-info-account-number-0-deposit-button",
        "account_type_op1_cheques": "transfer-payers-money-info-account-number-0-deposit-1-list-item",
        "account_type_op2_ahorros": "transfer-payers-money-info-account-number-0-deposit-2-list-item",
        "account_number_input": "transfer-payers-money-info-account-number-0-deposit-input",
        "account_number_len": [11, 16],
    },
    # home / mobile / atm: pendientes (mismos campos con su segmento de tipo).
}

_CATALOGO = Path(__file__).parent / "catalogo_disponibilidad.json"


def cargar() -> dict:
    """Lee el banco de datos persistido (o uno vacío si no existe)."""
    if _CATALOGO.exists():
        try:
            return json.loads(_CATALOGO.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "_doc": ("Disponibilidad País × Tipo de envío DESCUBIERTA en vivo desde el DOM "
                 "de Hermes2 (clase 'disabled-tab'). Crece con cada corrida."),
        "por_pais": {},
    }


def registrar_disponibilidad(pais: str, disponibles: dict, pagador: str = None) -> Path:
    """
    Fusiona lo observado en el catálogo. `disponibles` = {key: bool|None} tal como
    lo devuelve tipos_envio_disponibles(). Acumula con OR: si un tipo estuvo
    disponible alguna vez para ese país, queda en True. Si se pasa `pagador`,
    guarda además la foto puntual observada con ese pagador.
    """
    data = cargar()
    pais = (pais or "?").strip().upper()
    nodo = data["por_pais"].setdefault(pais, {"tipos": {}, "pagadores": {}})
    for k, v in (disponibles or {}).items():
        if v is None:
            continue
        nodo["tipos"][k] = bool(nodo["tipos"].get(k)) or bool(v)
    if pagador:
        nodo["pagadores"][pagador.strip().upper()] = {
            k: v for k, v in (disponibles or {}).items() if v is not None
        }
    data["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        _CATALOGO.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return _CATALOGO


def registrar_detalle(pais: str, tipo_key: str, fee_types=None, payers=None) -> Path:
    """
    Guarda el DETALLE descubierto de un tipo para un país: lista de tarifas
    (fee_types) y de pagadores (payers). Acumula sin duplicar. Marca también si
    ese tipo maneja sucursal (según el backend: solo cash/deposit/atm).
    """
    data = cargar()
    pais = (pais or "?").strip().upper()
    nodo = data["por_pais"].setdefault(pais, {"tipos": {}, "pagadores": {}})
    det = nodo.setdefault("detalle", {}).setdefault(tipo_key, {})
    if fee_types:
        det["fee_types"] = sorted(set((det.get("fee_types") or []) + list(fee_types)))
    if payers:
        det["payers"] = sorted(set((det.get("payers") or []) + list(payers)))
    det["usa_sucursal"] = tipo_key in TIPOS_CON_SUCURSAL
    data["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        _CATALOGO.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return _CATALOGO


def tipos_de_pais(pais: str) -> dict:
    """Tipos conocidos como disponibles para un país (según lo descubierto)."""
    data = cargar()
    return data.get("por_pais", {}).get((pais or "?").strip().upper(), {}).get("tipos", {})


def paises_conocidos() -> list:
    """Lista de países ya presentes en el banco de datos."""
    return sorted(cargar().get("por_pais", {}).keys())


def detalle_pais(pais: str) -> dict:
    """Detalle completo (tipos + detalle por tipo) de un país."""
    return cargar().get("por_pais", {}).get((pais or "?").strip().upper(), {})


def resumen_pais(pais: str) -> str:
    """Texto legible: qué tipos hay/no hay para un país (para el agente)."""
    tipos = tipos_de_pais(pais)
    if not tipos:
        return (f"Todavía no tengo datos de '{pais}'. Corré un envío a ese país una vez "
                f"y quedará registrado en el catálogo.")
    hay = [k for k, v in tipos.items() if v]
    no = [k for k, v in tipos.items() if not v]
    return (f"{pais.upper()} → disponibles: {', '.join(hay) or 'ninguno'}"
            + (f" · no disponibles: {', '.join(no)}" if no else ""))
