"""
Yokogawa OSA settings tab — with embedded live spectrum plot.
"""
import numpy as np

import os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QLabel, QDoubleSpinBox, QSpinBox,
    QLineEdit, QCheckBox, QComboBox, QPushButton,
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


class OSATab(QWidget):
    def __init__(self):
        super().__init__()
        self._scan_worker = None
        # Keep the last plotted arrays so loop updates can reuse the canvas
        self._last_x = None
        self._last_y = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # ── Top: settings (fixed height, priority for labels/controls) ───────
        ctrl_row = QHBoxLayout()
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

        # Settings row — horizontal group boxes (same pattern as Camera tab)
        settings_row = QHBoxLayout()
        settings_row.setSpacing(8)

        # Connection
        self.grp_conn = QGroupBox("Network Connection")
        form_c = QFormLayout(self.grp_conn)
        form_c.setHorizontalSpacing(10)
        form_c.setVerticalSpacing(8)
        form_c.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form_c.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.edit_host = QLineEdit("192.168.0.1")
        self.spin_port = QSpinBox()
        self.spin_port.setRange(1, 65535)
        self.spin_port.setValue(10001)

        form_c.addRow("Host IP:", self.edit_host)
        form_c.addRow("Port:", self.spin_port)
        settings_row.addWidget(self.grp_conn)

        # Measurement params
        self.grp_meas = QGroupBox("Measurement Parameters")
        form_m = QFormLayout(self.grp_meas)
        form_m.setHorizontalSpacing(10)
        form_m.setVerticalSpacing(8)
        form_m.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form_m.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.spin_wl_start = QDoubleSpinBox()
        self.spin_wl_start.setRange(400, 2000)
        self.spin_wl_start.setValue(610.0)
        self.spin_wl_start.setSuffix("  nm")

        self.spin_wl_stop = QDoubleSpinBox()
        self.spin_wl_stop.setRange(400, 2000)
        self.spin_wl_stop.setValue(700.0)
        self.spin_wl_stop.setSuffix("  nm")

        self.spin_resolution = QDoubleSpinBox()
        self.spin_resolution.setRange(0.02, 5.0)
        self.spin_resolution.setValue(0.5)
        self.spin_resolution.setSuffix("  nm")
        self.spin_resolution.setDecimals(2)

        self.spin_rlevel = QSpinBox()
        self.spin_rlevel.setRange(1, 100000)
        self.spin_rlevel.setValue(2000)
        self.spin_rlevel.setSuffix("  nW")

        self.spin_sampling = QDoubleSpinBox()
        self.spin_sampling.setRange(0.001, 10.0)
        self.spin_sampling.setValue(0.05)
        self.spin_sampling.setSuffix("  nm")
        self.spin_sampling.setDecimals(3)

        self.spin_avg = QSpinBox()
        self.spin_avg.setRange(1, 1000)
        self.spin_avg.setValue(1)

        self.combo_sensitivity = QComboBox()
        self.combo_sensitivity.addItems(["norm", "mid", "high1", "high2", "high3"])
        self.combo_sensitivity.setCurrentText("mid")

        self.combo_smoothing = QComboBox()
        self.combo_smoothing.addItems(["OFF", "2", "4", "8", "16", "32"])

        form_m.addRow("WL start:", self.spin_wl_start)
        form_m.addRow("WL stop:", self.spin_wl_stop)
        form_m.addRow("Resolution:", self.spin_resolution)
        form_m.addRow("Ref level:", self.spin_rlevel)
        form_m.addRow("Sampling:", self.spin_sampling)
        form_m.addRow("Averages:", self.spin_avg)
        form_m.addRow("Sensitivity:", self.combo_sensitivity)
        form_m.addRow("Smoothing:", self.combo_smoothing)
        settings_row.addWidget(self.grp_meas)

        # ── Save settings ─────────────────────────────────────────────────────
        self.grp_save = QGroupBox("Save Settings")
        form_s = QFormLayout(self.grp_save)
        form_s.setHorizontalSpacing(10)
        form_s.setVerticalSpacing(8)
        form_s.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form_s.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

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
        settings_row.addWidget(self.grp_save)

        # ── Reduce + H5 (optional, separate from camera H5) ───────────────────
        self.grp_h5 = QGroupBox("Reduce + H5  (optional)")
        form_h5 = QFormLayout(self.grp_h5)
        form_h5.setHorizontalSpacing(10)
        form_h5.setVerticalSpacing(8)
        form_h5.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form_h5.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.chk_osa_h5 = QCheckBox("Append reduced spectrum to H5")
        self.chk_osa_h5.setToolTip(
            "Uses the same labels as cropped images: roundXX_loopYY_j"
        )
        self.edit_osa_h5 = QLineEdit("osa_spectra.h5")
        self.spin_reduce_points = QSpinBox()
        self.spin_reduce_points.setRange(2, 5000)
        self.spin_reduce_points.setValue(300)
        self.spin_reduce_wl_min = QDoubleSpinBox()
        self.spin_reduce_wl_min.setRange(400, 2000)
        self.spin_reduce_wl_min.setValue(610.0)
        self.spin_reduce_wl_min.setSuffix(" nm")
        self.spin_reduce_wl_max = QDoubleSpinBox()
        self.spin_reduce_wl_max.setRange(400, 2000)
        self.spin_reduce_wl_max.setValue(680.0)
        self.spin_reduce_wl_max.setSuffix(" nm")
        self.spin_reduce_window = QSpinBox()
        self.spin_reduce_window.setRange(3, 501)
        self.spin_reduce_window.setValue(31)
        self.spin_reduce_poly = QSpinBox()
        self.spin_reduce_poly.setRange(1, 9)
        self.spin_reduce_poly.setValue(3)
        form_h5.addRow(self.chk_osa_h5)
        form_h5.addRow("OSA H5 file:", self.edit_osa_h5)
        form_h5.addRow("Reduce to N points:", self.spin_reduce_points)
        form_h5.addRow("WL range min:", self.spin_reduce_wl_min)
        form_h5.addRow("WL range max:", self.spin_reduce_wl_max)
        form_h5.addRow("SavGol window:", self.spin_reduce_window)
        form_h5.addRow("SavGol polyorder:", self.spin_reduce_poly)
        settings_row.addWidget(self.grp_h5)
        root.addLayout(settings_row)

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
        root.addStretch(1)

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
        self.grp_conn.setEnabled(checked)
        self.grp_meas.setEnabled(checked)
        self.grp_save.setEnabled(checked)
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
            "osa_host":        self.edit_host.text(),
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
