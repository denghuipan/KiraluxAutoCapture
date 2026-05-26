"""
Test Data Collection — automated RF power servo + Kiralux capture.

Uses PM100D reading × coupling efficiency to reach target output power (dBm),
then captures one frame per (wavelength, target power) point.
"""
import math
import os

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QLabel, QDoubleSpinBox, QSpinBox,
    QLineEdit, QPushButton, QComboBox, QCheckBox,
    QFileDialog, QFrame,
)
from PyQt5.QtCore import Qt

from ui.style_helpers import hint, muted
from core.power_math import dbm_to_watts, pm_watts_for_target


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
    def __init__(self, main_window=None):
        super().__init__()
        self._main_win = main_window

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        intro = QLabel(
            "Automated test-data collection (pure Python): NKT sets wavelength & RF, "
            "PM100D reads power over USB/VISA, then Kiralux captures one frame per point. "
            "Does not affect the normal Auto Capture Loop."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(hint())
        root.addWidget(intro)

        row_top = QHBoxLayout()
        row_top.setSpacing(8)

        # ── Laser / wavelength ───────────────────────────────────────────────
        grp_laser = QGroupBox("Laser & Targets")
        form_l = QFormLayout(grp_laser)
        form_l.setHorizontalSpacing(10)
        form_l.setVerticalSpacing(6)

        self.edit_wavelengths = QLineEdit("650")
        self.edit_wavelengths.setPlaceholderText("e.g. 650  or  640,650,660")
        self.edit_targets = QLineEdit("-20,-30,-40")
        self.edit_targets.setPlaceholderText("dBm list, e.g. -20,-30,-40,-50")

        coupling_row = QHBoxLayout()
        self.spin_coupling_m = QDoubleSpinBox()
        self.spin_coupling_m.setRange(0.001, 9.9999)
        self.spin_coupling_m.setDecimals(4)
        self.spin_coupling_m.setValue(1.0)
        self.spin_coupling_m.setToolTip("Mantissa (coefficient)")
        self.spin_coupling_exp = QSpinBox()
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

        self.spin_tol_db = QDoubleSpinBox()
        self.spin_tol_db.setRange(0.05, 10.0)
        self.spin_tol_db.setValue(0.5)
        self.spin_tol_db.setSuffix("  dB")

        self.lbl_pm_hint = QLabel("—")
        self.lbl_pm_hint.setWordWrap(True)
        self.lbl_pm_hint.setStyleSheet(muted())

        form_l.addRow("Wavelength(s) nm:", self.edit_wavelengths)
        form_l.addRow("Target power(s) dBm:", self.edit_targets)
        form_l.addRow("Coupling efficiency:", coupling_wrap)
        form_l.addRow("", coupling_note)
        form_l.addRow("Power tolerance:", self.spin_tol_db)
        form_l.addRow("", self.lbl_pm_hint)
        row_top.addWidget(grp_laser)

        # ── RF control ───────────────────────────────────────────────────────
        grp_rf = QGroupBox("RF Control")
        form_r = QFormLayout(grp_rf)
        self.spin_initial_rf = QSpinBox()
        self.spin_initial_rf.setRange(10, 1000)
        self.spin_initial_rf.setValue(500)
        self.spin_rf_min = QSpinBox()
        self.spin_rf_min.setRange(0, 999)
        self.spin_rf_min.setValue(10)
        self.spin_rf_min.setToolTip(
            "Stop with error if RF reaches this floor and power is still above target."
        )
        self.spin_rf_max = QSpinBox()
        self.spin_rf_max.setRange(1, 1000)
        self.spin_rf_max.setValue(1000)
        self.spin_laser_settle = QDoubleSpinBox()
        self.spin_laser_settle.setRange(0.0, 30.0)
        self.spin_laser_settle.setValue(0.5)
        self.spin_laser_settle.setSuffix("  s")
        self.spin_pm_settle = QDoubleSpinBox()
        self.spin_pm_settle.setRange(0.0, 10.0)
        self.spin_pm_settle.setValue(0.3)
        self.spin_pm_settle.setSuffix("  s")
        self.spin_rf_iter = QSpinBox()
        self.spin_rf_iter.setRange(5, 200)
        self.spin_rf_iter.setValue(40)

        form_r.addRow("Initial RF amp (0–1000):", self.spin_initial_rf)
        form_r.addRow("RF floor (stop if too high):", self.spin_rf_min)
        form_r.addRow("RF ceiling:", self.spin_rf_max)
        form_r.addRow("Laser settle:", self.spin_laser_settle)
        form_r.addRow("PM read settle:", self.spin_pm_settle)
        form_r.addRow("Max RF iterations:", self.spin_rf_iter)
        row_top.addWidget(grp_rf)

        root.addLayout(row_top)

        row_mid = QHBoxLayout()
        row_mid.setSpacing(8)

        # ── Power meter ────────────────────────────────────────────────────────
        grp_pm = QGroupBox("Power Meter (PM100D — USB/VISA)")
        form_p = QFormLayout(grp_pm)
        self.combo_pm = QComboBox()
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

        self.spin_sim_max = QDoubleSpinBox()
        self.spin_sim_max.setRange(1e-12, 1e6)
        self.spin_sim_max.setValue(1.0)
        self.spin_sim_max.setSuffix("  W")
        self.spin_sim_max.setToolTip("Simulated PM full-scale at RF=1000 (dev only).")

        self.lbl_pm_visa = QLabel("VISA resource:")
        self.lbl_pm_sim = QLabel("Sim max reading:")

        form_p.addRow("Backend:", self.combo_pm)
        form_p.addRow(self.lbl_pm_visa, visa_wrap)
        form_p.addRow(self.lbl_pm_sim, self.spin_sim_max)
        row_mid.addWidget(grp_pm)

        # ── Camera / output ──────────────────────────────────────────────────
        grp_cam = QGroupBox("Camera & Output")
        form_c = QFormLayout(grp_cam)
        self.chk_use_camera_tab = QCheckBox("Use exposure / gain / ROI from Camera tab")
        self.chk_use_camera_tab.setChecked(True)

        self.spin_exposure = QDoubleSpinBox()
        self.spin_exposure.setRange(0.03, 22806.0)
        self.spin_exposure.setValue(0.06)
        self.spin_exposure.setSuffix("  ms")
        self.spin_gain = QSpinBox()
        self.spin_gain.setRange(0, 480)
        self.spin_gain.setValue(0)

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
        form_c.addRow("Output dir:", dir_row)
        form_c.addRow("File prefix:", self.edit_prefix)
        form_c.addRow("Log CSV:", self.edit_log)
        row_mid.addWidget(grp_cam)
        root.addLayout(row_mid)

        self.chk_use_camera_tab.toggled.connect(self._on_use_camera_tab)
        self.combo_pm.currentIndexChanged.connect(self._on_pm_backend_changed)
        self.edit_targets.textChanged.connect(self._update_pm_hint)
        self.spin_coupling_m.valueChanged.connect(self._on_coupling_changed)
        self.spin_coupling_exp.valueChanged.connect(self._on_coupling_changed)
        self._on_use_camera_tab(True)
        self._on_pm_backend_changed()
        self._on_coupling_changed()

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
        root.addStretch(1)

    def _coupling_value(self) -> float:
        return self.spin_coupling_m.value() * (10 ** self.spin_coupling_exp.value())

    def _on_coupling_changed(self):
        self.lbl_coupling_sci.setText(f"= {_format_sci(self._coupling_value())}")
        self._update_pm_hint()

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

    def set_status(self, text: str):
        self.lbl_status.setText(text)

    def get_config(self) -> dict:
        cfg = {
            "test_data_enabled": True,
            "test_wavelengths_nm": self.edit_wavelengths.text().strip(),
            "test_target_dbm_list": self.edit_targets.text().strip(),
            "test_coupling_eff": self._coupling_value(),
            "test_coupling_mantissa": self.spin_coupling_m.value(),
            "test_coupling_exponent": self.spin_coupling_exp.value(),
            "test_power_tol_db": self.spin_tol_db.value(),
            "test_initial_rf": self.spin_initial_rf.value(),
            "test_rf_min": self.spin_rf_min.value(),
            "test_rf_max": self.spin_rf_max.value(),
            "test_laser_settle_s": self.spin_laser_settle.value(),
            "test_pm_settle_s": self.spin_pm_settle.value(),
            "test_rf_max_iter": self.spin_rf_iter.value(),
            "test_pm_backend": self._pm_backend(),
            "test_pm_visa_resource": self.edit_visa.text().strip(),
            "test_pm_sim_max_w": self.spin_sim_max.value(),
            "test_out_dir": self.edit_outdir.text().strip() or ".",
            "test_file_prefix": self.edit_prefix.text().strip() or "test",
            "test_log_csv": self.edit_log.text().strip() or "test_data_log.csv",
            "test_use_camera_tab": self.chk_use_camera_tab.isChecked(),
        }
        if not self.chk_use_camera_tab.isChecked():
            cfg["test_exposure_ms"] = self.spin_exposure.value()
            cfg["test_gain"] = self.spin_gain.value()
        return cfg
