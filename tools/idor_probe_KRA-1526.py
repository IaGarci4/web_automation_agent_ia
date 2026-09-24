#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
  IDOR PROBE  —  KRA-1526 / Autorización IdUser · IdAgent
================================================================================
Automatiza los pasos manuales de la prueba de autorización de Hermes 2:

  Manual (lo que hacías a mano)          Este script
  ─────────────────────────────         ─────────────────────────────
  1. Login en Hermes                     tú pegas UNA vez el curl que copiaste
  2. Búsqueda global del teléfono           del DevTools (con tu JWT vigente)
  3. Copiar el curl del endpoint         4. permuta IdUser / IdAgent
  4. Editar IdUser por otro              5. ejecuta cada variante con curl
  5. Pegar en WSL + Enter                6. verifica el HTTP status esperado
  6. Ver 403                             7. corre la REGRESIÓN automáticamente
  7. Regresión con IDs correctos → 200   8. imprime tabla PASS/FAIL + reporte HTML

Cómo funciona
─────────────
Le das el `curl` tal cual lo copias de las DevTools del navegador (botón derecho
sobre el request → Copy → Copy as cURL (bash)). El script:
  · localiza IdUser e IdAgent (en query string O en el body -d, ambos soportados),
  · genera las variantes de prueba,
  · ejecuta cada una con el `curl` del sistema (en WSL/Linux),
  · compara el HTTP status contra el esperado (mono-agente),
  · valida que SOLO la combinación correcta devuelva datos,
  · escribe un reporte HTML.

REGLA (confirmada por DEV — Eduardo López):
  · Mono-agente : se validan IdUser Y IdAgent  → cambiar cualquiera ⇒ 403

  ALCANCE DE ESTA PRUEBA: solo mono-agente. (El caso multi-agente, donde el
  IdAgent NO se valida y responde 200 por diseño, quedó fuera de alcance.)

USO (en WSL / Linux, requiere solo Python 3 y curl):

  # 1) Guarda el curl que copiaste del navegador en un archivo:
  #    (pega el curl completo, con tu JWT vigente, en curl.txt)

  # 2) Ejecuta: espera 403 al cambiar IdUser y al cambiar IdAgent, 200 en la regresión
  python3 idor_probe_KRA-1526.py --curl-file curl.txt

  # Opciones:
  #   --id-user-ajeno 99999   valor de IdUser ajeno a probar (default 99999)
  #   --id-agent-ajeno 9999   valor de IdAgent ajeno a probar (default 9999)
  #   --out reporte.html      ruta del reporte (default junto al script)
  #   --pegar                 en vez de --curl-file, pega el curl por STDIN

El token JWT expira a los ~20 min: si ves 401 en TODAS las variantes, el token
caducó — copia un curl nuevo y reintenta.
================================================================================
"""

import argparse, subprocess, re, sys, os, html, datetime, urllib.parse, json

# ── Extracción de IdUser / IdAgent del curl ───────────────────────────────────
# Se buscan en la URL (query string) y en el cuerpo -d/--data (JSON o form).
# Insensible a mayúsculas: IdUser, iduser, idUser… todos valen.
RE_PARAM_QS = lambda name: re.compile(r'(?i)([?&]' + name + r'=)([^&\'"\s]+)')
RE_PARAM_JSON = lambda name: re.compile(r'(?i)("' + name + r'"\s*:\s*)"?(\d+)"?')

def find_param(curl, name):
    """Devuelve ('qs'|'json', valor) o (None, None)."""
    m = RE_PARAM_QS(name).search(curl)
    if m:
        return 'qs', m.group(2)
    m = RE_PARAM_JSON(name).search(curl)
    if m:
        return 'json', m.group(2)
    return None, None

def replace_param(curl, name, new_value):
    """Reemplaza IdUser/IdAgent respetando dónde vive (query string o JSON body)."""
    loc, _ = find_param(curl, name)
    if loc == 'qs':
        return RE_PARAM_QS(name).sub(lambda mm: mm.group(1) + str(new_value), curl, count=1)
    if loc == 'json':
        return RE_PARAM_JSON(name).sub(lambda mm: mm.group(1) + str(new_value), curl, count=1)
    return curl

# ── Ejecución del curl ────────────────────────────────────────────────────────
def run_curl(curl_cmd):
    """
    Ejecuta el curl añadiendo -s -o /dev/null -w '%{http_code}' para capturar el
    status, y por separado el cuerpo (para verificar si hubo datos). Devuelve
    (http_status:int, body:str).
    """
    # status
    status_cmd = curl_cmd.strip()
    # quitar saltos de línea de continuación
    status_cmd = status_cmd.replace('\\\n', ' ')
    # status
    st = subprocess.run(status_cmd + " -s -o /dev/null -w '%{http_code}'",
                        shell=True, capture_output=True, text=True, timeout=60)
    try:
        code = int((st.stdout or '').strip() or 0)
    except ValueError:
        code = 0
    # body (para saber si vinieron datos)
    bd = subprocess.run(status_cmd + " -s",
                        shell=True, capture_output=True, text=True, timeout=60)
    return code, (bd.stdout or '')[:2000]

def has_customers(body):
    """True si el body trae datos de clientes (indicador de fuga/acceso)."""
    try:
        j = json.loads(body)
        data = j.get('data') or {}
        cust = data.get('customers') if isinstance(data, dict) else None
        if isinstance(cust, list):
            return len(cust) > 0
        # otros endpoints: cualquier arreglo no vacío en data
        return bool(data)
    except Exception:
        return ('customers' in body and 'idCustomer' in body)

# ── Definición de las variantes según el modo ─────────────────────────────────
def build_variants(iduser_ajeno, idagent_ajeno):
    """
    Cada variante: (nombre, cambios{param:valor}, status_esperado, debe_traer_datos)
    Alcance de esta prueba: SOLO mono-agente (se validan IdUser Y IdAgent).
    """
    return [
        ("Baseline: IdUser + IdAgent propios",  {},                          200, True),
        ("Negativo: IdUser ajeno",              {'IdUser': iduser_ajeno},    403, False),
        ("Negativo: IdAgent ajeno",             {'IdAgent': idagent_ajeno},  403, False),
        ("Regresión: restaurar IDs correctos",  {},                          200, True),
    ]

# ── Reporte HTML ──────────────────────────────────────────────────────────────
def build_html(rows, meta):
    n_pass = sum(1 for r in rows if r['veredicto'] == 'PASS')
    n_fail = sum(1 for r in rows if r['veredicto'] == 'FAIL')
    overall = 'PASS' if n_fail == 0 else 'FAIL'
    C = {'PASS': '#059669', 'FAIL': '#DC2626'}
    esc = lambda x: html.escape(str(x))
    trs = []
    for r in rows:
        c = C[r['veredicto']]
        trs.append(
            f"<tr><td>{esc(r['nombre'])}</td>"
            f"<td>{esc(r['cambios'])}</td>"
            f"<td style='text-align:center'>{esc(r['esperado'])}</td>"
            f"<td style='text-align:center'>{esc(r['obtenido'])}</td>"
            f"<td style='text-align:center'>{'sí' if r['datos'] else 'no'}</td>"
            f"<td style='text-align:center;color:{c};font-weight:700'>{r['veredicto']}</td></tr>")
    meta_rows = ''.join(f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>" for k, v in meta.items())
    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<title>IDOR Probe — KRA-1526</title><style>
body{{font-family:'Segoe UI',system-ui,sans-serif;background:#0f172a;color:#e2e8f0;margin:0}}
.wrap{{max-width:960px;margin:0 auto;padding:26px 20px 60px}}
h1{{font-size:21px;margin:0 0 4px}} .sub{{color:#94a3b8;font-size:13px;margin-bottom:20px}}
.hero{{text-align:center;padding:22px;border-radius:12px;margin-bottom:22px;background:#1e293b;border:1px solid #334155}}
.big{{font-size:38px;font-weight:800;color:{C[overall]}}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin-bottom:20px}}
td,th{{padding:8px 10px;border-bottom:1px solid #1e293b;text-align:left}}
th{{color:#94a3b8;font-weight:600}} .meta td:first-child{{color:#94a3b8;width:210px}}
code{{color:#fbbf24}}</style></head><body><div class="wrap">
<h1>🔐 IDOR Probe — KRA-1526</h1>
<div class="sub">Autorización IdUser / IdAgent · búsqueda global y endpoints relacionados</div>
<div class="hero"><div class="big">{overall}</div>
<div>{n_pass} PASS &nbsp;·&nbsp; {n_fail} FAIL &nbsp;·&nbsp; modo <b>{esc(meta.get('Modo',''))}</b></div></div>
<table class="meta">{meta_rows}</table>
<table><thead><tr><th>Variante</th><th>Cambio</th><th>HTTP esperado</th><th>HTTP obtenido</th><th>¿Datos?</th><th>Veredicto</th></tr></thead>
<tbody>{''.join(trs)}</tbody></table>
<p style="color:#64748b;font-size:12px">Regla: mono-agente valida IdUser+IdAgent (alcance de esta prueba: solo mono-agente).
Un veredicto FAIL significa que el status obtenido o la presencia de datos no coincide con lo esperado.
Si todas las variantes dan 401, el token JWT caducó (dura ~20 min): copia un curl nuevo.</p>
</div></body></html>"""

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Automatiza la prueba IDOR IdUser/IdAgent de KRA-1526")
    ap.add_argument('--curl-file', help="Archivo con el curl copiado del navegador")
    ap.add_argument('--pegar', action='store_true', help="Leer el curl desde STDIN")
    ap.add_argument('--modo', choices=['mono'], default='mono',
                    help="Alcance de la prueba: solo mono-agente (se conserva por compatibilidad)")
    ap.add_argument('--id-user-ajeno', default='99999')
    ap.add_argument('--id-agent-ajeno', default='9999')
    ap.add_argument('--out', default=None)
    args = ap.parse_args()

    if args.pegar:
        print("Pega el curl y termina con Ctrl-D:")
        curl = sys.stdin.read()
    elif args.curl_file:
        curl = open(args.curl_file, encoding='utf-8').read()
    else:
        print("ERROR: usa --curl-file <archivo> o --pegar"); sys.exit(2)

    curl = curl.strip()
    if not curl.lower().startswith('curl'):
        print("ERROR: el contenido no parece un comando curl."); sys.exit(2)

    loc_u, val_u = find_param(curl, 'IdUser')
    loc_a, val_a = find_param(curl, 'IdAgent')
    if not val_u or not val_a:
        print(f"ERROR: no encontré IdUser/IdAgent en el curl. IdUser={val_u} IdAgent={val_a}")
        print("       (se buscan en la URL y en el body -d, insensible a mayúsculas)")
        sys.exit(2)

    print("="*64)
    print("  IDOR PROBE — KRA-1526")
    print("="*64)
    print(f"  Modo: {args.modo}   IdUser propio={val_u} ({loc_u})   IdAgent propio={val_a} ({loc_a})")
    print("-"*64)

    variants = build_variants(args.id_user_ajeno, args.id_agent_ajeno)
    rows = []
    for nombre, cambios, esperado, debe_datos in variants:
        c = curl
        desc = []
        for p, v in cambios.items():
            c = replace_param(c, p, v)
            desc.append(f"{p}={v}")
        code, body = run_curl(c)
        datos = has_customers(body)
        # veredicto: status coincide Y presencia de datos coincide con lo esperado
        ok = (code == esperado) and (datos == debe_datos)
        veredicto = 'PASS' if ok else 'FAIL'
        rows.append({'nombre': nombre, 'cambios': ', '.join(desc) or '(propios)',
                     'esperado': esperado, 'obtenido': code, 'datos': datos, 'veredicto': veredicto})
        print(f"  [{veredicto}] {nombre}")
        print(f"         cambio={desc or '(propios)'}  esperado={esperado}  obtenido={code}  datos={'sí' if datos else 'no'}")

    print("-"*64)
    n_fail = sum(1 for r in rows if r['veredicto'] == 'FAIL')
    print(f"  RESULTADO: {'PASS' if n_fail==0 else 'FAIL'}  ({sum(1 for r in rows if r['veredicto']=='PASS')} PASS / {n_fail} FAIL)")

    out = args.out or os.path.join(os.path.dirname(os.path.abspath(args.curl_file or '.')) or '.',
                                   'reporte_idor_KRA-1526.html')
    meta = {
        'Fecha': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'Modo': args.modo,
        'IdUser propio': f"{val_u} (en {loc_u})",
        'IdAgent propio': f"{val_a} (en {loc_a})",
        'IdUser ajeno probado': args.id_user_ajeno,
        'IdAgent ajeno probado': args.id_agent_ajeno,
    }
    with open(out, 'w', encoding='utf-8') as f:
        f.write(build_html(rows, meta))
    print(f"  Reporte HTML: {out}")
    print("="*64)
    sys.exit(1 if n_fail else 0)

if __name__ == '__main__':
    main()
