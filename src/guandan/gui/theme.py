"""Visual tokens and Qt stylesheet for the desktop client."""
from __future__ import annotations

from PySide6.QtGui import QColor

BACKGROUND = QColor("#0b0f14")
SURFACE = QColor("#151b23")
SURFACE_RAISED = QColor("#1c2430")
FELT = QColor("#105742")
FELT_DARK = QColor("#0b3e31")
FELT_LINE = QColor("#3a8a73")
GOLD = QColor("#e2b854")
GOLD_BRIGHT = QColor("#f3cd6b")
CYAN = QColor("#65c7d0")
TEXT = QColor("#f3f5f7")
TEXT_MUTED = QColor("#9ca8b7")
RED = QColor("#d84f55")


APP_QSS = """
QWidget {
    font-family: "PingFang SC", "Microsoft YaHei", Arial, sans-serif;
    color: #f3f5f7;
    font-size: 14px;
}
QMainWindow, QWidget#root, QWidget#page {
    background: #0b0f14;
}
QDialog {
    background: #151b23;
}
QListWidget {
    background: #0f151d;
    color: #e9edf2;
    border: 1px solid #3b4858;
    border-radius: 6px;
    padding: 4px;
    outline: none;
}
QListWidget::item {
    min-height: 30px;
    padding: 2px 8px;
}
QListWidget::item:selected {
    background: #256b75;
    color: #ffffff;
}
QLabel#brandMark {
    background: #e2b854;
    color: #111820;
    border-radius: 6px;
    font-size: 18px;
    font-weight: 900;
    padding: 7px 9px;
}
QLabel#eyebrow {
    color: #65c7d0;
    font-size: 12px;
    font-weight: 700;
}
QLabel#heroTitle {
    color: #f3f5f7;
    font-size: 44px;
    font-weight: 900;
}
QLabel#pageTitle {
    color: #f3f5f7;
    font-size: 30px;
    font-weight: 850;
}
QLabel#subtitle, QLabel#muted {
    color: #9ca8b7;
}
QLabel#sectionTitle {
    color: #f3f5f7;
    font-size: 17px;
    font-weight: 800;
}
QLabel#accentTitle {
    color: #f3cd6b;
    font-size: 17px;
    font-weight: 850;
}
QLabel#statusText {
    color: #d9e0e8;
    font-size: 13px;
}
QLabel#statusBar {
    background: #151b23;
    color: #dce3ea;
    border: 1px solid #2f3a48;
    border-radius: 7px;
    padding: 9px 12px;
}
QLabel#turnBanner {
    color: #f3cd6b;
    font-size: 19px;
    font-weight: 900;
}
QLabel#chip {
    background: #202936;
    color: #dbe2ea;
    border: 1px solid #334052;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
    font-weight: 700;
}
QLabel#goldChip {
    background: #332b19;
    color: #f3cd6b;
    border: 1px solid #66542c;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
    font-weight: 750;
}
QFrame#panel, QFrame#actionPanel, QFrame#handDock, QFrame#historyPanel {
    background: #151b23;
    border: 1px solid #2b3543;
    border-radius: 8px;
}
QFrame#actionPanel {
    background: #171e27;
}
QFrame#handDock {
    background: #121922;
    border-color: #334052;
}
QFrame#hud {
    background: #121820;
    border: 1px solid #283341;
    border-radius: 8px;
}
QFrame#trickPanel {
    background: rgba(7, 31, 25, 205);
    border: 1px solid #4a937d;
    border-radius: 8px;
}
QFrame#tributeBanner {
    background: rgba(65, 51, 20, 190);
    border: 1px solid #a88a3f;
    border-radius: 5px;
}
QLabel#tributeText {
    color: #f6d779;
    font-size: 11px;
    font-weight: 800;
}
QFrame#trickRow {
    background: rgba(10, 53, 42, 180);
    border: 0;
    border-radius: 5px;
}
QFrame#seatPanel {
    background: #18212a;
    border: 1px solid #3a4655;
    border-radius: 8px;
}
QFrame#seatPanel[active="true"] {
    background: #253020;
    border: 2px solid #e2b854;
}
QFrame#seatPanel[human="true"] {
    background: #1b2730;
    border-color: #65c7d0;
}
QFrame#seatPanel[human="true"][active="true"] {
    background: #263329;
    border: 2px solid #f3cd6b;
}
QLabel#seatAvatar {
    background: #293442;
    color: #f3f5f7;
    border: 1px solid #465568;
    border-radius: 20px;
    font-size: 17px;
    font-weight: 900;
}
QLabel#seatAvatar[team="gold"] {
    background: #3b311b;
    color: #f3cd6b;
    border-color: #806a36;
}
QLabel#seatAvatar[team="cyan"] {
    background: #17313a;
    color: #7bd3dc;
    border-color: #326a75;
}
QLabel#seatName {
    color: #f3f5f7;
    font-size: 15px;
    font-weight: 850;
}
QLabel#seatMeta {
    color: #9ca8b7;
    font-size: 12px;
}
QLabel#seatMeta[active="true"] {
    color: #f3cd6b;
    font-weight: 800;
}
QLabel#claimBadge {
    min-width: 46px;
    padding: 4px 6px;
    background: #604814;
    color: #ffe89a;
    border: 1px solid #a9842f;
    border-radius: 5px;
    font-size: 11px;
    font-weight: 900;
}
QLabel#replayCardsText {
    color: #cfd7df;
    font-size: 10px;
}
QPushButton {
    min-height: 42px;
    background: #222b37;
    color: #e9edf2;
    border: 1px solid #3b4858;
    border-radius: 7px;
    padding: 0 16px;
    font-weight: 750;
}
QPushButton:hover {
    background: #2b3745;
    border-color: #69798e;
}
QPushButton:pressed {
    background: #1a222c;
}
QPushButton:disabled {
    color: #66717e;
    background: #171d25;
    border-color: #27303b;
}
QPushButton#primaryButton {
    background: #e2b854;
    color: #121820;
    border-color: #f3cd6b;
    font-weight: 900;
}
QPushButton#primaryButton:hover {
    background: #f0c963;
}
QPushButton#primaryButton:disabled {
    background: #24241f;
    color: #6f6b5d;
    border-color: #37362e;
}
QPushButton#infoButton {
    background: #183039;
    color: #83d8df;
    border-color: #356d77;
}
QPushButton#quietButton {
    background: transparent;
    color: #aeb8c5;
    border-color: #35404e;
}
QPushButton#dangerButton {
    background: #3a2025;
    color: #ffb2b7;
    border-color: #71363d;
}
QPushButton#difficultyCard {
    min-height: 86px;
    background: #171e27;
    color: #eef2f6;
    border: 1px solid #303b49;
    border-radius: 8px;
    padding: 12px 18px;
    text-align: left;
    font-size: 15px;
}
QPushButton#difficultyCard:hover {
    background: #202a36;
    border-color: #65c7d0;
}
QPushButton#difficultyCard[recommended="true"] {
    background: #282719;
    border: 1px solid #a88a3f;
    color: #f6d779;
}
QTableWidget {
    background: #11171e;
    alternate-background-color: #171f28;
    border: 1px solid #2d3947;
    border-radius: 8px;
    gridline-color: #26313d;
    selection-background-color: #264c55;
    selection-color: #ffffff;
}
QHeaderView::section {
    background: #202936;
    color: #cfd7e1;
    padding: 9px 7px;
    border: 0;
    border-right: 1px solid #303b49;
    font-weight: 800;
}
QTextBrowser {
    background: #11171e;
    color: #dce2e9;
    border: 1px solid #2d3947;
    border-radius: 8px;
    padding: 14px;
    selection-background-color: #365d67;
}
QScrollBar:vertical {
    background: #11171e;
    width: 10px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #3b4858;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QToolTip {
    background: #202936;
    color: #f3f5f7;
    border: 1px solid #556579;
    padding: 6px;
}
"""


__all__ = [
    "APP_QSS",
    "BACKGROUND",
    "CYAN",
    "FELT",
    "FELT_DARK",
    "FELT_LINE",
    "GOLD",
    "GOLD_BRIGHT",
    "RED",
    "SURFACE",
    "SURFACE_RAISED",
    "TEXT",
    "TEXT_MUTED",
]
