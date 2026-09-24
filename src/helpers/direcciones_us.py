"""
Banco de DIRECCIONES REALES de EE. UU. — para el validador de direcciones de
Hermes (Money Transfer / campo `transfer-customer-address`).

## Por que existe
Hermes valida que la direccion exista y sea entregable (estilo USPS) y
autocompleta City/State desde el ZIP. Una direccion sintetica (Faker) se
rechaza. Este banco entrega, por cada ZIP de `zips_us.py`, una direccion que SI
existe y CASA con su ZIP/ciudad/estado. `datos.py` toma el ZIP del MISMO
domicilio (ver `_domicilio`), asi direccion y ZIP siempre calzan.

## Regla de seguridad (esta suite tambien corre en PRODUCCION)
Solo direcciones PUBLICAS / COMERCIALES (ayuntamientos, estadios, museos,
convention centers, estaciones, escuelas publicas, oficinas de correo):
  - Son reales y entregables -> pasan el validador.
  - Son registro publico -> NO exponen el domicilio de una persona real.
NUNCA agregues direcciones residenciales.

## Verificacion
Las 60 direcciones se verificaron una a una contra el geocodificador del
US Census Bureau (2026-09-18): cada una devuelve match y su ZIP coincide con el de
`zips_us.py`. Para re-certificar o agregar ZIPs usa:
    python tools/verificar_direcciones_us.py            # verifica todo (Census)
    python tools/verificar_direcciones_us.py --usps     # verifica con USPS Web Tools (USPS_USERID)
    python tools/verificar_direcciones_us.py --sugerir 30301   # sugiere direccion para un ZIP nuevo
El oraculo final que replica a Hermes es USPS; Census es el fallback gratis sin
credenciales. Verificador manual: https://tools.usps.com/zip-code-lookup.htm?byaddress

Cada entrada: (zip, ciudad, estado_abrev, direccion).
"""

import random

# (zip, ciudad, estado, direccion) - publicas/comerciales, entregables y
# verificadas (Census 2026-09-18). El comentario indica el landmark publico.
DIRECCIONES_US = [
    ("10001", "New York", "NY", "421 8th Ave"),                 # James A Farley Post Office / Moynihan Train Hall
    ("10016", "New York", "NY", "225 Madison Ave"),             # The Morgan Library & Museum
    ("11201", "Brooklyn", "NY", "209 Joralemon St"),            # Brooklyn Borough Hall
    ("14202", "Buffalo", "NY", "65 Niagara Sq"),                # Buffalo City Hall
    ("02108", "Boston", "MA", "45 School St"),                  # Old City Hall (Boston)
    ("19103", "Philadelphia", "PA", "271 N 21st St"),           # The Franklin Institute
    ("15222", "Pittsburgh", "PA", "1000 Fort Duquesne Blvd"),   # David L Lawrence Convention Center
    ("20001", "Washington", "DC", "801 Mt Vernon Pl NW"),       # Walter E Washington Convention Center
    ("21201", "Baltimore", "MD", "333 W Camden St"),            # Oriole Park at Camden Yards
    ("23219", "Richmond", "VA", "900 E Broad St"),              # Richmond City Hall
    ("27601", "Raleigh", "NC", "500 S Salisbury St"),           # Raleigh Convention Center
    ("28202", "Charlotte", "NC", "333 E Trade St"),             # Spectrum Center
    ("29201", "Columbia", "SC", "1100 Gervais St"),             # South Carolina State House
    ("30303", "Atlanta", "GA", "55 Trinity Ave SW"),            # Atlanta City Hall
    ("32202", "Jacksonville", "FL", "117 W Duval St"),          # Jacksonville City Hall
    ("32801", "Orlando", "FL", "400 S Orange Ave"),             # Orlando City Hall
    ("33130", "Miami", "FL", "73 W Flagler St"),                # Miami-Dade County Courthouse
    ("33602", "Tampa", "FL", "401 Channelside Dr"),             # Amalie Arena
    ("35203", "Birmingham", "AL", "710 20th St N"),             # Birmingham City Hall
    ("37203", "Nashville", "TN", "501 Broadway"),               # Bridgestone Arena
    ("38103", "Memphis", "TN", "125 N Main St"),                # Memphis City Hall
    ("40202", "Louisville", "KY", "800 W Main St"),             # Louisville Slugger Museum
    ("43215", "Columbus", "OH", "90 W Broad St"),               # Columbus City Hall
    ("45202", "Cincinnati", "OH", "801 Plum St"),               # Cincinnati City Hall
    ("44114", "Cleveland", "OH", "601 Lakeside Ave E"),         # Cleveland City Hall
    ("46204", "Indianapolis", "IN", "200 W Washington St"),     # Indiana Statehouse
    ("48226", "Detroit", "MI", "2 Woodward Ave"),               # Coleman A Young Municipal Center
    ("53202", "Milwaukee", "WI", "700 N Art Museum Dr"),        # Milwaukee Art Museum
    ("55401", "Minneapolis", "MN", "704 S 2nd St"),             # Mill City Museum
    ("60601", "Chicago", "IL", "130 E Randolph St"),            # Prudential Plaza
    ("60614", "Chicago", "IL", "2001 N Clark St"),              # Lincoln Park Zoo
    ("63101", "St. Louis", "MO", "815 Olive St"),               # Old Post Office (Custom House)
    ("64106", "Kansas City", "MO", "414 E 12th St"),            # Kansas City City Hall
    ("68102", "Omaha", "NE", "455 N 10th St"),                  # CHI Health Center Omaha
    ("70112", "New Orleans", "LA", "1500 Sugar Bowl Dr"),       # Caesars Superdome
    ("73102", "Oklahoma City", "OK", "100 W Reno Ave"),         # Paycom Center
    ("75201", "Dallas", "TX", "1500 Marilla St"),               # Dallas City Hall
    ("76102", "Fort Worth", "TX", "1201 Houston St"),           # Fort Worth Convention Center
    ("77002", "Houston", "TX", "901 Bagby St"),                 # Houston City Hall
    ("78205", "San Antonio", "TX", "300 Alamo Plaza"),          # The Alamo
    ("78701", "Austin", "TX", "1100 Congress Ave"),             # Texas State Capitol
    ("79901", "El Paso", "TX", "500 E San Antonio Ave"),        # El Paso County Courthouse
    ("80202", "Denver", "CO", "1701 Wynkoop St"),               # Union Station Denver
    ("83702", "Boise", "ID", "150 N Capitol Blvd"),             # Boise City Hall
    ("84101", "Salt Lake City", "UT", "100 S West Temple"),     # Salt Palace Convention Center
    ("85004", "Phoenix", "AZ", "401 E Jefferson St"),           # Chase Field
    ("85701", "Tucson", "AZ", "260 S Church Ave"),              # Tucson Convention Center
    ("87102", "Albuquerque", "NM", "401 2nd St NW"),            # Albuquerque Convention Center
    ("89101", "Las Vegas", "NV", "495 S Main St"),              # Las Vegas City Hall
    ("90001", "Los Angeles", "CA", "1610 E Florence Ave"),      # LA Public Library - Florence Branch
    ("90012", "Los Angeles", "CA", "200 N Spring St"),          # Los Angeles City Hall
    ("90210", "Beverly Hills", "CA", "455 N Rexford Dr"),       # Beverly Hills City Hall
    ("92101", "San Diego", "CA", "910 N Harbor Dr"),            # USS Midway Museum
    ("93701", "Fresno", "CA", "1101 E Belmont Ave"),            # Columbia Elementary School
    ("94102", "San Francisco", "CA", "1 Dr Carlton B Goodlett Pl"),# San Francisco City Hall
    ("95110", "San Jose", "CA", "65 Cahill St"),                # San Jose Diridon Station
    ("95814", "Sacramento", "CA", "1315 10th St"),              # California State Capitol
    ("97201", "Portland", "OR", "1825 SW Broadway"),            # Portland State University
    ("98101", "Seattle", "WA", "85 Pike St"),                   # Pike Place Market
    ("99201", "Spokane", "WA", "720 W Mallon Ave"),             # Spokane Arena
]

# Indice ZIP -> lista de domicilios (por si un ZIP tuviera varias direcciones).
DIRECCIONES_POR_ZIP = {}
for _z, _c, _s, _d in DIRECCIONES_US:
    DIRECCIONES_POR_ZIP.setdefault(_z, []).append(
        {"direccion": _d, "zip": _z, "ciudad": _c, "estado": _s})


# ── Banco VALIDADO / cosechado (opcional, tiene PRIORIDAD) ──────────────────
# Cada par (zip, calle) de estos JSON fue CONFIRMADO por el propio validador de
# Hermes EN ese zip, así que al teclearlo la sugerencia reaparece en el mismo
# zip → coincide exacto y NO hay deriva de ciudad/estado (a diferencia del
# catálogo curado a mano de arriba). Prioridad:
#   1) direcciones_us_validadas.json  (reproducidas/validadas, las más limpias)
#   2) direcciones_us_bank.json       (cosecha)
# El primero que exista y traiga datos reemplaza la lista curada.
import json as _json
import os as _os

for _archivo in ("direcciones_us_validadas.json", "direcciones_us_bank.json"):
    _BANK = _os.path.join(_os.path.dirname(__file__), _archivo)
    try:
        if not _os.path.isfile(_BANK):
            continue
        _raw = _json.load(open(_BANK, encoding="utf-8"))
        _cos = []
        for _zp, _info in _raw.items():
            _ciudad = (_info.get("city", "") or "").title()
            _estado = _info.get("state", "") or ""
            for _calle in _info.get("streets", []):
                _c = str(_calle).strip()
                # Hermes exige formato número+calle.
                if _c[:1].isdigit():
                    _cos.append((_zp, _ciudad, _estado, _c.title()))
        if _cos:
            DIRECCIONES_US = _cos
            break
    except Exception:
        continue


def candidatos(n: int = 10) -> list:
    """Hasta `n` domicilios REALES distintos, en orden aleatorio, para que el
    flujo REINTENTE contra el validador de Hermes.

    El validador (Google) a veces no ofrece sugerencia para una dirección con su
    ZIP (o solo ofrece calles homónimas de otras ciudades). Cuando eso pasa, la
    dirección no es culpa del flujo: se descarta y se prueba otra. Devolver una
    lista barajada permite ese reintento sin repetir el mismo lugar."""
    pool = DIRECCIONES_US[:]
    random.shuffle(pool)
    salida = []
    for zip_, ciudad, estado, direccion in pool[:max(1, n)]:
        salida.append({"direccion": direccion, "zip": zip_, "ciudad": ciudad,
                       "estado": estado})
    return salida


def domicilio_aleatorio() -> dict:
    """Un domicilio REAL coherente: direccion + zip + ciudad + estado del MISMO
    lugar. Hermes autocompleta ciudad/estado desde el zip y el validador exige
    que la direccion exista."""
    zip_, ciudad, estado, direccion = random.choice(DIRECCIONES_US)
    return {"direccion": direccion, "zip": zip_, "ciudad": ciudad,
            "estado": estado}


def domicilio_por_zip(zip_: str) -> dict:
    """Domicilio real para un ZIP concreto (util para pruebas deterministas).
    Lanza KeyError si el ZIP no esta en el banco."""
    return dict(random.choice(DIRECCIONES_POR_ZIP[zip_]))
