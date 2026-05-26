"""
Application settings — persisted via QSettings (registry on Windows).
Provides theme stylesheets and font configuration.
"""
from PyQt5.QtCore import QSettings
from PyQt5.QtGui import QFont

ORGANIZATION = "KiraluxLab"
APPLICATION  = "KiraluxAutoCapture"
APP_NAME     = "Kiralux AutoCapture"
APP_VERSION  = "v2"

DEFAULTS = {
    "theme":      "dark",
    "font_family": "Segoe UI",
    "font_size":  10,
}


# ── Stylesheets ───────────────────────────────────────────────────────────────
DARK_STYLE = """
    QMainWindow, QDialog { background: #1e1e2e; }
    QWidget { background: #1e1e2e; }
    QTabWidget::pane { border: 1px solid #45475a; border-radius: 4px; background:#1e1e2e; }
    QTabBar::tab {
        background: #313244; color: #cdd6f4;
        padding: 6px 16px; border-radius: 4px 4px 0 0;
    }
    QTabBar::tab:selected { background: #89b4fa; color: #1e1e2e; font-weight: bold; }
    QGroupBox {
        color: #cdd6f4; font-weight: bold;
        border: 1px solid #45475a; border-radius: 6px; margin-top: 8px;
        padding-top: 6px; background: #1e1e2e;
    }
    QGroupBox::title { subcontrol-origin: margin; left: 10px; }
    QLabel { color: #cdd6f4; background: transparent; }
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
        background: #313244; color: #cdd6f4;
        border: 1px solid #585b70; border-radius: 4px; padding: 3px 6px;
    }
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
        border: 1px solid #89b4fa;
    }
    QComboBox QAbstractItemView { background: #313244; color: #cdd6f4; selection-background-color: #89b4fa; }
    QPushButton {
        background: #45475a; color: #cdd6f4;
        border: none; border-radius: 5px; padding: 5px 14px;
    }
    QPushButton:hover  { background: #585b70; }
    QPushButton:pressed { background: #6c7086; }
    QPushButton:disabled { background: #313244; color: #585b70; }
    QTextEdit {
        background: #181825; color: #a6e3a1;
        font-family: Consolas, monospace; font-size: {log_font_pt}pt;
        border: 1px solid #45475a; border-radius: 4px;
    }
    QProgressBar {
        background: #313244; border: 1px solid #45475a; border-radius: 4px;
        height: 14px; text-align: center; color: #cdd6f4;
    }
    QProgressBar::chunk { background: #89b4fa; border-radius: 3px; }
    QTableWidget {
        background: #313244; color: #cdd6f4;
        gridline-color: #45475a; border: 1px solid #45475a;
    }
    QTableWidget::item:selected { background: #89b4fa; color: #1e1e2e; }
    QHeaderView::section { background: #45475a; color: #cdd6f4; padding: 4px; border: none; }
    QCheckBox { color: #cdd6f4; background: transparent; }
    QSlider::groove:horizontal { background: #45475a; height: 4px; border-radius: 2px; }
    QSlider::handle:horizontal {
        background: #89b4fa; width: 14px; height: 14px;
        margin: -5px 0; border-radius: 7px;
    }
    QSplitter::handle { background: #45475a; }
    QScrollBar:vertical {
        background: #313244; width: 10px; border-radius: 5px;
    }
    QScrollBar::handle:vertical { background: #585b70; border-radius: 5px; min-height: 20px; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    QDialog { background: #1e1e2e; }
    QDialogButtonBox QPushButton { min-width: 70px; }
"""

LIGHT_STYLE = """
    QMainWindow, QDialog { background: #eff1f5; }
    QWidget { background: #eff1f5; }
    QTabWidget::pane { border: 1px solid #bcc0cc; border-radius: 4px; background:#eff1f5; }
    QTabBar::tab {
        background: #dce0e8; color: #4c4f69;
        padding: 6px 16px; border-radius: 4px 4px 0 0;
    }
    QTabBar::tab:selected { background: #1e66f5; color: #ffffff; font-weight: bold; }
    QGroupBox {
        color: #4c4f69; font-weight: bold;
        border: 1px solid #bcc0cc; border-radius: 6px; margin-top: 8px;
        padding-top: 6px; background: #eff1f5;
    }
    QGroupBox::title { subcontrol-origin: margin; left: 10px; }
    QLabel { color: #4c4f69; background: transparent; }
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
        background: #ffffff; color: #4c4f69;
        border: 1px solid #bcc0cc; border-radius: 4px; padding: 3px 6px;
    }
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
        border: 1px solid #1e66f5;
    }
    QComboBox QAbstractItemView { background: #ffffff; color: #4c4f69; selection-background-color: #1e66f5; selection-color: #fff; }
    QPushButton {
        background: #dce0e8; color: #4c4f69;
        border: 1px solid #bcc0cc; border-radius: 5px; padding: 5px 14px;
    }
    QPushButton:hover  { background: #ccd0da; }
    QPushButton:pressed { background: #bcc0cc; }
    QPushButton:disabled { background: #eff1f5; color: #bcc0cc; }
    QTextEdit {
        background: #ffffff; color: #40a02b;
        font-family: Consolas, monospace; font-size: {log_font_pt}pt;
        border: 1px solid #bcc0cc; border-radius: 4px;
    }
    QProgressBar {
        background: #dce0e8; border: 1px solid #bcc0cc; border-radius: 4px;
        height: 14px; text-align: center; color: #4c4f69;
    }
    QProgressBar::chunk { background: #1e66f5; border-radius: 3px; }
    QTableWidget {
        background: #ffffff; color: #4c4f69;
        gridline-color: #bcc0cc; border: 1px solid #bcc0cc;
    }
    QTableWidget::item:selected { background: #1e66f5; color: #ffffff; }
    QHeaderView::section { background: #dce0e8; color: #4c4f69; padding: 4px; border: none; }
    QCheckBox { color: #4c4f69; background: transparent; }
    QSlider::groove:horizontal { background: #bcc0cc; height: 4px; border-radius: 2px; }
    QSlider::handle:horizontal {
        background: #1e66f5; width: 14px; height: 14px;
        margin: -5px 0; border-radius: 7px;
    }
    QSplitter::handle { background: #bcc0cc; }
    QScrollBar:vertical {
        background: #dce0e8; width: 10px; border-radius: 5px;
    }
    QScrollBar::handle:vertical { background: #bcc0cc; border-radius: 5px; min-height: 20px; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    QDialog { background: #eff1f5; }
    QDialogButtonBox QPushButton { min-width: 70px; }
"""


# ── Settings manager ──────────────────────────────────────────────────────────
class AppSettings:
    def __init__(self):
        self._qs = QSettings(ORGANIZATION, APPLICATION)

    def get(self, key: str):
        return self._qs.value(key, DEFAULTS[key])

    def set(self, key: str, value):
        self._qs.setValue(key, value)

    def theme(self) -> str:
        return self.get("theme")

    def font_family(self) -> str:
        return self.get("font_family")

    def font_size(self) -> int:
        return int(self.get("font_size"))

    def stylesheet(self, font_size: int = None) -> str:
        fs = int(font_size if font_size is not None else self.font_size())
        log_pt = max(8, fs - 1)
        tmpl = DARK_STYLE if self.theme() == "dark" else LIGHT_STYLE
        return tmpl.replace("{log_font_pt}", str(log_pt))

    def app_font(self, family: str = None, size: int = None) -> QFont:
        return QFont(
            family if family is not None else self.font_family(),
            int(size if size is not None else self.font_size()),
        )

    def apply_to_app(self, app):
        """Apply persisted settings to a QApplication instance."""
        app.setStyleSheet(self.stylesheet())
        app.setFont(self.app_font())

    def apply_preview(self, app, theme: str, family: str, size: int):
        """Live preview while Settings dialog is open (not persisted)."""
        tmpl = DARK_STYLE if theme == "dark" else LIGHT_STYLE
        log_pt = max(8, int(size) - 1)
        app.setStyleSheet(tmpl.replace("{log_font_pt}", str(log_pt)))
        app.setFont(QFont(family, int(size)))


# Singleton
_instance = None

def get_settings() -> AppSettings:
    global _instance
    if _instance is None:
        _instance = AppSettings()
    return _instance
