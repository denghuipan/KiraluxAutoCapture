"""
Kiralux AutoCapture — Main Entry Point
"""
import sys
import os

# ── DLL / module path setup (must happen before any hardware SDK import) ─────
if getattr(sys, "frozen", False):
    _DATA_DIR = sys._MEIPASS
else:
    _DATA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DLL_PATH = os.path.join(_DATA_DIR, "Native_64_lib")
NKT_PATH = os.path.join(_DATA_DIR, "NKT")
SDK_PATH = os.path.join(_DATA_DIR, "thorlabs_tsi_sdk")

def _add_dir(p: str):
    if not os.path.isdir(p):
        return
    if p not in sys.path:
        sys.path.insert(0, p)
    os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")
    try:
        os.add_dll_directory(p)
    except (AttributeError, OSError):
        pass

for _p in [DLL_PATH, NKT_PATH, SDK_PATH, _DATA_DIR, os.path.join(_DATA_DIR, "NKTPDLL", "x64")]:
    _add_dir(_p)

# Resolve NKT DLL from project folder before NKTThread starts
try:
    from core.nkt_support import prepare_nkt_environment as _prep_nkt
    _nkt_ok, _nkt_err = _prep_nkt()
    if not _nkt_ok:
        print(f"NKT DLL warning: {_nkt_err}")
except Exception as _e:
    print(f"NKT DLL warning: {_e}")

# NOTE: Do NOT import NKTP_DLL here.  The DLL creates an internal IBHandler
# QObject that has thread affinity.  It must be first imported inside the
# dedicated NKTThread so all subsequent DLL calls happen in that same thread.

# ── Qt ────────────────────────────────────────────────────────────────────────
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
from ui.main_window import MainWindow
from core.app_settings import get_settings, APP_NAME, APP_VERSION
from core.nkt_thread import NKTThread


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION.lstrip("v"))
    app.setAttribute(Qt.AA_DontUseNativeMenuBar, False)

    settings = get_settings()
    settings.apply_to_app(app)

    nkt_thread = NKTThread()
    nkt_thread.start()

    win = MainWindow(nkt_thread=nkt_thread)
    win.show()

    code = app.exec()
    nkt_thread.shutdown()
    sys.exit(code)


if __name__ == "__main__":
    main()
