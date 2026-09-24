"""
Sincronización de EVIDENCIAS del sanity → QMetry.

Toma las capturas que dejó un caso en
`reports/evidence/sanity_general/<CPxx_...>/NN_nombre.png`
y las adjunta al PASO correspondiente del Test Case dentro del Test Cycle,
según `config/qmetry_mapeo.json`.

Reglas:
  • El Test Cycle sale del ambiente activo (settings.QMETRY_TEST_CYCLE:
    BM-TR-1370 en test · BM-TR-1412 en prod).
  • El paso se decide por el nombre del archivo (fragmento → seqNo).
  • Lo que no mapea va al nivel de EJECUCIÓN del caso (o se omite, según
    'resto' en el mapeo).
  • IDEMPOTENTE: si el paso ya tiene un adjunto con ese nombre, no lo repite.
  • NUNCA lanza: si algo falla, avisa en el log. Subir evidencias no debe
    tumbar una prueba que ya pasó.
"""

import json
import re
from pathlib import Path

from config import settings
from config.logger import get_logger
from src.helpers.qmetry_client import QMetryClient, QMetryError

logger = get_logger("qmetry.sync")

MAPEO_PATH = Path(settings.PROJECT_ROOT) / "config" / "qmetry_mapeo.json"
EVIDENCIAS_BASE = settings.EVIDENCE_DIR / "sanity_general"


def cargar_mapeo() -> dict:
    try:
        datos = json.loads(MAPEO_PATH.read_text(encoding="utf-8"))
        return {k: v for k, v in datos.items() if not k.startswith("_")}
    except Exception as e:
        logger.warning("[QMetry] No se pudo leer %s: %s", MAPEO_PATH.name, str(e)[:90])
        return {}


def carpeta_de_evidencias(cp: str) -> Path | None:
    """Carpeta de evidencias del CP (ej. 'CP02' → CP02_money_transfer_...)."""
    if not EVIDENCIAS_BASE.exists():
        return None
    for d in sorted(EVIDENCIAS_BASE.glob(f"{cp}*")):
        if d.is_dir():
            return d
    return None


# El PASO viene en el propio nombre del archivo (convención del proyecto), así
# no hay que mapear nada y ninguna imagen se omite. Formato principal:
#     Step02-cliente_beneficiario.png   → paso 2
# También se aceptan (compatibilidad):
#     03_p05_envio_continue.png · paso05_x.png · step7_x.png · 07_s10_x.png
_RE_PASO_EN_NOMBRE = re.compile(
    r"(?:^|[_\-])(?:step|paso|p|s)[ _\-]?0*(\d{1,2})(?:[_\-]|$)", re.I)

# Evidencias que SIEMPRE van al ÚLTIMO paso del caso, sin importar el mapeo.
# En el sanity todos los casos terminan con una cancelación, y ese cierre debe
# quedar documentado en el paso final aunque el texto del paso no coincida.
# Se puede ajustar por CP con "ultimo_paso": ["patrón", ...] en el mapeo.
PATRONES_ULTIMO_PASO = ["cancelacion", "cancelación", "cancellation",
                        "transaccion_encontrada", "cancelado"]


def _va_al_ultimo_paso(nombre_archivo: str, patrones) -> bool:
    base = Path(nombre_archivo).stem.lower()
    return any(str(p).lower() in base for p in (patrones or []))


def paso_en_nombre(nombre_archivo: str):
    """Número de paso indicado EN EL NOMBRE del archivo, o None."""
    base = Path(nombre_archivo).stem
    m = _RE_PASO_EN_NOMBRE.search(base)
    return int(m.group(1)) if m else None


def _paso_para(nombre_archivo: str, pasos: dict):
    """Paso destino de una evidencia.

    Prioridad:
      1. El número indicado en el NOMBRE (p05 / paso5 / step5) — la convención.
      2. El mapeo por fragmentos de config/qmetry_mapeo.json (respaldo).
    """
    directo = paso_en_nombre(nombre_archivo)
    if directo is not None:
        return directo
    base = Path(nombre_archivo).stem            # '05_envio_continue'
    sin_prefijo = base.split("_", 1)[-1] if "_" in base else base
    for fragmento, seq in pasos.items():
        f = str(fragmento).lower()
        if f in base.lower() or f in sin_prefijo.lower():
            return int(seq)
    return None


def subir_evidencias(cp: str, *, ciclo_key: str = None, carpeta=None,
                     cliente: QMetryClient = None, veredicto: str = None) -> dict:
    """Sube las evidencias de un CP a su caso/pasos en QMetry.

    `veredicto` (opcional): 'Pass' o 'Fail' — resultado REAL de la prueba. Si se
    pasa, además de las imágenes se marca el resultado de los pasos con
    evidencia y de la ejecución del caso. Se usa el veredicto de pytest, no la
    existencia de la imagen: una captura no demuestra por sí sola que el paso
    haya sido correcto.

    Devuelve un resumen {'subidas': n, 'omitidas': n, 'errores': n}.
    """
    resumen = {"subidas": 0, "omitidas": 0, "errores": 0}
    if veredicto:
        resumen["_resultado_paso"] = veredicto
    cp = (cp or "").upper()
    mapeo = cargar_mapeo().get(cp) or {}
    caso_key = (mapeo.get("test_case") or "").strip()
    if not caso_key:
        logger.info("[QMetry] %s no tiene 'test_case' en config/qmetry_mapeo.json "
                    "— no se sube nada.", cp)
        return resumen

    carpeta = Path(carpeta) if carpeta else carpeta_de_evidencias(cp)
    if not carpeta or not carpeta.exists():
        logger.info("[QMetry] %s: sin carpeta de evidencias — nada que subir.", cp)
        return resumen
    imagenes = sorted(carpeta.glob("*.png"))
    if not imagenes:
        logger.info("[QMetry] %s: la carpeta no tiene PNG.", cp)
        return resumen

    ciclo_key = ciclo_key or settings.QMETRY_TEST_CYCLE
    try:
        q = cliente or QMetryClient()
        ciclo = q.obtener_ciclo(ciclo_key)
        ciclo_id = ciclo["id"]
        caso = q.buscar_caso_en_ciclo(ciclo_id, caso_key)
        exec_id = caso.get("testCaseExecutionId")
        pasos_api = q.obtener_pasos(ciclo_id, exec_id)
        por_seq = {int(p.get("testStepSeqNo")): p.get("testStepExecutionId")
                   for p in pasos_api if p.get("testStepSeqNo") is not None}
    except QMetryError as e:
        logger.warning("[QMetry] %s: no se pudo preparar la subida (%s).", cp, str(e)[:140])
        resumen["errores"] += 1
        return resumen

    mapa_pasos = mapeo.get("pasos") or {}
    resto = mapeo.get("resto", "ejecucion")
    # Modo INLINE: sube la imagen como incrustada y la referencia en el campo
    # 'Actual Result' del paso — así se VE en la interfaz (es lo que hace QMetry
    # cuando se pega una captura a mano). Con QMETRY_INLINE=0 quedan como
    # adjuntos sueltos del paso.
    modo_inline = str(mapeo.get("inline", "1")).strip().lower() not in ("0", "false", "no")
    if modo_inline:
        return _subir_inline(q, cp, ciclo_key, ciclo_id, exec_id, pasos_api,
                             imagenes, mapa_pasos, resto, resumen)
    # Adjuntos ya existentes (para no duplicar)
    ya_en_paso = {}
    try:
        ya_en_ejecucion = {(a.get("name") or a.get("fileName"))
                           for a in q.listar_adjuntos_ejecucion(ciclo_id, exec_id)}
    except QMetryError:
        ya_en_ejecucion = set()

    logger.info("[QMetry] %s → %s (ciclo %s): %d evidencia(s) por subir.",
                cp, caso_key, ciclo_key, len(imagenes))

    for img in imagenes:
        seq = _paso_para(img.name, mapa_pasos)
        destino_paso = None
        if seq is not None:
            destino_paso = por_seq.get(seq)
            if destino_paso is None:
                logger.warning("[QMetry] %s: el paso %s no existe en el caso "
                               "(tiene %d pasos) — va a la ejecución.",
                               img.name, seq, len(por_seq))
        elif isinstance(resto, int) or (isinstance(resto, str) and resto.isdigit()):
            destino_paso = por_seq.get(int(resto))
        elif resto == "omitir":
            resumen["omitidas"] += 1
            continue

        try:
            if destino_paso:
                if destino_paso not in ya_en_paso:
                    ya_en_paso[destino_paso] = {
                        (a.get("name") or a.get("fileName"))
                        for a in q.listar_adjuntos_paso(ciclo_id, destino_paso)}
                if img.name in ya_en_paso[destino_paso]:
                    logger.info("[QMetry] '%s' ya estaba en el paso %s — se omite.",
                                img.name, seq)
                    resumen["omitidas"] += 1
                    continue
                q.adjuntar_a_paso(ciclo_id, destino_paso, img)
                ya_en_paso[destino_paso].add(img.name)
            else:
                if img.name in ya_en_ejecucion:
                    resumen["omitidas"] += 1
                    continue
                q.adjuntar_a_ejecucion(ciclo_id, exec_id, img)
                ya_en_ejecucion.add(img.name)
            resumen["subidas"] += 1
        except QMetryError as e:
            logger.warning("[QMetry] '%s' no se pudo adjuntar: %s", img.name, str(e)[:120])
            resumen["errores"] += 1

    logger.info("[QMetry] %s: %d subida(s), %d omitida(s), %d error(es).",
                cp, resumen["subidas"], resumen["omitidas"], resumen["errores"])
    return resumen


def _subir_inline(q, cp, ciclo_key, ciclo_id, exec_id, pasos_api, imagenes,
                  mapa_pasos, resto, resumen) -> dict:
    """Sube las evidencias como imágenes INCRUSTADAS en 'Actual Result'.

    Agrupa por paso: sube todas las imágenes de un paso y luego escribe el
    campo una sola vez (menos llamadas y sin pisar lo anterior)."""
    por_seq = {int(p.get("testStepSeqNo")): p for p in pasos_api
               if p.get("testStepSeqNo") is not None}
    # Agrupar imágenes por paso destino
    grupos: dict = {}
    sin_paso = []
    ultimo_paso = max(por_seq) if por_seq else None
    patrones_ultimo = mapeo_ultimo_paso(cp)
    for img in imagenes:
        # Regla del sanity: la evidencia de CANCELACIÓN cierra el caso, así que
        # va SIEMPRE al último paso (salvo que el nombre indique otro con StepNN).
        if (ultimo_paso is not None
                and paso_en_nombre(img.name) is None
                and _va_al_ultimo_paso(img.name, patrones_ultimo)):
            logger.info("[QMetry] '%s' → último paso (%s) por regla de cancelación.",
                        img.name, ultimo_paso)
            grupos.setdefault(ultimo_paso, []).append(img)
            continue
        seq = _paso_para(img.name, mapa_pasos)
        if seq is None and (isinstance(resto, int) or
                            (isinstance(resto, str) and str(resto).isdigit())):
            seq = int(resto)
        if seq is None:
            sin_paso.append(img)
            continue
        if seq not in por_seq:
            logger.warning("[QMetry] %s: el paso %s no existe (el caso tiene %d) "
                           "— va a la ejecución.", img.name, seq, len(por_seq))
            sin_paso.append(img)
            continue
        grupos.setdefault(seq, []).append(img)

    logger.info("[QMetry] %s → %s (ciclo %s): %d imagen(es) en %d paso(s) "
                "(modo incrustado).", cp, mapeo_caso(cp), ciclo_key,
                len(imagenes) - len(sin_paso), len(grupos))

    pasos_con_evidencia = []       # [(seq, step_id)] en orden de paso
    for seq, imgs in sorted(grupos.items()):
        imgs.sort(key=lambda p: (p.stat().st_mtime, p.name))   # orden de captura
        paso = por_seq[seq]
        step_id = paso.get("testStepExecutionId")
        previo = paso.get("actualResult") or ""
        markups = []
        for img in imgs:
            # Si ya está incrustada (por nombre base), no repetir.
            if img.stem in previo:
                logger.info("[QMetry] '%s' ya estaba incrustada en el paso %s.",
                            img.name, seq)
                resumen["omitidas"] += 1
                continue
            try:
                m = q.adjuntar_inline_a_paso(ciclo_id, step_id, img)
                if m:
                    markups.append(m)
                    resumen["subidas"] += 1
                else:
                    resumen["errores"] += 1
            except QMetryError as e:
                logger.warning("[QMetry] '%s': %s", img.name, str(e)[:110])
                resumen["errores"] += 1
        if markups:
            try:
                q.escribir_actual_result(ciclo_id, step_id, markups, previo=previo)
            except QMetryError as e:
                logger.warning("[QMetry] No se pudo escribir el Actual Result "
                               "del paso %s: %s", seq, str(e)[:110])
                resumen["errores"] += 1
        pasos_con_evidencia.append((seq, step_id))

    # Las que no mapean a ningún paso → adjunto de la ejecución (si aplica)
    if sin_paso and resto == "ejecucion":
        for img in sin_paso:
            try:
                q.adjuntar_a_ejecucion(ciclo_id, exec_id, img)
                resumen["subidas"] += 1
            except QMetryError as e:
                logger.warning("[QMetry] '%s': %s", img.name, str(e)[:110])
                resumen["errores"] += 1
    elif sin_paso:
        resumen["omitidas"] += len(sin_paso)

    # ── Resultados: por PASO y de la EJECUCIÓN ──────────────────────────────
    veredicto = resumen.pop("_resultado_paso", None)
    if veredicto:
        _marcar_resultados(q, cp, ciclo_id, exec_id, por_seq,
                           pasos_con_evidencia, veredicto)

    logger.info("[QMetry] %s: %d subida(s), %d omitida(s), %d error(es).",
                cp, resumen["subidas"], resumen["omitidas"], resumen["errores"])
    return resumen


MOTIVO_NA = ("No aplica en la ejecución automatizada "
             "(paso fuera del alcance de la automatización).")


def _marcar_resultados(q, cp, ciclo_id, exec_id, por_seq, con_evidencia,
                       veredicto: str) -> None:
    """Escribe el resultado de cada paso y de la ejecución.

    Reglas (el veredicto viene de pytest, no de "tiene imagen"):
      • Prueba EXITOSA → los pasos con evidencia quedan en **Pass**; los que no
        se ejecutaron (sin evidencia) quedan en **NA**.
      • Prueba FALLIDA → los pasos con evidencia anteriores al último quedan en
        **Pass**, el ÚLTIMO con evidencia en **Fail** (es donde se detuvo), y
        los posteriores en **NA**.
      • Los pasos declarados en `"na"` del mapeo quedan SIEMPRE en **NA** con un
        comentario que explica por qué (p.ej. impresión física: no aplica en un
        proceso automatizado). Así el ciclo queda honesto y auditable.
    """
    ids = {n: q.id_resultado(n) for n in ("Pass", "Fail", "NA")}
    faltantes = [n for n, v in ids.items() if not v]
    if faltantes:
        logger.error("[QMetry] %s: no pude resolver el id de %s en el proyecto — "
                     "esos pasos NO se marcarán. Corre "
                     "`python tools/qmetry_estatus.py` para ver el catálogo real.",
                     cp, ", ".join(faltantes))
    if not any(ids.values()):
        logger.error("[QMetry] %s: sin catálogo de resultados, el estatus queda "
                     "sin escribir (las imágenes sí se subieron).", cp)
        return
    cfg = cargar_mapeo().get(cp.upper(), {}) or {}
    na_declarados = {int(s) for s in (cfg.get("na") or [])}
    motivo = cfg.get("na_motivo") or MOTIVO_NA

    con_evidencia = sorted(s for s in con_evidencia if s[0] not in na_declarados)
    seqs_evidencia = [s for s, _ in con_evidencia]
    ultimo = seqs_evidencia[-1] if seqs_evidencia else None
    exitosa = str(veredicto).strip().lower().startswith("pass")

    plan = {}
    for seq, step_id in con_evidencia:
        if exitosa:
            plan[seq] = ("Pass", step_id, None)
        else:
            plan[seq] = (("Fail" if seq == ultimo else "Pass"), step_id, None)
    # Pasos declarados NA + los que no se ejecutaron → NA (con motivo)
    for seq, paso in por_seq.items():
        if seq in plan:
            continue
        comentario = motivo if seq in na_declarados else None
        plan[seq] = ("NA", paso.get("testStepExecutionId"), comentario)

    for seq in sorted(plan):
        nombre, step_id, comentario = plan[seq]
        rid = ids.get(nombre)
        if not rid or not step_id:
            logger.warning("[QMetry] Paso %s: sin %s — no se marca.", seq,
                           "id de resultado" if not rid else "id de ejecución")
            continue
        try:
            q.actualizar_paso(ciclo_id, step_id, resultado_id=rid,
                              comentario=comentario)
            logger.info("[QMetry] Paso %s → %s%s", seq, nombre,
                        " (declarado NA)" if seq in na_declarados else "")
        except QMetryError as e:
            logger.warning("[QMetry] No se pudo marcar el paso %s: %s",
                           seq, str(e)[:160])

    # Resultado de la ejecución del caso
    final = "Pass" if exitosa else "Fail"
    try:
        rid = q.id_resultado(final)
        if rid:
            q.actualizar_ejecucion(ciclo_id, exec_id, resultado_id=rid)
            logger.info("[QMetry] %s → ejecución marcada como '%s'.", cp, final)
    except QMetryError as e:
        logger.warning("[QMetry] No se pudo marcar la ejecución: %s", str(e)[:110])


def mapeo_caso(cp: str) -> str:
    """Key del test case configurado para ese CP (para los mensajes)."""
    return (cargar_mapeo().get(cp.upper(), {}) or {}).get("test_case", "?")


def mapeo_ultimo_paso(cp: str) -> list:
    """Patrones de evidencia que van al último paso (por CP, o los del proyecto)."""
    cfg = (cargar_mapeo().get(cp.upper(), {}) or {}).get("ultimo_paso")
    return cfg if isinstance(cfg, list) else PATRONES_ULTIMO_PASO


def cp_desde_nombre_test(nombre: str) -> str | None:
    """'test_CP02_money_transfer_ofac...' → 'CP02'."""
    import re
    m = re.search(r"(CP\d{2})", nombre or "", re.I)
    return m.group(1).upper() if m else None
