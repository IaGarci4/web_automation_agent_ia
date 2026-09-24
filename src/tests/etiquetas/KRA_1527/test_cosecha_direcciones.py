"""
Cosechador de direcciones REALES POR ZIPCODE (v5) — endpoint `suggestions`.

## Objetivo

Que CADA zipcode que usa la automatización tenga ~10 direcciones reales VÁLIDAS,
para que al mandar una transacción con un zip al azar, el validador de Hermes
(PostGrid) nunca frene el flujo. No se busca volumen: se busca que cada zip del
pool esté cubierto.

## Cómo

El endpoint `POST /api/bff/address/suggestions` recibe `{"address":"..."}` como
TEXTO LIBRE. Si se anexa el zip —`"MAIN ST 94533"`— PostGrid devuelve calles de
ESE zip. Para cada zip objetivo se consultan varias calles, se filtran las
sugerencias cuyo `secondaryText` trae EXACTAMENTE ese zip, y se acumulan hasta
llegar al objetivo (por defecto 10; puede quedar en 8, 12, 15… no importa).

## Fuente de zips objetivo

`src/helpers/zips_us.py` (US_ZIPS) — los mismos que el flujo usa. Cada uno trae
su ciudad y estado, así el banco queda coherente (Hermes autocompleta ciudad/
estado desde el zip de todos modos).

## Salida (incremental, crece entre corridas; con dedup)

  · src/helpers/direcciones_us_bank.json   {zip:{city,state,streets:[…]}}
  · src/helpers/direcciones_us_verificado.py   DIRECCIONES_US_VERIFICADO=[…]
  · reports/evidence/KRA-1527/cosecha_direcciones.html   cobertura por zip
`direcciones_us.py` YA carga el JSON si existe → el flujo lo usa solo.

## Ejecutar
    Remove-Item Env:KRA1527_COSECHA_MAX -ErrorAction SilentlyContinue
    $env:KRA1527_COSECHA="1"; pytest src/tests/etiquetas/KRA_1527/test_cosecha_direcciones.py -s
    # direcciones objetivo por zip (default 10):  $env:KRA1527_COSECHA_POR_ZIP="12"
    # probar pocos zips:                          $env:KRA1527_COSECHA_MAX_ZIPS="5"
    # re-cosechar zips ya completos:              $env:KRA1527_COSECHA_FORZAR="1"
    # forzar modo UI:                             $env:KRA1527_COSECHA_UI="1"
"""

import asyncio
import datetime
import html
import json
import os
import random
import re
import time
from pathlib import Path

import pytest

from config import settings
from config.logger import get_logger
from src.helpers.zips_us import US_ZIPS
from src.pages.hm_transferelektra_page import HmTransferelektraPage

logger = get_logger("KRA-1527.cosecha")

RE_ZIP = re.compile(r"\b(\d{5})\b")
ADDR_INPUT = "transfer-customer-address-0-input"
SUG_URL = "https://test-hermes-api-containers.maxilabs.net/api/bff/address/suggestions"
BANK_JSON = Path(settings.PROJECT_ROOT) / "src" / "helpers" / "direcciones_us_bank.json"

# Calles comunes para sondear cada zip (se prueban hasta llenar el objetivo).
_NOMBRES = [
    "MAIN ST", "OAK ST", "PARK AVE", "MAPLE AVE", "WASHINGTON ST", "LAKE ST",
    "CEDAR ST", "PINE ST", "ELM ST", "2ND ST", "3RD ST", "BROADWAY", "HILL RD",
    "CHURCH ST", "MARKET ST", "CENTER ST", "1ST AVE", "5TH AVE", "MADISON AVE",
    "FRANKLIN ST", "LINCOLN AVE", "JACKSON ST", "HIGHLAND AVE", "COLLEGE AVE",
    "SPRING ST", "HIGH ST", "WALNUT ST", "RIVER RD", "SUNSET BLVD", "JEFFERSON ST",
]
# Números de casa para sondear (Hermes EXIGE formato «número + calle», ej.
# «4512 ROAD DRIVE ST»; una sugerencia sin número inicial la rechaza).
_NUMS = [100, 300, 500, 800, 1200]
REFRESH_TOKEN_SECS = 480

# La calle DEBE empezar con número. Se descarta cualquier mainText que no.
RE_NUM_START = re.compile(r"^\d")


def _activa() -> bool:
    return os.getenv("KRA1527_COSECHA", "0").strip().lower() in (
        "1", "true", "si", "sí", "yes")


def _zip_de(sec: str) -> str:
    m = RE_ZIP.search(" ".join((sec or "").split()))
    return m.group(1) if m else ""


def _ciudad_de(sec: str) -> str:
    sec = " ".join((sec or "").split())
    zp = _zip_de(sec)
    return (sec.replace(zp, "").strip(" ,").upper() if zp else sec.upper())


def _calle_valida(main: str) -> str:
    """Normaliza y valida el mainText: DEBE empezar con número. Devuelve la
    calle en MAYÚSCULAS o '' si no cumple el formato número+calle."""
    main = " ".join((main or "").split()).upper()
    return main if RE_NUM_START.match(main) else ""


def _cargar_banco() -> dict:
    """{zip: {'city','state','streets': set()}}"""
    banco = {}
    try:
        if BANK_JSON.is_file():
            crudo = json.loads(BANK_JSON.read_text(encoding="utf-8"))
            for zp, info in crudo.items():
                # Depurar: conservar SOLO calles con formato número+calle.
                limpias = {s for s in info.get("streets", [])
                           if _calle_valida(s)}
                banco[zp] = {"city": info.get("city", ""),
                             "state": info.get("state", ""),
                             "streets": limpias}
    except Exception as e:
        logger.warning("[Cosecha] No se pudo cargar banco previo: %s", str(e)[:120])
    return banco


def _guardar_banco(banco: dict):
    crudo = {zp: {"city": v["city"], "state": v["state"],
                  "streets": sorted(v["streets"])}
             for zp, v in sorted(banco.items())}
    BANK_JSON.write_text(json.dumps(crudo, ensure_ascii=False, indent=1),
                         encoding="utf-8")


@pytest.mark.cosecha
@pytest.mark.asyncio
async def test_cosecha_direcciones(logged_page):
    if not _activa():
        pytest.skip("Cosecha desactivada. Actívala con KRA1527_COSECHA=1.")

    flow = HmTransferelektraPage(logged_page)
    page = logged_page
    await flow.navigate()
    try:
        await flow.fill_transfer_customer_cellphone_0_cellphone_input("2105550123")
        await flow.fill_transfer_customer_name_0_input("QA")
        await flow.fill_transfer_customer_first_lastname_0_input("COSECHA")
        await flow.click_close_table()
    except Exception as e:
        logger.warning("[Cosecha] Identidad mínima: %s", str(e)[:120])

    objetivo = int(os.getenv("KRA1527_COSECHA_POR_ZIP", "10") or "10")
    forzar = os.getenv("KRA1527_COSECHA_FORZAR", "0").strip() in ("1", "true", "si")
    forzar_ui = os.getenv("KRA1527_COSECHA_UI", "0").strip() in ("1", "true", "si")

    # Zips objetivo = los del pool de la automatización (dedup, conservan estado).
    objetivos = []
    vistos = set()
    for zp, ciudad, estado in US_ZIPS:
        if zp not in vistos:
            vistos.add(zp)
            objetivos.append((zp, ciudad.upper(), estado.upper()))
    tope_zips = os.getenv("KRA1527_COSECHA_MAX_ZIPS", "").strip()
    if tope_zips.isdigit():
        objetivos = objetivos[:int(tope_zips)]

    banco = _cargar_banco()

    # ── Token / modo directo ─────────────────────────────────────────────────
    # El modo DIRECTO llama al endpoint con `fetch` DESDE la página (mismo origen
    # que la app), reusando el bearer — así pasa el CORS igual que la app.
    # page.request salía de otro contexto y la API lo rechazaba.
    contrato = {"url": SUG_URL, "auth": "", "extra": {}}

    async def _grab(req):
        if contrato["auth"] or "suggestions" not in req.url.lower():
            return
        if req.method.upper() != "POST":
            return
        try:
            h = await req.all_headers()
        except Exception:
            h = {}
        contrato["url"] = req.url
        for k, v in h.items():
            if k.lower() == "authorization":
                contrato["auth"] = v
            elif k.lower().startswith("x-"):
                contrato["extra"][k] = v

    def _on_req(req):
        try:
            asyncio.ensure_future(_grab(req))
        except Exception:
            pass

    async def _token_storage() -> str:
        """Busca un JWT (eyJ....eyJ....) en local/sessionStorage de la app."""
        try:
            return await page.evaluate(
                "() => { for (const s of [localStorage, sessionStorage]) {"
                " for (let i=0;i<s.length;i++){ const v=s.getItem(s.key(i))||'';"
                " const m=v.match(/eyJ[A-Za-z0-9_-]+\\.eyJ[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+/);"
                " if(m) return m[0]; } } return ''; }") or ""
        except Exception:
            return ""

    async def _refrescar_token():
        contrato["auth"] = ""
        contrato["extra"] = {}
        page.on("request", _on_req)
        try:
            await flow.sugerencias_direccion_por_red("100 MAIN ST")
            await flow.fill_transfer_customer_address_0_input("")
        except Exception:
            pass
        finally:
            try:
                page.remove_listener("request", _on_req)
            except Exception:
                pass
        if not contrato["auth"]:
            tok = await _token_storage()
            if tok:
                contrato["auth"] = "Bearer " + tok

    await _refrescar_token()
    url = contrato["url"]

    _JS_FETCH = """async (a) => {
        const [url, body, headers] = a;
        try {
            const r = await fetch(url, {method:'POST', credentials:'include',
                headers: Object.assign({'content-type':'application/json'}, headers),
                body: JSON.stringify(body)});
            if (!r.ok) return {ok:false, status:r.status};
            const j = await r.json();
            return {ok:true, data:(j && j.data) || []};
        } catch (e) { return {ok:false, err:String(e)}; }
    }"""

    async def _pedir(address: str):
        headers = dict(contrato["extra"])
        if contrato["auth"]:
            headers["authorization"] = contrato["auth"]
        try:
            res = await page.evaluate(_JS_FETCH, [url, {"address": address}, headers])
            if isinstance(res, dict) and res.get("ok"):
                return res.get("data") or []
            return res if isinstance(res, dict) else {"ok": False}
        except Exception:
            return {"ok": False}

    modo_directo = False
    if not forzar_ui:
        pr = await _pedir(f"100 MAIN ST {objetivos[0][0]}" if objetivos else "100 MAIN ST 10001")
        if isinstance(pr, list) and pr:
            modo_directo = True
        else:
            logger.warning("[Cosecha] Directo NO disponible (resp=%s) — voy a UI.", pr)

    async def _consulta(address: str) -> list:
        if modo_directo:
            r = await _pedir(address)
            return r if isinstance(r, list) else []
        try:
            data = await flow.sugerencias_direccion_por_red(address)
            await flow.fill_transfer_customer_address_0_input("")
            return data
        except Exception:
            return []

    logger.info("[Cosecha] Modo: %s · %d zips objetivo · meta %d/zip · auth=%s",
                "DIRECTO (API)" if modo_directo else "UI (tecleo)",
                len(objetivos), objetivo, "sí" if contrato["auth"] else "no")

    # ── Barrido por zip ───────────────────────────────────────────────────────
    inicio = time.monotonic()
    ultimo_refresh = inicio
    for idx, (zp, ciudad, estado) in enumerate(objetivos, 1):
        entry = banco.setdefault(zp, {"city": ciudad, "state": estado, "streets": set()})
        entry["state"] = entry.get("state") or estado
        if not forzar and len(entry["streets"]) >= objetivo:
            logger.info("[Cosecha %d/%d] %s ya tiene %d — se omite.", idx,
                        len(objetivos), zp, len(entry["streets"]))
            continue

        calles = _NOMBRES[:]
        random.shuffle(calles)
        for calle in calles:
            if len(entry["streets"]) >= objetivo:
                break
            if modo_directo and time.monotonic() - ultimo_refresh > REFRESH_TOKEN_SECS:
                await _refrescar_token()
                ultimo_refresh = time.monotonic()
            # Consultar SIEMPRE con número (formato número+calle que exige Hermes),
            # anexando el zip para sesgar a ese código postal.
            agrego = False
            for num in _NUMS:
                if len(entry["streets"]) >= objetivo:
                    break
                data = await _consulta(f"{num} {calle} {zp}")
                for it in data:
                    if _zip_de(it.get("secondaryText")) != zp:
                        continue
                    main = _calle_valida(it.get("mainText"))   # DEBE iniciar con número
                    if main and main not in entry["streets"]:
                        entry["streets"].add(main)
                        agrego = True
                    ciu2 = _ciudad_de(it.get("secondaryText"))
                    if ciu2:
                        entry["city"] = ciu2
                if agrego:
                    break   # esta calle ya aportó; pasar a la siguiente

        logger.info("[Cosecha %d/%d] %s (%s %s) → %d dir%s", idx, len(objetivos),
                    zp, entry["city"], estado, len(entry["streets"]),
                    "" if len(entry["streets"]) >= objetivo else "  ⚠ <meta")
        _guardar_banco(banco)

    _guardar_banco(banco)
    completos = sum(1 for v in banco.values() if len(v["streets"]) >= objetivo)
    total = sum(len(v["streets"]) for v in banco.values())
    flojos = [z for z, v in banco.items() if len(v["streets"]) < objetivo]
    logger.info("═" * 70)
    logger.info("[Cosecha] %d zips · %d con ≥%d dir · %d direcciones totales.",
                len(banco), completos, objetivo, total)
    if flojos:
        logger.warning("[Cosecha] Zips por debajo de la meta (%d): %s",
                       len(flojos), ", ".join(sorted(flojos)))
    cat = _escribir_catalogo(banco)
    rep = _escribir_reporte(banco, objetivo)
    logger.info("[Cosecha] Banco .py:  %s", cat)
    logger.info("[Cosecha] Banco JSON: %s", BANK_JSON)
    logger.info("[Cosecha] Reporte:    %s", rep)
    logger.info("═" * 70)

    assert total > 0, "El endpoint `suggestions` no devolvió NADA. Revisa la sesión."


def _flat(banco: dict) -> list:
    filas = []
    for zp in sorted(banco):
        v = banco[zp]
        for calle in sorted(v["streets"]):
            filas.append((zp, v["city"], v["state"], calle))
    return filas


def _escribir_catalogo(banco: dict) -> Path:
    destino = (Path(settings.PROJECT_ROOT) / "src" / "helpers"
               / "direcciones_us_verificado.py")
    filas = "\n".join(
        f'    ("{zp}", "{(ciudad or "").title()}", "{estado}", "{calle.title()}"),'
        for (zp, ciudad, estado, calle) in _flat(banco)
    ) or "    # (vacío)"
    contenido = (
        '"""\n'
        'Banco de direcciones VERIFICADO por el validador de Hermes (PostGrid),\n'
        'organizado POR ZIP: cada zip trae ~N calles reales que existen en él.\n\n'
        f'GENERADO por test_cosecha_direcciones.py el '
        f'{datetime.datetime.now():%Y-%m-%d %H:%M}.\n'
        'Acumulado incremental en direcciones_us_bank.json. Lo consume\n'
        'direcciones_us.py automáticamente si el JSON existe.\n'
        '"""\n\n'
        'DIRECCIONES_US_VERIFICADO = [\n'
        f'{filas}\n'
        ']\n'
    )
    destino.write_text(contenido, encoding="utf-8")
    return destino


def _escribir_reporte(banco: dict, objetivo: int) -> Path:
    filas = ""
    for zp in sorted(banco):
        v = banco[zp]
        n = len(v["streets"])
        color = "#1a7f37" if n >= objetivo else "#b42318"
        ejemplos = ", ".join(sorted(v["streets"])[:8])
        filas += (f'<tr><td><b>{html.escape(zp)}</b></td>'
                  f'<td>{html.escape(v["city"].title())} {html.escape(v["state"])}</td>'
                  f'<td style="color:{color};font-weight:bold">{n}</td>'
                  f'<td>{html.escape(ejemplos)}</td></tr>')
    total = sum(len(v["streets"]) for v in banco.values())
    completos = sum(1 for v in banco.values() if len(v["streets"]) >= objetivo)
    doc = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Cosecha por ZIP — KRA-1527</title>
<style>
 body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#1b1b1b}}
 h1{{color:#2E75B6}} table{{border-collapse:collapse;width:100%;margin:10px 0}}
 th,td{{border:1px solid #ddd;padding:6px 9px;font-size:13px;text-align:left;vertical-align:top}}
 th{{background:#2E75B6;color:#fff}} tr:nth-child(even){{background:#f6f9fc}}
 .kpi b{{font-size:22px}}
</style></head><body>
<h1>🗺️ Direcciones reales por ZIP — KRA-1527</h1>
<p>Generado {datetime.datetime.now():%Y-%m-%d %H:%M} · fuente: validador de Hermes (PostGrid).</p>
<p class="kpi"><b>{len(banco)}</b> zips · <b>{completos}</b> con ≥{objetivo} dir · <b>{total}</b> direcciones.</p>
<table><thead><tr><th>ZIP</th><th>Ciudad/Estado</th><th># dir.</th><th>Ejemplos</th></tr></thead>
<tbody>{filas or '<tr><td colspan=4>—</td></tr>'}</tbody></table>
</body></html>"""
    ruta = settings.EVIDENCE_DIR / "KRA-1527" / "cosecha_direcciones.html"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(doc, encoding="utf-8")
    return ruta
