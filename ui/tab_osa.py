"""
Yokogawa OSA settings tab — with embedded live spectrum plot.
"""
import numpy as np

import os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QLabel,
    QLineEdit, QCheckBox, QPushButton,
    QSizePolicy, QFileDialog, QFrame,
)
from PyQt5.QtCore import Qt, pyqtSlot

# Matplotlib embedded in Qt
import matplotlib
matplotlib.use("Qt5Agg")
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from core.hw_tester import OSAScanWorker
from ui.style_helpers import (
    muted, accent, title, hint, warning, error, success,
    checkbox_emphasis, mpl_font_size,
)
from ui.layout_helpers import (
    install_scroll_content, configure_form_layout, prepare_group_box, GROUP_SPACING,
    NoScrollSpinBox, NoScrollDoubleSpinBox, NoScrollComboBox,
)


class OSATab(QWidget):
    def __init__(self):
        super().__init__()
        self._scan_worker = None
        # Keep the last plotted arrays so loop updates can reuse the canvas
        self._last_x = None
        self._last_y = None

        _, root = install_scroll_content(self)

        # ── Top: settings (fixed height, priority for labels/controls) ───────
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(10)
        self.chk_enable = QCheckBox("Enable OSA in capture loop")
        self.chk_enable.setChecked(False)
        self.chk_enable.setStyleSheet(checkbox_emphasis("#f9e2af"))
        self.chk_enable.toggled.connect(self._on_enable)
        ctrl_row.addWidget(self.chk_enable)

        self.chk_osa_only = QCheckBox("Only OSA  (NKT + OSA, no Camera)")
        self.chk_osa_only.setChecked(False)
        self.chk_osa_only.setStyleSheet(checkbox_emphasis("#cba6f7"))
        self.chk_osa_only.toggled.connect(self._on_osa_only_toggled)
        ctrl_row.addWidget(self.chk_osa_only)
        ctrl_row.addStretch()

        self.btn_scan = QPushButton("Scan Once")
        self.btn_scan.setStyleSheet(
            "QPushButton{background:#89b4fa;color:#1e1e2e;font-weight:bold;"
            "padding:6px 14px;border-radius:5px;}"
            "QPushButton:hover{background:#74c7ec;}"
            "QPushButton:disabled{background:#313244;color:#585b70;}"
        )
        self.btn_scan.clicked.connect(self._on_scan_once)
        ctrl_row.addWidget(self.btn_scan)

        self.lbl_scan_status = QLabel("Idle")
        self.lbl_scan_status.setStyleSheet(muted())
        self.lbl_scan_status.setMinimumWidth(120)
        ctrl_row.addWidget(self.lbl_scan_status)
        root.addLayout(ctrl_row)

        # Settings — stacked group boxes
        settings_col = QVBoxLayout()
        settings_col.setSpacing(GROUP_SPACING)

        # Connection
        self.grp_conn = QGroupBox("Network Connection")
        form_c = QFormLayout(self.grp_conn)
        configure_form_layout(form_c)

        self.edit_host = QLineEdit("192.168.0.1")
        self.spin_port = NoScrollSpinBox()
        self.spin_port.setRange(1, 65535)
        self.spin_port.setValue(10001)

        form_c.addRow("Host IP:", self.edit_host)
        form_c.addRow("Port:", self.spin_port)
        prepare_group_box(self.grp_conn)
        settings_col.addWidget(self.grp_conn)

        # Measurement params
        self.grp_meas = QGroupBox("Measurement Parameters")
        form_m = QFormLayout(self.grp_meas)
        configure_form_layout(form_m)

        self.spin_wl_start = NoScrollDoubleSpinBox()
        self.spin_wl_start.setRange(400, 2000)
        self.spin_wl_start.setValue(610.0)
        self.spin_wl_start.setSuffix("  nm")

        self.spin_wl_stop = NoScrollDoubleSpinBox()
        self.spin_wl_stop.setRange(400, 2000)
        self.spin_wl_stop.setValue(700.0)
        self.spin_wl_stop.setSuffix("  nm")

        self.spin_resolution = NoScrollDoubleSpinBox()
        self.spin_resolution.setRange(0.02, 5.0)
        self.spin_resolution.setValue(0.5)
        self.spin_resolution.setSuffix("  nm")
        self.spin_resolution.setDecimals(2)

        self.spin_rlevel = NoScrollSpinBox()
        self.spin_rlevel.setRange(1, 100000)
        self.spin_rlevel.setValue(2000)
        self.spin_rlevel.setSuffix("  nW")

        self.spin_sampling = NoScrollDoubleSpinBox()
        self.spin_sampling.setRange(0.001, 10.0)
        self.spin_sampling.setValue(0.05)
        self.spin_sampling.setSuffix("  nm")
        self.spin_sampling.setDecimals(3)

        self.spin_avg = NoScrollSpinBox()
        self.spin_avg.setRange(1, 1000)
        self.spin_avg.setValue(1)

        self.combo_sensitivity = NoScrollComboBox()
        self.combo_sensitivity.addItems(["norm", "mid", "high1", "high2", "high3"])
        self.combo_sensitivity.setCurrentText("mid")

        self.combo_smoothing = NoScrollComboBox()
        self.combo_smoothing.addItems(["OFF", "2", "4", "8", "16", "32"])

        form_m.addRow("WL start:", self.spin_wl_start)
        form_m.addRow("WL stop:", self.spin_wl_stop)
        form_m.addRow("Resolution:", self.spin_resolution)
        form_m.addRow("Ref level:", self.spin_rlevel)
        form_m.addRow("Sampling:", self.spin_sampling)
        form_m.addRow("Averages:", self.spin_avg)
        form_m.addRow("Sensitivity:", self.combo_sensitivity)
        form_m.addRow("Smoothing:", self.combo_smoothing)
        prepare_group_box(self.grp_meas)
        settings_col.addWidget(self.grp_meas)

        # ── Save settings ─────────────────────────────────────────────────────
        self.grp_save = QGroupBox("Save Settings")
        form_s = QFormLayout(self.grp_save)
        configure_form_layout(form_s)

        # Output directory
        dir_row = QHBoxLayout()
        self.edit_save_dir = QLineEdit(os.path.expanduser("~/Desktop/osa_output"))
        self.edit_save_dir.setPlaceholderText("Output folder...")
        btn_browse = QPushButton("Browse")
        btn_browse.setFixedWidth(60)
        btn_browse.clicked.connect(self._browse_save_dir)
        dir_row.addWidget(self.edit_save_dir)
        dir_row.addWidget(btn_browse)
        form_s.addRow("Output dir:", dir_row)

        # File prefix
        self.edit_prefix = QLineEdit("osa")
        self.edit_prefix.setPlaceholderText("e.g. osa  →  osa_0_3.csv")
        form_s.addRow("File prefix:", self.edit_prefix)

        # Save toggles
        chk_row = QHBoxLayout()
        self.chk_save_csv = QCheckBox("CSV")
        self.chk_save_csv.setChecked(True)
        self.chk_save_png = QCheckBox("PNG")
        self.chk_save_png.setChecked(True)
        chk_row.addWidget(self.chk_save_csv)
        chk_row.addWidget(self.chk_save_png)
        chk_row.addStretch()
        form_s.addRow("Save:", chk_row)
        prepare_group_box(self.grp_save)
        settings_col.addWidget(self.grp_save)

        # ── Reduce + H5 (optional, separate from camera H5) ───────────────────
        self.grp_h5 = QGroupBox("Reduce + H5  (optional)")
        form_h5 = QFormLayout(self.grp_h5)
        configure_form_layout(form_h5)
        self.chk_osa_h5 = QCheckBox("Append reduced spectrum to H5")
        self.chk_osa_h5.setToolTip(
            "Uses the same labels as cropped images: roundXX_loopYY_j"
        )
        self.edit_osa_h5 = QLineEdit("osa_spectra.h5")
        self.spin_reduce_points = NoScrollSpinBox()
        self.spin_reduce_points.setRange(2, 5000)
        self.spin_reduce_points.setValue(300)
        self.spin_reduce_wl_min = NoScrollDoubleSpinBox()
        self.spin_reduce_wl_min.setRange(400, 2000)
        self.spin_reduce_wl_min.setValue(610.0)
        self.spin_reduce_wl_min.setSuffix(" nm")
        self.spin_reduce_wl_max = NoScrollDoubleSpinBox()
        self.spin_reduce_wl_max.setRange(400, 2000)
        self.spin_reduce_wl_max.setValue(680.0)
        self.spin_reduce_wl_max.setSuffix(" nm")
        self.spin_reduce_window = NoScrollSpinBox()
        self.spin_reduce_window.setRange(3, 501)
        self.spin_reduce_window.setValue(31)
        self.spin_reduce_poly = NoScrollSpinBox()
        self.spin_reduce_poly.setRange(1, 9)
        self.spin_reduce_poly.setValue(3)
        form_h5.addRow(self.chk_osa_h5)
        form_h5.addRow("OSA H5 file:", self.edit_osa_h5)
        form_h5.addRow("Reduce to N points:", self.spin_reduce_points)
        form_h5.addRow("WL range min:", self.spin_reduce_wl_min)
        form_h5.addRow("WL range max:", self.spin_reduce_wl_max)
        form_h5.addRow("SavGol window:", self.spin_reduce_window)
        form_h5.addRow("SavGol polyorder:", self.spin_reduce_poly)
        prepare_group_box(self.grp_h5)
        settings_col.addWidget(self.grp_h5)
        root.addLayout(settings_col)

        info = QLabel(
            "If OSA is unreachable at loop start, NKT + camera continue without OSA."
        )
        info.setStyleSheet(hint())
        info.setWordWrap(True)
        root.addWidget(info)

        # ── Bottom: compact spectrum preview (fixed, non-resizable) ───────────
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #45475a;")
        root.addWidget(line)

        title_row = QHBoxLayout()
        title_lbl = QLabel("OSA Spectrum")
        title_lbl.setStyleSheet(title())
        self.lbl_peak_info = QLabel("—")
        self.lbl_peak_info.setStyleSheet(accent())
        title_row.addWidget(title_lbl)
        title_row.addStretch()
        title_row.addWidget(self.lbl_peak_info)
        root.addLayout(title_row)

        self.figure = Figure(facecolor="#1e1e2e")
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.canvas.setFixedHeight(200)
        self.ax = self.figure.add_subplot(111)
        self._style_axes()
        self.ax.text(
            0.5, 0.5, "No data yet — press 'Scan Once' or start capture loop",
            ha="center", va="center", transform=self.ax.transAxes,
            color="#585b70", fontsize=mpl_font_size(1)
        )
        self.canvas.draw()
        root.addWidget(self.canvas)

        # Initial enabled state
        self._on_enable(False)

    # ── Axes styling ──────────────────────────────────────────────────────────
    def _style_axes(self):
        ax = self.ax
        ax.set_facecolor("#181825")
        ax.tick_params(colors="#6c7086", labelsize=mpl_font_size(-1))
        ax.spines["bottom"].set_color("#45475a")
        ax.spines["left"].set_color("#45475a")
        ax.spines["top"].set_color("#45475a")
        ax.spines["right"].set_color("#45475a")
        ax.set_xlabel("Wavelength (nm)", color="#6c7086", fontsize=mpl_font_size())
        ax.set_ylabel("Power (nW)",      color="#6c7086", fontsize=mpl_font_size())
        ax.grid(True, color="#313244", linewidth=0.5)

    # ── Only-OSA toggle ───────────────────────────────────────────────────────
    def _on_osa_only_toggled(self, checked: bool):
        # Only OSA implies OSA is enabled
        if checked:
            self.chk_enable.setChecked(True)
            self.chk_enable.setEnabled(False)
        else:
            self.chk_enable.setEnabled(True)

    # ── Browse output directory ───────────────────────────────────────────────
    def _browse_save_dir(self):
        d = QFileDialog.getExistingDirectory(
            self, "Select OSA Output Directory",
            self.edit_save_dir.text() or os.path.expanduser("~")
        )
        if d:
            self.edit_save_dir.setText(d)

    # ── Enable/disable settings ───────────────────────────────────────────────
    def _on_enable(self, checked: bool):
        # Connection, measurement, and save settings are shared with Test Data OSA —
        # keep them always accessible so users can configure host/port even when
        # not running OSA in the capture loop.
        self.grp_h5.setEnabled(checked)
        # Scan Once is always available regardless of loop-enable toggle
        self.btn_scan.setEnabled(True)

    # ── Manual single scan ────────────────────────────────────────────────────
    def _on_scan_once(self):
        self.btn_scan.setEnabled(False)
        self.lbl_scan_status.setText("Connecting...")
        self.lbl_scan_status.setStyleSheet(warning())

        self._scan_worker = OSAScanWorker(self.get_config())
        self._scan_worker.data_signal.connect(self._on_scan_data)
        self._scan_worker.status_signal.connect(self._on_scan_status)
        self._scan_worker.error_signal.connect(self._on_scan_error)
        self._scan_worker.finished.connect(
            lambda: self.btn_scan.setEnabled(True)
        )
        self._scan_worker.start()

    def _on_scan_status(self, msg: str):
        self.lbl_scan_status.setText(msg)
        self.lbl_scan_status.setStyleSheet(warning())

    def _on_scan_error(self, msg: str):
        self.lbl_scan_status.setText(msg)
        self.lbl_scan_status.setStyleSheet(error())

    @pyqtSlot(np.ndarray, np.ndarray, str)
    def _on_scan_data(self, x_nm: np.ndarray, y_nw: np.ndarray, info: str):
        self.lbl_scan_status.setText("Done")
        self.lbl_scan_status.setStyleSheet(success())
        self.update_plot(x_nm, y_nw, info)

    # ── Plot update (called by scan worker AND by loop runner signal) ─────────
    def update_plot(self, x_nm: np.ndarray, y_nw: np.ndarray,
                    info: str = "", title: str = ""):
        """Redraw the spectrum. Thread-safe via Qt signal routing."""
        n = min(len(x_nm), len(y_nw))
        x_nm = x_nm[:n]
        y_nw = y_nw[:n]

        self._last_x = x_nm
        self._last_y = y_nw

        self.ax.cla()
        self._style_axes()

        self.ax.plot(x_nm, y_nw, color="#89b4fa", linewidth=0.9, label="Spectrum")

        self.ax.set_xlim(x_nm.min(), x_nm.max())
        y_max = y_nw.max() if y_nw.max() > 0 else 1.0
        self.ax.set_ylim(0, y_max * 1.1)

        peak_idx = int(np.argmax(y_nw))
        self.ax.axvline(x_nm[peak_idx], color="#f38ba8",
                        linestyle="--", linewidth=0.8, alpha=0.7)
        self.ax.plot(x_nm[peak_idx], y_nw[peak_idx],
                     "^", color="#f38ba8", markersize=7,
                     label=f"Peak {x_nm[peak_idx]:.3f} nm")

        if title:
            self.ax.set_title(title, color="#cdd6f4", fontsize=mpl_font_size(), pad=4)

        self.ax.legend(fontsize=mpl_font_size(-2), facecolor="#313244",
                       edgecolor="#45475a", labelcolor="#cdd6f4")
        self.lbl_peak_info.setText(info if info else
            f"Peak: {x_nm[peak_idx]:.3f} nm  |  {y_nw[peak_idx]:.1f} nW")
        self.canvas.draw_idle()

    # ── Config export ─────────────────────────────────────────────────────────
    def get_config(self) -> dict:
        return {
            "osa_enabled":     self.chk_enable.isChecked(),
            "osa_only":        self.chk_osa_only.isChecked(),
            "osa_host":        self.edit_host.text().strip(),
            "osa_port":        self.spin_port.value(),
            "osa_wl_start":    self.spin_wl_start.value(),
            "osa_wl_stop":     self.spin_wl_stop.value(),
            "osa_resolution":  self.spin_resolution.value(),
            "osa_rlevel_nw":   self.spin_rlevel.value(),
            "osa_sampling":    self.spin_sampling.value(),
            "osa_avg":         self.spin_avg.value(),
            "osa_sensitivity": self.combo_sensitivity.currentText(),
            "osa_smoothing":   self.combo_smoothing.currentText(),
            # Save settings
            "osa_save_dir":    self.edit_save_dir.text().strip() or os.path.expanduser("~/Desktop/osa_output"),
            "osa_prefix":      self.edit_prefix.text().strip() or "osa",
            "osa_save_csv":    self.chk_save_csv.isChecked(),
            "osa_save_png":    self.chk_save_png.isChecked(),
            # Dimensionality reduction + H5
            "osa_h5_enabled":       self.chk_osa_h5.isChecked(),
            "osa_h5_filename":      self.edit_osa_h5.text().strip() or "osa_spectra.h5",
            "osa_reduce_points":    self.spin_reduce_points.value(),
            "osa_reduce_wl_min":    self.spin_reduce_wl_min.value(),
            "osa_reduce_wl_max":    self.spin_reduce_wl_max.value(),
            "osa_reduce_window":    self.spin_reduce_window.value(),
            "osa_reduce_polyorder": self.spin_reduce_poly.value(),
        }
