"""
Banco de códigos postales REALES de Estados Unidos.

Hermes hace autocompletado de City/State a partir del Zip Code del cliente, por
lo que el zip DEBE existir y ser entregable (un zip sintácticamente válido pero
inexistente da "Invalid Zip Code"). Aquí mantenemos una lista curada de ZIPs
reales repartidos por todo el país; `Datos` elige uno al azar.

Cada entrada es (zip, ciudad, estado). El test normalmente solo necesita el zip
—Hermes rellena ciudad/estado solo— pero se guarda la tripleta por si algún
flujo requiere validar el autocompletado.

Para ampliar el banco: agrega más tuplas reales. No inventes zips.
"""

import random

US_ZIPS = [
    ("10001", "New York", "NY"),
    ("10016", "New York", "NY"),
    ("11201", "Brooklyn", "NY"),
    ("90001", "Los Angeles", "CA"),
    ("90012", "Los Angeles", "CA"),
    ("90210", "Beverly Hills", "CA"),
    ("92101", "San Diego", "CA"),
    ("94102", "San Francisco", "CA"),
    ("95110", "San Jose", "CA"),
    ("95814", "Sacramento", "CA"),
    ("93701", "Fresno", "CA"),
    ("60601", "Chicago", "IL"),
    ("60614", "Chicago", "IL"),
    ("77002", "Houston", "TX"),
    ("78205", "San Antonio", "TX"),
    ("75201", "Dallas", "TX"),
    ("78701", "Austin", "TX"),
    ("76102", "Fort Worth", "TX"),
    ("79901", "El Paso", "TX"),
    ("85004", "Phoenix", "AZ"),
    ("85701", "Tucson", "AZ"),
    ("19103", "Philadelphia", "PA"),
    ("15222", "Pittsburgh", "PA"),
    ("33130", "Miami", "FL"),
    ("32801", "Orlando", "FL"),
    ("33602", "Tampa", "FL"),
    ("32202", "Jacksonville", "FL"),
    ("30303", "Atlanta", "GA"),
    ("43215", "Columbus", "OH"),
    ("45202", "Cincinnati", "OH"),
    ("44114", "Cleveland", "OH"),
    ("46204", "Indianapolis", "IN"),
    ("98101", "Seattle", "WA"),
    ("80202", "Denver", "CO"),
    ("02108", "Boston", "MA"),
    ("20001", "Washington", "DC"),
    ("37203", "Nashville", "TN"),
    ("38103", "Memphis", "TN"),
    ("97201", "Portland", "OR"),
    ("73102", "Oklahoma City", "OK"),
    ("89101", "Las Vegas", "NV"),
    ("21201", "Baltimore", "MD"),
    ("53202", "Milwaukee", "WI"),
    ("87102", "Albuquerque", "NM"),
    ("64106", "Kansas City", "MO"),
    ("63101", "St. Louis", "MO"),
    ("70112", "New Orleans", "LA"),
    ("55401", "Minneapolis", "MN"),
    ("48226", "Detroit", "MI"),
    ("84101", "Salt Lake City", "UT"),
    ("14202", "Buffalo", "NY"),
    ("23219", "Richmond", "VA"),
    ("27601", "Raleigh", "NC"),
    ("28202", "Charlotte", "NC"),
    ("29201", "Columbia", "SC"),
    ("35203", "Birmingham", "AL"),
    ("40202", "Louisville", "KY"),
    ("68102", "Omaha", "NE"),
    ("83702", "Boise", "ID"),
    ("99201", "Spokane", "WA"),
]


def zip_aleatorio() -> str:
    """Devuelve un código postal real de EE.UU. (solo el zip de 5 dígitos)."""
    return random.choice(US_ZIPS)[0]


# ── Estados de EE.UU.: abreviatura → NOMBRE COMPLETO ────────────────────────
# Los catálogos de HERMES (estado del beneficiario doméstico, estado del ATM)
# esperan el NOMBRE COMPLETO en MAYÚSCULAS ('GEORGIA', no 'GA'). US_ZIPS guarda
# la abreviatura; este mapa la convierte. Cubre los 50 estados + DC.
US_STATES = {
    "AL": "ALABAMA", "AK": "ALASKA", "AZ": "ARIZONA", "AR": "ARKANSAS",
    "CA": "CALIFORNIA", "CO": "COLORADO", "CT": "CONNECTICUT", "DE": "DELAWARE",
    "DC": "DISTRICT OF COLUMBIA", "FL": "FLORIDA", "GA": "GEORGIA", "HI": "HAWAII",
    "ID": "IDAHO", "IL": "ILLINOIS", "IN": "INDIANA", "IA": "IOWA", "KS": "KANSAS",
    "KY": "KENTUCKY", "LA": "LOUISIANA", "ME": "MAINE", "MD": "MARYLAND",
    "MA": "MASSACHUSETTS", "MI": "MICHIGAN", "MN": "MINNESOTA", "MS": "MISSISSIPPI",
    "MO": "MISSOURI", "MT": "MONTANA", "NE": "NEBRASKA", "NV": "NEVADA",
    "NH": "NEW HAMPSHIRE", "NJ": "NEW JERSEY", "NM": "NEW MEXICO", "NY": "NEW YORK",
    "NC": "NORTH CAROLINA", "ND": "NORTH DAKOTA", "OH": "OHIO", "OK": "OKLAHOMA",
    "OR": "OREGON", "PA": "PENNSYLVANIA", "RI": "RHODE ISLAND", "SC": "SOUTH CAROLINA",
    "SD": "SOUTH DAKOTA", "TN": "TENNESSEE", "TX": "TEXAS", "UT": "UTAH",
    "VT": "VERMONT", "VA": "VIRGINIA", "WA": "WASHINGTON", "WV": "WEST VIRGINIA",
    "WI": "WISCONSIN", "WY": "WYOMING",
}


def estado_aleatorio() -> str:
    """Nombre COMPLETO de un estado de EE.UU. al azar (ej. 'TEXAS')."""
    return random.choice(list(US_STATES.values()))


def ciudad_estado_aleatorio() -> tuple:
    """Devuelve (CIUDAD_REAL, ESTADO_NOMBRE_COMPLETO) tomados de un ZIP real del
    banco — así la ciudad es real y el estado coincide. Para envíos DOMÉSTICOS
    (beneficiario US + estado del ATM), que exigen el nombre completo del estado.

    Ej.: ('ATLANTA', 'GEORGIA'), ('DALLAS', 'TEXAS'), ('SEATTLE', 'WASHINGTON')."""
    _, ciudad, abrev = random.choice(US_ZIPS)
    return ciudad.upper(), US_STATES.get(abrev, abrev)
