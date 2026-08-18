"""
Runner en vivo para la GUI.

Ejecuta pytest en un SUBPROCESO no bloqueante (Popen) volcando su salida a un
archivo de log. La GUI lo consulta cada pocos segundos para:
  • mostrar el CASO en curso (CP + nombre legible),
  • mostrar un LOG amigable en vivo (los pasos que va haciendo el test),
  • ofrecer un botón DETENER (mata el árbol de procesos, incl. el navegador),
  • al terminar, parsear resultados (pass/fail por caso) y enlazar el reporte.

No bloquea el hilo de Streamlit: por eso el botón Detener sigue respondiendo
aunque la corrida esté en marcha (a diferencia de subprocess.run, que colgaba
la interfaz y dejaba el "cargando…" infinito).
"""

import os
import re
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).parent.parent
LOG_DIR = RAIZ / "reports" / "gui" / "logs"
REPORT_DIR = RAIZ / "reports" / "gui"

# ── Nombres legibles de cada CP (tomados del sanity del repo viejo) ──────────
CP_NOMBRES = {
    "CP01": "Money Transfer Cash + KYC",
    "CP02": "Money Transfer OFAC + cancelación",
    "CP03": "Money Transfer Depósito + Tarjeta de débito",
    "CP04": "Money Transfer doméstico ATM (multi-agente)",
    "CP05": "Bill Payment nacional — Fidelity Express",
    "CP06": "Bill Payment nacional — Fiserv",
    "CP07": "Recargas (Top Ups) — Lunex/DTOne",
}
CP_NOMBRES_EN = {
    "CP01": "Money Transfer Cash + KYC",
    "CP02": "Money Transfer OFAC + cancellation",
    "CP03": "Money Transfer Deposit + Debit card",
    "CP04": "Domestic ATM Money Transfer (multi-agent)",
    "CP05": "Domestic Bill Payment — Fidelity Express",
    "CP06": "Domestic Bill Payment — Fiserv",
    "CP07": "Top-Ups (Recharges) — Lunex/DTOne",
}


def nombre_cp(cp: str, lang: str = "es") -> str:
    """'CP05' → 'CP05 · Bill Payment nacional — Fidelity Express' (según idioma)."""
    cp = (cp or "").upper()
    tabla = CP_NOMBRES_EN if lang == "en" else CP_NOMBRES
    desc = tabla.get(cp)
    return f"{cp} · {desc}" if desc else cp


# ── Parseo del log ───────────────────────────────────────────────────────────

# CP SOLO desde señales inequívocas: el nombre de archivo del test (test_CP03_…)
# o un tag de logger [CP03]. Antes se usaba un regex laxo que producía falsos
# positivos (p.ej. 'CP12') al toparse con números sueltos del log crudo.
_CP_NODE_RE = re.compile(r"test[_-]?CP0*(\d{1,2})", re.I)
_CP_TAG_RE = re.compile(r"\[\s*CP0*(\d{1,2})\s*\]", re.I)
# xdist:  "[gw0] [ 50%] PASSED src/tests/...::test"  → RESULT antes del nodeid
_RES_A = re.compile(r"\b(PASSED|FAILED|ERROR|SKIPPED)\b\s+(\S+::\S+)")
# normal: "src/tests/...::test PASSED"                → nodeid antes del RESULT
_RES_B = re.compile(r"(\S+::\S+)\s+\b(PASSED|FAILED|ERROR|SKIPPED)\b")
_SUM_RE = re.compile(r"(\d+)\s+(passed|failed|error|skipped)")


def cp_en_curso(texto: str):
    """Último CP visto en el log, SOLO desde el nombre del test (test_CP03…) o un
    tag [CP03]. Devuelve None si no hay (p.ej. envíos por pagador, sin CP)."""
    ms = _CP_NODE_RE.findall(texto or "") or _CP_TAG_RE.findall(texto or "")
    if not ms:
        return None
    return f"CP{int(ms[-1]):02d}"


def resultados_por_caso(texto: str) -> dict:
    """{nodeid_corto: 'PASSED'|'FAILED'|...} a partir del log (xdist o normal)."""
    res = {}
    for m in _RES_A.finditer(texto or ""):
        res[_corto(m.group(2))] = m.group(1)
    for m in _RES_B.finditer(texto or ""):
        res.setdefault(_corto(m.group(1)), m.group(2))
    return res


def _corto(nodeid: str) -> str:
    """'src/tests/sanity_general/test_CP01_x.py::test_...[p]' → 'test_CP01_x::test_...'."""
    nid = nodeid.split("/")[-1]
    return nid


def resumen(texto: str) -> dict:
    """Conteo global {'passed':n,'failed':n,...} desde la línea de resumen."""
    out = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
    for m in _SUM_RE.finditer(texto or ""):
        out[m.group(2)] = int(m.group(1))
    return out


_KEEP = re.compile(
    r"\[\s*(?:INFO|WARNING|ERROR|CRITICAL)\s*\]"     # líneas de logger del test
    r"|\b(PASSED|FAILED|ERROR|SKIPPED)\b"            # veredictos de pytest
    r"|=+ .* =+",                                    # cabeceras de sección pytest
)
_DROP = re.compile(
    r"^platform |^cachedir|^rootdir|^plugins:|^collected |^configfile"
    r"|^\s*$|warnings summary|::.*\bwarning\b", re.I)
_TS = re.compile(r"^\d{4}-\d\d-\d\d(?:[ T]\d\d:\d\d:\d\d[,.\d]*)?\s*")


def log_amigable(texto: str, incluir_tecnico: bool = False) -> str:
    """Log legible: pasos del test (logger) + veredictos, sin ruido de pytest.

    Con incluir_tecnico=True devuelve todo (para depurar). El log técnico
    completo siempre queda guardado en el reporte/log de la corrida.
    """
    if incluir_tecnico:
        return texto or ""
    lineas = []
    for ln in (texto or "").splitlines():
        if _DROP.search(ln):
            continue
        if not _KEEP.search(ln):
            continue
        ln = _TS.sub("", ln).rstrip()
        # Compactar el nivel: "[    INFO] msg" → "• msg" ; WARNING/ERROR se marcan
        ln = re.sub(r"\[\s*INFO\s*\]\s*", "• ", ln)
        ln = re.sub(r"\[\s*WARNING\s*\]\s*", "⚠ ", ln)
        ln = re.sub(r"\[\s*(?:ERROR|CRITICAL)\s*\]\s*", "✖ ", ln)
        lineas.append(ln)
    return "\n".join(lineas[-400:])


# ── Ejecución (proceso en background) ────────────────────────────────────────

class Ejecucion:
    """Una corrida de pytest en background, con log en archivo."""

    def __init__(self, label, args, ambiente="test", extra_env=None,
                 con_reporte=True, casos=None, repeticiones=1, duracion_seg=0):
        self.id = uuid.uuid4().hex[:8]
        self.label = label
        self.ambiente = ambiente
        self.casos = casos or []          # CPs esperados (para la gráfica)
        self.repeticiones = repeticiones or 1
        self.duracion_seg = duracion_seg or 0
        self.inicio = datetime.now()
        self.fin = None
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        ts = self.inicio.strftime("%Y%m%d_%H%M%S")
        self.log_path = LOG_DIR / f"{ts}_{self.id}.log"
        self.report_path = REPORT_DIR / f"{ts}_{self.id}.html"

        pytest_args = list(args) + ["-v", "-s", "-p", "no:cacheprovider"]
        if con_reporte:
            pytest_args += [f"--html={self.report_path}", "--self-contained-html"]

        # ¿Repetir? Por CANTIDAD (>1) o por TIEMPO (>0) → usa el driver run_repeat.
        repetir = (self.repeticiones and self.repeticiones > 1) or \
                  (self.duracion_seg and self.duracion_seg > 0)
        if repetir:
            driver = str(RAIZ / "tools" / "run_repeat.py")
            cmd = [sys.executable, driver]
            if self.repeticiones and self.repeticiones > 1:
                cmd += ["--count", str(self.repeticiones)]
            if self.duracion_seg and self.duracion_seg > 0:
                cmd += ["--seconds", str(self.duracion_seg)]
            cmd += ["--", *pytest_args]
        else:
            cmd = [sys.executable, "-m", "pytest", *pytest_args]
        self.cmd = cmd

        env = os.environ.copy()
        env["HERMES_ENV"] = ambiente
        env["PYTHONUNBUFFERED"] = "1"
        # UTF-8 en el subproceso para que el log salga limpio (sin \xNN ni �),
        # coincidiendo con el archivo de log abierto en utf-8. Clave en Windows,
        # cuya consola usa cp1252 por defecto y corrompía acentos/emojis.
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        if extra_env:
            env.update({k: str(v) for k, v in extra_env.items()})

        self._f = open(self.log_path, "w", encoding="utf-8", errors="replace")
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        self.proc = subprocess.Popen(
            cmd, cwd=str(RAIZ), env=env,
            stdout=self._f, stderr=subprocess.STDOUT, text=True, **kwargs)

    # — Estado —
    @property
    def viva(self) -> bool:
        return self.proc.poll() is None

    @property
    def returncode(self):
        return self.proc.poll()

    def duracion(self) -> str:
        fin = self.fin or datetime.now()
        s = int((fin - self.inicio).total_seconds())
        return f"{s // 60}m {s % 60:02d}s"

    def leer_log(self) -> str:
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""

    def refrescar(self):
        """Cierra el archivo si el proceso ya terminó (marca la hora de fin)."""
        if not self.viva and self.fin is None:
            self.fin = datetime.now()
            try:
                self._f.flush(); self._f.close()
            except Exception:
                pass

    def detener(self):
        """Detiene la corrida como un Ctrl+C persistente: mata el árbol de
        procesos (incluye los navegadores lanzados por Playwright)."""
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)],
                               capture_output=True)
            else:
                self.proc.terminate()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=8)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        self.refrescar()

    # — Resumen para la gráfica / historial —
    def snapshot(self) -> dict:
        texto = self.leer_log()
        return {
            "id": self.id,
            "label": self.label,
            "ambiente": self.ambiente,
            "inicio": self.inicio.strftime("%H:%M:%S"),
            "duracion": self.duracion(),
            "viva": self.viva,
            "returncode": self.returncode,
            "cp_en_curso": cp_en_curso(texto),
            "por_caso": resultados_por_caso(texto),
            "resumen": resumen(texto),
            "report": str(self.report_path) if self.report_path.exists() else None,
            "log_path": str(self.log_path),
        }
