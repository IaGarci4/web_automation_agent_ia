"""
Lanzador de la GUI (Streamlit) del AutomationAgent.

Ventajas frente a `streamlit run gui/app.py` directo:
  • No pide el correo al iniciar (headless).
  • Usa un puerto propio (8502) para NO chocar con otros proyectos Streamlit.
  • Abre el navegador automáticamente.

Uso:
    python run_gui.py
    python run_gui.py --port 8600   # puerto alterno si el 8502 está ocupado
"""

import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

RAIZ = Path(__file__).parent

def _puerto() -> str:
    if "--port" in sys.argv:
        try:
            return sys.argv[sys.argv.index("--port") + 1]
        except IndexError:
            pass
    return os.getenv("GUI_PORT", "8502")


def main():
    port = _puerto()

    def _abrir():
        time.sleep(2.5)
        webbrowser.open(f"http://localhost:{port}")

    threading.Thread(target=_abrir, daemon=True).start()

    cmd = [
        sys.executable, "-m", "streamlit", "run", "gui/app.py",
        "--server.port", port,
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
    ]
    # Ctrl+C detiene Streamlit; el proceso padre también recibe la señal. Lo
    # atrapamos para salir LIMPIO (sin traceback de KeyboardInterrupt).
    try:
        subprocess.run(cmd, cwd=str(RAIZ))
    except KeyboardInterrupt:
        print("\n👋 GUI detenida. ¡Hasta pronto!")
    except Exception as e:
        print(f"\nGUI finalizada ({e}).")


if __name__ == "__main__":
    main()
