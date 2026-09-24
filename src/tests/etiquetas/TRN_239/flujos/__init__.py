"""
Flujos de la etiqueta TRN-239.

| Módulo | Qué hace |
|---|---|
| `lunex_api.py` | El «Page Object» de la API: un método por operación, JSON y SOAP |
| `bodies.py` | Construcción de los cuerpos y de la firma MD5 |
| `bd.py` | Consultas a `lunex.TransferLN` — la validación de integridad |

## Evidencia sin capturas de pantalla

Aquí no hay navegador, así que la evidencia no son PNG: es el **par
petición/respuesta** de cada llamada, guardado como `.json` legible. Esa es la
prueba de una migración de API — enseña exactamente qué se mandó y qué
contestó cada endpoint, que es lo que alguien va a querer comparar contra el
legacy dentro de seis meses.
"""

import json
from datetime import datetime

from config import settings

EVIDENCIAS_BASE = settings.EVIDENCE_DIR / "TRN-239"


def evidencia_dir(caso: str):
    d = EVIDENCIAS_BASE / caso
    d.mkdir(parents=True, exist_ok=True)
    return d


class Evidencia:
    """Guarda el par petición/respuesta de cada llamada, numerado.

        evi = Evidencia(P.CP02)
        evi.http("alta_json", peticion=body, respuesta=resp, paso=1)

    Nunca lanza: una evidencia que falla no debe tumbar el caso que está
    probando la migración.
    """

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
        # `_MODIFICADO` va PRIMERO para que, al abrir el .json, se vea de un
        # vistazo qué campo del request se alteró para provocar el resultado —
        # útil para reproducirlo a mano en Postman sin leer todo el cuerpo.
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
        """Para lo que no es JSON: un sobre SOAP, una consulta SQL."""
        self.n += 1
        etiqueta = (f"Step{int(paso):02d}-{nombre}" if paso
                    else f"{self.n:02d}_{nombre}")
        ruta = evidencia_dir(self.caso) / f"{etiqueta}.txt"
        try:
            ruta.write_text(contenido, encoding="utf-8")
        except Exception:
            pass
        return str(ruta)
