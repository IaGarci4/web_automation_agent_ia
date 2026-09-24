"""
Cliente de QMetry Test Management for Jira **Cloud** (QTM4J).

Sirve para subir las EVIDENCIAS del sanity al Test Cycle correspondiente y, si
se quiere, actualizar el resultado de cada paso.

────────────────────────────────────────────────────────────────────────────────
CÓMO FUNCIONA LA SUBIDA (importante)
La API de QMetry **no recibe el archivo**: entrega credenciales S3 pre-firmadas
y el archivo se sube DIRECTO a S3. Son dos pasos:

  1. GET  .../teststep-executions/attachments/url?...   → {endpoint_url, params}
  2. POST multipart a `endpoint_url` con TODOS los `params` + el binario
     (sin cabeceras de QMetry: es S3 puro). Éxito = HTTP 201.

Encadenado completo para dejar una imagen en un paso:
  ciclo (BM-TR-1370) → id interno
  → caso (BM-TC-4644) dentro del ciclo → testCaseExecutionId
  → pasos de esa ejecución → testStepExecutionId
  → credenciales → subida a S3

Autenticación: header `apiKey` (API Key de QMetry). Según la documentación,
algunos despliegues piden además el Basic auth de Jira (correo + API token de
Atlassian); si están configurados (QMETRY_JIRA_EMAIL / QMETRY_JIRA_TOKEN) se
envía también.

Docs: https://app.swaggerhub.com/apis-docs/qmetry-ada/qtm4j_cloud/restapi
────────────────────────────────────────────────────────────────────────────────
"""

import base64
import json
import mimetypes
from pathlib import Path

import requests

from config import settings
from config.logger import get_logger

logger = get_logger("qmetry")

API = "/rest/api/latest"
TIMEOUT = 60


class QMetryError(RuntimeError):
    """Error de la API de QMetry (con el detalle de la respuesta)."""


class QMetryClient:
    def __init__(self, api_key: str = None, base_url: str = None,
                 project_id=None, jira_email: str = None, jira_token: str = None):
        self.api_key = api_key or settings.QMETRY_API_KEY
        self.base_url = (base_url or settings.QMETRY_BASE_URL).rstrip("/")
        self.project_id = int(project_id or settings.QMETRY_PROJECT_ID)
        self.jira_email = jira_email or settings.QMETRY_JIRA_EMAIL
        self.jira_token = jira_token or settings.QMETRY_JIRA_TOKEN
        if not self.api_key:
            raise QMetryError("Falta QMETRY_API_KEY en el .env")

    # ── HTTP ────────────────────────────────────────────────────────────────
    def _headers(self, con_json: bool = False) -> dict:
        h = {"apiKey": self.api_key, "Accept": "application/json"}
        if con_json:
            h["Content-Type"] = "application/json"
        # Basic auth de Jira: solo si está configurado (algunos tenants lo piden).
        if self.jira_email and self.jira_token:
            cred = f"{self.jira_email}:{self.jira_token}".encode()
            h["Authorization"] = "Basic " + base64.b64encode(cred).decode()
        return h

    def _pedir(self, metodo: str, ruta: str, *, params=None, body=None) -> dict:
        url = f"{self.base_url}{API}{ruta}"
        r = requests.request(metodo, url, headers=self._headers(body is not None),
                             params=params,
                             data=json.dumps(body) if body is not None else None,
                             timeout=TIMEOUT)
        if r.status_code >= 400:
            raise QMetryError(f"{metodo} {ruta} → HTTP {r.status_code}: "
                              f"{(r.text or '')[:400]}")
        if not r.text:
            return {}
        try:
            return r.json()
        except Exception:
            return {"raw": r.text}

    # ── 1. Test Cycle ───────────────────────────────────────────────────────
    def obtener_ciclo(self, ciclo_key: str) -> dict:
        """Datos del Test Cycle por su key (ej. 'BM-TR-1370').

        Devuelve el dict de QMetry; el campo 'id' es el identificador interno
        alfanumérico que piden el resto de los endpoints."""
        data = self._pedir("GET", f"/testcycles/{ciclo_key}")
        ciclo = data.get("data", data)
        if not ciclo.get("id"):
            raise QMetryError(f"No se obtuvo el id del ciclo {ciclo_key}: "
                              f"{str(data)[:300]}")
        logger.info("[QMetry] Ciclo %s → id=%s | %s", ciclo_key, ciclo.get("id"),
                    ciclo.get("summary", ""))
        return ciclo

    # ── 2. Caso dentro del ciclo ────────────────────────────────────────────
    def buscar_caso_en_ciclo(self, ciclo_id: str, caso_key: str) -> dict:
        """Ejecución del caso dentro del ciclo (por key, ej. 'BM-TC-4644').

        Del resultado interesan `testCaseExecutionId` (para pasos/adjuntos) y
        `testCycleTestCaseMapId`."""
        data = self._pedir("POST", f"/testcycles/{ciclo_id}/testcases/search",
                           params={"startAt": 0, "maxResults": 50},
                           body={"filter": {"key": caso_key}})
        filas = data.get("data") or []
        if not filas:
            raise QMetryError(f"El caso {caso_key} no está ligado al ciclo "
                              f"{ciclo_id} (o no hay permisos).")
        caso = filas[0]
        logger.info("[QMetry] Caso %s → testCaseExecutionId=%s (map=%s) | %s",
                    caso_key, caso.get("testCaseExecutionId"),
                    caso.get("testCycleTestCaseMapId"), caso.get("summary", ""))
        return caso

    # ── 3. Pasos de la ejecución ────────────────────────────────────────────
    def obtener_pasos(self, ciclo_id: str, testcase_execution_id) -> list:
        """Pasos de la ejecución (cada uno con su `testStepExecutionId`)."""
        data = self._pedir(
            "GET",
            f"/testcycles/{ciclo_id}/testcase-executions/"
            f"{testcase_execution_id}/teststeps",
            params={"startAt": 0, "maxResults": 100})
        pasos = data.get("data") or []
        logger.info("[QMetry] %d paso(s) en la ejecución %s",
                    len(pasos), testcase_execution_id)
        return pasos

    # ── 4. Credenciales de subida (S3 pre-firmado) ──────────────────────────
    def _credenciales_paso(self, ciclo_id: str, step_execution_id,
                           nombre_archivo: str, inline: bool = False) -> dict:
        """Credenciales S3 para adjuntar a un PASO.

        `inline=True` marca la imagen como INCRUSTADA en el richtext (es lo que
        hace QMetry cuando se pega una captura en 'Actual Result'); con
        `inline=False` queda como adjunto suelto del paso."""
        return self._pedir(
            "GET", f"/testcycles/{ciclo_id}/teststep-executions/attachments/url",
            params={"projectId": self.project_id, "fileName": nombre_archivo,
                    "testStepExecutionId": step_execution_id,
                    "inline": str(bool(inline)).lower()})

    def _credenciales_ejecucion(self, ciclo_id: str, testcase_execution_id,
                                nombre_archivo: str) -> dict:
        return self._pedir(
            "GET", f"/testcycles/{ciclo_id}/testcase-executions/attachments/url",
            params={"projectId": self.project_id, "fileName": nombre_archivo,
                    "testcaseExecutionId": testcase_execution_id,
                    "inline": "false"})

    # ── 5. Subida directa a S3 ──────────────────────────────────────────────
    @staticmethod
    def _subir_a_s3(credenciales: dict, ruta: Path,
                    campo_archivo: str = "file") -> int:
        """POST multipart a S3 con los `params` firmados + el binario.

        El binario va SIEMPRE al final (requisito de las políticas POST de S3).
        Devuelve el status HTTP (201 = subido)."""
        endpoint = credenciales.get("endpoint_url")
        params = credenciales.get("params") or {}
        if not endpoint or not params:
            raise QMetryError(f"Credenciales de subida incompletas: "
                              f"{str(credenciales)[:300]}")
        tipo = params.get("Content-Type") or \
            mimetypes.guess_type(ruta.name)[0] or "application/octet-stream"
        campos = [(k, (None, str(v))) for k, v in params.items()]
        campos.append((campo_archivo, (ruta.name, ruta.read_bytes(), tipo)))
        r = requests.post(endpoint, files=campos, timeout=TIMEOUT)
        if r.status_code not in (200, 201, 204):
            raise QMetryError(f"S3 → HTTP {r.status_code}: {(r.text or '')[:400]}")
        return r.status_code

    # ── API de alto nivel ───────────────────────────────────────────────────
    def adjuntar_a_paso(self, ciclo_id: str, step_execution_id, ruta,
                        inline: bool = False) -> bool:
        """Sube una imagen/archivo a un PASO de la ejecución.

        Con `inline=True` la imagen queda marcada como incrustada en el richtext
        (igual que al pegarla a mano en 'Actual Result'). Ojo: además de subirla
        así, para que se VEA en el campo hay que referenciarla en `actualResult`
        — usa `incrustar_en_actual_result()`."""
        ruta = Path(ruta)
        if not ruta.exists():
            logger.warning("[QMetry] No existe el archivo %s", ruta)
            return False
        cred = self._credenciales_paso(ciclo_id, step_execution_id, ruta.name,
                                       inline=inline)
        code = self._subir_a_s3(cred, ruta)
        logger.info("[QMetry] ✓ '%s' adjuntado al paso %s (HTTP %s, inline=%s)",
                    ruta.name, step_execution_id, code, str(inline).lower())
        return True

    # ── Imágenes INCRUSTADAS en 'Actual Result' (como al pegarlas a mano) ───
    #
    # QMetry no usa HTML: usa el wiki markup de Jira para imágenes:
    #   !<url>|width=W,height=H!
    # donde la url es
    #   {base}/app/inline-attachments/TESTCASE_EXECUTION?fileName=<archivo>&token=<token>
    # El <archivo> lleva un timestamp y el <token> los da QMetry en los params
    # de las credenciales de subida (x-amz-Meta-file-name / x-amz-Meta-token).

    def _dimensiones(self, ruta: Path):
        try:
            from PIL import Image
            with Image.open(ruta) as im:
                return im.size
        except Exception:
            return (1366, 768)      # tamaño de la ventana del sanity

    def adjuntar_inline_a_paso(self, ciclo_id: str, step_execution_id, ruta):
        """Sube la imagen como INLINE y devuelve el markup para 'Actual Result'.

        Devuelve el string `!...!` listo para escribir, o None si algo falló."""
        ruta = Path(ruta)
        if not ruta.exists():
            logger.warning("[QMetry] No existe el archivo %s", ruta)
            return None
        cred = self._credenciales_paso(ciclo_id, step_execution_id, ruta.name,
                                       inline=True)
        params = cred.get("params") or {}
        # El nombre definitivo (con timestamp) y el token los pone QMetry.
        nombre = (params.get("x-amz-Meta-file-name")
                  or params.get("x-amz-meta-file-name") or ruta.name)
        token = (params.get("x-amz-Meta-token")
                 or params.get("x-amz-meta-token") or "")
        self._subir_a_s3(cred, ruta)
        if not token:
            logger.warning("[QMetry] '%s' subida, pero sin token para incrustarla.",
                           ruta.name)
            return None
        ancho, alto = self._dimensiones(ruta)
        markup = (f"!{self.base_url}/app/inline-attachments/TESTCASE_EXECUTION"
                  f"?fileName={nombre}&token={token}"
                  f"|width={ancho},height={alto}!")
        logger.info("[QMetry] ✓ '%s' subida como inline (%dx%d).",
                    ruta.name, ancho, alto)
        return markup

    def escribir_actual_result(self, ciclo_id: str, step_execution_id,
                               markups: list, *, previo: str = None,
                               conservar: bool = True) -> bool:
        """Escribe en 'Actual Result' del paso los markups de las imágenes.

        Con `conservar=True` se añade a lo que ya hubiera (`previo`), sin
        duplicar lo que ya esté presente."""
        markups = [m for m in markups if m]
        if not markups:
            return False
        partes = []
        if conservar and previo:
            partes.append(previo.strip())
        for m in markups:
            if conservar and previo and m in previo:
                continue                     # ya estaba incrustada
            partes.append(m)
        contenido = "\n".join(p for p in partes if p)
        self._pedir("PUT",
                    f"/testcycles/{ciclo_id}/teststep-executions/{step_execution_id}",
                    body={"actualResult": contenido})
        logger.info("[QMetry] Actual Result del paso %s actualizado con %d "
                    "imagen(es).", step_execution_id, len(markups))
        return True

    def adjuntar_a_ejecucion(self, ciclo_id: str, testcase_execution_id, ruta) -> bool:
        """Sube una imagen/archivo a la EJECUCIÓN del caso."""
        ruta = Path(ruta)
        if not ruta.exists():
            logger.warning("[QMetry] No existe el archivo %s", ruta)
            return False
        cred = self._credenciales_ejecucion(ciclo_id, testcase_execution_id, ruta.name)
        code = self._subir_a_s3(cred, ruta)
        logger.info("[QMetry] ✓ '%s' adjuntado a la ejecución %s (HTTP %s)",
                    ruta.name, testcase_execution_id, code)
        return True

    def listar_adjuntos_paso(self, ciclo_id: str, step_execution_id,
                             inline: bool = False,
                             level: str = "teststep_execution,teststep") -> list:
        """Adjuntos de un paso.

        OJO con `inline`: al PEDIR credenciales el default de la API es `false`
        (adjunto normal), pero al LISTAR el default es `true` (adjuntos
        incrustados en richtext). Si no se pasa `inline=False` la lista sale
        VACÍA aunque la subida haya funcionado. `level` va como CSV."""
        data = self._pedir(
            "GET",
            f"/testcycles/{ciclo_id}/teststep-executions/{step_execution_id}/attachments",
            params={"startAt": 0, "maxResults": 50,
                    "inline": str(bool(inline)).lower(), "level": level})
        return data.get("data") or []

    def listar_adjuntos_ejecucion(self, ciclo_id: str, testcase_execution_id,
                                  inline: bool = False,
                                  level: str = "testcase_execution,teststep_execution") -> list:
        """Adjuntos de la ejecución del caso (mismo detalle de `inline`)."""
        data = self._pedir(
            "GET",
            f"/testcycles/{ciclo_id}/testcase-executions/{testcase_execution_id}/attachments",
            params={"startAt": 0, "maxResults": 50,
                    "inline": str(bool(inline)).lower(), "level": level})
        return data.get("data") or []

    def esperar_adjunto(self, ciclo_id: str, step_execution_id, nombre: str,
                        intentos: int = 6, espera: float = 2.0) -> dict:
        """Espera a que QMetry INDEXE el archivo recién subido.

        El registro del adjunto es ASÍNCRONO (un evento de S3 lo indexa), así que
        un GET inmediato puede venir vacío. Reintenta con backoff y devuelve el
        adjunto encontrado, o {} si no aparece."""
        import time
        for i in range(1, intentos + 1):
            for en_linea in (False, True):      # por si el tenant lo marca inline
                for a in self.listar_adjuntos_paso(ciclo_id, step_execution_id,
                                                   inline=en_linea):
                    if (a.get("name") or a.get("fileName") or "") == nombre:
                        logger.info("[QMetry] Adjunto '%s' visible (intento %d, "
                                    "inline=%s).", nombre, i, en_linea)
                        return a
            if i < intentos:
                time.sleep(espera * i)          # backoff
        logger.warning("[QMetry] '%s' no aparece todavía tras %d intentos "
                       "(el indexado puede tardar).", nombre, intentos)
        return {}

    # ── Resultados (opcional) ───────────────────────────────────────────────
    # Rutas candidatas del catálogo de resultados: cambia según el tenant/versión.
    _RUTAS_RESULTADOS = (
        "/projects/{pid}/execution-results",
        "/projects/{pid}/executionresults",
        "/execution-results",
        "/executionresults",
    )

    def resultados_disponibles(self) -> list:
        """Catálogo de resultados de ejecución (Pass/Fail/…) con sus ids.

        La ruta cambia entre tenants/versiones de QTM4J, así que se prueban
        varias y se normalizan las formas de respuesta habituales."""
        errores = []
        for plantilla in self._RUTAS_RESULTADOS:
            ruta = plantilla.format(pid=self.project_id)
            try:
                data = self._pedir("GET", ruta)
            except QMetryError as e:
                errores.append(f"{ruta}: {str(e)[:70]}")
                continue
            filas = self._normalizar_lista(data)
            if filas:
                logger.info("[QMetry] Catálogo de resultados vía %s: %s", ruta,
                            ", ".join(f"{self._nombre_resultado(r)}={r.get('id')}"
                                      for r in filas))
                return filas
            errores.append(f"{ruta}: respuesta vacía")
        raise QMetryError("No se pudo leer el catálogo de resultados. "
                          + " | ".join(errores))

    @staticmethod
    def _normalizar_lista(data) -> list:
        """Extrae la lista de filas de las formas típicas de respuesta."""
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
        if not isinstance(data, dict):
            return []
        for clave in ("data", "results", "executionResults", "content", "items"):
            valor = data.get(clave)
            if isinstance(valor, list) and valor:
                return [r for r in valor if isinstance(r, dict)]
        return []

    @staticmethod
    def _nombre_resultado(fila: dict) -> str:
        for clave in ("name", "defaultName", "label", "value", "displayName"):
            v = fila.get(clave)
            if v:
                return str(v).strip()
        return ""

    # Nombres equivalentes: cada tenant escribe estos estados a su manera.
    _ALIAS_RESULTADO = {
        "pass": ("pass", "passed", "aprobado", "exitoso", "ok"),
        "fail": ("fail", "failed", "fallido", "error"),
        "na":   ("na", "n/a", "n.a.", "not applicable", "no aplica",
                 "not executed", "no ejecutado", "not run", "blocked"),
    }

    def id_resultado(self, nombre: str):
        """Id del resultado por NOMBRE ('Pass', 'Fail', 'NA'…).

        Se resuelve contra el catálogo del proyecto (los ids cambian por
        proyecto), con caché en memoria. Devuelve None si no existe — y en ese
        caso deja en el log el catálogo real, que es lo que hace falta para
        entender por qué no se escribió el estatus."""
        if not hasattr(self, "_cache_resultados"):
            try:
                self._cache_resultados = self.resultados_disponibles()
            except QMetryError as e:
                logger.error("[QMetry] Sin catálogo de resultados → NO se podrá "
                             "escribir el estatus de los pasos. %s", str(e)[:220])
                self._cache_resultados = []
        if not self._cache_resultados:
            return None

        buscado = (nombre or "").strip().lower()
        nombres = {self._nombre_resultado(r).lower(): r.get("id")
                   for r in self._cache_resultados}
        if buscado in nombres:
            return nombres[buscado]
        # Por alias (Pass↔Passed, NA↔N/A↔Not Applicable…)
        familia = next((v for k, v in self._ALIAS_RESULTADO.items()
                        if buscado == k or buscado in v), ())
        for alias in familia:
            if alias in nombres:
                return nombres[alias]
        # Último recurso: coincidencia parcial
        for n, rid in nombres.items():
            if n and (n.startswith(buscado) or buscado.startswith(n)):
                return rid
        logger.warning("[QMetry] No encontré el resultado '%s'. Disponibles: %s",
                       nombre, ", ".join(sorted(n for n in nombres if n)) or "(ninguno)")
        return None

    def _put_tolerante(self, ruta: str, cuerpos: list, desc: str) -> bool:
        """PUT probando varias formas de cuerpo (los tenants difieren).

        Si la primera falla por el nombre de un campo, se reintenta con la
        siguiente en vez de dar el estatus por perdido en silencio."""
        errores = []
        for body in cuerpos:
            if not body:
                continue
            try:
                self._pedir("PUT", ruta, body=body)
                logger.info("[QMetry] %s actualizado (%s).", desc, ", ".join(body))
                return True
            except QMetryError as e:
                errores.append(f"{list(body)}→{str(e)[:90]}")
        raise QMetryError(f"{desc}: ningún cuerpo fue aceptado. "
                          + " | ".join(errores))

    def actualizar_paso(self, ciclo_id: str, step_execution_id, *,
                        resultado_id: int = None, actual: str = None,
                        comentario: str = None) -> bool:
        base = {}
        if resultado_id is not None:
            base["executionResultId"] = int(resultado_id)
        if actual is not None:
            base["actualResult"] = actual
        if not base and comentario is None:
            return False
        ruta = f"/testcycles/{ciclo_id}/teststep-executions/{step_execution_id}"
        # El comentario es un extra: si el tenant lo rechaza, el estatus (que es
        # lo importante) debe escribirse igual.
        cuerpos = []
        if comentario is not None:
            cuerpos.append({**base, "comment": comentario})
            cuerpos.append({**base, "comments": comentario})
        cuerpos.append(base)
        return self._put_tolerante(ruta, cuerpos, f"Paso {step_execution_id}")

    def actualizar_ejecucion(self, ciclo_id: str, testcase_execution_id, *,
                             resultado_id: int = None, comentario: str = None) -> bool:
        base = {}
        if resultado_id is not None:
            base["executionResultId"] = int(resultado_id)
        if not base and comentario is None:
            return False
        ruta = (f"/testcycles/{ciclo_id}/testcase-executions/"
                f"{testcase_execution_id}")
        cuerpos = []
        if comentario is not None:
            cuerpos.append({**base, "comment": comentario})
            cuerpos.append({**base, "comments": comentario})
        cuerpos.append(base)
        return self._put_tolerante(ruta, cuerpos,
                                   f"Ejecución {testcase_execution_id}")
