"""
Control negativo del inspector — la compuerta de la etiqueta.

## Qué responde

«¿Cómo sabes que tu detector detecta?» Es la primera pregunta de cualquiera
que audite esta evidencia, y sin respuesta ningún PASS de la suite es
defendible: un inspector roto diría *«sin token en claro»* en los siete
flujos, el reporte diría que el fix cumple, y nadie se enteraría. Un falso
negativo sobre un hallazgo de severidad Alta.

Se fabrica un archivo con un JWT de autenticación **plantado a propósito** y
se exige que `dump_token_inspector.py` lo encuentre (exit code 1).

## Por qué es una COMPUERTA y ya no un caso de prueba

Vivía como `CP06-ControlNegativo`, y estaba mal por dos motivos:

1. **No validaba el criterio del ticket.** No busca el token expuesto en la
   aplicación: prueba el instrumento. No figura en `qmetry_mapeo.json` porque
   no es un caso que el negocio haya pedido; ocupaba un número entre flujos
   reales sin serlo.
2. **Su fallo no detenía nada.** `pytest.ini` no lleva `-x`, así que un
   control negativo en rojo dejaba correr los demás casos igual, que podían
   seguir reportando PASS. La protección dependía de que alguien leyera el
   log — es decir, no era protección.

Como compuerta del preflight sí hace lo que aparentaba: si el inspector está
roto, la corrida se detiene en el segundo cero en vez de producir siete
aprobados que no valen nada.

## Coste

Un archivo de 4 KB y una llamada al inspector: ~0.5 s, sin navegador y sin
Hardware Agent. Se paga una vez por sesión.

Para saltarla —solo si estás depurando el propio inspector—:

    $env:KRA1527_SIN_CONTROL="1"
"""

import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from config import settings
from config.logger import get_logger

logger = get_logger("KRA-1527.preflight")

INSPECTOR = Path(settings.PROJECT_ROOT) / "tools" / "dump_token_inspector.py"

OMITIR = os.getenv("KRA1527_SIN_CONTROL", "0").strip().lower() in (
    "1", "true", "si", "sí", "yes")


def _b64(obj) -> str:
    return base64.urlsafe_b64encode(
        json.dumps(obj).encode()).rstrip(b"=").decode()


def _senuelo(carpeta: Path) -> Path:
    """Un .DMP falso con un JWT de auth dentro de una cabecera Authorization.

    Las fechas son RELATIVAS a la corrida. Estuvieron clavadas en 2030 y el
    inspector —que compara el `iat` contra la fecha del archivo— informaba
    «Token emitido 1740658 min DESPUÉS del volcado»: cierto y absurdo a la
    vez, y justo en la comprobación cuyo trabajo es dar confianza.
    """
    ahora = int(time.time())
    jwt = ".".join([
        _b64({"alg": "RS256", "typ": "JWT", "kid": "kra1527"}),
        _b64({"exp": ahora + 3600, "iat": ahora - 300,
              "iss": "https://sso.maxilabs.net/auth/realms/Agents",
              "sub": "control-negativo", "azp": "hermes2",
              "preferred_username": "qa.control.negativo"}),
        "ZmlybWFfZGVfcHJ1ZWJhX25vX3ZhbGlkYQ",
    ])
    ruta = carpeta / "control_negativo.dmp"
    # Relleno binario alrededor, para parecerse a un volcado real: el token no
    # está en un archivo de texto limpio, sino entre megas de ruido.
    ruta.write_bytes(
        os.urandom(2048) + b"\x00Authorization: Bearer " + jwt.encode()
        + b"\x00" + os.urandom(2048))
    return ruta


def verificar() -> tuple:
    """Corre el control. Devuelve `(ok, motivo)`.

    Nunca lanza: un error inesperado aquí no debe impedir la corrida por sí
    mismo, pero sí devolver `ok=False` con el motivo — quien decide qué hacer
    es el preflight.
    """
    if OMITIR:
        return True, "omitido por KRA1527_SIN_CONTROL=1"
    if not INSPECTOR.is_file():
        return False, f"no existe el inspector en {INSPECTOR}"

    carpeta = Path(tempfile.mkdtemp(prefix="kra1527_control_"))
    reporte = settings.EVIDENCE_DIR / "KRA-1527" / "control_negativo.html"
    try:
        ruta = _senuelo(carpeta)
        reporte.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(
            [sys.executable, str(INSPECTOR), str(ruta),
             "--caso", "ControlNegativo", "--proceso", "(señuelo)",
             "--out", str(reporte)],
            # El inspector escribe UTF-8 en su stdout; sin decirlo aquí,
            # `text=True` descodifica con el locale y salen «sesiÃ³n», «Ã—».
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace")
    except Exception as e:
        return False, f"no se pudo ejecutar el inspector: {str(e)[:120]}"
    finally:
        try:
            for f in carpeta.iterdir():
                f.unlink()
            carpeta.rmdir()
        except Exception:
            pass

    if r.returncode != 1:
        cola = ((r.stdout or "") + (r.stderr or ""))[-400:]
        return False, (f"el inspector NO detectó un JWT plantado a propósito "
                       f"(exit={r.returncode}). Salida:\n{cola}")
    if not reporte.exists():
        return False, "el inspector detectó el token pero no generó el reporte"
    return True, "el inspector detecta tokens expuestos"
