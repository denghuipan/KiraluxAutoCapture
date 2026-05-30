"""
Hardware Status & Test Tab
  - NKT:     COM warning + 3-step bring-up (Extreme → RF → wavelength/amp), Turn OFF
  - Camera:  status light + test capture + live image preview
  - OSA:     status light + ping test

NKT operations use the shared NKTThread (single persistent thread for all DLL
calls) to avoid Qt IBHandler cross-thread errors.
"""
import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QLabel, QPushButton,
    QSlider, QSizePolicy, QFrame, QLineEdit, QMessageBox
)
from PyQt5.QtCore import Qt, pyqtSlot

import matplotlib
matplotlib.use("Qt5Agg")
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from core.hw_tester import CameraTestWorker, OSAPingWorker, PMTestWorker, PMZeroWorker
from ui.style_helpers import title, muted, warning, mpl_font_size
from ui.layout_helpers import install_scroll_content, prepare_group_box, NoScrollSpinBox, NoScrollDoubleSpinBox


# ── Helpers ───────────────────────────────────────────────────────────────────
def _status_label() -> QLabel:
    lbl = QLabel()
    lbl.setFixedSize(14, 14)
    lbl.setStyleSheet(_style("gray"))
    return lbl


def _style(color: str) -> str:
    colors = {
        "gray":   "#585b70",
        "green":  "#a6e3a1",
        "red":    "#f38ba8",
        "yellow": "#f9e2af",
    }
    c = colors.get(color, color)
    return (
        f"background:{c}; border-radius:7px;"
        f" min-width:14px; max-width:14px;"
        f" min-height:14px; max-height:14px;"
    )


def _section_title(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(title())
    return lbl


# ── Main Tab ──────────────────────────────────────────────────────────────────
class HardwareTestTab(QWidget):
    def __init__(self, main_window=None, nkt_thread=None):
        super().__init__()
        self._main_win  = main_window
        self._nkt_thread = nkt_thread

        # Internal state
        self._nkt_extreme  = -1
        self._nkt_rf       = -1
        self._nkt_sel      = -1
        self._nkt_comport  = None
        self._nkt_step1_done = False
        self._nkt_step2_done = False
        self._nkt_busy       = False
        self._cam_worker   = None
        self._osa_worker   = None
        self._pm_worker    = None

        _, root = install_scroll_content(self)

        root.addWidget(_section_title("Hardware Status & Test"))

        # ── NKT ──────────────────────────────────────────────────────────────
        grp_nkt = QGroupBox("NKT SuperK Laser")
        nkt_layout = QVBoxLayout(grp_nkt)
        nkt_layout.setSpacing(10)
        nkt_layout.setContentsMargins(12, 14, 12, 12)

        port_hint = QLabel(
            "⚠ Always double-check the COM port — Windows may reassign it after replug.\n"
            "Use Scan, then confirm the port in the NKT Laser tab matches your cable."
        )
        port_hint.setWordWrap(True)
        port_hint.setStyleSheet(warning())
        nkt_layout.addWidget(port_hint)

        self.nkt_port_label = QLabel("Current port: —  (not scanned)")
        self.nkt_port_label.setStyleSheet(muted())
        nkt_layout.addWidget(self.nkt_port_label)

        # Status row
        nkt_st_row = QHBoxLayout()
        self.nkt_status = _status_label()
        self.nkt_status_text = QLabel("Not scanned")
        self.nkt_status_text.setStyleSheet("color:#6c7086;")
        nkt_st_row.addWidget(self.nkt_status)
        nkt_st_row.addWidget(self.nkt_status_text)
        nkt_st_row.addStretch()

        self.btn_nkt_scan = QPushButton("Scan all NKT ports")
        self.btn_nkt_scan.setStyleSheet(
            "QPushButton{background:#cba6f7;color:#1e1e2e;font-weight:bold;"
            "padding:4px 12px;border-radius:5px;}"
            "QPushButton:hover{background:#b4befe;}"
            "QPushButton:disabled{background:#313244;color:#585b70;}"
        )
        self.btn_nkt_scan.clicked.connect(self._on_nkt_scan)
        nkt_st_row.addWidget(self.btn_nkt_scan)
        nkt_layout.addLayout(nkt_st_row)

        step_info = QLabel(
            "Workflow: (1) Extreme ON @ 100%  →  (2) RF ON  →  (3) set wavelength & RF power below."
        )
        step_info.setWordWrap(True)
        step_info.setStyleSheet(muted())
        nkt_layout.addWidget(step_info)

        self.btn_nkt_step1 = QPushButton("①  Step 1 — Extreme ON (100%)")
        self.btn_nkt_step1.setEnabled(False)
        self.btn_nkt_step1.setStyleSheet(
            "QPushButton{background:#89b4fa;color:#1e1e2e;font-weight:bold;"
            "padding:6px 14px;border-radius:5px;}"
            "QPushButton:hover{background:#74c7ec;}"
            "QPushButton:disabled{background:#313244;color:#585b70;}"
        )
        self.btn_nkt_step1.clicked.connect(self._on_nkt_step1)
        nkt_layout.addWidget(self.btn_nkt_step1)

        self.btn_nkt_step2 = QPushButton("②  Step 2 — RF ON")
        self.btn_nkt_step2.setEnabled(False)
        self.btn_nkt_step2.setStyleSheet(
            "QPushButton{background:#89b4fa;color:#1e1e2e;font-weight:bold;"
            "padding:6px 14px;border-radius:5px;}"
            "QPushButton:hover{background:#74c7ec;}"
            "QPushButton:disabled{background:#313244;color:#585b70;}"
        )
        self.btn_nkt_step2.clicked.connect(self._on_nkt_step2)
        nkt_layout.addWidget(self.btn_nkt_step2)

        wl_row = QHBoxLayout()
        wl_row.addWidget(QLabel("Step 3 — Wavelength:"))
        self.nkt_wl = NoScrollDoubleSpinBox()
        self.nkt_wl.setRange(400, 1100)
        self.nkt_wl.setValue(670.0)
        self.nkt_wl.setSuffix(" nm")
        self.nkt_wl.setDecimals(1)
        self.nkt_wl.setFixedWidth(110)
        wl_row.addWidget(self.nkt_wl)

        wl_row.addSpacing(16)
        wl_row.addWidget(QLabel("RF ch0 amp:"))
        self.nkt_amp_slider = QSlider(Qt.Horizontal)
        self.nkt_amp_slider.setRange(0, 1000)
        self.nkt_amp_slider.setValue(1000)
        self.nkt_amp_slider.setFixedWidth(160)
        self.nkt_amp_label = QLabel("100%")
        self.nkt_amp_label.setFixedWidth(44)
        self.nkt_amp_slider.valueChanged.connect(
            lambda v: self.nkt_amp_label.setText(f"{v/10:.0f}%")
        )
        wl_row.addWidget(self.nkt_amp_slider)
        wl_row.addWidget(self.nkt_amp_label)
        wl_row.addStretch()
        nkt_layout.addLayout(wl_row)

        self.btn_nkt_step3 = QPushButton("③  Step 3 — Apply emission / RF amp / wavelength")
        self.btn_nkt_step3.setEnabled(False)
        self.btn_nkt_step3.setStyleSheet(
            "QPushButton{background:#a6e3a1;color:#1e1e2e;font-weight:bold;"
            "padding:6px 14px;border-radius:5px;}"
            "QPushButton:hover{background:#94e2d5;}"
            "QPushButton:disabled{background:#313244;color:#585b70;}"
        )
        self.btn_nkt_step3.clicked.connect(self._on_nkt_step3)
        nkt_layout.addWidget(self.btn_nkt_step3)

        btn_off_row = QHBoxLayout()
        self.btn_nkt_off = QPushButton("Turn OFF")
        self.btn_nkt_off.setEnabled(False)
        self.btn_nkt_off.setStyleSheet(
            "QPushButton{background:#f38ba8;color:#1e1e2e;font-weight:bold;"
            "padding:5px 12px;border-radius:5px;}"
            "QPushButton:hover{background:#eba0ac;}"
            "QPushButton:disabled{background:#313244;color:#585b70;}"
        )
        self.btn_nkt_off.clicked.connect(self._on_nkt_off)
        btn_off_row.addWidget(self.btn_nkt_off)
        btn_off_row.addStretch()
        nkt_layout.addLayout(btn_off_row)

        prepare_group_box(grp_nkt)
        root.addWidget(grp_nkt)

        # ── Camera ────────────────────────────────────────────────────────────
        grp_cam = QGroupBox("Camera  (Thorlabs Kiralux)")
        cam_layout = QVBoxLayout(grp_cam)
        cam_layout.setSpacing(10)
        cam_layout.setContentsMargins(12, 14, 12, 12)

        st_row = QHBoxLayout()
        self.cam_status = _status_label()
        self.cam_status_text = QLabel("Not tested")
        self.cam_status_text.setStyleSheet("color:#6c7086;")
        st_row.addWidget(self.cam_status)
        st_row.addWidget(self.cam_status_text)
        st_row.addStretch()

        param_row = QHBoxLayout()
        param_row.addWidget(QLabel("Exposure:"))
        self.cam_exp = NoScrollDoubleSpinBox()
        self.cam_exp.setRange(0.03, 22806.0)
        self.cam_exp.setValue(0.06)
        self.cam_exp.setSuffix(" ms")
        self.cam_exp.setDecimals(3)
        self.cam_exp.setFixedWidth(110)
        param_row.addWidget(self.cam_exp)
        param_row.addSpacing(12)
        param_row.addWidget(QLabel("Gain:"))
        self.cam_gain = NoScrollSpinBox()
        self.cam_gain.setRange(0, 480)
        self.cam_gain.setValue(0)
        self.cam_gain.setFixedWidth(70)
        param_row.addWidget(self.cam_gain)
        param_row.addStretch()

        self.btn_cam_test = QPushButton("Capture Test Frame")
        self.btn_cam_test.setStyleSheet(
            "QPushButton{background:#89b4fa;color:#1e1e2e;font-weight:bold;"
            "padding:5px 14px;border-radius:5px;}"
            "QPushButton:hover{background:#74c7ec;}"
            "QPushButton:disabled{background:#313244;color:#585b70;}"
        )
        self.btn_cam_test.clicked.connect(self._on_cam_test)

        self._cam_frame_cache = None
        contrast_row = QHBoxLayout()
        contrast_row.addWidget(QLabel("vmin %:"))
        self.cam_vmin = NoScrollSpinBox()
        self.cam_vmin.setRange(0, 99)
        self.cam_vmin.setValue(0)
        self.cam_vmin.setSuffix(" %")
        self.cam_vmin.setFixedWidth(70)
        self.cam_vmin.valueChanged.connect(self._redraw_cam)
        contrast_row.addWidget(self.cam_vmin)
        contrast_row.addSpacing(12)
        contrast_row.addWidget(QLabel("vmax %:"))
        self.cam_vmax = NoScrollSpinBox()
        self.cam_vmax.setRange(1, 100)
        self.cam_vmax.setValue(100)
        self.cam_vmax.setSuffix(" %")
        self.cam_vmax.setFixedWidth(70)
        self.cam_vmax.valueChanged.connect(self._redraw_cam)
        contrast_row.addWidget(self.cam_vmax)
        contrast_row.addStretch()

        self._cam_fig = Figure(facecolor="#1e1e2e", tight_layout=True)
        self._cam_canvas = FigureCanvas(self._cam_fig)
        self._cam_canvas.setMinimumHeight(200)
        self._cam_canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._cam_ax = self._cam_fig.add_subplot(111)
        self._style_cam_axes()
        self._cam_ax.text(0.5, 0.5, "No frame yet",
                          ha="center", va="center",
                          transform=self._cam_ax.transAxes,
                          color="#585b70", fontsize=mpl_font_size(1))
        self._cam_canvas.draw()

        cam_layout.addLayout(st_row)
        cam_layout.addLayout(param_row)
        cam_layout.addWidget(self.btn_cam_test)
        cam_layout.addLayout(contrast_row)
        cam_layout.addWidget(self._cam_canvas)
        prepare_group_box(grp_cam)
        root.addWidget(grp_cam)

        # ── PM100D ──────────────────────────────────────────────────────────
        grp_pm = QGroupBox("Power Meter  (Thorlabs PM100D — USB/VISA)")
        pm_layout = QVBoxLayout(grp_pm)
        pm_layout.setSpacing(10)
        pm_layout.setContentsMargins(12, 14, 12, 12)

        pm_st_row = QHBoxLayout()
        self.pm_status = _status_label()
        self.pm_status_text = QLabel("Not tested")
        self.pm_status_text.setStyleSheet("color:#6c7086;")
        pm_st_row.addWidget(self.pm_status)
        pm_st_row.addWidget(self.pm_status_text)
        pm_st_row.addStretch()
        pm_layout.addLayout(pm_st_row)

        pm_visa_row = QHBoxLayout()
        pm_visa_row.addWidget(QLabel("VISA resource:"))
        self.pm_visa = QLineEdit("")
        self.pm_visa.setPlaceholderText("USB0::0x1313::0x8078::P0001234::INSTR")
        self.btn_pm_scan = QPushButton("Scan")
        self.btn_pm_scan.setFixedWidth(52)
        self.btn_pm_scan.clicked.connect(self._on_pm_scan)
        self.btn_pm_read = QPushButton("Read Power")
        self.btn_pm_read.setStyleSheet(
            "QPushButton{background:#89b4fa;color:#1e1e2e;font-weight:bold;"
            "padding:5px 14px;border-radius:5px;}"
            "QPushButton:hover{background:#74c7ec;}"
            "QPushButton:disabled{background:#313244;color:#585b70;}"
        )
        self.btn_pm_read.clicked.connect(self._on_pm_read)
        self.btn_pm_zero = QPushButton("Zero (Dark Adj)")
        self.btn_pm_zero.setStyleSheet(
            "QPushButton{background:#a6e3a1;color:#1e1e2e;font-weight:bold;"
            "padding:5px 14px;border-radius:5px;}"
            "QPushButton:hover{background:#94e2d5;}"
            "QPushButton:disabled{background:#313244;color:#585b70;}"
        )
        self.btn_pm_zero.clicked.connect(self._on_pm_zero)
        pm_visa_row.addWidget(self.pm_visa)
        pm_visa_row.addWidget(self.btn_pm_scan)
        pm_visa_row.addWidget(self.btn_pm_read)
        pm_visa_row.addWidget(self.btn_pm_zero)
        pm_layout.addLayout(pm_visa_row)

        # PM wavelength setting
        pm_wl_row = QHBoxLayout()
        pm_wl_row.addWidget(QLabel("Wavelength:"))
        self.pm_wavelength = NoScrollDoubleSpinBox()
        self.pm_wavelength.setRange(400, 2000)
        self.pm_wavelength.setDecimals(1)
        self.pm_wavelength.setValue(650.0)
        self.pm_wavelength.setSuffix("  nm")
        self.pm_wavelength.setFixedWidth(100)
        self.pm_wavelength.setToolTip("Set PM100D correction wavelength (must match laser)")
        pm_wl_row.addWidget(self.pm_wavelength)
        pm_wl_row.addStretch()
        pm_layout.addLayout(pm_wl_row)

        pm_hint = QLabel(
            "Pure Python: pip install pyvisa + NI-VISA. Same resource string is used in Test Data tab."
        )
        pm_hint.setWordWrap(True)
        pm_hint.setStyleSheet(muted())
        pm_layout.addWidget(pm_hint)
        prepare_group_box(grp_pm)
        root.addWidget(grp_pm)

        # ── OSA ──────────────────────────────────────────────────────────────
        grp_osa = QGroupBox("OSA  (Yokogawa)")
        osa_layout = QHBoxLayout(grp_osa)
        osa_layout.setSpacing(10)
        osa_layout.setContentsMargins(12, 14, 12, 12)
        self.osa_status = _status_label()
        self.osa_status_text = QLabel("Not tested")
        self.osa_status_text.setStyleSheet("color:#6c7086;")
        self.btn_osa_ping = QPushButton("Ping OSA")
        self.btn_osa_ping.setStyleSheet(
            "QPushButton{background:#89b4fa;color:#1e1e2e;font-weight:bold;"
            "padding:5px 14px;border-radius:5px;}"
            "QPushButton:hover{background:#74c7ec;}"
            "QPushButton:disabled{background:#313244;color:#585b70;}"
        )
        self.btn_osa_ping.clicked.connect(self._on_osa_ping)
        osa_layout.addWidget(self.osa_status)
        osa_layout.addWidget(self.osa_status_text)
        osa_layout.addWidget(self.btn_osa_ping)
        prepare_group_box(grp_osa)
        root.addWidget(grp_osa)

        # ── Connect NKTThread signals ────────────────────────────────────────
        if self._nkt_thread:
            t = self._nkt_thread
            t.scan_done.connect(self._on_nkt_found, Qt.QueuedConnection)
            t.scan_error.connect(self._on_nkt_scan_error, Qt.QueuedConnection)
            t.step_done.connect(self._on_nkt_step_ok, Qt.QueuedConnection)
            t.step_error.connect(self._on_nkt_step_err, Qt.QueuedConnection)
            t.off_done.connect(self._on_nkt_off_done, Qt.QueuedConnection)
            t.off_error.connect(
                lambda m: self._set_nkt_status("red", m), Qt.QueuedConnection
            )

    # ── Camera axes styling ───────────────────────────────────────────────
    def _style_cam_axes(self):
        ax = self._cam_ax
        ax.set_facecolor("#181825")
        for spine in ax.spines.values():
            spine.set_color("#45475a")
        ax.tick_params(colors="#6c7086", labelsize=mpl_font_size(-1))
        ax.set_xlabel("X  (pixels)", color="#6c7086", fontsize=mpl_font_size())
        ax.set_ylabel("Y  (pixels)", color="#6c7086", fontsize=mpl_font_size())

    def _redraw_cam(self):
        if self._cam_frame_cache is not None:
            self._show_frame(self._cam_frame_cache)

    def _show_frame(self, img: np.ndarray):
        self._cam_frame_cache = img
        h, w = img.shape
        pmax = img.max() if img.max() > 0 else 1
        vmin = pmax * self.cam_vmin.value() / 100.0
        vmax = pmax * self.cam_vmax.value() / 100.0
        if vmax <= vmin:
            vmax = vmin + 1
        self._cam_ax.cla()
        self._style_cam_axes()
        self._cam_ax.imshow(
            img, cmap="gray", vmin=vmin, vmax=vmax,
            aspect="auto", interpolation="nearest",
            extent=[0, w, h, 0],
        )
        self._cam_ax.set_xlim(0, w)
        self._cam_ax.set_ylim(h, 0)
        self._cam_ax.set_title(
            f"{w}×{h} px  |  max={img.max()}  "
            f"vmin={self.cam_vmin.value()}%  vmax={self.cam_vmax.value()}%",
            color="#cdd6f4", fontsize=mpl_font_size(), pad=3
        )
        self._cam_canvas.draw_idle()

    # ── Helpers ───────────────────────────────────────────────────────────
    def _get_cam_cfg(self) -> dict:
        if self._main_win and hasattr(self._main_win, "cam_tab"):
            return self._main_win.cam_tab.get_config()
        return {
            "exposure_time_ms": 0.06,
            "gain": 0,
            "timeout_ms": 5000,
            "roi": (0, 0, 4096, 2160),
        }

    def _get_nkt_cfg(self) -> dict:
        if self._main_win and hasattr(self._main_win, "nkt_tab"):
            cfg = dict(self._main_win.nkt_tab.get_config())
        else:
            cfg = {"comport": "COM5", "emission_percent": 100}
        if self._nkt_comport:
            cfg["comport"] = self._nkt_comport
        return cfg

    def _get_osa_cfg(self) -> dict:
        if self._main_win and hasattr(self._main_win, "osa_tab"):
            return self._main_win.osa_tab.get_config()
        return {"osa_host": "192.168.0.1", "osa_port": 10001}

    def _set_cam_status(self, color: str, text: str):
        self.cam_status.setStyleSheet(_style(color))
        self.cam_status_text.setText(text)

    def _set_nkt_status(self, color: str, text: str):
        self.nkt_status.setStyleSheet(_style(color))
        self.nkt_status_text.setText(text)

    def _set_osa_status(self, color: str, text: str):
        self.osa_status.setStyleSheet(_style(color))
        self.osa_status_text.setText(text)

    def _set_pm_status(self, color: str, text: str):
        self.pm_status.setStyleSheet(_style(color))
        self.pm_status_text.setText(text)

    def _nkt_set_busy(self, busy: bool):
        self._nkt_busy = busy
        if busy:
            self.btn_nkt_scan.setEnabled(False)
            self.btn_nkt_step1.setEnabled(False)
            self.btn_nkt_step2.setEnabled(False)
            self.btn_nkt_step3.setEnabled(False)
            self.btn_nkt_off.setEnabled(False)

    def _nkt_restore_buttons(self):
        self._nkt_busy = False
        self.btn_nkt_scan.setEnabled(True)
        has = (self._nkt_comport and self._nkt_extreme >= 0 and self._nkt_rf >= 0)
        self.btn_nkt_step1.setEnabled(bool(has))
        self.btn_nkt_step2.setEnabled(bool(has) and self._nkt_step1_done)
        self.btn_nkt_step3.setEnabled(bool(has) and self._nkt_step2_done)
        self.btn_nkt_off.setEnabled(bool(has))

    # ── Camera ────────────────────────────────────────────────────────────
    def _on_cam_test(self):
        self.btn_cam_test.setEnabled(False)
        self._set_cam_status("yellow", "Capturing...")
        cam_cfg = self._get_cam_cfg()
        self._cam_worker = CameraTestWorker(
            exposure_ms=cam_cfg.get("exposure_time_ms", self.cam_exp.value()),
            gain=cam_cfg.get("gain", self.cam_gain.value()),
            timeout_ms=cam_cfg.get("timeout_ms", 5000),
            roi=cam_cfg.get("roi", (0, 0, 4096, 2160)),
        )
        self._cam_worker.success_signal.connect(self._on_cam_frame, Qt.QueuedConnection)
        self._cam_worker.error_signal.connect(self._on_cam_error, Qt.QueuedConnection)
        self._cam_worker.finished.connect(
            lambda: self.btn_cam_test.setEnabled(True), Qt.QueuedConnection
        )
        self._cam_worker.start()

    @pyqtSlot(np.ndarray)
    def _on_cam_frame(self, img: np.ndarray):
        self._set_cam_status("green", f"OK  —  {img.shape[1]}×{img.shape[0]} px  dtype {img.dtype}")
        self._show_frame(img)

    def _on_cam_error(self, msg: str):
        self._set_cam_status("red", msg)
        self._cam_ax.cla()
        self._style_cam_axes()
        self._cam_ax.text(0.5, 0.5, f"Error: {msg}",
                          ha="center", va="center",
                          transform=self._cam_ax.transAxes,
                          color="#f38ba8", fontsize=mpl_font_size())
        self._cam_canvas.draw_idle()

    # ── NKT scan ─────────────────────────────────────────────────────────
    def _on_nkt_scan(self):
        if not self._nkt_thread or self._nkt_busy:
            return
        if self._main_win and hasattr(self._main_win, "nkt_tab"):
            preferred = self._main_win.nkt_tab.get_config().get("comport", "")
        else:
            preferred = ""
        hint = preferred if preferred and not preferred.startswith("(no ports") else "auto"
        self._nkt_set_busy(True)
        self._set_nkt_status("yellow", f"Scanning NKTP ports (prefer {hint})…")
        self._nkt_thread.submit_scan(preferred)

    @pyqtSlot(str, int, int, int)
    def _on_nkt_found(self, comport: str, extreme: int, RF_power: int, SuperK_sel: int):
        self._nkt_comport = comport
        self._nkt_extreme = extreme
        self._nkt_rf      = RF_power
        self._nkt_sel     = SuperK_sel
        if self._main_win and hasattr(self._main_win, "nkt_tab"):
            nkt_tab = self._main_win.nkt_tab
            combo = nkt_tab.combo_port
            idx = combo.findText(comport)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            nkt_tab.set_nkt_addresses(comport, extreme, RF_power)
        sk_txt = SuperK_sel if SuperK_sel >= 0 else "—"
        self.nkt_port_label.setText(
            f"Current port: {comport}  — Windows may change COM after replug; re-scan if needed."
        )
        self._set_nkt_status(
            "green",
            f"{comport}  |  extreme@{extreme}  RF@{RF_power}  sel@{sk_txt}"
        )
        self._nkt_step1_done = False
        self._nkt_step2_done = False
        self._nkt_restore_buttons()

    def _on_nkt_scan_error(self, msg: str):
        self._nkt_comport = None
        self.nkt_port_label.setText("Current port: —  (not scanned)")
        self._set_nkt_status("red", msg)
        self._nkt_step1_done = False
        self._nkt_step2_done = False
        self._nkt_restore_buttons()

    # ── NKT steps ────────────────────────────────────────────────────────
    def _on_nkt_step1(self):
        if not self._nkt_thread or self._nkt_busy:
            return
        cfg = self._get_nkt_cfg()
        comport = cfg.get("comport", "COM5")
        self._nkt_step1_done = False
        self._nkt_step2_done = False
        self._nkt_set_busy(True)
        self._set_nkt_status("yellow", "Step 1: Extreme ON (100%)…")
        self._nkt_thread.submit_step1(comport, self._nkt_extreme)

    def _on_nkt_step2(self):
        if not self._nkt_thread or self._nkt_busy:
            return
        if not self._nkt_step1_done:
            self._set_nkt_status("yellow", "Run Step 1 first (Extreme ON).")
            return
        cfg = self._get_nkt_cfg()
        comport = cfg.get("comport", "COM5")
        self._nkt_step2_done = False
        self._nkt_set_busy(True)
        self._set_nkt_status("yellow", "Step 2: RF ON…")
        self._nkt_thread.submit_step2(comport, self._nkt_rf)

    def _on_nkt_step3(self):
        if not self._nkt_thread or self._nkt_busy:
            return
        if not self._nkt_step2_done:
            self._set_nkt_status("yellow", "Run Step 2 first (RF ON).")
            return
        cfg = self._get_nkt_cfg()
        comport = cfg.get("comport", "COM5")
        wl  = self.nkt_wl.value()
        amp = self.nkt_amp_slider.value()
        self._nkt_set_busy(True)
        self._set_nkt_status("yellow", f"Step 3: emission + RF amp + {wl:.1f} nm…")
        self._nkt_thread.submit_step3(comport, self._nkt_extreme, self._nkt_rf, amp, wl)

    @pyqtSlot(str)
    def _on_nkt_step_ok(self, msg: str):
        if "Step 1" in msg:
            self._nkt_step1_done = True
        elif "Step 2" in msg:
            self._nkt_step2_done = True
        self._set_nkt_status("green", msg)
        self._nkt_restore_buttons()

    @pyqtSlot(str)
    def _on_nkt_step_err(self, msg: str):
        self._set_nkt_status("red", msg)
        self._nkt_restore_buttons()

    # ── NKT OFF ──────────────────────────────────────────────────────────
    def _on_nkt_off(self):
        if not self._nkt_thread or self._nkt_busy:
            return
        cfg = self._get_nkt_cfg()
        comport = cfg.get("comport", "COM5")
        self._nkt_set_busy(True)
        self._set_nkt_status("yellow", "Turning off...")
        self._nkt_thread.submit_off(comport, self._nkt_extreme, self._nkt_rf)

    @pyqtSlot(str)
    def _on_nkt_off_done(self, msg: str):
        self._set_nkt_status("gray", msg)
        self._nkt_step1_done = False
        self._nkt_step2_done = False
        self._nkt_restore_buttons()

    # ── PM100D ───────────────────────────────────────────────────────────
    def _on_pm_scan(self):
        from core.pm_meter import list_visa_resources

        resources = list_visa_resources()
        if not resources:
            QMessageBox.warning(
                self,
                "VISA Scan",
                "No VISA devices found.\n\n"
                "Check PM100D USB, Thorlabs drivers, and NI-VISA.\n"
                "Install: pip install pyvisa",
            )
            self._set_pm_status("red", "No VISA devices")
            return
        pm_like = [r for r in resources if "1313" in r or "PM" in r.upper()]
        pick = pm_like[0] if pm_like else resources[0]
        self.pm_visa.setText(pick)
        self._sync_pm_visa_to_test_tab(pick)
        self._set_pm_status("green", f"Found {len(resources)} device(s)")
        if len(resources) > 1:
            QMessageBox.information(
                self,
                "VISA Scan",
                "Found:\n" + "\n".join(resources) + f"\n\nSelected: {pick}",
            )

    def _sync_pm_visa_to_test_tab(self, resource: str):
        if self._main_win and hasattr(self._main_win, "test_tab"):
            self._main_win.test_tab.edit_visa.setText(resource)

    def _on_pm_read(self):
        resource = self.pm_visa.text().strip()
        if not resource:
            self._set_pm_status("red", "Enter or Scan VISA resource first")
            return
        self._sync_pm_visa_to_test_tab(resource)
        self.btn_pm_read.setEnabled(False)
        self.btn_pm_scan.setEnabled(False)
        self._set_pm_status("yellow", "Reading PM100D...")
        wl = self.pm_wavelength.value()
        self._pm_worker = PMTestWorker(resource, wavelength_nm=wl)
        self._pm_worker.success_signal.connect(
            lambda m: self._set_pm_status("green", m), Qt.QueuedConnection
        )
        self._pm_worker.error_signal.connect(
            lambda m: self._set_pm_status("red", m), Qt.QueuedConnection
        )
        self._pm_worker.finished.connect(self._on_pm_read_done, Qt.QueuedConnection)
        self._pm_worker.start()

    def _on_pm_read_done(self):
        self.btn_pm_read.setEnabled(True)
        self.btn_pm_scan.setEnabled(True)

    def _on_pm_zero(self):
        resource = self.pm_visa.text().strip()
        if not resource:
            self._set_pm_status("red", "Scan or enter VISA resource first")
            return
        wl = self.pm_wavelength.value()
        self.btn_pm_zero.setEnabled(False)
        self.btn_pm_read.setEnabled(False)
        self._set_pm_status("yellow", f"Zeroing (cover sensor!) @ {wl:.0f} nm...")
        self._pm_worker = PMZeroWorker(resource, wavelength_nm=wl)
        self._pm_worker.success_signal.connect(
            lambda m: self._set_pm_status("green", m), Qt.QueuedConnection
        )
        self._pm_worker.error_signal.connect(
            lambda m: self._set_pm_status("red", m), Qt.QueuedConnection
        )
        self._pm_worker.finished.connect(self._on_pm_zero_done, Qt.QueuedConnection)
        self._pm_worker.start()

    def _on_pm_zero_done(self):
        self.btn_pm_zero.setEnabled(True)
        self.btn_pm_read.setEnabled(True)

    # ── OSA ping ─────────────────────────────────────────────────────────
    def _on_osa_ping(self):
        cfg  = self._get_osa_cfg()
        host = cfg.get("osa_host", "192.168.0.1")
        port = cfg.get("osa_port", 10001)
        self.btn_osa_ping.setEnabled(False)
        self._set_osa_status("yellow", f"Pinging {host}:{port}...")
        self._osa_worker = OSAPingWorker(host, port)
        self._osa_worker.success_signal.connect(
            lambda m: self._set_osa_status("green", m), Qt.QueuedConnection
        )
        self._osa_worker.error_signal.connect(
            lambda m: self._set_osa_status("red", m), Qt.QueuedConnection
        )
        self._osa_worker.finished.connect(
            lambda: self.btn_osa_ping.setEnabled(True), Qt.QueuedConnection
        )
        self._osa_worker.start()
