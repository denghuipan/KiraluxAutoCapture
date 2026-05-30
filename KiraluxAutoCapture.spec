# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_submodules
import os

_ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

# ── Data files (native SDKs, DLLs, manuals) ───────────────────────────────────
datas = [
    (os.path.join(_ROOT, "Native_64_lib"),    "Native_64_lib"),
    (os.path.join(_ROOT, "NKT"),              "NKT"),
    (os.path.join(_ROOT, "thorlabs_tsi_sdk"), "thorlabs_tsi_sdk"),
    ("MANUAL_en.md", "."),
    ("MANUAL_zh.md", "."),
    (os.path.join(_ROOT, "roi_processor", "core", "roi_finder.py"), "roi_processor/core"),
    (os.path.join(_ROOT, "roi_processor", "core", "image_io.py"),   "roi_processor/core"),
]

# NKTPDLL — main.py also searches _MEIPASS/NKTPDLL/x64
_nkt_x64 = os.path.join(_ROOT, "NKT", "NKTPDLL", "x64")
if os.path.isdir(_nkt_x64):
    datas.append((_nkt_x64, os.path.join("NKTPDLL", "x64")))
_nkt_root_x64 = os.path.join(_ROOT, "NKTPDLL", "x64")
if os.path.isdir(_nkt_root_x64):
    datas.append((_nkt_root_x64, os.path.join("NKTPDLL", "x64")))

# ── Binaries: NKTPDLL.dll (explicit, in addition to datas tree) ───────────────
binaries = []
for _dll in (
    os.path.join(_ROOT, "NKT", "NKTPDLL", "x64", "NKTPDLL.dll"),
    os.path.join(_ROOT, "NKT", "NKTPDLL.dll"),
    os.path.join(_ROOT, "NKTPDLL", "x64", "NKTPDLL.dll"),
):
    if os.path.isfile(_dll):
        binaries.append((_dll, "NKT"))
        break

hiddenimports = [
    "NKTP_DLL",
    "PyQt5.QtCore", "PyQt5.QtWidgets", "PyQt5.QtGui",
    "serial", "serial.tools", "serial.tools.list_ports",
    "matplotlib", "matplotlib.backends.backend_qt5agg",
    "matplotlib.backends.backend_qtagg",
    "tifffile",
    "numpy",
    "scipy", "scipy.signal",
    "h5py",
    "pyvisa",
    "pyvisa.constants",
    "pyvisa.resources",
    "pyvisa_py",
    "pyvisa_py.protocols",
    "pyvisa_py.protocols.usbtmc",
    "zeroconf",
    # core
    "core.camera_support",
    "core.roi_postprocess",
    "core.sample_label",
    "core.osa_reduce",
    "core.h5_store",
    "core.loop_runner",
    "core.nkt_thread",
    "core.nkt_support",
    "core.hw_tester",
    "core.app_settings",
    "core.pm_meter",
    "core.power_math",
    "core.rf_power_control",
    "core.test_data_runner",
    "core.image_contrast",
    # ui
    "ui.main_window",
    "ui.tab_loop",
    "ui.tab_camera",
    "ui.tab_nkt",
    "ui.tab_osa",
    "ui.tab_hardware_test",
    "ui.tab_test_data",
    "ui.settings_dialog",
    "ui.style_helpers",
    "ui.layout_helpers",
]
hiddenimports += collect_submodules("pyvisa_py")

for _pkg in ("PyQt5", "pyvisa", "h5py", "scipy"):
    try:
        tmp = collect_all(_pkg)
        datas += tmp[0]
        binaries += tmp[1]
        hiddenimports += tmp[2]
    except Exception:
        pass


a = Analysis(
    ["main.py"],
    pathex=[os.path.join(_ROOT, "NKT")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="KiraluxAutoCapture_v2",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="KiraluxAutoCapture_v2",
)
