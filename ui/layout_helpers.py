"""
Shared layout utilities — scrollable tab bodies and consistent spacing.
"""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QFrame,
    QSpinBox,
    QDoubleSpinBox,
)
from PyQt5.QtCore import Qt

CONTENT_MARGINS = (16, 16, 16, 16)
CONTENT_SPACING = 12
GROUP_SPACING = 12

MAIN_MIN_WIDTH = 1000
MAIN_MIN_HEIGHT = 720


def install_scroll_content(host: QWidget) -> tuple[QScrollArea, QVBoxLayout]:
    """Wrap tab body in a vertical scroll area; return scroll and inner layout."""
    outer = QVBoxLayout(host)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)

    scroll = QScrollArea(host)
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll.setFrameShape(QFrame.NoFrame)

    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(*CONTENT_MARGINS)
    layout.setSpacing(CONTENT_SPACING)

    scroll.setWidget(content)
    outer.addWidget(scroll)
    return scroll, layout


def configure_form_layout(
    form: QFormLayout,
    *,
    horizontal_spacing: int = 14,
    vertical_spacing: int = 8,
) -> None:
    form.setHorizontalSpacing(horizontal_spacing)
    form.setVerticalSpacing(vertical_spacing)
    form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
    form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)


def prepare_group_box(box: QGroupBox) -> None:
    box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)


class NoScrollSpinBox(QSpinBox):
    """QSpinBox that ignores mouse-wheel events so scroll only moves the view."""

    def wheelEvent(self, event):
        event.ignore()


class NoScrollDoubleSpinBox(QDoubleSpinBox):
    """QDoubleSpinBox that ignores mouse-wheel events so scroll only moves the view."""

    def wheelEvent(self, event):
        event.ignore()


def stack_group_boxes(*boxes: QGroupBox, spacing: int = GROUP_SPACING) -> QVBoxLayout:
    """Stack group boxes vertically so labels and fields do not overlap."""
    col = QVBoxLayout()
    col.setSpacing(spacing)
    for box in boxes:
        prepare_group_box(box)
        col.addWidget(box)
    return col
