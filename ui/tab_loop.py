"""
Auto Capture Loop settings tab
"""
import math
import copy

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QLabel, QSpinBox, QDoubleSpinBox,
    QComboBox, QSizePolicy, QCheckBox, QPushButton
)
from PyQt5.QtCore import Qt

from ui.style_helpers import checkbox_emphasis, muted, accent, success, error

MODE_LABELS = ("Random Multi-Peak", "Manual Multi-Peak", "Single Peak Scan")


class LoopTab(QWidget):
    def __init__(self, main_window=None):
        super().__init__()
        self._main_win = main_window
        self._saved_rounds: dict[int, dict] = {}
        self._loading_round = False

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ── Training Strategy ─────────────────────────────────────────────
        grp_train = QGroupBox("Training Strategy")
        train_layout = QVBoxLayout(grp_train)
        train_layout.setSpacing(8)

        self.chk_training = QCheckBox(
            "Enable multi-round training  (each round can use a different capture mode)"
        )
        self.chk_training.setStyleSheet(checkbox_emphasis("#cba6f7"))
        self.chk_training.toggled.connect(self._on_training_toggled)
        train_layout.addWidget(self.chk_training)

        train_form = QFormLayout()
        train_form.setHorizontalSpacing(16)
        train_form.setVerticalSpacing(6)

        self.spin_n_rounds = QSpinBox()
        self.spin_n_rounds.setRange(1, 50)
        self.spin_n_rounds.setValue(4)
        self.spin_n_rounds.valueChanged.connect(self._on_n_rounds_changed)

        round_nav = QHBoxLayout()
        self.btn_prev_round = QPushButton("◀ Prev")
        self.btn_prev_round.setFixedWidth(72)
        self.btn_prev_round.clicked.connect(self._on_prev_round)
        self.combo_current_round = QComboBox()
        self.combo_current_round.setMinimumWidth(100)
        self.combo_current_round.currentIndexChanged.connect(self._on_current_round_changed)
        self.btn_next_round = QPushButton("Next ▶")
        self.btn_next_round.setFixedWidth(72)
        self.btn_next_round.clicked.connect(self._on_next_round)
        round_nav.addWidget(self.btn_prev_round)
        round_nav.addWidget(self.combo_current_round)
        round_nav.addWidget(self.btn_next_round)
        round_nav.addStretch()

        self.btn_save_round = QPushButton("💾  Save Current Round Configuration")
        self.btn_save_round.setStyleSheet(
            "QPushButton{background:#a6e3a1;color:#1e1e2e;font-weight:bold;"
            "padding:6px 14px;border-radius:5px;}"
            "QPushButton:hover{background:#94e2d5;}"
        )
        self.btn_save_round.clicked.connect(self._on_save_round)

        self.lbl_round_hint = QLabel(
            "For each round: pick Capture Mode below, configure settings "
            "(Manual → also set channels in NKT Laser tab), then Save."
        )
        self.lbl_round_hint.setWordWrap(True)
        self.lbl_round_hint.setStyleSheet(muted())

        self.lbl_round_status = QLabel()
        self.lbl_round_status.setWordWrap(True)
        self.lbl_round_status.setStyleSheet(accent())

        train_form.addRow("Training rounds:", self.spin_n_rounds)
        train_form.addRow("Editing round:", round_nav)
        train_layout.addLayout(train_form)
        train_layout.addWidget(self.btn_save_round)
        train_layout.addWidget(self.lbl_round_hint)
        train_layout.addWidget(self.lbl_round_status)
        root.addWidget(grp_train)

        # Mode
        grp_mode = QGroupBox("Capture Mode")
        mode_layout = QHBoxLayout(grp_mode)
        mode_layout.addWidget(QLabel("Mode:"))
        self.combo_mode = QComboBox()
        self.combo_mode.addItems([
            "Random Multi-Peak  (reproducible seed)",
            "Manual Multi-Peak  (from NKT tab)",
            "Single Peak Scan  (1ch wavelength sweep)",
        ])
        self.combo_mode.setMinimumWidth(300)
        self.combo_mode.currentIndexChanged.connect(self._on_mode_changed)
        mode_layout.addWidget(self.combo_mode)
        mode_layout.addStretch()
        root.addWidget(grp_mode)

        # Random config
        self.grp_random = QGroupBox("Random Sequence Config")
        form_r = QFormLayout(self.grp_random)
        form_r.setHorizontalSpacing(16)
        form_r.setVerticalSpacing(8)

        self.spin_seed = QSpinBox()
        self.spin_seed.setRange(0, 999999)
        self.spin_seed.setValue(42)

        self.spin_steps = QSpinBox()
        self.spin_steps.setRange(1, 10000)
        self.spin_steps.setValue(50)

        self.spin_wl_min = QDoubleSpinBox()
        self.spin_wl_min.setRange(400, 2000)
        self.spin_wl_min.setValue(620.0)
        self.spin_wl_min.setSuffix("  nm")
        self.spin_wl_min.setDecimals(1)

        self.spin_wl_max = QDoubleSpinBox()
        self.spin_wl_max.setRange(400, 2000)
        self.spin_wl_max.setValue(690.0)
        self.spin_wl_max.setSuffix("  nm")
        self.spin_wl_max.setDecimals(1)

        wl_range_row = QHBoxLayout()
        wl_range_row.addWidget(self.spin_wl_min)
        wl_range_row.addWidget(QLabel(" to "))
        wl_range_row.addWidget(self.spin_wl_max)
        wl_range_row.addStretch()

        # Spacing mode
        self.combo_spacing = QComboBox()
        self.combo_spacing.addItems([
            "Fixed grid",
            "Fully random",
        ])
        self.combo_spacing.setFixedWidth(130)
        self.combo_spacing.currentIndexChanged.connect(self._on_spacing_changed)

        self.spin_wl_step = QDoubleSpinBox()
        self.spin_wl_step.setRange(0.1, 100)
        self.spin_wl_step.setValue(5.0)
        self.spin_wl_step.setSuffix("  nm")
        self.spin_wl_step.setDecimals(1)
        self.spin_wl_step.setSingleStep(0.1)

        self.lbl_grid_step = QLabel("step:")

        self.spin_spacing_min = QDoubleSpinBox()
        self.spin_spacing_min.setRange(0.1, 100)
        self.spin_spacing_min.setValue(0.1)
        self.spin_spacing_min.setSuffix("  nm")
        self.spin_spacing_min.setDecimals(1)
        self.spin_spacing_min.setSingleStep(0.1)

        self.lbl_spacing_dash = QLabel(" – ")

        self.spin_spacing_max = QDoubleSpinBox()
        self.spin_spacing_max.setRange(0.1, 100)
        self.spin_spacing_max.setValue(1.0)
        self.spin_spacing_max.setSuffix("  nm")
        self.spin_spacing_max.setDecimals(1)
        self.spin_spacing_max.setSingleStep(0.1)

        self.lbl_spacing_range = QLabel("spacing:")

        spacing_row = QHBoxLayout()
        spacing_row.addWidget(self.combo_spacing)
        spacing_row.addSpacing(8)
        spacing_row.addWidget(self.lbl_grid_step)
        spacing_row.addWidget(self.spin_wl_step)
        spacing_row.addWidget(self.lbl_spacing_range)
        spacing_row.addWidget(self.spin_spacing_min)
        spacing_row.addWidget(self.lbl_spacing_dash)
        spacing_row.addWidget(self.spin_spacing_max)
        spacing_row.addStretch()

        self.spin_ch_min = QSpinBox()
        self.spin_ch_min.setRange(1, 8)
        self.spin_ch_min.setValue(2)

        self.spin_ch_max = QSpinBox()
        self.spin_ch_max.setRange(1, 8)
        self.spin_ch_max.setValue(8)

        ch_row = QHBoxLayout()
        ch_row.addWidget(self.spin_ch_min)
        ch_row.addWidget(QLabel(" – "))
        ch_row.addWidget(self.spin_ch_max)
        ch_row.addWidget(QLabel("channels"))
        ch_row.addStretch()

        self.spin_amp_min = QSpinBox()
        self.spin_amp_min.setRange(0, 1000)
        self.spin_amp_min.setValue(200)

        self.spin_amp_max = QSpinBox()
        self.spin_amp_max.setRange(0, 1000)
        self.spin_amp_max.setValue(1000)

        amp_row = QHBoxLayout()
        amp_row.addWidget(self.spin_amp_min)
        amp_row.addWidget(QLabel(" – "))
        amp_row.addWidget(self.spin_amp_max)
        amp_row.addWidget(QLabel("  (0 = 0%,  1000 = 100%)"))
        amp_row.addStretch()

        form_r.addRow("Random seed:", self.spin_seed)
        form_r.addRow("N steps:", self.spin_steps)
        form_r.addRow("Wavelength range:", wl_range_row)
        form_r.addRow("Channel spacing:", spacing_row)
        form_r.addRow("Channels per step:", ch_row)
        form_r.addRow("Amplitude range:", amp_row)
        root.addWidget(self.grp_random)

        # Single Peak Scan config
        self.grp_single = QGroupBox("Single Peak Scan Config")
        form_s = QFormLayout(self.grp_single)
        form_s.setHorizontalSpacing(16)
        form_s.setVerticalSpacing(8)

        self.spin_single_wl_min = QDoubleSpinBox()
        self.spin_single_wl_min.setRange(400, 2000)
        self.spin_single_wl_min.setValue(620.0)
        self.spin_single_wl_min.setSuffix("  nm")
        self.spin_single_wl_min.setDecimals(1)

        self.spin_single_wl_max = QDoubleSpinBox()
        self.spin_single_wl_max.setRange(400, 2000)
        self.spin_single_wl_max.setValue(690.0)
        self.spin_single_wl_max.setSuffix("  nm")
        self.spin_single_wl_max.setDecimals(1)

        wl_range_row = QHBoxLayout()
        wl_range_row.addWidget(self.spin_single_wl_min)
        wl_range_row.addWidget(QLabel(" to "))
        wl_range_row.addWidget(self.spin_single_wl_max)
        wl_range_row.addStretch()

        self.spin_single_step = QDoubleSpinBox()
        self.spin_single_step.setRange(0.1, 100)
        self.spin_single_step.setValue(0.5)
        self.spin_single_step.setSuffix("  nm")
        self.spin_single_step.setDecimals(1)
        self.spin_single_step.setSingleStep(0.1)
        self.spin_single_step.setToolTip("Wavelength step (min 0.1 nm)")

        self.spin_single_amplitude = QSpinBox()
        self.spin_single_amplitude.setRange(0, 1000)
        self.spin_single_amplitude.setValue(1000)
        self.spin_single_amplitude.setToolTip("RF channel amplitude (0 = 0%, 1000 = 100%)")

        form_s.addRow("Start wavelength:", self.spin_single_wl_min)
        form_s.addRow("End wavelength:", self.spin_single_wl_max)
        form_s.addRow("Step:", self.spin_single_step)
        form_s.addRow("RF amplitude:", self.spin_single_amplitude)
        root.addWidget(self.grp_single)

        # Repeat & timing
        grp_rep = QGroupBox("Repeat & Timing")
        form_rep = QFormLayout(grp_rep)
        form_rep.setHorizontalSpacing(16)
        form_rep.setVerticalSpacing(8)

        self.spin_repeats = QSpinBox()
        self.spin_repeats.setRange(1, 1000)
        self.spin_repeats.setValue(5)

        self.spin_start_idx = QSpinBox()
        self.spin_start_idx.setRange(0, 99999)
        self.spin_start_idx.setValue(1)
        self.spin_start_idx.setToolTip(
            "Index offset — useful to resume a partially completed run")

        self.spin_settle = QDoubleSpinBox()
        self.spin_settle.setRange(0.0, 10.0)
        self.spin_settle.setValue(0.5)
        self.spin_settle.setSuffix("  s")
        self.spin_settle.setDecimals(2)
        self.spin_settle.setToolTip(
            "Wait after NKT config change before capturing")

        form_rep.addRow("Repeats per config:", self.spin_repeats)
        form_rep.addRow("Start index offset:", self.spin_start_idx)
        form_rep.addRow("Laser settle time:", self.spin_settle)
        root.addWidget(grp_rep)

        # Summary
        self.lbl_summary = QLabel()
        self.lbl_summary.setStyleSheet(
            accent("padding:4px;"))
        self.lbl_summary.setWordWrap(True)
        root.addWidget(self.lbl_summary)

        root.addStretch()

        for w in [self.spin_steps, self.spin_repeats, self.spin_seed,
                  self.spin_wl_min, self.spin_wl_max, self.spin_wl_step,
                  self.spin_spacing_min, self.spin_spacing_max,
                  self.spin_ch_min, self.spin_ch_max,
                  self.spin_amp_min, self.spin_amp_max,
                  self.spin_single_wl_min, self.spin_single_wl_max,
                  self.spin_single_step, self.spin_single_amplitude]:
            w.valueChanged.connect(self._update_summary)
        self._rebuild_round_combo()
        self._on_training_toggled(False)
        self._update_summary()
        self._on_mode_changed(0)
        self._on_spacing_changed(0)

    def _on_mode_changed(self, idx: int):
        self.grp_random.setVisible(idx == 0)
        self.grp_single.setVisible(idx == 2)
        self._update_summary()

    def _on_spacing_changed(self, idx: int):
        is_grid = (idx == 0)
        self.lbl_grid_step.setVisible(is_grid)
        self.spin_wl_step.setVisible(is_grid)
        self.lbl_spacing_range.setVisible(not is_grid)
        self.spin_spacing_min.setVisible(not is_grid)
        self.lbl_spacing_dash.setVisible(not is_grid)
        self.spin_spacing_max.setVisible(not is_grid)
        self._update_summary()

    def _update_summary(self):
        if self.chk_training.isChecked():
            n = self.spin_n_rounds.value()
            saved = len([i for i in range(1, n + 1) if i in self._saved_rounds])
            if saved == n:
                total = self.training_summary_captures()
                self.lbl_summary.setText(
                    f"  Training strategy: {n} rounds  →  {total} total captures\n"
                    f"  All rounds saved — ready to Start Acquisition"
                )
            else:
                self.lbl_summary.setText(
                    f"  Training strategy: save each round ({saved}/{n} done)\n"
                    f"  Round {self._current_round_number()}: configure mode below, then Save"
                )
            self._update_round_status()
            return

        mode      = self.combo_mode.currentIndex()
        n_repeats = self.spin_repeats.value()

        if mode == 1:
            self.lbl_summary.setText(
                f"  Manual: 1 fixed config  x  {n_repeats} repeats  "
                f"=  {n_repeats} total captures\n"
                f"  (channels defined in NKT Laser tab)"
            )
            return

        if mode == 2:
            wl_min  = self.spin_single_wl_min.value()
            wl_max  = self.spin_single_wl_max.value()
            step    = self.spin_single_step.value()
            n_steps = max(1, math.floor((wl_max - wl_min) / step) + 1)
            total   = n_steps * n_repeats
            amp     = self.spin_single_amplitude.value()
            self.lbl_summary.setText(
                f"  Single peak sweep: {wl_min:.1f} → {wl_max:.1f} nm, "
                f"step {step:.1f} nm  =  {n_steps} wavelengths\n"
                f"  x {n_repeats} repeats  =  {total} total captures\n"
                f"  RF amplitude: {amp}  ({amp/10:.0f}%)"
            )
            return

        n_steps = self.spin_steps.value()
        total   = n_steps * n_repeats
        wl_min  = self.spin_wl_min.value()
        wl_max  = self.spin_wl_max.value()
        spacing = self.combo_spacing.currentIndex()

        if spacing == 0:
            wl_step = self.spin_wl_step.value()
            n_cands = max(1, math.floor((wl_max - wl_min) / wl_step) + 1)
            self.lbl_summary.setText(
                f"  {n_steps} NKT configs  x  {n_repeats} repeats  "
                f"=  {total} total captures\n"
                f"  Fixed grid: {n_cands} candidates  "
                f"({wl_min:.1f} – {wl_max:.1f} nm, step {wl_step:.1f} nm)"
            )
        else:
            sp_min = self.spin_spacing_min.value()
            sp_max = self.spin_spacing_max.value()
            self.lbl_summary.setText(
                f"  {n_steps} NKT configs  x  {n_repeats} repeats  "
                f"=  {total} total captures\n"
                f"  Fully random: {wl_min:.1f} – {wl_max:.1f} nm, "
                f"spacing {sp_min:.1f} – {sp_max:.1f} nm"
            )

    def get_config(self) -> dict:
        base = self.get_loop_snapshot()
        if self.chk_training.isChecked():
            base["training_enabled"] = True
            base["training_n_rounds"] = self.spin_n_rounds.value()
            base["training_rounds"] = self.get_training_rounds()
        else:
            base["training_enabled"] = False
        return base

    def get_loop_snapshot(self) -> dict:
        """Loop-only config (capture mode + parameters)."""
        mode = self.combo_mode.currentIndex()
        if mode == 1:
            n_steps = 1
        elif mode == 2:
            wl_min = self.spin_single_wl_min.value()
            wl_max = self.spin_single_wl_max.value()
            step   = self.spin_single_step.value()
            n_steps = max(1, math.floor((wl_max - wl_min) / step) + 1)
        else:
            n_steps = self.spin_steps.value()

        base = {
            "mode":           mode,
            "seed":           self.spin_seed.value(),
            "n_steps":        n_steps,
            "n_repeats":      self.spin_repeats.value(),
            "start_index":    self.spin_start_idx.value(),
            "wl_min":         self.spin_wl_min.value(),
            "wl_max":         self.spin_wl_max.value(),
            "spacing_mode":   self.combo_spacing.currentIndex(),
            "wl_step":        self.spin_wl_step.value(),
            "spacing_min":    self.spin_spacing_min.value(),
            "spacing_max":    self.spin_spacing_max.value(),
            "n_ch_min":       self.spin_ch_min.value(),
            "n_ch_max":       self.spin_ch_max.value(),
            "amp_min":        self.spin_amp_min.value(),
            "amp_max":        self.spin_amp_max.value(),
            "laser_settle_s": self.spin_settle.value(),
        }

        if mode == 2:
            base["single_wl_min"]  = self.spin_single_wl_min.value()
            base["single_wl_max"]  = self.spin_single_wl_max.value()
            base["single_step"]    = self.spin_single_step.value()
            base["single_amp"]     = self.spin_single_amplitude.value()

        return base

    # ── Training strategy ─────────────────────────────────────────────────

    def set_main_window(self, main_window):
        self._main_win = main_window

    def _rebuild_round_combo(self):
        n = self.spin_n_rounds.value()
        cur = self.combo_current_round.currentIndex()
        self.combo_current_round.blockSignals(True)
        self.combo_current_round.clear()
        for i in range(1, n + 1):
            tag = " ✓" if i in self._saved_rounds else ""
            self.combo_current_round.addItem(f"Round {i}{tag}", i)
        if cur >= 0 and cur < n:
            self.combo_current_round.setCurrentIndex(cur)
        else:
            self.combo_current_round.setCurrentIndex(0)
        self.combo_current_round.blockSignals(False)

    def _on_training_toggled(self, checked: bool):
        self.spin_n_rounds.setEnabled(checked)
        self.combo_current_round.setEnabled(checked)
        self.btn_prev_round.setEnabled(checked)
        self.btn_next_round.setEnabled(checked)
        self.btn_save_round.setEnabled(checked)
        self.lbl_round_hint.setVisible(checked)
        self.lbl_round_status.setVisible(checked)
        if checked:
            self._update_round_status()
        self._update_summary()

    def _on_n_rounds_changed(self, n: int):
        self._saved_rounds = {k: v for k, v in self._saved_rounds.items() if k <= n}
        self._rebuild_round_combo()
        self._update_round_status()
        self._update_summary()

    def _current_round_number(self) -> int:
        return self.combo_current_round.currentIndex() + 1

    def _on_prev_round(self):
        idx = self.combo_current_round.currentIndex()
        if idx > 0:
            self.combo_current_round.setCurrentIndex(idx - 1)

    def _on_next_round(self):
        idx = self.combo_current_round.currentIndex()
        if idx < self.combo_current_round.count() - 1:
            self.combo_current_round.setCurrentIndex(idx + 1)

    def _on_current_round_changed(self, _idx: int):
        if self._loading_round or not self.chk_training.isChecked():
            return
        r = self._current_round_number()
        saved = self._saved_rounds.get(r)
        if saved:
            self.apply_config(saved)
        self._update_round_status()

    def _on_save_round(self):
        r = self._current_round_number()
        snap = copy.deepcopy(self.get_loop_snapshot())
        if self._main_win and hasattr(self._main_win, "nkt_tab"):
            nkt = self._main_win.nkt_tab.get_config()
            snap["manual_wavelengths"] = nkt.get("manual_wavelengths", [])
            snap["manual_amplitudes"] = nkt.get("manual_amplitudes", [])
        if snap.get("mode") == 1 and not snap.get("manual_wavelengths"):
            self.lbl_round_status.setStyleSheet(error())
            self.lbl_round_status.setText(
                f"Round {r}: Manual mode needs channels in NKT Laser tab."
            )
            return
        snap["round_number"] = r
        self._saved_rounds[r] = snap
        self._rebuild_round_combo()
        self.combo_current_round.setCurrentIndex(r - 1)
        self._update_round_status()
        mode_name = MODE_LABELS[snap.get("mode", 0)]
        self.lbl_round_status.setStyleSheet(success())
        self._update_round_status()

    def apply_config(self, cfg: dict):
        """Restore loop UI (+ NKT manual table) from a saved snapshot."""
        self._loading_round = True
        try:
            self.combo_mode.setCurrentIndex(int(cfg.get("mode", 0)))
            self.spin_seed.setValue(int(cfg.get("seed", 42)))
            self.spin_steps.setValue(int(cfg.get("n_steps", 50)))
            self.spin_repeats.setValue(int(cfg.get("n_repeats", 5)))
            self.spin_start_idx.setValue(int(cfg.get("start_index", 1)))
            self.spin_settle.setValue(float(cfg.get("laser_settle_s", 0.5)))
            self.spin_wl_min.setValue(float(cfg.get("wl_min", 620.0)))
            self.spin_wl_max.setValue(float(cfg.get("wl_max", 690.0)))
            self.combo_spacing.setCurrentIndex(int(cfg.get("spacing_mode", 0)))
            self.spin_wl_step.setValue(float(cfg.get("wl_step", 5.0)))
            self.spin_spacing_min.setValue(float(cfg.get("spacing_min", 0.1)))
            self.spin_spacing_max.setValue(float(cfg.get("spacing_max", 1.0)))
            self.spin_ch_min.setValue(int(cfg.get("n_ch_min", 2)))
            self.spin_ch_max.setValue(int(cfg.get("n_ch_max", 8)))
            self.spin_amp_min.setValue(int(cfg.get("amp_min", 200)))
            self.spin_amp_max.setValue(int(cfg.get("amp_max", 1000)))
            self.spin_single_wl_min.setValue(float(cfg.get("single_wl_min", 620.0)))
            self.spin_single_wl_max.setValue(float(cfg.get("single_wl_max", 690.0)))
            self.spin_single_step.setValue(float(cfg.get("single_step", 0.5)))
            self.spin_single_amplitude.setValue(int(cfg.get("single_amp", 1000)))
            if self._main_win and hasattr(self._main_win, "nkt_tab"):
                wls = cfg.get("manual_wavelengths")
                amps = cfg.get("manual_amplitudes")
                if wls is not None and amps is not None:
                    self._main_win.nkt_tab.set_manual_channels(wls, amps)
            self._on_mode_changed(self.combo_mode.currentIndex())
            self._on_spacing_changed(self.combo_spacing.currentIndex())
            self._update_summary()
        finally:
            self._loading_round = False

    def _update_round_status(self):
        if not self.chk_training.isChecked():
            return
        n = self.spin_n_rounds.value()
        parts = []
        total_captures = 0
        for i in range(1, n + 1):
            if i in self._saved_rounds:
                sc = self._saved_rounds[i]
                m = MODE_LABELS[sc.get("mode", 0)]
                steps = sc.get("n_steps", 0)
                reps = sc.get("n_repeats", 1)
                cap = steps * reps
                total_captures += cap
                parts.append(f"R{i}✓ {m} ({cap})")
            else:
                parts.append(f"R{i}○ pending")
        saved_n = len([i for i in range(1, n + 1) if i in self._saved_rounds])
        self.lbl_round_status.setText(
            f"Saved {saved_n}/{n}  |  " + "  ·  ".join(parts)
            + (f"  →  {total_captures} total captures" if saved_n == n else "")
        )
        self.lbl_round_status.setStyleSheet(
            success() if saved_n == n else accent()
        )

    def get_training_rounds(self) -> list:
        """Ordered list of saved round configs (1..n)."""
        n = self.spin_n_rounds.value()
        return [self._saved_rounds[i] for i in range(1, n + 1) if i in self._saved_rounds]

    def all_rounds_saved(self) -> bool:
        n = self.spin_n_rounds.value()
        return all(i in self._saved_rounds for i in range(1, n + 1))

    def training_summary_captures(self) -> int:
        total = 0
        for sc in self.get_training_rounds():
            total += sc.get("n_steps", 0) * sc.get("n_repeats", 1)
        return total
