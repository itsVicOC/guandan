"""PySide6 desktop GUI for the local Guandan game."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def button(
    text: str,
    callback: Callable[..., object],
    *,
    primary: bool = False,
    role: str | None = None,
) -> QPushButton:
    btn = QPushButton(text)
    if primary:
        btn.setObjectName("primaryButton")
    elif role is not None:
        btn.setObjectName(role)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.clicked.connect(callback)
    return btn


def make_panel(object_name: str = "panel") -> QFrame:
    frame = QFrame()
    frame.setObjectName(object_name)
    frame.setFrameShape(QFrame.Shape.StyledPanel)
    return frame


def set_property(widget: QWidget, name: str, value: object) -> None:
    """Set a QSS property and immediately refresh the widget's style."""
    widget.setProperty(name, value)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


def page_header(eyebrow: str, title: str, detail: str) -> QWidget:
    header = QWidget()
    layout = QVBoxLayout(header)
    layout.setContentsMargins(0, 0, 0, 4)
    layout.setSpacing(5)
    kicker = QLabel(eyebrow.upper())
    kicker.setObjectName("eyebrow")
    heading = QLabel(title)
    heading.setObjectName("pageTitle")
    body = QLabel(detail)
    body.setObjectName("subtitle")
    body.setWordWrap(True)
    layout.addWidget(kicker)
    layout.addWidget(heading)
    layout.addWidget(body)
    return header
