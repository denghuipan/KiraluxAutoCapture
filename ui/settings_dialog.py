"""
Settings dialog — theme, font family, font size.
Changes apply immediately (live preview) and are saved on OK.
"""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QLabel, QComboBox, QSpinBox,
    QDialogButtonBox, QPushButton, QFontComboBox,
    QApplication
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from core.app_settings import get_settings, APP_NAME, APP_VERSION


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(380)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        self._settings = get_settings()
        # Snapshot for cancel
        self._orig_theme  = self._settings.theme()
        self._orig_family = self._settings.font_family()
        self._orig_size   = self._settings.font_size()

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 12)

        # ── Appearance ────────────────────────────────────────────────────────
        grp_app = QGroupBox("Appearance")
        form_a  = QFormLayout(grp_app)
        form_a.setHorizontalSpacing(16)
        form_a.setVerticalSpacing(10)

        self.combo_theme = QComboBox()
        self.combo_theme.addItem("Dark",  "dark")
        self.combo_theme.addItem("Light", "light")
        idx = 0 if self._settings.theme() == "dark" else 1
        self.combo_theme.setCurrentIndex(idx)
        self.combo_theme.currentIndexChanged.connect(self._on_theme_changed)
        form_a.addRow("Theme:", self.combo_theme)
        root.addWidget(grp_app)

        # ── Font ─────────────────────────────────────────────────────────────
        grp_font = QGroupBox("Font")
        form_f   = QFormLayout(grp_font)
        form_f.setHorizontalSpacing(16)
        form_f.setVerticalSpacing(10)

        self.font_combo = QFontComboBox()
        self.font_combo.setCurrentFont(QFont(self._settings.font_family()))
        self.font_combo.currentFontChanged.connect(self._on_font_changed)

        self.spin_size = QSpinBox()
        self.spin_size.setRange(8, 24)
        self.spin_size.setValue(self._settings.font_size())
        self.spin_size.setSuffix("  pt")
        self.spin_size.valueChanged.connect(self._on_font_changed)

        # Preview label
        self.lbl_preview = QLabel(f"Preview: {APP_NAME}  {APP_VERSION}  0123456789")
        self.lbl_preview.setWordWrap(True)
        self._update_preview()

        form_f.addRow("Font family:", self.font_combo)
        form_f.addRow("Font size:", self.spin_size)
        form_f.addRow("", self.lbl_preview)
        root.addWidget(grp_font)

        # ── Reset button ──────────────────────────────────────────────────────
        btn_reset = QPushButton("Reset to Defaults")
        btn_reset.clicked.connect(self._on_reset)
        reset_row = QHBoxLayout()
        reset_row.addWidget(btn_reset)
        reset_row.addStretch()
        root.addLayout(reset_row)

        # ── Dialog buttons ────────────────────────────────────────────────────
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self._on_cancel)
        root.addWidget(buttons)

    # ── Live preview handlers ─────────────────────────────────────────────────
    def _on_theme_changed(self):
        self._apply_live()

    def _on_font_changed(self):
        self._update_preview()
        self._apply_live()

    def _apply_live(self):
        s = self._settings
        s.apply_preview(
            QApplication.instance(),
            self.combo_theme.currentData(),
            self.font_combo.currentFont().family(),
            self.spin_size.value(),
        )

    def _update_preview(self):
        family = self.font_combo.currentFont().family()
        size   = self.spin_size.value()
        self.lbl_preview.setFont(QFont(family, size))

    def _on_reset(self):
        self.combo_theme.setCurrentIndex(0)           # dark
        self.font_combo.setCurrentFont(QFont("Segoe UI"))
        self.spin_size.setValue(10)

    # ── Accept / Cancel ───────────────────────────────────────────────────────
    def _on_ok(self):
        s = self._settings
        s.set("theme",       self.combo_theme.currentData())
        s.set("font_family", self.font_combo.currentFont().family())
        s.set("font_size",   self.spin_size.value())
        s.apply_to_app(QApplication.instance())
        self.accept()

    def _on_cancel(self):
        app = QApplication.instance()
        self._settings.apply_to_app(app)
        self.reject()
