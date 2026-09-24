"""
Flujos de la etiqueta KRA-1526.

| Módulo | Qué hace |
|---|---|
| `captura.py`  | Inicia sesión y CAPTURA en vivo el request real de la búsqueda global (token + IdUser/IdAgent propios). Sin curl manual. |
| `idor_api.py` | Reproduce el baseline permutando IdUser/IdAgent y emite el veredicto. |

## Evidencia sin capturas de pantalla

Como en TRN-239, aquí la evidencia es el **par petición/respuesta** de cada
llamada, en `.json` legible: enseña exactamente qué IDs se enviaron y qué
contestó el endpoint — lo que alguien querrá revisar para confirmar que la fuga
IDOR quedó cerrada.
"""

import json
from datetime import datetime

from config import settings

EVIDENCIAS_BASE = settings.EVIDENCE_DIR / "KRA-1526"


def evidencia_dir(caso: str):
    d = EVIDENCIAS_BASE / caso
    d.mkdir(parents=True, exist_ok=True)
    return d


class Evidencia:
    """Guarda el par petición/respuesta de cada llamada, numerado. Nunca lanza."""

    def __init__(self, caso: str, start: int = 0):
        self.caso = caso
        self.n = start

    def http(self, nombre: str, *, peticion=None, respuesta=None,
             url: str = "", estado=None, ms=None, paso: int = None,
             modificado: str = "") -> str:
        self.n += 1
        etiqueta = (f"Step{int(paso):02d}-{nombre}" if paso
                    else f"{self.n:02d}_{nombre}")
        ruta = evidencia_dir(self.caso) / f"{etiqueta}.json"
        cuerpo = {}
        if modificado:
            cuerpo["_MODIFICADO"] = f"⬅ {modificado}"
        cuerpo.update({
            "caso": self.caso,
            "momento": datetime.now().isoformat(timespec="seconds"),
            "url": url,
            "http": estado,
            "duracion_ms": ms,
            "peticion": peticion,
            "respuesta": respuesta,
        })
        try:
            ruta.write_text(
                json.dumps(cuerpo, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8")
        except Exception:
            pass
        return str(ruta)

    def texto(self, nombre: str, contenido: str, *, paso: int = None) -> str:
        self.n += 1
        etiqueta = (f"Step{int(paso):02d}-{nombre}" if paso
                    else f"{self.n:02d}_{nombre}")
        ruta = evidencia_dir(self.caso) / f"{etiqueta}.txt"
        try:
            ruta.write_text(contenido, encoding="utf-8")
        except Exception:
            pass
        return str(ruta)
