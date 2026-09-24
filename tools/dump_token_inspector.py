#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
  DUMP TOKEN INSPECTOR  —  KRA-1527 / Pentesting 2026 (5.2.1)
================================================================================
Analiza archivos de volcado de memoria (.DMP) de los procesos del agente de
hardware de Hermes 2.0 y detecta si el token de autenticación (JWT) se
encuentra expuesto en texto plano.

Contexto de la corrección (KRA-1527):
  - Hermes2Agent.exe  recibe el mensaje del Front End y, al hacer el request,
    pasa el token ENCRIPTADO a Maxi.RulesOffice.Security.HttpProxy.exe.
  - HttpProxy.exe desencripta y ejecuta el request; regresa la respuesta a
    Hermes2Agent.exe. (HttpProxy solo está abierto durante el request.)
  - Objetivo de QA: en NINGÚN volcado de memoria debe aparecer el JWT completo
    en texto plano.

Un JWT tiene la forma:  eyJxxxxx.eyJxxxxx.firma   (header.payload.firma)
Tanto el header como el payload arrancan con "eyJ" (que es '{"' en base64url).

VEREDICTO:
  - FAIL  -> Se encontró al menos un JWT completo y decodificable (token expuesto).
  - WARN  -> Se hallaron fragmentos "eyJ..." que NO decodifican como JWT válido
             (posible dato cifrado / parcial — revisar manualmente).
  - PASS  -> No se encontró ningún token de autenticación en texto plano.

--------------------------------------------------------------------------------
USO (Windows CMD, PowerShell o WSL/Bash — requiere solo Python 3, sin librerías
externas):

  # Un archivo
  python dump_token_inspector.py "C:\\Users\\...\\Temp\\Hermes2Agent (2).DMP"

  # Varios archivos / carpeta completa (escanea todos los .DMP)
  python dump_token_inspector.py "C:\\Users\\...\\Temp"

  # Especificar salida del reporte y etiquetar la prueba
  python dump_token_inspector.py "C:\\...\\Temp" --out reporte.html \\
        --caso "CP01 - Imprimir recibo" --proceso Hermes2Agent

Genera un archivo HTML autocontenido con el resultado de la inspección.
================================================================================
"""

import argparse
import base64
import datetime as _dt
import html
import json
import mmap
import os
import re
import sys
import time

# ── Patrones ──────────────────────────────────────────────────────────────────
#
# La búsqueda es la misma que se hace a mano (`findstr /i /c:"eyJ"`), pero cada
# hallazgo se CLASIFICA. Eso es lo que separa un reporte útil de uno ruidoso:
# un volcado limpio tiene cientos de cadenas que empiezan por "eyJ" y ninguna es
# un token. Marcarlas todas como «revisar manualmente» equivale a no revisar
# nada.
#
# Lo que hay de verdad en un volcado del agente:
#
#   eyJhbGciOiJSUzI1NiI….eyJleHAiOjE3…. firma   → JWT de auth      → HALLAZGO
#   {"statusCode":200,"body":"eyJzdGF0dXMiOjIwMH0="}  → respuesta API  → benigno
#   eyJsb2dUeXBlIjoiQVBQIiwi…                    → log en base64    → benigno
#   "eyJ" (3 letras, suelto)                     → constante del      → benigno
#                                                   propio saneador
#
# Esa última merece una nota: el `SecureJsonProcessor` lleva "eyJ", "Bearer" y
# "TokenAppId" como literales porque son las cadenas que BUSCA para tapar. Su
# presencia no es una fuga: es la prueba de que el saneador está compilado ahí.
#
# ⚠️ Las cadenas del .NET viven en UTF-16 (`e\0y\0J\0…`), así que un escaneo
# solo-ASCII se saltaría cualquier token guardado como string gestionado. Se
# buscan las dos codificaciones.
_B64 = r'[A-Za-z0-9_\-+/=]'
RE_CAND_ASCII = re.compile(
    (r'eyJ' + _B64 + r'{6,}(?:\.' + _B64 + r'+){0,2}').encode())
# Misma expresión intercalando el byte nulo del UTF-16LE.
RE_CAND_U16 = re.compile(
    (r'e\x00y\x00J\x00(?:' + _B64 + r'\x00){6,}'
     r'(?:\.\x00(?:' + _B64 + r'\x00)+){0,2}').encode('latin-1'))

# ── Detectores COMPARTIDOS con src/helpers/ha_audit.py ──────────────────────
# La auditoría de tráfico importa estos tres nombres a propósito: volcado y
# comunicación deben juzgarse con el MISMO criterio, o el reporte se
# contradice a sí mismo. Cambiarles el nombre aquí rompe el import allá — ya
# pasó una vez.
#
# Sobre un cuerpo HTTP de unos kilobytes sí tiene sentido señalar un fragmento
# suelto (es raro y merece mirarse); sobre un volcado de 500 MB no, y por eso
# el escaneo de volcados usa los `RE_CAND_*` de arriba, que además clasifican.
RE_JWT_FULL = re.compile(
    rb'eyJ[A-Za-z0-9_\-]{5,}\.eyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}')
RE_JWT_FRAG = re.compile(rb'eyJ[A-Za-z0-9_\-]{10,}')

# Palabras clave de autenticación. Van en BYTES porque así las consume
# `ha_audit`, que trabaja sobre cuerpos crudos de las peticiones.
KEYWORDS = [b'Authorization', b'Bearer', b'access_token', b'Authorizer',
            b'refresh_token', b'id_token']
# Una sola pasada por el archivo, con alternancia: siete `count()` sobre un
# volcado de medio giga era siete recorridos completos.
RE_KEYWORDS = re.compile(
    b'|'.join(b'(' + k + b')' for k in KEYWORDS), re.I)

# Contexto que se guarda antes de un hallazgo: es lo que permite decir
# «apareció detrás de `Authorizer:`» en vez de solo «apareció».
RE_CTX_AUTH = re.compile(rb'(authorizer|authorization|bearer)\s*:?\s*$', re.I)

# Claims típicos que confirman que es un JWT de autenticación real
AUTH_CLAIMS = {'exp', 'iat', 'iss', 'sub', 'azp', 'preferred_username',
               'realm_access', 'session_state', 'aud', 'typ'}

# ── Huella de actividad del Hardware Agent ───────────────────────────────────
#
# Por qué existe: la auditoría HTTP mira el tráfico DESDE EL NAVEGADOR. El canal
# que Hermes usa para hablar con el agente local no siempre pasa por ahí, así
# que la auditoría puede ver «0 llamadas» aunque el agente haya trabajado. Eso
# hacía que el reporte dijera «no se registró ninguna llamada» justo en los
# casos donde la impresión SÍ ocurrió — y el analista se quedaba sin saber si
# la prueba había ejercitado el fix o no.
#
# La memoria del propio agente sí lo sabe: si procesó una petición, en el
# volcado quedan sus rutas de endpoint y sus componentes internos. Buscarlos
# convierte al .DMP en la prueba de que hubo comunicación, no solo en la prueba
# de que el token no está en claro.
MARCADORES_ACTIVIDAD = [
    (b'WS/Printer',          'Endpoint de impresión (WS/Printer)'),
    (b'WS/Configuration',    'Endpoint de configuración (WS/Configuration)'),
    (b'WS/Scanner',          'Endpoint de escáner (WS/Scanner)'),
    (b'SecureJsonProcessor', 'Procesador seguro de JSON (componente del fix)'),
    (b'PrintReceipt',        'Impresión de recibo'),
    (b'GetPrinters',         'Consulta de impresoras'),
]


def _u16(patron: bytes) -> bytes:
    """Versión UTF-16LE de un literal ASCII: las cadenas .NET viven así."""
    return b''.join(bytes([c]) + b'\x00' for c in patron)


def actividad_agente(data) -> dict:
    """
    Marcadores de trabajo del Hardware Agent presentes en el volcado.

    Devuelve {descripción: nº de apariciones}. Cuenta en ASCII y en UTF-16LE
    porque el agente es .NET y sus literales están en UTF-16 en memoria — una
    búsqueda solo ASCII devolvía cero y hacía parecer que no había actividad.
    """
    encontrados = {}
    for patron, descripcion in MARCADORES_ACTIVIDAD:
        n = 0
        for variante in (patron, _u16(patron)):
            desde = 0
            while True:
                i = data.find(variante, desde)
                if i < 0:
                    break
                n += 1
                desde = i + len(variante)
                if n > 5000:            # tope: interesa que haya, no cuántos
                    break
        if n:
            encontrados[descripcion] = n
    return encontrados


def _b64url_decode(seg: bytes):
    """Decodifica un segmento base64url con padding tolerante."""
    pad = (-len(seg)) % 4
    try:
        return base64.urlsafe_b64decode(seg + b'=' * pad)
    except Exception:
        return None


def decode_jwt(token_bytes: bytes):
    """
    Intenta decodificar un JWT. Devuelve dict con header, payload y validez,
    o None si no decodifica como JWT.
    """
    parts = token_bytes.split(b'.')
    if len(parts) != 3:
        return None
    header_raw = _b64url_decode(parts[0])
    payload_raw = _b64url_decode(parts[1])
    if not header_raw or not payload_raw:
        return None
    try:
        header = json.loads(header_raw)
        payload = json.loads(payload_raw)
    except Exception:
        return None
    if not isinstance(header, dict) or not isinstance(payload, dict):
        return None
    # ¿tiene pinta de JWT de autenticación?
    claim_hits = AUTH_CLAIMS.intersection(payload.keys())
    is_auth = ('alg' in header) and (len(claim_hits) >= 2)
    return {
        'header': header,
        'payload': payload,
        'is_auth': is_auth,
        'claim_hits': sorted(claim_hits),
        'length': len(token_bytes),
    }


def _fmt_exp(payload: dict):
    """Formatea claims de tiempo del JWT si existen."""
    out = {}
    for k in ('iat', 'exp', 'auth_time'):
        if k in payload:
            try:
                out[k] = _dt.datetime.utcfromtimestamp(int(payload[k])).strftime('%Y-%m-%d %H:%M:%S UTC')
            except Exception:
                out[k] = str(payload[k])
    return out


def _leer_con_espera(path: str, result: dict, intentos: int = 12,
                     espera_s: float = 5.0):
    """Lee el .DMP completo, esperando si todavía está bloqueado.

    Un volcado recién creado suele estar retenido unos segundos: el antivirus
    escanea el archivo nuevo (y aquí son cientos de MB), y mientras lo tiene
    abierto Windows devuelve «Permission denied» a cualquiera que intente
    leerlo. Ese error tumbaba la inspección justo después de haber hecho el
    volcado bien.

    Se reintenta hasta ~1 minuto y, si no se puede, se dice POR QUÉ."""
    ultimo = ""
    for intento in range(1, intentos + 1):
        try:
            # mmap en vez de read(): un volcado son cientos de MB y cargarlos
            # enteros en RAM no aporta nada — las expresiones regulares y los
            # cortes funcionan igual sobre el mapeo, y el sistema pagina solo
            # lo que se toca.
            f = open(path, 'rb')
            try:
                if os.path.getsize(path) == 0:
                    f.close()
                    result['error'] = "el archivo está vacío (0 bytes)"
                    return None
                return mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            finally:
                f.close()          # el mapeo sobrevive al descriptor
        except PermissionError as e:
            ultimo = f"{e} (archivo retenido por otro proceso)"
        except Exception as e:
            result['error'] = str(e)
            return None
        if intento < intentos:
            print(f"  … el volcado sigue bloqueado (intento {intento}/{intentos}), "
                  f"espero {espera_s:.0f}s")
            time.sleep(espera_s)
    result['error'] = (
        f"{ultimo}. Tras {intentos} intentos el archivo seguía sin poder "
        f"leerse. Suele ser el antivirus escaneando el volcado; si persiste, "
        f"añade la carpeta de volcados a las exclusiones de Windows Defender "
        f"o cambia DUMP_OUT_DIR a una carpeta excluida.")
    return None


def _contexto(data, inicio: int, largo: int = 48) -> str:
    """Texto imprimible que precede a un hallazgo (sin nulos del UTF-16).

    Sirve para distinguir `Authorizer: eyJ…` —un token puesto en una cabecera—
    de un `eyJ…` suelto dentro de un blob cualquiera. Es exactamente el dato que
    se mira a ojo cuando uno corre findstr y lee la línea."""
    ini = max(0, inicio - largo)
    try:
        crudo = bytes(data[ini:inicio]).replace(b'\x00', b'')
    except Exception:
        return ''
    return ''.join(chr(b) if 32 <= b < 127 else ' ' for b in crudo).strip()


# ── Vector de exposición: POR DÓNDE llegó el token a la memoria ─────────────
#
# Por qué importa: el hallazgo 5.2.1 del pentest señala el token de la cabecera
# `Authorizer` del canal Front End ↔ Hardware Agent, y el fix lo protege con
# `SecureJsonProcessor`. Si el inspector llama «5.2.1» a CUALQUIER JWT que
# encuentre, un hallazgo por otra vía se escala al sitio equivocado: desarrollo
# revisa la cabecera, la ve protegida, y cierra el ticket como no reproducible
# — con razón.
#
# Caso real (CP03, 2026-09-09): el token apareció detrás de `id_token_hint=`,
# es decir dentro de una URL de logout OIDC en el WebView que el agente abre
# para el SSO. Misma clase de exposición, vector distinto y fix distinto.
RE_VEC_CABECERA = re.compile(rb'(authorizer|authorization)\s*:', re.I)
RE_VEC_BEARER   = re.compile(rb'bearer\s+$', re.I)
RE_VEC_URL      = re.compile(rb'[?&][a-z0-9_\-]*(token|assertion|hint)[a-z0-9_\-]*=$', re.I)
RE_VEC_JSON     = re.compile(rb'"\s*[a-z0-9_\-]*(token|jwt)[a-z0-9_\-]*"\s*:\s*"?$', re.I)

VECTORES = {
    'cabecera': ("Cabecera Authorizer/Authorization",
                 "Es el vector del hallazgo 5.2.1 del pentest: el token del "
                 "canal Front End ↔ Hardware Agent."),
    'bearer':   ("Esquema Bearer",
                 "Token de autorización precedido por 'Bearer'. Mismo vector "
                 "que el hallazgo 5.2.1."),
    'url':      ("Parámetro de una URL",
                 "El token viaja en el query string (p. ej. id_token_hint= "
                 "del logout OIDC). NO es la cabecera que protege el fix: "
                 "suele ser el WebView del SSO dejando la URL en memoria. "
                 "Vector DISTINTO al 5.2.1 — repórtalo como tal."),
    'json':     ("Campo de un JSON",
                 "El token está en una propiedad JSON. Si el payload debería "
                 "pasar por SecureJsonProcessor, es una ruta no cubierta."),
    'suelto':   ("Sin contexto reconocible",
                 "La cadena está en memoria sin nada identificable delante: "
                 "puede ser un buffer reutilizado. Revisa el contexto crudo."),
}


def _vector(contexto: str) -> str:
    """Clasifica POR DÓNDE llegó el token, a partir de lo que le precede."""
    ctx = (contexto or "").encode('utf-8', 'replace')
    if RE_VEC_CABECERA.search(ctx):
        return 'cabecera'
    if RE_VEC_BEARER.search(ctx):
        return 'bearer'
    if RE_VEC_URL.search(ctx):
        return 'url'
    if RE_VEC_JSON.search(ctx):
        return 'json'
    return 'suelto'


def vida_del_token(dec: dict, momento_volcado: float) -> dict:
    """¿El token estaba VIVO cuando se tomó el volcado?

    Esta comparación decidió el análisis de CP03 y la hice a mano, cruzando el
    `iat` en UTC con la hora local del archivo. Hacerlo a mano es justo lo que
    no debe pasar: distingue un hallazgo real de basura acumulada en un proceso
    de larga vida, y nadie debería tener que calcular husos horarios para
    saberlo.

    Devuelve {'emitido_hace_min', 'vigente', 'resumen'} — o {} si no hay claims.
    """
    payload = (dec or {}).get('payload') or {}
    iat, exp = payload.get('iat'), payload.get('exp')
    if not isinstance(iat, (int, float)) and not isinstance(exp, (int, float)):
        return {}
    out = {}
    if isinstance(iat, (int, float)):
        out['emitido_hace_min'] = round((momento_volcado - iat) / 60, 1)
    if isinstance(exp, (int, float)):
        out['vigente'] = momento_volcado < exp
        out['expira_en_min'] = round((exp - momento_volcado) / 60, 1)

    partes = []
    if 'emitido_hace_min' in out:
        m = out['emitido_hace_min']
        partes.append(f"emitido {abs(m):.0f} min "
                      f"{'ANTES' if m >= 0 else 'DESPUÉS'} del volcado")
    if 'vigente' in out:
        partes.append("VIGENTE en ese momento" if out['vigente']
                      else "ya EXPIRADO en ese momento")
    out['resumen'] = " · ".join(partes)
    # El juicio, escrito una sola vez y en claro.
    if out.get('vigente'):
        out['juicio'] = ("Credencial VIVA en memoria: el hallazgo es real, no "
                         "residuo de una sesión anterior al fix.")
    elif 'vigente' in out:
        out['juicio'] = ("Token ya expirado al tomar el volcado: sigue siendo "
                         "una fuga, pero el riesgo es menor y puede ser "
                         "memoria acumulada. Confirma cuándo se reinició el "
                         "agente por última vez.")
    return out


def _clasificar(tok: bytes, contexto: str) -> dict:
    """Decide QUÉ es una cadena que empieza por 'eyJ'.

    Devuelve un dict con `tipo`:
      · 'jwt_auth' → JWT completo con claims de sesión  → HALLAZGO
      · 'jwt'      → 3 segmentos que decodifican, sin claims de auth
      · 'json'     → un solo segmento que decodifica a JSON (log, respuesta API)
      · 'opaco'    → no decodifica: dato cifrado, truncado o basura de memoria
    """
    dec = decode_jwt(tok)
    if dec:
        return {
            'tipo': 'jwt_auth' if dec['is_auth'] else 'jwt',
            'preview': tok[:40].decode('ascii', 'replace') + '...'
                       + tok[-12:].decode('ascii', 'replace'),
            'length': len(tok),
            'decoded': dec,
            'contexto': contexto,
            'en_cabecera': bool(RE_CTX_AUTH.search(contexto.encode())),
            'vector': _vector(contexto),
        }
    # Un solo segmento: puede ser un JSON en base64 (los logs y las respuestas
    # del agente viajan así). Si decodifica a JSON, sabemos qué es y NO es un
    # token.
    cuerpo = _b64url_decode(tok.split(b'.')[0])
    if cuerpo:
        try:
            obj = json.loads(cuerpo)
            if isinstance(obj, dict):
                return {'tipo': 'json', 'claves': sorted(obj.keys())[:6],
                        'length': len(tok), 'contexto': contexto}
        except Exception:
            pass
    return {'tipo': 'opaco', 'length': len(tok), 'contexto': contexto}


def explicada(tok: bytes) -> bool:
    """True si una cadena «eyJ…» se explica SIN ser un token de autenticación.

    Público a propósito: `ha_audit` lo usa para juzgar los cuerpos HTTP con el
    mismo criterio que se juzgan los volcados. Antes cada lado tenía su regla y
    el reporte se contradecía — la memoria salía limpia y el tráfico marcaba
    «revisar» por la misma cadena.

    Se consideran explicadas:
      · los JSON en base64 (respuestas de la API y líneas de log del agente);
      · las cadenas que no decodifican, que es justo la pinta que tiene un dato
        protegido — o sea, la señal de que el fix está haciendo su trabajo.
    """
    return _clasificar(tok, '')['tipo'] in ('json', 'opaco')


def scan_file(path: str):
    """Escanea un archivo .DMP y devuelve el resultado de la inspección."""
    result = {
        'path': path,
        'name': os.path.basename(path),
        'size': os.path.getsize(path) if os.path.exists(path) else 0,
        'full_jwts': [],       # JWTs completos y decodificables
        'auth_jwts': [],       # subset: JWTs de autenticación (los peligrosos)
        'benignos': {},        # tipo -> conteo (json / opaco), para explicarlos
        'candidatos': 0,       # total de cadenas 'eyJ…' vistas
        'fragments': 0,        # compat: cadenas no explicadas
        'keyword_hits': {},    # keyword -> conteo
        'actividad': {},       # huella de trabajo del agente (ver más abajo)
        'error': None,
    }
    data = _leer_con_espera(path, result)
    if data is None:
        # ⚠️ CLAVE: se marca ERROR, no se deja sin veredicto.
        # Antes esta rama volvía sin fijar `verdict`, y el resumen final
        # explotaba con KeyError → Python salía con código 1 → quien invocaba
        # al inspector leía ese 1 como «hay FAIL» y reportaba un token en claro
        # que nadie había visto. Un archivo ilegible es una comprobación NO
        # REALIZADA; nunca un hallazgo.
        result['verdict'] = 'ERROR'
        return result

    # ── Todas las cadenas 'eyJ…', en ASCII y en UTF-16 ──────────────────────
    vistos = set()
    benignos = {}
    for rx, u16 in ((RE_CAND_ASCII, False), (RE_CAND_U16, True)):
        for m in rx.finditer(data):
            tok = m.group(0).replace(b'\x00', b'') if u16 else m.group(0)
            tok = tok.rstrip(b'=')          # el padding sobra para clasificar
            if len(tok) < 10 or tok in vistos:
                continue
            vistos.add(tok)
            info = _clasificar(tok, _contexto(data, m.start()))
            tipo = info['tipo']
            if tipo == 'jwt_auth':
                result['full_jwts'].append(info)
                result['auth_jwts'].append(info)
            elif tipo == 'jwt':
                result['full_jwts'].append(info)
            else:
                benignos[tipo] = benignos.get(tipo, 0) + 1
    result['candidatos'] = len(vistos)
    result['benignos'] = benignos
    # `fragments` se mantiene por compatibilidad, pero ya NO dispara un WARN:
    # una cadena base64 que no decodifica es exactamente lo que uno espera
    # encontrar en un volcado de 500 MB, y tratarla como sospechosa convertía
    # todos los reportes en «revisión manual» — es decir, en nada.
    result['fragments'] = benignos.get('opaco', 0)

    # Keywords: UNA sola pasada con la alternancia, en vez de siete pasadas y
    # una copia en minúsculas del archivo entero (que en un volcado de 559 MB
    # duplicaba la memoria del proceso sin necesidad).
    conteo = {}
    for m in RE_KEYWORDS.finditer(data):
        idx = m.lastindex or 0
        if idx:
            k = KEYWORDS[idx - 1].decode('ascii', 'replace')
            conteo[k] = conteo.get(k, 0) + 1
    result['keyword_hits'] = conteo
    result['actividad'] = actividad_agente(data)

    # ── ¿El token estaba vivo cuando se tomó la foto? ───────────────────────
    # Se usa la mtime del .DMP como «momento del volcado»: es la hora real de
    # captura y evita depender del reloj de quien analiza (el inspector puede
    # correr días después, como pasó aquí).
    try:
        momento = os.path.getmtime(path)
    except OSError:
        momento = time.time()
    result['momento_volcado'] = momento
    for info in result['auth_jwts']:
        info['vida'] = vida_del_token(info.get('decoded'), momento)

    # ── Veredicto por archivo ───────────────────────────────────────────────
    # Solo un JWT de AUTENTICACIÓN, completo y decodificable, es un hallazgo.
    # Lo demás se explica y se deja pasar: el objetivo del ticket es que el
    # token no esté legible, no que no haya base64 en memoria.
    if result['auth_jwts']:
        result['verdict'] = 'FAIL'
    elif result['full_jwts']:
        result['verdict'] = 'WARN'
    else:
        result['verdict'] = 'PASS'
    try:
        data.close()               # libera el mapeo del volcado
    except Exception:
        pass
    return result


def gather_files(target: str):
    """Devuelve lista de .DMP a escanear a partir de un archivo o carpeta."""
    if os.path.isdir(target):
        files = []
        for root, _dirs, names in os.walk(target):
            for n in names:
                if n.lower().endswith('.dmp'):
                    files.append(os.path.join(root, n))
        return sorted(files)
    return [target]


# ── Reporte HTML ──────────────────────────────────────────────────────────────
def _human(n):
    for u in ('B', 'KB', 'MB', 'GB'):
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


def build_html(results, meta):
    n_fail = sum(1 for r in results if r.get('verdict') == 'FAIL')
    n_warn = sum(1 for r in results if r.get('verdict') == 'WARN')
    n_pass = sum(1 for r in results if r.get('verdict') == 'PASS')
    n_err = sum(1 for r in results if r.get('verdict') == 'ERROR' or r.get('error'))
    # Un volcado que no se pudo leer NO puede rendir un PASS: la conclusión
    # honesta es «no analizado». Antes el veredicto global salía PASS («la
    # corrección cumple») con cero archivos leídos, y el color verde invitaba
    # a creerlo.
    if n_fail:
        overall = 'FAIL'
    elif n_warn:
        overall = 'WARN'
    elif n_pass:
        overall = 'PASS'
    elif n_err:
        overall = 'ERROR'
    else:
        overall = 'PASS'

    colors = {'FAIL': '#DC2626', 'WARN': '#D97706', 'PASS': '#059669',
              'ERROR': '#64748b'}
    verdict_txt = {
        'FAIL': 'TOKEN EXPUESTO — la corrección NO cumple',
        'WARN': 'REVISIÓN MANUAL — se hallaron fragmentos no concluyentes',
        'PASS': 'SIN TOKEN EN TEXTO PLANO — la corrección cumple',
        'ERROR': 'NO ANALIZADO — no se pudo leer el volcado; no concluye nada',
    }

    def esc(x):
        return html.escape(str(x))

    cards = []
    for r in results:
        v = r.get('verdict', 'PASS')
        c = colors.get(v, colors['ERROR'])
        rows = []
        if r.get('error'):
            rows.append(f"<p class='err'>⚠ Error al leer: {esc(r['error'])}</p>")
        else:
            rows.append(f"<div class='meta'>Tamaño: <b>{_human(r['size'])}</b> · "
                         f"Cadenas «eyJ…» analizadas: <b>{r.get('candidatos', 0)}</b> · "
                         f"JWT de autenticación: "
                         f"<b style='color:{colors['FAIL'] if r['auth_jwts'] else colors['PASS']}'>"
                         f"{len(r['auth_jwts'])}</b></div>")
            if r['keyword_hits']:
                kw = ', '.join(f"{esc(k)} ({v2})" for k, v2 in r['keyword_hits'].items())
                rows.append(f"<div class='kw'>Palabras clave de autenticación en memoria: {kw} "
                            f"— presentes también cuando el token está protegido: "
                            f"son las cadenas que el propio saneador busca.</div>")
            # Detalle de JWTs de auth (los peligrosos)
            for j in r['auth_jwts']:
                dec = j['decoded']
                times = _fmt_exp(dec['payload']) if dec else {}
                who = ''
                if dec:
                    p = dec['payload']
                    who = esc(p.get('preferred_username') or p.get('name') or p.get('sub') or '')
                times_txt = ' · '.join(f"{k}: {esc(v)}" for k, v in times.items())
                ctx = j.get('contexto') or ''
                donde = ("<div class='claims'>Contexto: <span class='mono2'>"
                         f"{esc(ctx[-60:])}</span>"
                         + (" <b>— va detrás de una cabecera de autorización</b>"
                            if j.get('en_cabecera') else "")
                         + "</div>") if ctx else ""
                rows.append(
                    f"<div class='jwt fail'>"
                    f"<div class='jwt-h'>🔴 JWT de autenticación detectado ({j['length']} bytes)</div>"
                    f"<div class='mono'>{esc(j['preview'])}</div>"
                    + donde
                    + f"<div class='claims'>Usuario: <b>{who}</b>"
                    + (f" · claims: {', '.join(esc(x) for x in dec['claim_hits'])}" if dec else "")
                    + (f"<br>{times_txt}" if times_txt else "")
                    + "</div></div>"
                )
            # JWTs completos que NO son de auth
            non_auth = [j for j in r['full_jwts'] if j not in r['auth_jwts']]
            for j in non_auth:
                rows.append(
                    f"<div class='jwt warn'>"
                    f"<div class='jwt-h'>🟠 Cadena tipo-JWT completa (no confirmada como auth)</div>"
                    f"<div class='mono'>{esc(j['preview'])}</div></div>"
                )
            # Lo benigno se EXPLICA en una línea, no se convierte en alarma.
            # Un volcado de medio giga tiene cientos de base64 que no son
            # tokens; listarlas como «revisar manualmente» hacía que el reporte
            # dijera siempre lo mismo y no sirviera para decidir nada.
            ben = r.get('benignos') or {}
            if ben:
                detalle = []
                if ben.get('json'):
                    detalle.append(f"{ben['json']} son JSON en base64 "
                                   f"(logs y respuestas del agente, decodificados "
                                   f"y verificados: no llevan credenciales)")
                if ben.get('opaco'):
                    detalle.append(f"{ben['opaco']} no decodifican "
                                   f"(datos cifrados, cadenas truncadas o restos "
                                   f"de memoria)")
                rows.append("<div class='benigno'>ℹ️ Descartadas por análisis: "
                            + "; ".join(detalle) + ".</div>")
            if v == 'PASS':
                rows.append("<div class='ok'>✅ Ninguna de las cadenas encontradas es "
                            "un token de autenticación: el JWT no está legible en "
                            "la memoria de este proceso.</div>")

        cards.append(f"""
        <div class="card" style="border-left:6px solid {c}">
          <div class="card-head">
            <span class="badge" style="background:{c}">{v}</span>
            <span class="fname" title="{esc(r['path'])}">{esc(r['name'])}</span>
          </div>
          {''.join(rows)}
        </div>""")

    meta_rows = ''.join(f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>" for k, v in meta.items())

    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<title>Inspección de Token en Memoria — KRA-1527</title>
<style>
  * {{ box-sizing:border-box; }}
  body {{ font-family:'Segoe UI',system-ui,sans-serif; margin:0; background:#0f172a; color:#e2e8f0; }}
  .wrap {{ max-width:1000px; margin:0 auto; padding:28px 20px 60px; }}
  h1 {{ font-size:22px; margin:0 0 4px; }}
  .sub {{ color:#94a3b8; font-size:13px; margin-bottom:22px; }}
  .hero {{ text-align:center; padding:26px; border-radius:14px; margin-bottom:24px;
           background:linear-gradient(135deg,#1e293b,#0f172a); border:1px solid #334155; }}
  .hero .big {{ font-size:40px; font-weight:800; letter-spacing:1px; color:{colors[overall]}; }}
  .hero .lbl {{ font-size:15px; margin-top:6px; color:#cbd5e1; }}
  .counts {{ display:flex; gap:12px; justify-content:center; margin-top:18px; flex-wrap:wrap; }}
  .count {{ padding:10px 18px; border-radius:10px; font-weight:700; font-size:14px; }}
  table.meta-t {{ width:100%; border-collapse:collapse; margin-bottom:24px; font-size:13px; }}
  table.meta-t td {{ padding:6px 10px; border-bottom:1px solid #1e293b; }}
  table.meta-t td:first-child {{ color:#94a3b8; width:180px; }}
  .card {{ background:#1e293b; border-radius:10px; padding:16px 18px; margin-bottom:14px; }}
  .card-head {{ display:flex; align-items:center; gap:10px; margin-bottom:10px; }}
  .badge {{ color:#fff; font-weight:700; font-size:12px; padding:3px 10px; border-radius:6px; }}
  .fname {{ font-weight:600; font-size:15px; }}
  .meta {{ font-size:13px; color:#cbd5e1; margin-bottom:6px; }}
  .kw {{ font-size:12px; color:#fbbf24; margin-bottom:8px; }}
  .jwt {{ padding:10px 12px; border-radius:8px; margin:8px 0; font-size:12px; }}
  .jwt.fail {{ background:#3f1d1d; border:1px solid #dc2626; }}
  .jwt.warn {{ background:#3a2f13; border:1px solid #d97706; }}
  .jwt-h {{ font-weight:700; margin-bottom:6px; }}
  .mono {{ font-family:Consolas,monospace; background:#0f172a; padding:6px 8px; border-radius:5px;
           word-break:break-all; color:#f87171; }}
  .claims {{ margin-top:6px; color:#cbd5e1; }}
  .frag {{ background:#3a2f13; border:1px solid #d97706; padding:10px 12px; border-radius:8px; font-size:12px; }}
  .benigno {{ font-size:12px; color:#94a3b8; padding:6px 0; }}
  .mono2 {{ font-family:Consolas,monospace; color:#fbbf24; }}
  .ok {{ color:#34d399; font-size:13px; padding:6px 0; }}
  .err {{ color:#f87171; }}
  footer {{ margin-top:30px; text-align:center; color:#64748b; font-size:12px; }}
</style></head>
<body><div class="wrap">
  <h1>🔒 Inspección de Token en Memoria — KRA-1527</h1>
  <div class="sub">Pentesting 2026 · 5.2.1 Insecure Storage of Authentication Token in Agent Memory</div>

  <div class="hero">
    <div class="big">{overall}</div>
    <div class="lbl">{verdict_txt[overall]}</div>
    <div class="counts">
      <span class="count" style="background:{colors['FAIL']}22;color:{colors['FAIL']}">FAIL: {n_fail}</span>
      <span class="count" style="background:{colors['WARN']}22;color:{colors['WARN']}">WARN: {n_warn}</span>
      <span class="count" style="background:{colors['PASS']}22;color:{colors['PASS']}">PASS: {n_pass}</span>
      <span class="count" style="background:{colors['ERROR']}22;color:{colors['ERROR']}">NO ANALIZADOS: {n_err}</span>
    </div>
  </div>

  <table class="meta-t">{meta_rows}</table>

  {''.join(cards)}

  <footer>Generado por dump_token_inspector.py · {esc(meta.get('Fecha de análisis',''))}<br>
  Se buscan todas las cadenas «eyJ…» (ASCII y UTF-16) y se clasifica cada una.
  <b>FAIL solo si un JWT de autenticación decodifica completo</b>; los JSON en base64
  —logs y respuestas del agente— se descartan tras decodificarlos, no se reportan como dudas.</footer>
</div></body></html>"""


def main():
    # La consola de Windows usa cp1252 y revienta con cualquier carácter fuera
    # de ese juego. Un `print` decorativo llegó a tumbar el análisis ENTERO de
    # un volcado de 680 MB, y el caso reportó ERROR en vez de su veredicto real.
    # Nada de lo que se imprime vale una corrida perdida: se fuerza UTF-8 y, si
    # el terminal no puede, se reemplaza el carácter en vez de lanzar.
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="Inspector de token JWT en volcados de memoria (.DMP) — KRA-1527")
    ap.add_argument('target', help="Archivo .DMP o carpeta que los contiene")
    ap.add_argument('--out', default=None, help="Ruta del reporte HTML (default: junto al target)")
    ap.add_argument('--caso', default='(no especificado)', help="Etiqueta del caso de prueba en curso")
    ap.add_argument('--proceso', default='(auto)', help="Proceso analizado (Hermes2Agent / HttpProxy)")
    args = ap.parse_args()

    files = gather_files(args.target)
    if not files:
        print(f"No se encontraron archivos .DMP en: {args.target}")
        sys.exit(2)

    results = [scan_file(f) for f in files]

    meta = {
        'Fecha de análisis': _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'Caso de prueba': args.caso,
        'Proceso analizado': args.proceso,
        'Objetivo escaneado': args.target,
        'Archivos .DMP analizados': len(files),
    }

    out = args.out
    if not out:
        base = args.target if os.path.isdir(args.target) else os.path.dirname(args.target) or '.'
        out = os.path.join(base, 'reporte_inspeccion_token_KRA-1527.html')

    html_doc = build_html(results, meta)
    with open(out, 'w', encoding='utf-8') as f:
        f.write(html_doc)

    # Resumen por consola
    n_fail = sum(1 for r in results if r.get('verdict') == 'FAIL')
    n_warn = sum(1 for r in results if r.get('verdict') == 'WARN')
    n_pass = sum(1 for r in results if r.get('verdict') == 'PASS')
    n_err = sum(1 for r in results if r.get('verdict') == 'ERROR' or r.get('error'))
    print("=" * 64)
    print("  INSPECCIÓN DE TOKEN EN MEMORIA — KRA-1527")
    print("=" * 64)
    for r in results:
        if r.get('error'):
            print(f"  [ERR ] {r['name']}  ({_human(r['size'])}) — NO ANALIZADO: "
                  f"{r['error'][:160]}")
            continue
        ben = r.get('benignos') or {}
        print(f"  [{r.get('verdict', '?'):4}] {r['name']}  ({_human(r['size'])}) "
              f"— JWT de auth: {len(r['auth_jwts'])} · "
              f"cadenas 'eyJ' analizadas: {r.get('candidatos', 0)} "
              f"(JSON en base64: {ben.get('json', 0)}, sin decodificar: "
              f"{ben.get('opaco', 0)})")
        for desc, n in (r.get('actividad') or {}).items():
            print(f"         · actividad: {desc} ×{n}")
        # El VECTOR y la VIDA del token: es lo que decide cómo se escala.
        for info in r.get('auth_jwts') or []:
            vec = info.get('vector', 'suelto')
            titulo, explicacion = VECTORES.get(vec, VECTORES['suelto'])
            print(f"         >> VECTOR={vec} - {titulo}")
            print(f"           {explicacion}")
            vida = info.get('vida') or {}
            if vida.get('resumen'):
                print(f"           Token {vida['resumen']}.")
            if vida.get('juicio'):
                print(f"           {vida['juicio']}")
            ctx = (info.get('contexto') or "").strip()
            if ctx:
                print(f"           Contexto: …{ctx[-70:]}")
    print("-" * 64)
    # Línea legible por máquina, para que el helper pueda matizar el veredicto
    # sin volver a parsear el HTML.
    vectores = sorted({i.get('vector', 'suelto')
                       for r in results for i in (r.get('auth_jwts') or [])})
    if vectores:
        vivos = any((i.get('vida') or {}).get('vigente')
                    for r in results for i in (r.get('auth_jwts') or []))
        print(f"  VECTOR_HA={','.join(vectores)} VIVO={'si' if vivos else 'no'}")
    # Línea legible por máquina: el helper la lee para poder afirmar en el
    # reporte que el agente SÍ trabajó, aunque la auditoría HTTP del navegador
    # no viera nada. Sin esto, el reporte solo podía decir «0 llamadas».
    total_act = {}
    for r in results:
        for desc, n in (r.get('actividad') or {}).items():
            total_act[desc] = total_act.get(desc, 0) + n
    print(f"  ACTIVIDAD_HA={len(total_act)}"
          + (f" :: {'; '.join(f'{d} ×{n}' for d, n in total_act.items())}"
             if total_act else ""))
    print(f"  TOTAL: FAIL={n_fail}  WARN={n_warn}  PASS={n_pass}  ERROR={n_err}")
    print(f"  Reporte HTML: {out}")
    print("=" * 64)
    # Códigos de salida, pensados para que NADIE los malinterprete:
    #   0 = analizado y limpio          1 = analizado y HAY token en claro
    #   2 = no había .DMP que analizar  3 = había .DMP pero NO se pudo analizar
    # El 3 es el que faltaba: antes un archivo ilegible hacía explotar el
    # resumen, Python salía con 1, y ese 1 se leía como «token encontrado».
    if n_fail:
        sys.exit(1)
    if n_err and not (n_pass or n_warn):
        sys.exit(3)
    sys.exit(0)


if __name__ == '__main__':
    main()
