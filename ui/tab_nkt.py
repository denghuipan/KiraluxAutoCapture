"""
NKT SuperK Laser settings tab — with Test Emit button.
"""
import serial.tools.list_ports

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QCheckBox
)
from PyQt5.QtCore import Qt, pyqtSlot

from ui.style_helpers import muted, warning, error, success
from ui.layout_helpers import install_scroll_content, configure_form_layout, prepare_group_box, NoScrollSpinBox, NoScrollComboBox


class NKTTab(QWidget):
    def __init__(self, nkt_thread=None):
        super().__init__()
        self._nkt_thread = nkt_thread
        self._nkt_comport = None
        self._nkt_extreme = -1
        self._nkt_rf = -1

        _, root = install_scroll_content(self)

        # Connection
        grp_conn = QGroupBox("Connection")
        conn_layout = QHBoxLayout(grp_conn)
        conn_layout.setSpacing(10)
        conn_layout.setContentsMargins(12, 14, 12, 12)

        conn_layout.addWidget(QLabel("COM Port:"))
        self.combo_port = NoScrollComboBox()
        self.combo_port.setMinimumWidth(100)
        self._refresh_ports()
        conn_layout.addWidget(self.combo_port)

        btn_refresh = QPushButton("Refresh")
        btn_refresh.setFixedWidth(80)
        btn_refresh.clicked.connect(self._refresh_ports)
        conn_layout.addWidget(btn_refresh)

        conn_layout.addSpacing(24)
        conn_layout.addWidget(QLabel("Crystal:"))
        self.combo_crystal = NoScrollComboBox()
        self.combo_crystal.addItems(["0 — VIS (430–690 nm)", "1 — NIR (690–1100 nm)"])
        self.combo_crystal.setMinimumWidth(200)
        conn_layout.addWidget(self.combo_crystal)
        conn_layout.addStretch()
        prepare_group_box(grp_conn)
        root.addWidget(grp_conn)

        # Laser power
        grp_pwr = QGroupBox("Laser Power")
        form_pwr = QFormLayout(grp_pwr)
        configure_form_layout(form_pwr)

        self.spin_emission = NoScrollSpinBox()
        self.spin_emission.setRange(1, 100)
        self.spin_emission.setValue(100)
        self.spin_emission.setSuffix("  %")
        form_pwr.addRow("Emission level:", self.spin_emission)
        prepare_group_box(grp_pwr)
        root.addWidget(grp_pwr)

        # Manual multi-peak table
        grp_mp = QGroupBox("Manual Multi-Peak Config  (up to 8 channels)")
        mp_layout = QVBoxLayout(grp_mp)

        mp_info = QLabel(
            "Set up to 8 simultaneous channels.\n"
            "Used when Auto Capture Loop is set to 'Manual' mode."
        )
        mp_info.setStyleSheet(muted())
        mp_info.setWordWrap(True)
        mp_layout.addWidget(mp_info)

        self.table = QTableWidget(8, 3)
        self.table.setHorizontalHeaderLabels(["Enabled", "Wavelength (nm)", "Amplitude (0–1000)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setFixedHeight(230)
        self._populate_table()
        mp_layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        btn_fill_100 = QPushButton("Set all amp = 1000 (100%)")
        btn_fill_100.clicked.connect(lambda: self._set_all_amp(1000))
        btn_clear = QPushButton("Disable all")
        btn_clear.clicked.connect(self._clear_all)
        btn_row.addWidget(btn_fill_100)
        btn_row.addWidget(btn_clear)
        btn_row.addStretch()
        mp_layout.addLayout(btn_row)

        # Test emit button
        test_row = QHBoxLayout()
        self.btn_test_emit = QPushButton("⚡  Test Emit Selected Channels")
        self.btn_test_emit.setStyleSheet(
            "QPushButton{background:#a6e3a1;color:#1e1e2e;font-weight:bold;"
            "padding:6px 16px;border-radius:5px;}"
            "QPushButton:hover{background:#94e2d5;}"
            "QPushButton:disabled{background:#313244;color:#585b70;}"
        )
        self.btn_test_emit.clicked.connect(self._on_test_emit)
        test_row.addWidget(self.btn_test_emit)

        self.btn_test_off = QPushButton("Turn OFF")
        self.btn_test_off.setStyleSheet(
            "QPushButton{background:#f38ba8;color:#1e1e2e;font-weight:bold;"
            "padding:6px 12px;border-radius:5px;}"
            "QPushButton:hover{background:#eba0ac;}"
            "QPushButton:disabled{background:#313244;color:#585b70;}"
        )
        self.btn_test_off.clicked.connect(self._on_test_off)
        test_row.addWidget(self.btn_test_off)
        test_row.addStretch()
        mp_layout.addLayout(test_row)

        self.test_status = QLabel("")
        self.test_status.setStyleSheet(muted())
        self.test_status.setWordWrap(True)
        mp_layout.addWidget(self.test_status)

        prepare_group_box(grp_mp)
        root.addWidget(grp_mp)

        if self._nkt_thread:
            self._nkt_thread.scan_done.connect(self._on_scan_done, Qt.QueuedConnection)
            self._nkt_thread.step_done.connect(self._on_step_done, Qt.QueuedConnection)
            self._nkt_thread.step_error.connect(self._on_step_error, Qt.QueuedConnection)
            self._nkt_thread.off_done.connect(self._on_off_done, Qt.QueuedConnection)
            self._nkt_thread.off_error.connect(self._on_step_error, Qt.QueuedConnection)

    def set_nkt_addresses(self, comport, extreme, rf):
        """Called by HardwareTestTab after a successful scan."""
        self._nkt_comport = comport
        self._nkt_extreme = extreme
        self._nkt_rf = rf

    @pyqtSlot(str, int, int, int)
    def _on_scan_done(self, comport, extreme, rf, sk):
        self._nkt_comport = comport
        self._nkt_extreme = extreme
        self._nkt_rf = rf

    def _on_test_emit(self):
        if not self._nkt_thread:
            self.test_status.setText("NKT thread not available.")
            self.test_status.setStyleSheet(error())
            return
        if self._nkt_extreme < 0 or self._nkt_rf < 0:
            self.test_status.setText(
                "Scan NKT first in Hardware Test tab, then come back here."
            )
            self.test_status.setStyleSheet(error())
            return

        cfg = self.get_config()
        wls = cfg["manual_wavelengths"]
        amps = cfg["manual_amplitudes"]
        if not wls:
            self.test_status.setText("No channels enabled — check the table above.")
            self.test_status.setStyleSheet(warning())
            return

        comport = self._nkt_comport or self.combo_port.currentText()
        self.btn_test_emit.setEnabled(False)
        self.test_status.setText(f"Emitting {len(wls)} ch: {[f'{w}nm' for w in wls]}…")
        self.test_status.setStyleSheet(warning())

        self._nkt_thread.submit_test_multi(
            comport, self._nkt_extreme, self._nkt_rf, wls, amps
        )

    def _on_test_off(self):
        if not self._nkt_thread or self._nkt_extreme < 0:
            return
        comport = self._nkt_comport or self.combo_port.currentText()
        self.btn_test_off.setEnabled(False)
        self.test_status.setText("Turning off…")
        self.test_status.setStyleSheet(warning())
        self._nkt_thread.submit_off(comport, self._nkt_extreme, self._nkt_rf)

    @pyqtSlot(str)
    def _on_step_done(self, msg):
        self.test_status.setText(msg)
        self.test_status.setStyleSheet(success())
        self.btn_test_emit.setEnabled(True)

    @pyqtSlot(str)
    def _on_step_error(self, msg):
        self.test_status.setText(msg)
        self.test_status.setStyleSheet(error())
        self.btn_test_emit.setEnabled(True)
        self.btn_test_off.setEnabled(True)

    @pyqtSlot(str)
    def _on_off_done(self, msg):
        self.test_status.setText(msg)
        self.test_status.setStyleSheet(muted())
        self.btn_test_off.setEnabled(True)
        self.btn_test_emit.setEnabled(True)

    def _refresh_ports(self):
        self.combo_port.clear()
        ports = [p.device for p in serial.tools.list_ports.comports()]
        if ports:
            self.combo_port.addItems(ports)
        else:
            self.combo_port.addItem("(no ports found)")

    def _populate_table(self):
        default_wls = [620, 630, 640, 650, 660, 670, 680, 690]
        for row in range(8):
            chk = QCheckBox()
            chk.setChecked(True)
            cell_widget = QWidget()
            h = QHBoxLayout(cell_widget)
            h.addWidget(chk)
            h.setAlignment(Qt.AlignCenter)
            h.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(row, 0, cell_widget)

            wl_item = QTableWidgetItem(str(default_wls[row]))
            wl_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 1, wl_item)

            amp_item = QTableWidgetItem("1000")
            amp_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 2, amp_item)

    def _set_all_amp(self, value: int):
        for row in range(8):
            item = self.table.item(row, 2)
            if item:
                item.setText(str(value))

    def _clear_all(self):
        for row in range(8):
            w = self.table.cellWidget(row, 0)
            if w:
                chk = w.findChild(QCheckBox)
                if chk:
                    chk.setChecked(False)

    def _get_checkbox(self, row: int) -> bool:
        w = self.table.cellWidget(row, 0)
        if w:
            chk = w.findChild(QCheckBox)
            if chk:
                return chk.isChecked()
        return False

    def set_manual_channels(self, wavelengths: list, amplitudes: list):
        """Restore manual multi-peak table from a saved training-round snapshot."""
        self._clear_all()
        for row, (wl, amp) in enumerate(zip(wavelengths, amplitudes)):
            if row >= 8:
                break
            w = self.table.cellWidget(row, 0)
            if w:
                chk = w.findChild(QCheckBox)
                if chk:
                    chk.setChecked(True)
            wl_item = self.table.item(row, 1)
            if wl_item:
                wl_item.setText(str(wl))
            amp_item = self.table.item(row, 2)
            if amp_item:
                amp_item.setText(str(int(amp)))

    def get_config(self) -> dict:
        manual_wavelengths = []
        manual_amplitudes  = []
        for row in range(8):
            if self._get_checkbox(row):
                try:
                    wl  = float(self.table.item(row, 1).text())
                    amp = int(self.table.item(row, 2).text())
                    manual_wavelengths.append(wl)
                    manual_amplitudes.append(amp)
                except (ValueError, AttributeError):
                    pass
        return {
            "comport":            self.combo_port.currentText(),
            "crystal_num":        self.combo_crystal.currentIndex(),
            "emission_percent":   self.spin_emission.value(),
            "manual_wavelengths": manual_wavelengths,
            "manual_amplitudes":  manual_amplitudes,
        }
