# -*- coding: utf-8 -*-
"""
Verificador / generador del banco de direcciones de EE.UU. (src/helpers/direcciones_us.py).

Sirve para que CUALQUIERA del equipo re-certifique el banco o agregue ZIPs
nuevos sin depender de Google Maps a mano.

Uso:
    python tools/verificar_direcciones_us.py
        Verifica TODAS las direcciones contra el geocodificador del US Census
        (gratis, sin credenciales). Marca OK / ZIP-DISTINTO / SIN-MATCH.
        Sale con codigo !=0 si alguna falla (util para CI).

    python tools/verificar_direcciones_us.py --usps
        Verifica contra USPS Web Tools (el mismo tipo de check que hace Hermes).
        Requiere la variable de entorno USPS_USERID (registro gratis en
        https://www.usps.com/business/web-tools-apis/).

    python tools/verificar_direcciones_us.py --sugerir 30301 [--sugerir 55402 ...]
        Sugiere una direccion PUBLICA real para un ZIP nuevo consultando
        OpenStreetMap (Overpass). Copia/pega la tupla en direcciones_us.py y
        vuelve a correr la verificacion.

Notas de red:
    Census / USPS / OSM son de acceso publico pero requieren SALIDA a internet.
    Si tu entorno bloquea el egress (proxy corporativo), corre este script desde
    una maquina/CI con salida libre. Solo stdlib: no instala nada.

Regla de seguridad: SOLO direcciones publicas/comerciales. Nunca residenciales.
"""
import argparse, json, os, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from src.helpers.direcciones_us import DIRECCIONES_US  # noqa: E402

UA = {"User-Agent": "MaxiAutomationAgent-verificador/1.0 (QA)"}
CENSUS = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
USPS = "https://secure.shippingapis.com/ShippingAPI.dll"
OVERPASS = "https://overpass-api.de/api/interpreter"


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


# ---------------- Census ----------------
def verifica_census(addr, city, st, zip_):
    q = urllib.parse.urlencode({
        "address": f"{addr}, {city}, {st} {zip_}",
        "benchmark": "Public_AR_Current", "format": "json"})
    try:
        data = json.loads(_get(f"{CENSUS}?{q}"))
    except Exception as e:
        return ("ERROR", str(e)[:80])
    m = data.get("result", {}).get("addressMatches", [])
    if not m:
        return ("SIN-MATCH", "")
    got = m[0].get("addressComponents", {}).get("zip", "")
    if got == zip_:
        return ("OK", m[0].get("matchedAddress", ""))
    return ("ZIP-DISTINTO", f"{got} :: {m[0].get('matchedAddress','')}")


# ---------------- USPS Web Tools ----------------
def verifica_usps(addr, city, st, zip_, userid):
    xml = (f'<AddressValidateRequest USERID="{userid}">'
           f'<Revision>1</Revision>'
           f'<Address ID="0"><Address1></Address1><Address2>{addr}</Address2>'
           f'<City>{city}</City><State>{st}</State>'
           f'<Zip5>{zip_}</Zip5><Zip4></Zip4></Address></AddressValidateRequest>')
    q = urllib.parse.urlencode({"API": "Verify", "XML": xml})
    try:
        resp = _get(f"{USPS}?{q}")
    except Exception as e:
        return ("ERROR", str(e)[:80])
    if "<Error>" in resp:
        import re
        d = re.search(r"<Description>(.*?)</Description>", resp)
        return ("SIN-MATCH", (d.group(1)[:80] if d else "USPS error"))
    import re
    z = re.search(r"<Zip5>(\d{5})</Zip5>", resp)
    got = z.group(1) if z else ""
    return ("OK", f"USPS Zip5={got}") if got == zip_ else ("ZIP-DISTINTO", got)


# ---------------- Sugerir (OSM Overpass) ----------------
def sugiere_osm(zip_):
    # Amenities publicas con direccion en ese ZIP.
    ql = (f'[out:json][timeout:25];'
          f'nwr["addr:postcode"="{zip_}"]["amenity"~"townhall|library|courthouse|'
          f'community_centre|arts_centre|theatre|university|college|post_office"]'
          f'["addr:housenumber"]["addr:street"];out tags 20;')
    try:
        data = json.loads(_get(f"{OVERPASS}?{urllib.parse.urlencode({'data': ql})}", 40))
    except Exception as e:
        return f"(no se pudo consultar OSM: {str(e)[:80]})"
    els = data.get("elements", [])
    if not els:
        return "(OSM sin resultados publicos para ese ZIP; prueba Google Maps a mano)"
    out = []
    for el in els[:8]:
        t = el.get("tags", {})
        out.append(f'    ("{zip_}", "{t.get("addr:city","?")}", "??", '
                   f'"{t.get("addr:housenumber","")} {t.get("addr:street","")}"),'
                   f'  # {t.get("name","?")} [{t.get("amenity","")}]')
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Verifica/genera el banco de direcciones US.")
    ap.add_argument("--usps", action="store_true", help="Verifica con USPS Web Tools (USPS_USERID).")
    ap.add_argument("--sugerir", action="append", default=[], metavar="ZIP",
                    help="Sugiere direccion publica para un ZIP nuevo (OSM).")
    ap.add_argument("--delay", type=float, default=0.4, help="Pausa entre consultas (s).")
    args = ap.parse_args()

    if args.sugerir:
        for z in args.sugerir:
            print(f"\n# Sugerencias para {z} (VERIFICA y respeta la regla publica/comercial):")
            print(sugiere_osm(z)); time.sleep(args.delay)
        return

    userid = os.environ.get("USPS_USERID", "")
    if args.usps and not userid:
        print("ERROR: define USPS_USERID para usar --usps.", file=sys.stderr); sys.exit(2)

    fuente = "USPS" if args.usps else "Census"
    print(f"Verificando {len(DIRECCIONES_US)} direcciones contra {fuente}...\n")
    fails = 0
    for zip_, city, st, addr in DIRECCIONES_US:
        if args.usps:
            estado, detalle = verifica_usps(addr, city, st, zip_, userid)
        else:
            estado, detalle = verifica_census(addr, city, st, zip_)
        if estado != "OK":
            fails += 1
        print(f"[{estado:12}] {zip_}  {addr}, {city}, {st}"
              + (f"   -> {detalle}" if detalle and estado != "OK" else ""))
        time.sleep(args.delay)

    print(f"\nResultado: {len(DIRECCIONES_US)-fails}/{len(DIRECCIONES_US)} OK, {fails} con problema.")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
