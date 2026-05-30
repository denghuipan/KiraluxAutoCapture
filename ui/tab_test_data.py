"""
Test Data Collection — automated RF power servo + Kiralux capture.

Uses PM100D reading × coupling efficiency to reach target output power (dBm),
then captures one frame per (wavelength, target power) point.
"""
import math
import os

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QLabel,
    QLineEdit, QPushButton, QCheckBox,
    QFileDialog, QFrame, QTextEdit, QSizePolicy,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QTextCursor

import matplotlib
matplotlib.use("Qt5Agg")
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from ui.style_helpers import hint, muted, mpl_font_size
from ui.layout_helpers import (
    install_scroll_content, configure_form_layout, prepare_group_box, GROUP_SPACING,
    NoScrollSpinBox, NoScrollDoubleSpinBox, NoScrollComboBox,
)
from core.power_math import dbm_to_watts, pm_watts_for_target, watts_to_dbm


def _format_watts_auto(watts: float) -> str:
    """Auto-scale watts to pW / nW / μW / mW / W with 3-4 sig-figs."""
    if not math.isfinite(watts) or watts < 0:
        return "--- W"
    if watts == 0:
        return "0 W"
    abs_w = abs(watts)
    if abs_w < 1e-9:
        return f"{watts * 1e12:.3g} pW"
    if abs_w < 1e-6:
        return f"{watts * 1e9:.3g} nW"
    if abs_w < 1e-3:
        return f"{watts * 1e6:.3g} μW"
    if abs_w < 1.0:
        return f"{watts * 1e3:.3g} mW"
    return f"{watts:.3g} W"


def _format_sci(value: float) -> str:
    """Display like 4.53 × 10⁻¹⁰ (plain ASCII: 4.53 x 10^-10)."""
    if value <= 0:
        return "0"
    exp = int(math.floor(math.log10(value)))
    mant = value / (10 ** exp)
    if abs(mant - round(mant)) < 1e-6:
        mant_s = f"{int(round(mant))}"
    elif abs(mant * 100 - round(mant * 100)) < 1e-6:
        mant_s = f"{mant:.2f}".rstrip("0").rstrip(".")
    else:
        mant_s = f"{mant:.4g}"
    return f"{mant_s} × 10^{exp}"


class TestDataTab(QWidget):
    _PM_LOG_MAX_LINES = 200
    _PM_TRACE_WINDOW_S = 45.0  # rolling time axis (seconds visible)

    def __init__(self, main_window=None):
        super().__init__()
        self._main_win = main_window
        self._pm_tol_db = 0.5
        self._live_monitor = None
        self._trace_target_dbm = None
        self._trace_t = []
        self._trace_dbm = []
        self._trace_w = []       # actual watts (parallel to _trace_dbm)
        self._trace_rf = []
        self._trace_phase = []
        self._trigger_t = None
        self._pm_unit = "dBm"    # "dBm" or "W"

        _, root = install_scroll_content(self)

        intro = QLabel(
            "Test collection: Extreme + RF stay on; only channel-0 wavelength/amplitude "
            "registers are written (no RF off/on while stepping). RF ramps low→high in 0.1% "
            "steps. Live power-vs-time trace. Does not affect Auto Capture Loop."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(hint())
        root.addWidget(intro)

        row_top = QVBoxLayout()
        row_top.setSpacing(GROUP_SPACING)

        # ── Laser / wavelength ───────────────────────────────────────────────
        grp_laser = QGroupBox("Laser & Targets")
        form_l = QFormLayout(grp_laser)
        configure_form_layout(form_l)

        # Wavelength source selector (Manual vs From Loop Tab)
        self.combo_wl_source = NoScrollComboBox()
        self.combo_wl_source.addItem("Manual")
        self.combo_wl_source.addItem("From Loop Tab")
        self.combo_wl_source.setToolTip(
            "Manual: use the wavelength list below.\n"
            "From Loop Tab: use the current Loop tab's NKT channel configuration "
            "(multi_random, single_scan, manual multi-peak, etc.)."
        )

        # Info label shown when "From Loop Tab" is selected
        self.lbl_loop_tab_info = QLabel(
            "Using Loop Tab NKT config  "
            "(center wavelength = mean of active channels, used for PM calibration)"
        )
        self.lbl_loop_tab_info.setWordWrap(True)
        self.lbl_loop_tab_info.setStyleSheet(hint())
        self.lbl_loop_tab_info.setVisible(False)

        # Sync button shown when "From Loop Tab" is selected
        self.btn_sync_loop = QPushButton("↺  Sync from Loop Tab")
        self.btn_sync_loop.setFixedWidth(160)
        self.btn_sync_loop.setToolTip(
            "Read the current Loop tab config and update the summary below."
        )
        self.btn_sync_loop.clicked.connect(self._on_sync_loop_tab)
        self.btn_sync_loop.setVisible(False)

        self.lbl_loop_tab_summary = QLabel("")
        self.lbl_loop_tab_summary.setWordWrap(True)
        self.lbl_loop_tab_summary.setStyleSheet(muted())
        self.lbl_loop_tab_summary.setVisible(False)

        # Row containing both sync button + summary
        loop_row = QHBoxLayout()
        loop_row.addWidget(self.btn_sync_loop)
        loop_row.addSpacing(8)
        loop_row.addWidget(self.lbl_loop_tab_summary, 1)
        loop_wrap = QWidget()
        loop_wrap.setLayout(loop_row)
        loop_wrap.setVisible(False)
        self._loop_wrap = loop_wrap

        self.edit_wavelengths = QLineEdit("650")
        self.edit_wavelengths.setPlaceholderText("e.g. 650  or  640,650,660")
        self.lbl_wl_manual = QLabel("Wavelength(s) nm:")

        self.edit_targets = QLineEdit("-20,-30,-40")
        self.edit_targets.setPlaceholderText("dBm list, e.g. -20,-30,-40,-50")

        coupling_row = QHBoxLayout()
        self.spin_coupling_m = NoScrollDoubleSpinBox()
        self.spin_coupling_m.setRange(0.001, 9.9999)
        self.spin_coupling_m.setDecimals(4)
        self.spin_coupling_m.setValue(1.0)
        self.spin_coupling_m.setToolTip("Mantissa (coefficient)")
        self.spin_coupling_exp = NoScrollSpinBox()
        self.spin_coupling_exp.setRange(-20, 0)
        self.spin_coupling_exp.setValue(-5)
        self.spin_coupling_exp.setToolTip("Exponent (power of ten)")
        self.lbl_coupling_sci = QLabel("= 1 × 10^-5")
        self.lbl_coupling_sci.setStyleSheet(muted())
        coupling_row.addWidget(self.spin_coupling_m)
        coupling_row.addWidget(QLabel("× 10"))
        coupling_row.addWidget(self.spin_coupling_exp)
        coupling_row.addSpacing(8)
        coupling_row.addWidget(self.lbl_coupling_sci)
        coupling_row.addStretch()
        coupling_wrap = QWidget()
        coupling_wrap.setLayout(coupling_row)

        coupling_note = QLabel("Actual output = PM reading × coupling")
        coupling_note.setStyleSheet(hint())

        self.spin_tol_db = NoScrollDoubleSpinBox()
        self.spin_tol_db.setRange(0.05, 10.0)
        self.spin_tol_db.setValue(0.5)
        self.spin_tol_db.setSuffix("  dB")

        self.lbl_pm_hint = QLabel("—")
        self.lbl_pm_hint.setWordWrap(True)
        self.lbl_pm_hint.setStyleSheet(muted())

        form_l.addRow("Wavelength source:", self.combo_wl_source)
        form_l.addRow("", self.lbl_loop_tab_info)
        form_l.addRow("", self._loop_wrap)
        form_l.addRow(self.lbl_wl_manual, self.edit_wavelengths)
        form_l.addRow("Target power(s) dBm:", self.edit_targets)
        form_l.addRow("Coupling efficiency:", coupling_wrap)
        form_l.addRow("", coupling_note)
        form_l.addRow("Power tolerance:", self.spin_tol_db)
        form_l.addRow("", self.lbl_pm_hint)
        prepare_group_box(grp_laser)
        row_top.addWidget(grp_laser)

        # ── RF control ───────────────────────────────────────────────────────
        grp_rf = QGroupBox("RF Control")
        form_r = QFormLayout(grp_rf)
        configure_form_layout(form_r)
        self.spin_initial_rf = NoScrollSpinBox()
        self.spin_initial_rf.setRange(10, 1000)
        self.spin_initial_rf.setValue(500)
        self.spin_initial_rf.setToolTip(
            "Reserved — each target always starts at RF floor and ramps up."
        )
        self.spin_rf_min = NoScrollSpinBox()
        self.spin_rf_min.setRange(0, 999)
        self.spin_rf_min.setValue(10)
        self.spin_rf_min.setToolTip(
            "Stop with error if RF reaches this floor and power is still above target."
        )
        self.spin_rf_max = NoScrollSpinBox()
        self.spin_rf_max.setRange(1, 1000)
        self.spin_rf_max.setValue(1000)
        self.spin_laser_settle = NoScrollDoubleSpinBox()
        self.spin_laser_settle.setRange(0.0, 30.0)
        self.spin_laser_settle.setValue(0.5)
        self.spin_laser_settle.setSuffix("  s")
        self.spin_laser_settle.setToolTip(
            "After target is triggered (RF locked), hold this long while PM is sampled "
            "for the live trace before camera capture."
        )
        self.spin_pm_settle = NoScrollDoubleSpinBox()
        self.spin_pm_settle.setRange(0.001, 10.0)
        self.spin_pm_settle.setValue(0.1)
        self.spin_pm_settle.setSuffix("  s")
        self.spin_pm_settle.setToolTip(
            "Interval between PM samples during settle / verify (RF amplitude fixed)."
        )
        self.spin_rf_iter = NoScrollSpinBox()
        self.spin_rf_iter.setRange(5, 200)
        self.spin_rf_iter.setValue(40)
        self.spin_rf_step_ms = NoScrollDoubleSpinBox()
        self.spin_rf_step_ms.setRange(0.01, 5000.0)
        self.spin_rf_step_ms.setDecimals(2)
        self.spin_rf_step_ms.setValue(50.0)
        self.spin_rf_step_ms.setSuffix("  ms")
        self.spin_rf_step_ms.setToolTip(
            "Time delay (milliseconds) after each 0.1% RF step during the downward ramp. "
            "The power meter is read once per step, after this wait. "
            "Lower = faster sweep (may be noisier); higher = slower, more stable readings."
        )

        self.combo_rf_algo = NoScrollComboBox()
        self.combo_rf_algo.addItem("Linear ramp")
        self.combo_rf_algo.addItem("Binary search")
        self.combo_rf_algo.setToolTip(
            "Linear ramp: sweep RF low→high in 0.1% steps until target power is hit.\n"
            "Binary search: bisect [RF min, RF max] bracket — fewer PM reads, "
            "converges in ≤20 steps."
        )

        form_r.addRow("Initial RF amp (0–1000):", self.spin_initial_rf)
        form_r.addRow("RF floor (stop if too high):", self.spin_rf_min)
        form_r.addRow("RF ceiling:", self.spin_rf_max)
        form_r.addRow("RF search algorithm:", self.combo_rf_algo)
        form_r.addRow("Settle after trigger:", self.spin_laser_settle)
        form_r.addRow("PM sample interval:", self.spin_pm_settle)
        form_r.addRow("Max RF iterations:", self.spin_rf_iter)
        form_r.addRow("Delay per RF step:", self.spin_rf_step_ms)

        # OSA enable checkbox
        self.chk_osa_test = QCheckBox("Enable OSA in Test Data")
        self.chk_osa_test.setChecked(False)
        self.chk_osa_test.setToolTip("Collect OSA spectrum at each test point (uses OSA tab settings)")
        form_r.addRow(self.chk_osa_test)
        prepare_group_box(grp_rf)
        row_top.addWidget(grp_rf)

        root.addLayout(row_top)

        row_mid = QVBoxLayout()
        row_mid.setSpacing(GROUP_SPACING)

        # ── Power meter ────────────────────────────────────────────────────────
        grp_pm = QGroupBox("Power Meter (PM100D — USB/VISA)")
        form_p = QFormLayout(grp_pm)
        configure_form_layout(form_p)
        self.combo_pm = NoScrollComboBox()
        self.combo_pm.addItem("PM100D (USB / VISA)", "pm100d")
        self.combo_pm.addItem("Simulated (development)", "simulated")

        visa_row = QHBoxLayout()
        self.edit_visa = QLineEdit("")
        self.edit_visa.setPlaceholderText("USB0::0x1313::0x8078::P0001234::INSTR")
        self.btn_visa_scan = QPushButton("Scan")
        self.btn_visa_scan.setFixedWidth(52)
        self.btn_visa_scan.setToolTip("List VISA devices (requires pyvisa + NI-VISA)")
        self.btn_visa_scan.clicked.connect(self._scan_visa)
        visa_row.addWidget(self.edit_visa)
        visa_row.addWidget(self.btn_visa_scan)
        visa_wrap = QWidget()
        visa_wrap.setLayout(visa_row)

        self.spin_sim_max = NoScrollDoubleSpinBox()
        self.spin_sim_max.setRange(1e-12, 1e6)
        self.spin_sim_max.setValue(1.0)
        self.spin_sim_max.setSuffix("  W")
        self.spin_sim_max.setToolTip("Simulated PM full-scale at RF=1000 (dev only).")

        self.lbl_pm_visa = QLabel("VISA resource:")
        self.lbl_pm_sim = QLabel("Sim max reading:")

        form_p.addRow("Backend:", self.combo_pm)
        form_p.addRow(self.lbl_pm_visa, visa_wrap)
        form_p.addRow(self.lbl_pm_sim, self.spin_sim_max)
        prepare_group_box(grp_pm)
        row_mid.addWidget(grp_pm)

        # ── Camera / output ──────────────────────────────────────────────────
        grp_cam = QGroupBox("Camera & Output")
        form_c = QFormLayout(grp_cam)
        configure_form_layout(form_c)
        self.chk_use_camera_tab = QCheckBox("Use exposure / gain / ROI from Camera tab")
        self.chk_use_camera_tab.setChecked(True)

        self.spin_exposure = NoScrollDoubleSpinBox()
        self.spin_exposure.setRange(0.03, 22806.0)
        self.spin_exposure.setValue(0.06)
        self.spin_exposure.setSuffix("  ms")
        self.spin_gain = NoScrollSpinBox()
        self.spin_gain.setRange(0, 480)
        self.spin_gain.setValue(0)

        self.spin_repeats = NoScrollSpinBox()
        self.spin_repeats.setRange(1, 200)
        self.spin_repeats.setValue(1)
        self.spin_repeats.setToolTip(
            "Number of frames to capture per (wavelength, target) step. "
            "The RF servo runs once; the camera fires N times at the locked power. "
            "Filenames get a _rep1, _rep2, … suffix when N > 1."
        )

        dir_row = QHBoxLayout()
        self.edit_outdir = QLineEdit(os.path.expanduser("~/Desktop/test_data"))
        btn_browse = QPushButton("Browse")
        btn_browse.setFixedWidth(60)
        btn_browse.clicked.connect(self._browse_dir)
        dir_row.addWidget(self.edit_outdir)
        dir_row.addWidget(btn_browse)

        self.edit_prefix = QLineEdit("test")
        self.edit_log = QLineEdit("test_data_log.csv")

        form_c.addRow(self.chk_use_camera_tab)
        form_c.addRow("Exposure:", self.spin_exposure)
        form_c.addRow("Gain:", self.spin_gain)
        form_c.addRow("Repeats per step:", self.spin_repeats)
        form_c.addRow("Output dir:", dir_row)
        form_c.addRow("File prefix:", self.edit_prefix)
        form_c.addRow("Log CSV:", self.edit_log)
        prepare_group_box(grp_cam)
        row_mid.addWidget(grp_cam)
        root.addLayout(row_mid)

        self.chk_use_camera_tab.toggled.connect(self._on_use_camera_tab)
        self.combo_pm.currentIndexChanged.connect(self._on_pm_backend_changed)
        self.edit_targets.textChanged.connect(self._update_pm_hint)
        self.spin_coupling_m.valueChanged.connect(self._on_coupling_changed)
        self.spin_coupling_exp.valueChanged.connect(self._on_coupling_changed)
        self.combo_wl_source.currentIndexChanged.connect(self._on_wl_source_changed)
        self._on_use_camera_tab(True)
        self._on_pm_backend_changed()
        self._on_coupling_changed()
        self._on_wl_source_changed(0)

        # ── Bright Field Pre-capture ──────────────────────────────────────────
        grp_bright = QGroupBox("Bright Field Pre-capture")
        form_b = QFormLayout(grp_bright)
        configure_form_layout(form_b)

        self.chk_bright_enabled = QCheckBox(
            "Enable bright field pre-capture per wavelength"
        )
        self.chk_bright_enabled.setChecked(False)
        self.chk_bright_enabled.setToolTip(
            "Before the power servo loop for each wavelength, capture a series of\n"
            "images at full RF power with multiple exposure times.\n"
            "Saved to bright/ subfolder; no OSA measurement in this phase."
        )

        # Container widget — hidden when unchecked
        bright_inner = QWidget()
        form_bi = QFormLayout(bright_inner)
        configure_form_layout(form_bi)

        self.spin_bright_rf_amp = NoScrollSpinBox()
        self.spin_bright_rf_amp.setRange(0, 1000)
        self.spin_bright_rf_amp.setValue(1000)
        self.spin_bright_rf_amp.setToolTip(
            "RF amplitude (0–1000) used during bright-field captures."
        )

        self.spin_bright_settle_s = NoScrollDoubleSpinBox()
        self.spin_bright_settle_s.setRange(0.0, 10.0)
        self.spin_bright_settle_s.setValue(0.5)
        self.spin_bright_settle_s.setDecimals(2)
        self.spin_bright_settle_s.setSuffix("  s")
        self.spin_bright_settle_s.setToolTip(
            "Wait this long after setting bright RF amplitude before capturing."
        )

        self.edit_bright_exposures = QLineEdit("100, 500, 1000, 2000, 5000")
        self.edit_bright_exposures.setPlaceholderText("comma-separated ms values")
        self.edit_bright_exposures.setToolTip(
            "List of camera exposure times (ms) for bright-field captures.\n"
            "One image is saved per exposure value, per wavelength."
        )

        bright_hint_lbl = QLabel("Images saved to bright/ subfolder, no OSA")
        bright_hint_lbl.setStyleSheet(hint())

        form_bi.addRow("RF amplitude:", self.spin_bright_rf_amp)
        form_bi.addRow("Settle time (s):", self.spin_bright_settle_s)
        form_bi.addRow("Exposure times (ms):", self.edit_bright_exposures)
        form_bi.addRow(bright_hint_lbl)

        form_b.addRow(self.chk_bright_enabled)
        form_b.addRow(bright_inner)

        self.chk_bright_enabled.toggled.connect(bright_inner.setVisible)
        bright_inner.setVisible(False)

        prepare_group_box(grp_bright)
        root.addWidget(grp_bright)

        # ── Real-time PM reading monitor (power vs time, PM100D-style) ─────────
        grp_pm_monitor = QGroupBox("Real-Time Power Trace")
        pm_monitor_layout = QVBoxLayout(grp_pm_monitor)
        pm_monitor_layout.setContentsMargins(8, 8, 8, 8)
        pm_monitor_layout.setSpacing(4)

        # Top row: current values
        pm_values_row = QHBoxLayout()
        pm_values_row.setSpacing(16)

        # RF amplitude
        self.lbl_live_rf = QLabel("RF: ---")
        self.lbl_live_rf.setFont(QFont("Consolas", 10))
        self.lbl_live_rf.setStyleSheet("color: #89b4fa;")
        pm_values_row.addWidget(self.lbl_live_rf)

        # PM reading (W)
        self.lbl_live_pm = QLabel("PM: --- W")
        self.lbl_live_pm.setFont(QFont("Consolas", 10))
        self.lbl_live_pm.setStyleSheet("color: #a6e3a1;")
        pm_values_row.addWidget(self.lbl_live_pm)

        # Actual power (dBm or W)
        self.lbl_live_dbm = QLabel("Actual: --- dBm")
        self.lbl_live_dbm.setFont(QFont("Consolas", 10))
        self.lbl_live_dbm.setStyleSheet("color: #f9e2af;")
        pm_values_row.addWidget(self.lbl_live_dbm)

        # Target dBm
        self.lbl_live_target = QLabel("Target: --- dBm")
        self.lbl_live_target.setFont(QFont("Consolas", 10))
        self.lbl_live_target.setStyleSheet("color: #cba6f7;")
        pm_values_row.addWidget(self.lbl_live_target)

        # Unit selector
        self.combo_pm_unit = NoScrollComboBox()
        self.combo_pm_unit.addItems(["dBm", "W (auto)"])
        self.combo_pm_unit.setToolTip(
            "Display unit for Actual power.\n"
            "W (auto): auto-scales to pW / nW / μW / mW / W."
        )
        self.combo_pm_unit.setFixedWidth(90)
        self.combo_pm_unit.currentTextChanged.connect(self._on_pm_unit_changed)
        pm_values_row.addWidget(self.combo_pm_unit)

        pm_values_row.addStretch()

        # Live power button — read the meter NOW, before any test collection.
        self.btn_live = QPushButton("●  Show Live Power")
        self.btn_live.setCheckable(True)
        self.btn_live.setToolTip(
            "Stream the power meter live (PM only — does not touch NKT/RF/laser). "
            "Uses the Backend + coupling above. Stops automatically when a test starts."
        )
        self.btn_live.setStyleSheet(
            "QPushButton{background:#45475a;color:#cdd6f4;font-weight:bold;"
            "padding:5px 12px;border-radius:5px;}"
            "QPushButton:hover{background:#585b70;}"
            "QPushButton:checked{background:#94e2d5;color:#1e1e2e;}"
            "QPushButton:disabled{background:#313244;color:#585b70;}"
        )
        self.btn_live.toggled.connect(self._on_toggle_live)
        pm_values_row.addWidget(self.btn_live)

        pm_monitor_layout.addLayout(pm_values_row)

        self.fig_pm = Figure(figsize=(6, 2.4), dpi=100)
        self.fig_pm.patch.set_facecolor("#1e1e2e")
        self.ax_pm = self.fig_pm.add_subplot(111)
        self._style_pm_axes()
        self.canvas_pm = FigureCanvas(self.fig_pm)
        self.canvas_pm.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.canvas_pm.setMinimumHeight(160)
        pm_monitor_layout.addWidget(self.canvas_pm)

        # Scrollable log of readings (last ~200 lines, auto-scroll)
        self.pm_log = QTextEdit()
        self.pm_log.setReadOnly(True)
        self.pm_log.setMaximumHeight(72)
        self.pm_log.setFont(QFont("Consolas", 8))
        self.pm_log.setStyleSheet(
            "QTextEdit { background: #1e1e2e; color: #cdd6f4; "
            "border: 1px solid #45475a; border-radius: 4px; }"
        )
        pm_monitor_layout.addWidget(self.pm_log)

        # Target line indicator
        self.lbl_in_tolerance = QLabel("Status: Waiting...")
        self.lbl_in_tolerance.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.lbl_in_tolerance.setStyleSheet("color: #585b70;")
        pm_monitor_layout.addWidget(self.lbl_in_tolerance)

        prepare_group_box(grp_pm_monitor)
        root.addWidget(grp_pm_monitor)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #45475a;")
        root.addWidget(line)

        btn_row = QHBoxLayout()
        self.btn_run = QPushButton("▶  Start Test Collection")
        self.btn_run.setStyleSheet(
            "QPushButton{background:#a6e3a1;color:#1e1e2e;font-weight:bold;"
            "padding:8px 18px;border-radius:5px;}"
            "QPushButton:hover{background:#94e2d5;}"
            "QPushButton:disabled{background:#313244;color:#585b70;}"
        )
        self.btn_run.clicked.connect(self._on_run)
        self.lbl_status = QLabel("Idle")
        self.lbl_status.setStyleSheet(muted())
        btn_row.addWidget(self.btn_run)
        btn_row.addStretch()
        btn_row.addWidget(self.lbl_status)
        root.addLayout(btn_row)

        note = QLabel(
            "Setup: NKT COM port in NKT Laser tab, PM100D USB + VISA resource above "
            "(Hardware Test → Read PM can verify). "
            "Safety: if RF drops to the floor (default 10/1000) and measured power is "
            "still above target, collection stops with an error."
        )
        note.setWordWrap(True)
        note.setStyleSheet(hint())
        root.addWidget(note)

    def _on_pm_unit_changed(self, text: str):
        self._pm_unit = "W" if text.startswith("W") else "dBm"
        self._redraw_pm_trace()

    def _fmt_actual(self, actual_dbm: float, actual_w: float) -> str:
        """Format the 'Actual' label according to the selected unit."""
        if self._pm_unit == "W":
            return f"Actual: {_format_watts_auto(actual_w)}"
        return f"Actual: {actual_dbm:.2f} dBm"

    def _fmt_target(self, target_dbm: float) -> str:
        if self._pm_unit == "W":
            return f"Target: {_format_watts_auto(dbm_to_watts(target_dbm))}"
        return f"Target: {target_dbm:.2f} dBm"

    def _fmt_pm_head(self, pm_w: float) -> str:
        """PM head reading: always show both auto-scaled W and dBm."""
        pm_dbm = watts_to_dbm(pm_w) if pm_w > 0 else float("-inf")
        w_str = _format_watts_auto(pm_w)
        if math.isfinite(pm_dbm):
            return f"PM: {w_str}  ({pm_dbm:.2f} dBm)"
        return f"PM: {w_str}"

    def _coupling_value(self) -> float:
        return self.spin_coupling_m.value() * (10 ** self.spin_coupling_exp.value())

    def _on_coupling_changed(self):
        self.lbl_coupling_sci.setText(f"= {_format_sci(self._coupling_value())}")
        self._update_pm_hint()

    def _on_wl_source_changed(self, idx: int):
        use_loop = (idx == 1)
        self.lbl_wl_manual.setVisible(not use_loop)
        self.edit_wavelengths.setVisible(not use_loop)
        self.lbl_loop_tab_info.setVisible(use_loop)
        self._loop_wrap.setVisible(use_loop)
        if use_loop:
            self._on_sync_loop_tab()

    def _on_sync_loop_tab(self):
        """Read current Loop tab config and refresh the summary label."""
        if self._main_win is None or not hasattr(self._main_win, "loop_tab"):
            self.lbl_loop_tab_summary.setText("(main window not available)")
            return
        snap = self._main_win.loop_tab.get_loop_snapshot()
        mode = snap.get("mode", 0)
        mode_names = {0: "Random Multi-Peak", 1: "Manual Multi-Peak", 2: "Single Peak Scan"}
        mode_name = mode_names.get(mode, f"mode={mode}")
        n_steps = snap.get("n_steps", "?")
        if mode == 0:
            detail = (
                f"{snap.get('wl_min', '?')}–{snap.get('wl_max', '?')} nm  "
                f"seed={snap.get('seed', '?')}  "
                f"{snap.get('n_ch_min', '?')}–{snap.get('n_ch_max', '?')} ch"
            )
        elif mode == 2:
            detail = (
                f"{snap.get('single_wl_min', '?')}–{snap.get('single_wl_max', '?')} nm  "
                f"step={snap.get('single_step', '?')} nm"
            )
        else:
            wls = snap.get("manual_wavelengths", [])
            detail = f"{len(wls)} manual channels: {wls}"
        self.lbl_loop_tab_summary.setText(
            f"{mode_name}  |  {n_steps} steps  |  {detail}"
        )

    def _on_use_camera_tab(self, use_cam: bool):
        self.spin_exposure.setEnabled(not use_cam)
        self.spin_gain.setEnabled(not use_cam)

    def _pm_backend(self) -> str:
        return self.combo_pm.currentData() or "pm100d"

    def _on_pm_backend_changed(self, _index=None):
        sim = self._pm_backend() == "simulated"
        self.lbl_pm_visa.setVisible(not sim)
        self.edit_visa.setVisible(not sim)
        self.btn_visa_scan.setVisible(not sim)
        self.lbl_pm_sim.setVisible(sim)
        self.spin_sim_max.setVisible(sim)

    def _scan_visa(self):
        from core.pm_meter import list_visa_resources
        from PyQt5.QtWidgets import QMessageBox

        resources = list_visa_resources()
        if not resources:
            QMessageBox.warning(
                self,
                "VISA Scan",
                "No VISA devices found.\n\n"
                "Check PM100D USB, Thorlabs drivers, and NI-VISA.\n"
                "Install: pip install pyvisa",
            )
            return
        pm_like = [r for r in resources if "1313" in r or "PM" in r.upper()]
        pick = pm_like[0] if pm_like else resources[0]
        self.edit_visa.setText(pick)
        if len(resources) == 1:
            QMessageBox.information(self, "VISA Scan", f"Found:\n{pick}")
        else:
            QMessageBox.information(
                self,
                "VISA Scan",
                "Found:\n" + "\n".join(resources) + f"\n\nSelected: {pick}",
            )

    def _update_pm_hint(self):
        try:
            txt = self.edit_targets.text().strip().split(",")[0].strip()
            if not txt:
                self.lbl_pm_hint.setText("—")
                return
            tgt = float(txt)
            eff = self._coupling_value()
            pm_w = pm_watts_for_target(tgt, eff)
            act_w = dbm_to_watts(tgt)
            self.lbl_pm_hint.setText(
                f"Target {tgt:.1f} dBm = {act_w:.3e} W actual  |  "
                f"coupling {_format_sci(eff)}  →  PM ≈ {pm_w:.3e} W"
            )
        except ValueError:
            self.lbl_pm_hint.setText("—")

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Test data output folder")
        if d:
            self.edit_outdir.setText(d)

    def _on_run(self):
        if self._main_win is not None:
            self._main_win.start_test_data_collection()

    def set_running(self, running: bool):
        self.btn_run.setEnabled(not running)
        self.btn_live.setEnabled(not running)

    def set_status(self, text: str):
        self.lbl_status.setText(text)

    # ── Live power monitor (before / outside a test run) ────────────────────

    def _first_wavelength(self) -> float:
        if self.combo_wl_source.currentIndex() == 1:
            if self._main_win is not None and hasattr(self._main_win, "loop_tab"):
                try:
                    from core.nkt_support import build_nkt_step_configs
                    snap = self._main_win.loop_tab.get_loop_snapshot()
                    cfgs = build_nkt_step_configs(snap)
                    if cfgs:
                        wls = cfgs[0].get("wavelengths", [])
                        if wls:
                            return float(sum(wls) / len(wls))
                except Exception:
                    pass
            return 600.0
        txt = self.edit_wavelengths.text().strip().split(",")[0].strip()
        try:
            return float(txt)
        except ValueError:
            return 600.0

    def _first_target_dbm(self):
        txt = self.edit_targets.text().strip().split(",")[0].strip()
        try:
            return float(txt)
        except ValueError:
            return None

    def _on_toggle_live(self, checked: bool):
        if checked:
            self._start_live_monitor()
        else:
            self.stop_live_monitor()

    def _start_live_monitor(self):
        from PyQt5.QtWidgets import QMessageBox

        if self._live_monitor is not None:
            return
        backend = self._pm_backend()
        if backend == "pm100d" and not self.edit_visa.text().strip():
            QMessageBox.warning(
                self,
                "Live Power",
                "PM100D VISA resource is empty.\n\n"
                "Scan it here or in Hardware Test, or paste the USB resource string.",
            )
            self.btn_live.blockSignals(True)
            self.btn_live.setChecked(False)
            self.btn_live.blockSignals(False)
            return

        from core.test_data_runner import LivePowerMonitor

        cfg = {
            "test_pm_backend": backend,
            "test_pm_visa_resource": self.edit_visa.text().strip(),
            "test_pm_sim_max_w": self.spin_sim_max.value(),
            "test_coupling_eff": self._coupling_value(),
            "test_pm_settle_s": self.spin_pm_settle.value(),
            "live_wavelength_nm": self._first_wavelength(),
        }

        self.reset_pm_monitor()
        self.begin_live_trace()
        self.btn_run.setEnabled(False)
        self.btn_live.setText("■  Stop Live Power")
        self.lbl_in_tolerance.setText("Status: Connecting power meter…")
        self.lbl_in_tolerance.setStyleSheet("color: #f9e2af;")

        mon = LivePowerMonitor(cfg)
        mon.reading_signal.connect(self.on_live_reading, Qt.QueuedConnection)
        mon.error_signal.connect(self._on_live_error, Qt.QueuedConnection)
        mon.started_signal.connect(self._on_live_started, Qt.QueuedConnection)
        mon.finished.connect(self._on_live_finished, Qt.QueuedConnection)
        self._live_monitor = mon
        mon.start()

    def stop_live_monitor(self):
        """Stop the live monitor (also called by the main window before a run)."""
        mon = self._live_monitor
        if mon is not None:
            mon.request_stop()
            mon.wait(2000)
        if self.btn_live.isChecked():
            self.btn_live.blockSignals(True)
            self.btn_live.setChecked(False)
            self.btn_live.blockSignals(False)
        self.btn_live.setText("●  Show Live Power")

    def _on_live_started(self, desc: str):
        self.pm_log.append(f"[live] connected: {desc}")
        self.lbl_in_tolerance.setText("Status: Live monitoring…")
        self.lbl_in_tolerance.setStyleSheet("color: #94e2d5;")

    def _on_live_error(self, msg: str):
        self.pm_log.append(f"[live error] {msg}")
        self.lbl_in_tolerance.setText(f"Status: Live error — {msg}")
        self.lbl_in_tolerance.setStyleSheet("color: #f38ba8;")

    def _on_live_finished(self):
        self._live_monitor = None
        self.btn_live.setText("●  Show Live Power")
        if self.btn_live.isChecked():
            self.btn_live.blockSignals(True)
            self.btn_live.setChecked(False)
            self.btn_live.blockSignals(False)
        if self._main_win is None or not (
            getattr(self._main_win, "test_runner", None)
            and self._main_win.test_runner.isRunning()
        ):
            self.btn_run.setEnabled(True)

    def begin_live_trace(self):
        """Start a rolling live-power chart (target band from first target, if any)."""
        self._trace_target_dbm = self._first_target_dbm()
        self._trace_t.clear()
        self._trace_dbm.clear()
        self._trace_w.clear()
        self._trace_rf.clear()
        self._trace_phase.clear()
        self._trigger_t = None
        tgt = self._trace_target_dbm
        self.lbl_live_target.setText(
            self._fmt_target(tgt) if tgt is not None else "Target: ---"
        )
        self._redraw_pm_trace()

    def on_live_reading(self, t_sec: float, pm_w: float, actual_w: float,
                        actual_dbm: float):
        """Live PM stream slot (LivePowerMonitor.reading_signal)."""
        self.lbl_live_rf.setText("RF: live (PM only)")
        self.lbl_live_pm.setText(self._fmt_pm_head(pm_w))
        self.lbl_live_dbm.setText(self._fmt_actual(actual_dbm, actual_w))
        self.lbl_in_tolerance.setText(f"Status: Live monitoring…  t={t_sec:.1f}s")
        self.lbl_in_tolerance.setStyleSheet("color: #94e2d5;")

        self._trace_t.append(t_sec)
        self._trace_dbm.append(actual_dbm)
        self._trace_w.append(actual_w)
        self._trace_rf.append(-1)
        self._trace_phase.append("live")
        self._trim_trace()
        self._redraw_pm_trace()

        line = f"t={t_sec:6.1f}s  PM={_format_watts_auto(pm_w)}  act={actual_dbm:.2f} dBm  ({_format_watts_auto(actual_w)})  [live]"
        self.pm_log.append(line)
        doc = self.pm_log.document()
        if doc.blockCount() > self._PM_LOG_MAX_LINES:
            cursor = QTextCursor(doc)
            cursor.movePosition(QTextCursor.Start)
            for _ in range(doc.blockCount() - self._PM_LOG_MAX_LINES):
                cursor.select(QTextCursor.BlockUnderCursor)
                cursor.removeSelectedText()
                cursor.deleteChar()
        self.pm_log.moveCursor(QTextCursor.End)

    def _trim_trace(self, max_points: int = 4000):
        """Bound trace memory during long live sessions."""
        n = len(self._trace_t)
        if n > max_points:
            cut = n - max_points
            del self._trace_t[:cut]
            del self._trace_dbm[:cut]
            del self._trace_w[:cut]
            del self._trace_rf[:cut]
            del self._trace_phase[:cut]

    def _style_pm_axes(self, use_watts: bool = False):
        ax = self.ax_pm
        ax.set_facecolor("#181825")
        ax.tick_params(colors="#6c7086", labelsize=mpl_font_size(-1))
        for spine in ax.spines.values():
            spine.set_color("#45475a")
        ax.set_xlabel("Time (s)", color="#6c7086", fontsize=mpl_font_size())
        ylabel = "Power (W)" if use_watts else "Power (dBm)"
        ax.set_ylabel(ylabel, color="#6c7086", fontsize=mpl_font_size())
        ax.grid(True, color="#313244", linewidth=0.5, alpha=0.8)

    def reset_pm_monitor(self):
        """Clear real-time PM panel (idle or before a new run)."""
        self.lbl_live_rf.setText("RF: ---")
        self.lbl_live_pm.setText("PM: ---")
        self.lbl_live_dbm.setText("Actual: ---")
        self.lbl_live_target.setText("Target: ---")
        self.pm_log.clear()
        self.lbl_in_tolerance.setText("Status: Waiting...")
        self.lbl_in_tolerance.setStyleSheet("color: #585b70;")
        self._trace_target_dbm = None
        self._trace_t.clear()
        self._trace_dbm.clear()
        self._trace_w.clear()
        self._trace_rf.clear()
        self._trace_phase.clear()
        self._trigger_t = None
        self._redraw_pm_trace()

    def set_pm_tolerance(self, tol_db: float):
        self._pm_tol_db = max(0.01, float(tol_db))

    def begin_pm_trace(self, target_dbm: float, tol_db: float):
        """Start a new power-vs-time chart for one target point."""
        self._pm_tol_db = max(0.01, float(tol_db))
        self._trace_target_dbm = float(target_dbm)
        self._trace_t.clear()
        self._trace_dbm.clear()
        self._trace_w.clear()
        self._trace_rf.clear()
        self._trace_phase.clear()
        self._trigger_t = None
        self.lbl_live_target.setText(self._fmt_target(target_dbm))
        self._redraw_pm_trace()

    def on_pm_reading(
        self,
        t_sec: float,
        amp: int,
        pm_w: float,
        actual_w: float,
        actual_dbm: float,
        target_dbm: float,
        phase: str,
    ):
        """Update live labels, trace plot, and log (TestDataRunner Qt signal)."""
        self.lbl_live_rf.setText(f"RF: {amp}/1000")
        self.lbl_live_pm.setText(self._fmt_pm_head(pm_w))
        self.lbl_live_dbm.setText(self._fmt_actual(actual_dbm, actual_w))
        self.lbl_live_target.setText(self._fmt_target(target_dbm))

        phase_l = (phase or "").lower()
        if phase_l == "adjust":
            status = f"Status: Adjusting RF…  t={t_sec:.2f}s"
            color = "#f9e2af"
        elif phase_l in ("triggered", "overshoot"):
            if phase_l == "overshoot":
                status = (
                    f"Status: Crossed upper band — capture @ {amp}/1000, "
                    f"{actual_dbm:.2f} dBm"
                )
            else:
                status = f"Status: Target triggered — RF locked @ {amp}/1000"
            color = "#89b4fa"
            if self._trigger_t is None:
                self._trigger_t = t_sec
        elif phase_l == "settle":
            status = f"Status: Settling…  t={t_sec:.2f}s  (RF fixed)"
            color = "#cba6f7"
        elif phase_l == "verify":
            status = f"Status: Verifying…  t={t_sec:.2f}s"
            color = "#a6e3a1"
        else:
            status = f"Status: {phase}  t={t_sec:.2f}s"
            color = "#cdd6f4"

        err_db = abs(actual_dbm - target_dbm)
        if phase_l in ("triggered", "overshoot", "settle", "verify") and (
            err_db <= self._pm_tol_db or phase_l == "overshoot"
        ):
            status += f"  (±{self._pm_tol_db:.2f} dB OK)"
        self.lbl_in_tolerance.setText(status)
        self.lbl_in_tolerance.setStyleSheet(f"color: {color};")

        self._trace_t.append(t_sec)
        self._trace_dbm.append(actual_dbm)
        self._trace_w.append(actual_w)
        self._trace_rf.append(amp)
        self._trace_phase.append(phase_l)
        self._redraw_pm_trace()

        line = (
            f"t={t_sec:6.2f}s  RF={amp:4d}  PM={_format_watts_auto(pm_w)}  "
            f"act={actual_dbm:.2f} dBm  ({_format_watts_auto(actual_w)})  [{phase}]"
        )
        self.pm_log.append(line)
        doc = self.pm_log.document()
        if doc.blockCount() > self._PM_LOG_MAX_LINES:
            cursor = QTextCursor(doc)
            cursor.movePosition(QTextCursor.Start)
            for _ in range(doc.blockCount() - self._PM_LOG_MAX_LINES):
                cursor.select(QTextCursor.BlockUnderCursor)
                cursor.removeSelectedText()
                cursor.deleteChar()
        self.pm_log.moveCursor(QTextCursor.End)

    def _redraw_pm_trace(self):
        ax = self.ax_pm
        ax.cla()
        use_watts = (self._pm_unit == "W")
        self._style_pm_axes(use_watts=use_watts)

        trace_y = self._trace_w if (use_watts and self._trace_w) else self._trace_dbm

        tgt = self._trace_target_dbm
        tol = self._pm_tol_db
        if tgt is not None:
            if use_watts:
                tgt_w = dbm_to_watts(tgt)
                tol_w_lo = dbm_to_watts(tgt - tol)
                tol_w_hi = dbm_to_watts(tgt + tol)
                ax.axhline(tgt_w, color="#cba6f7", linewidth=1.0, linestyle="--",
                           label=f"Target {_format_watts_auto(tgt_w)}")
                ax.axhspan(tol_w_lo, tol_w_hi, color="#cba6f7", alpha=0.12,
                           label=f"±{tol:.2f} dB band")
            else:
                ax.axhline(tgt, color="#cba6f7", linewidth=1.0, linestyle="--",
                           label=f"Target {tgt:.1f} dBm")
                ax.axhspan(tgt - tol, tgt + tol, color="#cba6f7", alpha=0.12,
                           label=f"±{tol:.2f} dB")

        if self._trace_t and len(trace_y) == len(self._trace_t):
            adj_t, adj_y = [], []
            lock_t, lock_y = [], []
            live_t, live_y = [], []
            for t, y, ph in zip(self._trace_t, trace_y, self._trace_phase):
                if not math.isfinite(y):
                    continue
                if ph == "adjust":
                    adj_t.append(t)
                    adj_y.append(y)
                elif ph == "live":
                    live_t.append(t)
                    live_y.append(y)
                else:
                    lock_t.append(t)
                    lock_y.append(y)
            # overshoot uses same green segment as triggered
            if adj_t:
                ax.plot(adj_t, adj_y, color="#89b4fa", linewidth=1.2,
                        marker=".", markersize=3, label="Adjusting")
            if lock_t:
                ax.plot(lock_t, lock_y, color="#a6e3a1", linewidth=1.4,
                        marker=".", markersize=4, label="Triggered / settle")
            if live_t:
                ax.plot(live_t, live_y, color="#94e2d5", linewidth=1.2,
                        marker=".", markersize=3, label="Live")
            if self._trigger_t is not None:
                ax.axvline(self._trigger_t, color="#f38ba8", linewidth=0.9,
                           linestyle=":", alpha=0.85, label="Trigger")

            # Rolling time window — view follows latest samples (PM100D-style).
            t_max = max(self._trace_t)
            t_min = max(0.0, t_max - self._PM_TRACE_WINDOW_S)
            ax.set_xlim(t_min, t_max + 0.05 * self._PM_TRACE_WINDOW_S)
            vis_y = [y for t, y in zip(self._trace_t, trace_y)
                     if t >= t_min and math.isfinite(y)]
            if vis_y:
                y_lo = min(vis_y)
                y_hi = max(vis_y)
                if tgt is not None:
                    if use_watts:
                        y_lo = min(y_lo, dbm_to_watts(tgt - tol))
                        y_hi = max(y_hi, dbm_to_watts(tgt + tol))
                    else:
                        y_lo = min(y_lo, tgt - tol)
                        y_hi = max(y_hi, tgt + tol)
                if use_watts:
                    pad = max(y_hi * 0.05, (y_hi - y_lo) * 0.12)
                    ax.set_ylim(max(0.0, y_lo - pad), y_hi + pad)
                    import matplotlib.ticker as mticker
                    ax.yaxis.set_major_formatter(
                        mticker.FuncFormatter(
                            lambda v, _: _format_watts_auto(v) if v >= 0 else ""
                        )
                    )
                else:
                    pad = max(0.5, (y_hi - y_lo) * 0.12)
                    ax.set_ylim(y_lo - pad, y_hi + pad)

            ax.legend(fontsize=mpl_font_size(-2), loc="upper right",
                      facecolor="#313244", edgecolor="#45475a",
                      labelcolor="#cdd6f4")
        else:
            ax.text(
                0.5, 0.5,
                "Power vs time — click “Show Live Power” or start Test Collection",
                transform=ax.transAxes, ha="center", va="center",
                color="#585b70", fontsize=mpl_font_size(),
            )

        self.fig_pm.tight_layout(pad=0.6)
        self.canvas_pm.draw_idle()

    def get_config(self) -> dict:
        use_loop = (self.combo_wl_source.currentIndex() == 1)
        cfg = {
            "test_data_enabled": True,
            "test_osa_enabled": self.chk_osa_test.isChecked(),
            "test_wl_source": "loop_tab" if use_loop else "manual",
            "test_wavelengths_nm": self.edit_wavelengths.text().strip(),
            "test_target_dbm_list": self.edit_targets.text().strip(),
            "test_coupling_eff": self._coupling_value(),
            "test_coupling_mantissa": self.spin_coupling_m.value(),
            "test_coupling_exponent": self.spin_coupling_exp.value(),
            "test_power_tol_db": self.spin_tol_db.value(),
            "test_initial_rf": self.spin_initial_rf.value(),
            "test_rf_min": self.spin_rf_min.value(),
            "test_rf_max": self.spin_rf_max.value(),
            "test_rf_algo": (
                "bisect"
                if self.combo_rf_algo.currentText() == "Binary search"
                else "ramp"
            ),
            "test_laser_settle_s": self.spin_laser_settle.value(),
            "test_pm_settle_s": self.spin_pm_settle.value(),
            "test_rf_max_iter": self.spin_rf_iter.value(),
            "test_rf_step_interval_ms": self.spin_rf_step_ms.value(),
            "test_pm_backend": self._pm_backend(),
            "test_pm_visa_resource": self.edit_visa.text().strip(),
            "test_pm_sim_max_w": self.spin_sim_max.value(),
            "test_out_dir": self.edit_outdir.text().strip() or ".",
            "test_file_prefix": self.edit_prefix.text().strip() or "test",
            "test_log_csv": self.edit_log.text().strip() or "test_data_log.csv",
            "test_use_camera_tab": self.chk_use_camera_tab.isChecked(),
            "test_repeats": self.spin_repeats.value(),
            "bright_enabled": self.chk_bright_enabled.isChecked(),
            "bright_rf_amp": self.spin_bright_rf_amp.value(),
            "bright_settle_s": self.spin_bright_settle_s.value(),
            "bright_exposures_ms": self.edit_bright_exposures.text().strip(),
        }
        if not self.chk_use_camera_tab.isChecked():
            cfg["test_exposure_ms"] = self.spin_exposure.value()
            cfg["test_gain"] = self.spin_gain.value()

        if use_loop and self._main_win is not None and hasattr(self._main_win, "loop_tab"):
            snap = self._main_win.loop_tab.get_loop_snapshot()
            cfg.update(snap)
            if hasattr(self._main_win, "nkt_tab"):
                nkt = self._main_win.nkt_tab.get_config()
                cfg["manual_wavelengths"] = nkt.get("manual_wavelengths", [])
                cfg["manual_amplitudes"] = nkt.get("manual_amplitudes", [])

        return cfg

    def apply_config(self, cfg: dict) -> None:
        """Restore UI state from a saved config dict."""
        algo = cfg.get("test_rf_algo", "ramp")
        self.combo_rf_algo.setCurrentText(
            "Binary search" if algo == "bisect" else "Linear ramp"
        )
        if "test_wl_source" in cfg:
            idx = 1 if cfg["test_wl_source"] == "loop_tab" else 0
            self.combo_wl_source.setCurrentIndex(idx)
        if "test_wavelengths_nm" in cfg:
            self.edit_wavelengths.setText(str(cfg["test_wavelengths_nm"]))
        if "test_target_dbm_list" in cfg:
            self.edit_targets.setText(str(cfg["test_target_dbm_list"]))
        if "test_coupling_mantissa" in cfg:
            self.spin_coupling_m.setValue(float(cfg["test_coupling_mantissa"]))
        if "test_coupling_exponent" in cfg:
            self.spin_coupling_exp.setValue(int(cfg["test_coupling_exponent"]))
        if "test_power_tol_db" in cfg:
            self.spin_tol_db.setValue(float(cfg["test_power_tol_db"]))
        if "test_initial_rf" in cfg:
            self.spin_initial_rf.setValue(int(cfg["test_initial_rf"]))
        if "test_rf_min" in cfg:
            self.spin_rf_min.setValue(int(cfg["test_rf_min"]))
        if "test_rf_max" in cfg:
            self.spin_rf_max.setValue(int(cfg["test_rf_max"]))
        if "test_laser_settle_s" in cfg:
            self.spin_laser_settle.setValue(float(cfg["test_laser_settle_s"]))
        if "test_pm_settle_s" in cfg:
            self.spin_pm_settle.setValue(float(cfg["test_pm_settle_s"]))
        if "test_rf_step_interval_ms" in cfg:
            self.spin_rf_step_ms.setValue(float(cfg["test_rf_step_interval_ms"]))
        if "test_pm_backend" in cfg:
            idx = self.combo_pm.findData(cfg["test_pm_backend"])
            if idx >= 0:
                self.combo_pm.setCurrentIndex(idx)
        if "test_pm_visa_resource" in cfg:
            self.edit_visa.setText(str(cfg["test_pm_visa_resource"]))
        if "test_pm_sim_max_w" in cfg:
            self.spin_sim_max.setValue(float(cfg["test_pm_sim_max_w"]))
        if "test_out_dir" in cfg:
            self.edit_outdir.setText(str(cfg["test_out_dir"]))
        if "test_file_prefix" in cfg:
            self.edit_prefix.setText(str(cfg["test_file_prefix"]))
        if "test_log_csv" in cfg:
            self.edit_log.setText(str(cfg["test_log_csv"]))
        if "test_repeats" in cfg:
            self.spin_repeats.setValue(int(cfg["test_repeats"]))
        if "bright_enabled" in cfg:
            self.chk_bright_enabled.setChecked(bool(cfg["bright_enabled"]))
        if "bright_rf_amp" in cfg:
            self.spin_bright_rf_amp.setValue(int(cfg["bright_rf_amp"]))
        if "bright_settle_s" in cfg:
            self.spin_bright_settle_s.setValue(float(cfg["bright_settle_s"]))
        if "bright_exposures_ms" in cfg:
            self.edit_bright_exposures.setText(str(cfg["bright_exposures_ms"]))
