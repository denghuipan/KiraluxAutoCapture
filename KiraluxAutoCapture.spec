# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
import os

# ── Data files ────────────────────────────────────────────────────────────────
datas = [
    ('..\\Native_64_lib',    'Native_64_lib'),
    ('..\\NKT',              'NKT'),
    ('..\\thorlabs_tsi_sdk', 'thorlabs_tsi_sdk'),
    ('MANUAL_en.md',         '.'),
    ('MANUAL_zh.md',         '.'),
    ('..\\roi_processor\\core\\roi_finder.py', 'roi_processor/core'),
    ('..\\roi_processor\\core\\image_io.py',   'roi_processor/core'),
]

# ── Binaries: explicitly pull in NKTPDLL.dll if present ──────────────────────
_nkt_dll = os.path.abspath('..\\NKT\\NKTPDLL.dll')
binaries = [(_nkt_dll, 'NKT')] if os.path.isfile(_nkt_dll) else []

hiddenimports = [
    'NKTP_DLL',
    'PyQt5.QtCore', 'PyQt5.QtWidgets', 'PyQt5.QtGui',
    'serial.tools.list_ports',
    'matplotlib', 'matplotlib.backends.backend_qt5agg',
    'tifffile',
    'numpy',
    'core.camera_support',
    'core.roi_postprocess',
    'core.sample_label',
    'core.osa_reduce',
    'core.h5_store',
    'scipy.signal',
    'h5py',
    'core.loop_runner',
    'core.nkt_thread',
    'core.nkt_support',
    'core.hw_tester',
    'core.app_settings',
    'ui.main_window',
    'ui.tab_loop',
    'ui.tab_camera',
    'ui.tab_nkt',
    'ui.tab_osa',
    'ui.tab_hardware_test',
    'ui.settings_dialog',
]
tmp_ret = collect_all('PyQt5')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main.py'],
    # Add NKT folder to pathex so PyInstaller compiles NKTP_DLL.py into the bundle
    pathex=[os.path.abspath('..\\NKT')],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='KiraluxAutoCapture_v2',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
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
    upx=True,
    upx_exclude=[],
    name='KiraluxAutoCapture_v2',
)
