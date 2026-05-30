"""
Main application window — holds all tabs + shared bottom status bar.
"""
import numpy as np
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QPushButton, QProgressBar, QLabel,
    QTextEdit, QSplitter, QSizePolicy, QMessageBox
)
from PyQt5.QtCore import Qt, QDateTime
from PyQt5.QtGui import QFont, QTextCursor

from ui.tab_camera import CameraTab
from ui.tab_nkt import NKTTab
from ui.tab_loop import LoopTab
from ui.tab_osa import OSATab
from ui.tab_hardware_test import HardwareTestTab
from ui.tab_test_data import TestDataTab
from ui.settings_dialog import SettingsDialog
from core.loop_runner import LoopRunner
from core.test_data_runner import TestDataRunner
from core.app_settings import get_settings, APP_NAME, APP_VERSION
from ui.style_helpers import muted
from ui.layout_helpers import MAIN_MIN_WIDTH, MAIN_MIN_HEIGHT


class MainWindow(QMainWindow):
    def __init__(self, nkt_thread=None):
        super().__init__()
        self.nkt_thread = nkt_thread
        self.setWindowTitle(f"{APP_NAME}  {APP_VERSION}")
        self.setMinimumSize(MAIN_MIN_WIDTH, MAIN_MIN_HEIGHT)
        self.resize(MAIN_MIN_WIDTH, 820)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # Header row
        hdr_row = QHBoxLayout()
        self.hdr_label_ref = QLabel(f"{APP_NAME}  {APP_VERSION}")
        self.hdr_label_ref.setFont(QFont("Segoe UI", 14, QFont.Bold))
        self.hdr_label_ref.setStyleSheet("color: #89b4fa; padding: 2px 4px;")
        hdr_row.addWidget(self.hdr_label_ref)
        hdr_row.addStretch()

        self.btn_settings_ref = QPushButton("⚙  Settings")
        self.btn_settings_ref.setFixedWidth(100)
        self.btn_settings_ref.setStyleSheet(
            "QPushButton{background:#45475a;color:#cdd6f4;border-radius:5px;padding:4px 10px;}"
            "QPushButton:hover{background:#585b70;}"
        )
        self.btn_settings_ref.clicked.connect(self._open_settings)
        hdr_row.addWidget(self.btn_settings_ref)
        root.addLayout(hdr_row)

        # Main splitter
        splitter = QSplitter(Qt.Vertical)
        root.addWidget(splitter, stretch=1)

        # Tabs
        self.tabs = QTabWidget()
        self.cam_tab  = CameraTab()
        self.nkt_tab  = NKTTab(nkt_thread=nkt_thread)
        self.loop_tab = LoopTab(main_window=self)
        self.osa_tab  = OSATab()
        self.test_tab = TestDataTab(main_window=self)
        self.hw_tab   = HardwareTestTab(main_window=self, nkt_thread=nkt_thread)
        self.tabs.addTab(self.hw_tab,   "Hardware Test")
        self.tabs.addTab(self.cam_tab,  "Camera")
        self.tabs.addTab(self.nkt_tab,  "NKT Laser")
        self.tabs.addTab(self.loop_tab, "Auto Capture Loop")
        self.tabs.addTab(self.test_tab, "Test Data")
        self.tabs.addTab(self.osa_tab,  "OSA")
        splitter.addWidget(self.tabs)

        # Log panel
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.setContentsMargins(0, 4, 0, 0)
        log_layout.setSpacing(2)
        log_hdr = QLabel("Log Output")
        log_hdr.setStyleSheet(muted())
        log_layout.addWidget(log_hdr)
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(180)
        self.log_box.setMinimumHeight(100)
        log_layout.addWidget(self.log_box)
        splitter.addWidget(log_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        # Bottom control bar
        bottom = QHBoxLayout()
        bottom.setSpacing(8)

        self.btn_start = QPushButton("Start Acquisition")
        self.btn_start.setStyleSheet(
            "QPushButton { background:#a6e3a1; color:#1e1e2e; font-weight:bold;"
            " padding:6px 20px; border-radius:5px; }"
            "QPushButton:hover { background:#94e2d5; }"
            "QPushButton:disabled { background:#313244; color:#585b70; }"
        )
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet(
            "QPushButton { background:#f38ba8; color:#1e1e2e; font-weight:bold;"
            " padding:6px 16px; border-radius:5px; }"
            "QPushButton:hover { background:#eba0ac; }"
            "QPushButton:disabled { background:#313244; color:#585b70; }"
        )
        self.btn_clear_log = QPushButton("Clear Log")

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.status_label = QLabel("Idle")
        self.status_label.setStyleSheet(muted())

        bottom.addWidget(self.btn_start)
        bottom.addWidget(self.btn_stop)
        bottom.addWidget(self.btn_clear_log)
        bottom.addSpacing(12)
        bottom.addWidget(self.progress, stretch=1)
        bottom.addSpacing(8)
        bottom.addWidget(self.status_label)
        root.addLayout(bottom)

        self.runner = None  # type: LoopRunner
        self.test_runner = None  # type: TestDataRunner

        self.btn_start.clicked.connect(self._on_start)
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_clear_log.clicked.connect(self.log_box.clear)

        self._log("Application started. Configure settings in each tab, then press Start.")

    def _log(self, msg: str, level: str = "info"):
        ts = QDateTime.currentDateTime().toString("hh:mm:ss")
        colors = {"info": "#a6e3a1", "warn": "#f9e2af", "error": "#f38ba8"}
        color = colors.get(level, "#cdd6f4")
        self.log_box.append(
            f'<span style="color:#585b70">[{ts}]</span> '
            f'<span style="color:{color}">{msg}</span>'
        )
        self.log_box.moveCursor(QTextCursor.End)

    def _on_start(self):
        if self.test_runner and self.test_runner.isRunning():
            QMessageBox.warning(self, "Busy", "Test Data collection is running.")
            return
        cfg = self._collect_config()
        if cfg.get("training_enabled"):
            if not self.loop_tab.all_rounds_saved():
                n = cfg.get("training_n_rounds", 0)
                saved = len(cfg.get("training_rounds", []))
                QMessageBox.warning(
                    self,
                    "Training Strategy Incomplete",
                    f"Save all {n} training rounds before starting.\n"
                    f"Currently saved: {saved}/{n}.\n\n"
                    "For each round: select mode, configure settings, click Save.",
                )
                return
            total = self.loop_tab.training_summary_captures()
            n_r = cfg.get("training_n_rounds", 0)
            self._log(
                f"Starting training — {n_r} rounds, {total} total captures"
            )
        else:
            self._log(
                f"Starting acquisition — {cfg['n_steps']} steps x "
                f"{cfg['n_repeats']} repeats"
            )
        if cfg.get("auto_roi_enabled"):
            sub = cfg.get("auto_roi_subdir", "cropped")
            self._log(
                f"Auto ROI crop enabled → {sub}/ after each frame"
            )
        if cfg.get("auto_roi_h5_enabled"):
            self._log(
                f"Image H5 enabled → {cfg.get('auto_roi_h5_filename', 'images.h5')}"
            )
            if cfg.get("auto_roi_h5_contrast_enabled"):
                self._log(
                    f"  H5 contrast: vmin "
                    f"{cfg.get('auto_roi_h5_vmin_pct', 0)}%  vmax "
                    f"{cfg.get('auto_roi_h5_vmax_pct', 100)}%  (% of frame max)"
                )
        if cfg.get("osa_h5_enabled"):
            self._log(
                f"OSA H5 enabled → {cfg.get('osa_h5_filename', 'osa_spectra.h5')} "
                f"({cfg.get('osa_reduce_points', 300)} pts)"
            )
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress.setValue(0)
        self.status_label.setText("Running...")

        self.runner = LoopRunner(cfg, nkt_thread=self.nkt_thread)
        self.runner.log_signal.connect(lambda m: self._log(m), Qt.QueuedConnection)
        self.runner.warn_signal.connect(lambda m: self._log(m, "warn"), Qt.QueuedConnection)
        self.runner.error_signal.connect(lambda m: self._log(m, "error"), Qt.QueuedConnection)
        self.runner.progress_signal.connect(self._on_progress, Qt.QueuedConnection)
        self.runner.finished_signal.connect(self._on_finished, Qt.QueuedConnection)
        self.runner.osa_spectrum_signal.connect(self._on_osa_spectrum, Qt.QueuedConnection)
        self.runner.camera_frame_signal.connect(self._on_camera_frame, Qt.QueuedConnection)
        self.runner.start()

    def _on_stop(self):
        self.test_tab.stop_live_monitor()
        if self.runner:
            self.runner.request_stop()
        if self.test_runner:
            self.test_runner.request_stop()
        self._log("Stop requested — waiting for current step to finish...", "warn")
        self.btn_stop.setEnabled(False)

    def start_test_data_collection(self):
        """Start automated test-data run (Test Data tab)."""
        if self.runner and self.runner.isRunning():
            QMessageBox.warning(self, "Busy", "Auto Capture Loop is running.")
            return
        if self.test_runner and self.test_runner.isRunning():
            return

        cfg = self._collect_config()
        cfg.update(self.test_tab.get_config())

        if not cfg.get("test_wavelengths_nm", "").strip():
            QMessageBox.warning(self, "Test Data", "Enter at least one wavelength (nm).")
            return
        if not cfg.get("test_target_dbm_list", "").strip():
            QMessageBox.warning(self, "Test Data", "Enter at least one target power (dBm).")
            return
        if cfg.get("test_pm_backend", "pm100d") == "pm100d":
            if not cfg.get("test_pm_visa_resource", "").strip():
                QMessageBox.warning(
                    self,
                    "Test Data",
                    "PM100D VISA resource is empty.\n\n"
                    "Hardware Test → Scan / Read PM, or paste the USB resource string.",
                )
                return

        self.test_tab.stop_live_monitor()
        self._log(
            f"Starting test data collection — λ=[{cfg['test_wavelengths_nm']}]  "
            f"targets dBm=[{cfg['test_target_dbm_list']}]"
        )
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.test_tab.set_running(True)
        self.test_tab.set_status("Running...")
        self.test_tab.reset_pm_monitor()
        self.test_tab.set_pm_tolerance(cfg.get("test_power_tol_db", 0.5))
        self.test_tab.lbl_in_tolerance.setText("Status: Running…")
        self.test_tab.lbl_in_tolerance.setStyleSheet("color: #89b4fa;")
        self.progress.setValue(0)
        self.status_label.setText("Test data...")

        self.test_runner = TestDataRunner(cfg, nkt_thread=self.nkt_thread)
        self.test_runner.log_signal.connect(lambda m: self._log(m), Qt.QueuedConnection)
        self.test_runner.warn_signal.connect(lambda m: self._log(m, "warn"), Qt.QueuedConnection)
        self.test_runner.error_signal.connect(lambda m: self._log(m, "error"), Qt.QueuedConnection)
        self.test_runner.progress_signal.connect(self._on_progress, Qt.QueuedConnection)
        self.test_runner.finished_signal.connect(self._on_test_finished, Qt.QueuedConnection)
        self.test_runner.camera_frame_signal.connect(self._on_camera_frame, Qt.QueuedConnection)
        self.test_runner.osa_spectrum_signal.connect(self._on_osa_spectrum, Qt.QueuedConnection)
        self.test_runner.pm_reading_signal.connect(
            self.test_tab.on_pm_reading, Qt.QueuedConnection
        )
        self.test_runner.pm_trace_reset_signal.connect(
            self.test_tab.begin_pm_trace, Qt.QueuedConnection
        )
        self.test_runner.start()

    def _on_test_finished(self, success: bool):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.test_tab.set_running(False)
        if success:
            self._log("Test data collection complete", "info")
            self.test_tab.set_status("Done")
            self.test_tab.lbl_in_tolerance.setText("Status: Done")
            self.test_tab.lbl_in_tolerance.setStyleSheet("color: #a6e3a1;")
            self.status_label.setText("Done")
        else:
            self._log("Test data collection stopped / error.", "warn")
            self.test_tab.set_status("Stopped / error")
            self.test_tab.lbl_in_tolerance.setText("Status: Stopped / error")
            self.test_tab.lbl_in_tolerance.setStyleSheet("color: #f38ba8;")
            self.status_label.setText("Stopped")
        self.progress.setValue(0)
        self.test_runner = None

    def _on_progress(self, value: int, status_text: str):
        self.progress.setValue(value)
        self.status_label.setText(status_text)

    def _on_finished(self, success: bool):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        if success:
            self._log("Acquisition complete", "info")
            self.status_label.setText("Done")
        else:
            self._log("Acquisition stopped / error.", "warn")
            self.status_label.setText("Stopped")
        self.progress.setValue(0)

    def _on_osa_spectrum(self, x_nm, y_nw, info: str, title: str):
        self.osa_tab.update_plot(x_nm, y_nw, info, title)
        self.tabs.setCurrentWidget(self.osa_tab)

    def _on_camera_frame(self, frame, info: str):
        """Forward captured frame to Camera tab live preview."""
        self.cam_tab.update_preview(frame, info)
        self.tabs.setCurrentWidget(self.cam_tab)

    def _open_settings(self):
        dlg = SettingsDialog(self)
        dlg.exec_()
        # After dialog closes, refresh header button style to match new theme
        from core.app_settings import get_settings as _gs
        s = _gs()
        is_dark = s.theme() == "dark"
        accent    = "#89b4fa" if is_dark else "#1e66f5"
        btn_bg    = "#45475a" if is_dark else "#dce0e8"
        btn_hover = "#585b70" if is_dark else "#ccd0da"
        btn_fg    = "#cdd6f4" if is_dark else "#4c4f69"
        self.btn_settings_ref.setStyleSheet(
            f"QPushButton{{background:{btn_bg};color:{btn_fg};border-radius:5px;padding:4px 10px;}}"
            f"QPushButton:hover{{background:{btn_hover};}}"
        )
        # Update header label color
        self.hdr_label_ref.setStyleSheet(f"color: {accent}; padding: 2px 4px;")
        self._refresh_plot_fonts()

    def _refresh_plot_fonts(self):
        """Redraw matplotlib views after global font size changes."""
        self.cam_tab._redraw()
        if self.osa_tab._last_x is not None and self.osa_tab._last_y is not None:
            self.osa_tab.update_plot(
                self.osa_tab._last_x, self.osa_tab._last_y,
            )

    def _collect_config(self) -> dict:
        cfg = {}
        cfg.update(self.cam_tab.get_config())
        cfg.update(self.nkt_tab.get_config())
        cfg.update(self.loop_tab.get_config())
        cfg.update(self.osa_tab.get_config())
        cfg.update(self.test_tab.get_config())
        return cfg
