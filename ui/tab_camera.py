"""
Camera settings tab — Thorlabs Kiralux
Layout: settings on top, live preview canvas on bottom.
"""
import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QLabel, QDoubleSpinBox, QSpinBox,
    QPushButton, QLineEdit, QFileDialog, QCheckBox,
    QComboBox, QSizePolicy, QFrame, QSlider
)
from PyQt5.QtCore import Qt, pyqtSlot

import matplotlib
matplotlib.use("Qt5Agg")
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from ui.style_helpers import title, accent, mpl_font_size
from core.camera_support import EXPOSURE_MAX_MS, EXPOSURE_MIN_MS


class CameraTab(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # ── Top: settings (horizontal row of group boxes) ─────────────────────
        settings_row = QHBoxLayout()
        settings_row.setSpacing(8)

        # Acquisition params
        grp_acq = QGroupBox("Acquisition Parameters")
        form_acq = QFormLayout(grp_acq)
        form_acq.setHorizontalSpacing(12)
        form_acq.setVerticalSpacing(6)

        self.spin_exposure = QDoubleSpinBox()
        self.spin_exposure.setRange(EXPOSURE_MIN_MS, EXPOSURE_MAX_MS)
        self.spin_exposure.setValue(0.06)
        self.spin_exposure.setSuffix("  ms")
        self.spin_exposure.setDecimals(3)
        self.spin_exposure.setToolTip(
            f"Camera exposure time (min {EXPOSURE_MIN_MS} ms, max {EXPOSURE_MAX_MS:g} ms)"
        )
        exposure_row = QHBoxLayout()
        exposure_row.addWidget(self.spin_exposure)
        self.btn_exposure_max = QPushButton("Max")
        self.btn_exposure_max.setFixedWidth(52)
        self.btn_exposure_max.setToolTip(f"Set exposure to maximum ({EXPOSURE_MAX_MS:g} ms)")
        self.btn_exposure_max.clicked.connect(self._set_exposure_max)
        self.chk_exposure_max = QCheckBox("Always max")
        self.chk_exposure_max.setToolTip(
            "Lock exposure to maximum for every capture (auto-adjusts timeout)."
        )
        self.chk_exposure_max.toggled.connect(self._on_exposure_max_toggled)
        exposure_row.addWidget(self.btn_exposure_max)
        exposure_row.addWidget(self.chk_exposure_max)
        exposure_wrap = QWidget()
        exposure_wrap.setLayout(exposure_row)

        self.spin_gain = QSpinBox()
        self.spin_gain.setRange(0, 480)
        self.spin_gain.setValue(0)
        self.spin_gain.setToolTip("Gain: 0–480  (480 = 48 dB)")

        self.spin_timeout = QSpinBox()
        self.spin_timeout.setRange(100, 60000)
        self.spin_timeout.setValue(5000)
        self.spin_timeout.setSuffix("  ms")
        self.spin_timeout.setToolTip("Polling timeout — must be >> exposure time")

        form_acq.addRow("Exposure:", exposure_wrap)
        form_acq.addRow("Gain:", self.spin_gain)
        form_acq.addRow("Timeout:", self.spin_timeout)
        settings_row.addWidget(grp_acq)

        # ROI
        grp_roi = QGroupBox("Region of Interest (ROI)")
        form_roi = QFormLayout(grp_roi)
        form_roi.setHorizontalSpacing(12)
        form_roi.setVerticalSpacing(6)

        self.chk_full_frame = QCheckBox("Full frame  (4096 × 2160)")
        self.chk_full_frame.setChecked(True)
        self.chk_full_frame.toggled.connect(self._on_full_frame_toggled)

        roi_row = QHBoxLayout()
        self.spin_roi = {}
        for label, default, maximum in [("x1", 0, 4096), ("y1", 0, 2160),
                                         ("x2", 4096, 4096), ("y2", 2160, 2160)]:
            sp = QSpinBox()
            sp.setRange(0, maximum)
            sp.setValue(default)
            sp.setPrefix(f"{label}: ")
            sp.setEnabled(False)
            self.spin_roi[label] = sp
            roi_row.addWidget(sp)

        form_roi.addRow(self.chk_full_frame)
        form_roi.addRow("x1,y1,x2,y2:", roi_row)
        settings_row.addWidget(grp_roi)

        # Output
        grp_out = QGroupBox("Output Settings")
        form_out = QFormLayout(grp_out)
        form_out.setHorizontalSpacing(12)
        form_out.setVerticalSpacing(6)

        dir_row = QHBoxLayout()
        self.edit_outdir = QLineEdit(".")
        self.edit_outdir.setPlaceholderText("Output directory")
        btn_browse = QPushButton("Browse")
        btn_browse.setFixedWidth(60)
        btn_browse.clicked.connect(self._browse_dir)
        dir_row.addWidget(self.edit_outdir)
        dir_row.addWidget(btn_browse)

        self.edit_prefix = QLineEdit("img_loop")
        self.edit_prefix.setPlaceholderText("e.g. img_loop")

        self.combo_fmt = QComboBox()
        self.combo_fmt.addItems(["tif  (16-bit TIFF)", "npy  (NumPy array)", "dat  (raw binary)"])
        self.combo_fmt.setCurrentIndex(0)

        form_out.addRow("Directory:", dir_row)
        form_out.addRow("Prefix:", self.edit_prefix)
        form_out.addRow("Format:", self.combo_fmt)
        settings_row.addWidget(grp_out)

        # Optional inline ROI crop (same algorithm as roi_processor)
        grp_crop = QGroupBox("Auto ROI Crop  (optional, after each frame)")
        form_crop = QFormLayout(grp_crop)
        self.chk_auto_roi = QCheckBox("Save cropped TIFF / PNG files")
        self.chk_auto_roi.setToolTip(
            "Uses max-sum signal window + centered outer crop (notebook algorithm).\n"
            "Camera ROI should be large enough to contain the signal."
        )
        self.spin_auto_signal_w = QSpinBox()
        self.spin_auto_signal_w.setRange(1, 10000)
        self.spin_auto_signal_w.setValue(380)
        self.spin_auto_signal_h = QSpinBox()
        self.spin_auto_signal_h.setRange(1, 10000)
        self.spin_auto_signal_h.setValue(35)
        self.spin_auto_outer_w = QSpinBox()
        self.spin_auto_outer_w.setRange(1, 10000)
        self.spin_auto_outer_w.setValue(400)
        self.spin_auto_outer_h = QSpinBox()
        self.spin_auto_outer_h.setRange(1, 10000)
        self.spin_auto_outer_h.setValue(40)
        self.edit_auto_roi_subdir = QLineEdit("cropped")
        self.edit_auto_roi_subdir.setPlaceholderText("subfolder under capture dir")
        self.chk_auto_roi_png = QCheckBox("Save 1–99% contrast PNG preview")
        self.chk_auto_roi_png.setChecked(True)
        self.chk_auto_roi_preview = QCheckBox("Show cropped frame in live preview")
        self.chk_auto_roi_preview.setChecked(True)

        form_crop.addRow(self.chk_auto_roi)
        form_crop.addRow("Signal W × H:", self._pair_row(
            self.spin_auto_signal_w, self.spin_auto_signal_h))
        form_crop.addRow("Outer W × H:", self._pair_row(
            self.spin_auto_outer_w, self.spin_auto_outer_h))
        form_crop.addRow("Output subdir:", self.edit_auto_roi_subdir)
        form_crop.addRow("", self.chk_auto_roi_png)
        form_crop.addRow("", self.chk_auto_roi_preview)
        self.chk_auto_roi_h5 = QCheckBox("Append cropped frames to H5 (paired labels)")
        self.edit_auto_roi_h5 = QLineEdit("images.h5")
        form_crop.addRow(self.chk_auto_roi_h5)
        form_crop.addRow("Image H5 file:", self.edit_auto_roi_h5)

        self.chk_h5_contrast = QCheckBox("Apply vmin/vmax contrast before H5 save")
        self.chk_h5_contrast.setToolTip(
            "Clip to vmin–vmax then scale to 16-bit full range for training data."
        )
        self.combo_h5_contrast_mode = QComboBox()
        self.combo_h5_contrast_mode.addItem("% of frame max", "percent_max")
        self.combo_h5_contrast_mode.addItem("Percentile (p_low–p_high)", "percentile")
        h5_vminmax_row = QHBoxLayout()
        self.spin_h5_vmin = QSpinBox()
        self.spin_h5_vmin.setRange(0, 99)
        self.spin_h5_vmin.setValue(0)
        self.spin_h5_vmin.setSuffix(" %")
        self.spin_h5_vmax = QSpinBox()
        self.spin_h5_vmax.setRange(1, 100)
        self.spin_h5_vmax.setValue(100)
        self.spin_h5_vmax.setSuffix(" %")
        h5_vminmax_row.addWidget(QLabel("vmin"))
        h5_vminmax_row.addWidget(self.spin_h5_vmin)
        h5_vminmax_row.addWidget(QLabel("vmax"))
        h5_vminmax_row.addWidget(self.spin_h5_vmax)
        h5_vminmax_row.addStretch()
        h5_pct_row = QHBoxLayout()
        self.spin_h5_p_low = QDoubleSpinBox()
        self.spin_h5_p_low.setRange(0.0, 99.0)
        self.spin_h5_p_low.setValue(1.0)
        self.spin_h5_p_low.setSuffix(" %")
        self.spin_h5_p_high = QDoubleSpinBox()
        self.spin_h5_p_high.setRange(1.0, 100.0)
        self.spin_h5_p_high.setValue(99.0)
        self.spin_h5_p_high.setSuffix(" %")
        h5_pct_row.addWidget(QLabel("p_low"))
        h5_pct_row.addWidget(self.spin_h5_p_low)
        h5_pct_row.addWidget(QLabel("p_high"))
        h5_pct_row.addWidget(self.spin_h5_p_high)
        h5_pct_row.addStretch()
        form_crop.addRow(self.chk_h5_contrast)
        form_crop.addRow("H5 contrast mode:", self.combo_h5_contrast_mode)
        form_crop.addRow("H5 vmin / vmax:", h5_vminmax_row)
        form_crop.addRow("H5 percentile:", h5_pct_row)
        self.chk_h5_contrast.toggled.connect(self._on_h5_contrast_toggled)
        self.combo_h5_contrast_mode.currentIndexChanged.connect(self._on_h5_contrast_mode)
        self._on_h5_contrast_toggled(self.chk_h5_contrast.isChecked())
        self._on_h5_contrast_mode()
        settings_row.addWidget(grp_crop)

        root.addLayout(settings_row)

        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #45475a;")
        root.addWidget(line)

        # ── Bottom: live preview ──────────────────────────────────────────────
        preview_header = QHBoxLayout()
        lbl_title = QLabel("Live Preview")
        lbl_title.setStyleSheet(title())
        self.lbl_frame_info = QLabel("Waiting for first frame...")
        self.lbl_frame_info.setStyleSheet(accent())
        preview_header.addWidget(lbl_title)
        preview_header.addStretch()

        # Contrast controls
        preview_header.addWidget(QLabel("vmin %:"))
        self.spin_vmin = QSpinBox()
        self.spin_vmin.setRange(0, 99)
        self.spin_vmin.setValue(0)
        self.spin_vmin.setSuffix(" %")
        self.spin_vmin.setFixedWidth(70)
        self.spin_vmin.valueChanged.connect(self._redraw)
        preview_header.addWidget(self.spin_vmin)
        preview_header.addSpacing(8)
        preview_header.addWidget(QLabel("vmax %:"))
        self.spin_vmax = QSpinBox()
        self.spin_vmax.setRange(1, 100)
        self.spin_vmax.setValue(100)
        self.spin_vmax.setSuffix(" %")
        self.spin_vmax.setFixedWidth(70)
        self.spin_vmax.valueChanged.connect(self._redraw)
        preview_header.addWidget(self.spin_vmax)
        preview_header.addSpacing(16)
        preview_header.addWidget(self.lbl_frame_info)
        root.addLayout(preview_header)

        self._frame_cache = None

        self.figure = Figure(facecolor="#1e1e2e", tight_layout=True)
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.ax = self.figure.add_subplot(111)
        self._style_axes()
        self.ax.text(
            0.5, 0.5, "No frame yet — start acquisition to see live preview",
            ha="center", va="center", transform=self.ax.transAxes,
            color="#585b70", fontsize=mpl_font_size(1)
        )
        self.canvas.draw()
        root.addWidget(self.canvas, stretch=1)

    # ── Axes styling ──────────────────────────────────────────────────────────
    def _style_axes(self):
        ax = self.ax
        ax.set_facecolor("#181825")
        ax.tick_params(colors="#6c7086", labelsize=mpl_font_size(-1))
        for spine in ax.spines.values():
            spine.set_color("#45475a")
        ax.set_xlabel("X  (pixels)", color="#6c7086", fontsize=mpl_font_size())
        ax.set_ylabel("Y  (pixels)", color="#6c7086", fontsize=mpl_font_size())

    # ── Live frame update (called from main_window via signal) ────────────────
    @pyqtSlot(np.ndarray, str)
    def update_preview(self, frame: np.ndarray, info: str = ""):
        """Cache frame and render with current contrast settings."""
        self._frame_cache = (frame, info)
        self._redraw()

    def _redraw(self):
        """Redraw cached frame with current vmin/vmax %."""
        if self._frame_cache is None:
            return
        frame, info = self._frame_cache
        h, w = frame.shape
        pmax = frame.max() if frame.max() > 0 else 1
        vmin = pmax * self.spin_vmin.value() / 100.0
        vmax = pmax * self.spin_vmax.value() / 100.0
        if vmax <= vmin:
            vmax = vmin + 1

        self.ax.cla()
        self._style_axes()
        self.ax.imshow(
            frame, cmap="gray", vmin=vmin, vmax=vmax,
            aspect="auto", interpolation="nearest",
            extent=[0, w, h, 0],
        )
        self.ax.set_xlim(0, w)
        self.ax.set_ylim(h, 0)
        title = (f"{info}  |  " if info else "") + \
                f"vmin={self.spin_vmin.value()}%  vmax={self.spin_vmax.value()}%"
        self.ax.set_title(title, color="#cdd6f4", fontsize=mpl_font_size(), pad=3)
        self.lbl_frame_info.setText(
            f"{w}×{h} px  max={frame.max()}"
        )
        self.canvas.draw_idle()

    # ── Helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _pair_row(spin_a: QSpinBox, spin_b: QSpinBox) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(spin_a)
        row.addWidget(QLabel("×"))
        row.addWidget(spin_b)
        row.addStretch()
        return row

    def _ensure_timeout_for_exposure(self):
        """Polling timeout must exceed exposure time."""
        exp_ms = self.spin_exposure.value()
        need = int(exp_ms * 1.1 + 500)
        if self.spin_timeout.value() < need:
            self.spin_timeout.setValue(min(need, self.spin_timeout.maximum()))

    def _set_exposure_max(self):
        self.spin_exposure.setValue(EXPOSURE_MAX_MS)
        self._ensure_timeout_for_exposure()

    def _on_exposure_max_toggled(self, checked: bool):
        self.spin_exposure.setEnabled(not checked)
        self.btn_exposure_max.setEnabled(not checked)
        if checked:
            self.spin_exposure.setValue(EXPOSURE_MAX_MS)
            self._ensure_timeout_for_exposure()

    def _on_full_frame_toggled(self, checked: bool):
        for sp in self.spin_roi.values():
            sp.setEnabled(not checked)

    def _on_h5_contrast_toggled(self, checked: bool):
        self.combo_h5_contrast_mode.setEnabled(checked)
        self._on_h5_contrast_mode()

    def _on_h5_contrast_mode(self):
        use_pct = (
            self.chk_h5_contrast.isChecked()
            and self.combo_h5_contrast_mode.currentData() == "percentile"
        )
        use_max = (
            self.chk_h5_contrast.isChecked()
            and self.combo_h5_contrast_mode.currentData() == "percent_max"
        )
        self.spin_h5_vmin.setEnabled(use_max)
        self.spin_h5_vmax.setEnabled(use_max)
        self.spin_h5_p_low.setEnabled(use_pct)
        self.spin_h5_p_high.setEnabled(use_pct)

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select output directory")
        if d:
            self.edit_outdir.setText(d)

    def get_config(self) -> dict:
        if self.chk_full_frame.isChecked():
            roi = (0, 0, 4096, 2160)
        else:
            roi = tuple(self.spin_roi[k].value() for k in ("x1", "y1", "x2", "y2"))
        fmt_map = {0: "tif", 1: "npy", 2: "dat"}
        return {
            "exposure_time_ms": (
                EXPOSURE_MAX_MS if self.chk_exposure_max.isChecked()
                else self.spin_exposure.value()
            ),
            "exposure_use_max": self.chk_exposure_max.isChecked(),
            "gain":             self.spin_gain.value(),
            "timeout_ms":       self.spin_timeout.value(),
            "roi":              roi,
            "out_dir":          self.edit_outdir.text() or ".",
            "file_prefix":      self.edit_prefix.text() or "img_loop",
            "img_format":       fmt_map[self.combo_fmt.currentIndex()],
            # Optional inline ROI crop (roi_processor algorithm)
            "auto_roi_enabled":        self.chk_auto_roi.isChecked(),
            "auto_roi_signal_w":       self.spin_auto_signal_w.value(),
            "auto_roi_signal_h":       self.spin_auto_signal_h.value(),
            "auto_roi_outer_w":        self.spin_auto_outer_w.value(),
            "auto_roi_outer_h":        self.spin_auto_outer_h.value(),
            "auto_roi_subdir":         self.edit_auto_roi_subdir.text().strip() or "cropped",
            "auto_roi_save_png":       self.chk_auto_roi_png.isChecked(),
            "auto_roi_show_preview":   self.chk_auto_roi_preview.isChecked(),
            "auto_roi_p_low":          1.0,
            "auto_roi_p_high":         99.0,
            "auto_roi_h5_enabled":     self.chk_auto_roi_h5.isChecked(),
            "auto_roi_h5_filename":    self.edit_auto_roi_h5.text().strip() or "images.h5",
            "auto_roi_h5_contrast_enabled": self.chk_h5_contrast.isChecked(),
            "auto_roi_h5_contrast_mode": self.combo_h5_contrast_mode.currentData(),
            "auto_roi_h5_vmin_pct":    self.spin_h5_vmin.value(),
            "auto_roi_h5_vmax_pct":    self.spin_h5_vmax.value(),
            "auto_roi_h5_p_low":       self.spin_h5_p_low.value(),
            "auto_roi_h5_p_high":      self.spin_h5_p_high.value(),
        }
