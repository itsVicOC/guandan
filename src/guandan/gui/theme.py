"""Visual tokens and Qt stylesheet for the desktop client.

The desktop theme borrows the hierarchy of modern Chinese card rooms: a quiet
lacquer-black shell, a deep jade table, and sparing warm gold for the actions
that matter. Keeping those roles stable makes dense game state easy to scan.
"""
from __future__ import annotations

from PySide6.QtGui import QColor

BACKGROUND = QColor("#07100d")
SURFACE = QColor("#111c19")
SURFACE_RAISED = QColor("#182521")
FELT = QColor("#075842")
FELT_DARK = QColor("#042f27")
FELT_LINE = QColor("#319273")
GOLD = QColor("#d8a83d")
GOLD_BRIGHT = QColor("#f2cb70")
CYAN = QColor("#63d3c0")
TEXT = QColor("#f6f1e5")
TEXT_MUTED = QColor("#9eaaa3")
RED = QColor("#d94b51")


APP_QSS = """
QWidget {
    font-family: "PingFang SC", Arial, sans-serif;
    color: #f6f1e5;
    font-size: 14px;
}
QMainWindow, QWidget#root {
    background: #07100d;
}
QWidget#page {
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 #07110e, stop: 0.54 #0a1512, stop: 1 #101710
    );
}
QDialog { background: #101a17; }
QListWidget {
    background: #091411;
    color: #f1eee5;
    border: 1px solid #344b42;
    border-radius: 12px;
    padding: 6px;
    outline: none;
}
QListWidget::item {
    min-height: 34px;
    padding: 3px 10px;
    border-radius: 7px;
}
QListWidget::item:hover { background: #152720; }
QListWidget::item:selected { background: #b98a2c; color: #10150f; }
QLabel#brandMark {
    min-width: 30px;
    min-height: 30px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #f2cf76, stop:1 #c38b28);
    color: #132019;
    border: 1px solid #ffe1a0;
    border-radius: 10px;
    font-size: 18px;
    font-weight: 900;
    padding: 7px 10px;
}
QLabel#mastheadTitle { color: #f5efe1; font-size: 16px; font-weight: 850; }
QLabel#versionBadge {
    background: rgba(218, 173, 72, 25);
    color: #d6c08c;
    border: 1px solid #493e25;
    border-radius: 11px;
    padding: 5px 11px;
    font-size: 11px;
    font-weight: 750;
}
QLabel#eyebrow {
    color: #71d9c2;
    font-size: 11px;
    font-weight: 850;
    letter-spacing: 2px;
}
QLabel#heroTitle { color: #fff8e8; font-size: 40px; font-weight: 900; }
QLabel#heroCopy { color: #aeb9b2; font-size: 15px; }
QLabel#pageTitle { color: #fff8e8; font-size: 29px; font-weight: 900; }
QLabel#subtitle, QLabel#muted { color: #9eaaa3; }
QLabel#sectionTitle { color: #f8f1df; font-size: 18px; font-weight: 850; }
QLabel#accentTitle { color: #f2cb70; font-size: 17px; font-weight: 900; }
QLabel#statusText { color: #c7d0ca; font-size: 12px; }
QLabel#statusText[opening="true"] { color: #ffe59d; font-size: 13px; font-weight: 850; }
QFrame#roundInfo {
    background: rgba(91, 65, 18, 185);
    border: 1px solid #ad8739;
    border-radius: 10px;
}
QLabel#roundPhase { color: #d9bd7a; font-size: 10px; font-weight: 800; }
QLabel#roundLevel { color: #ffe394; font-size: 18px; font-weight: 900; }
QLabel#statusBar {
    background: rgba(15, 28, 24, 220);
    color: #ccd5ce;
    border: 1px solid #2d4239;
    border-radius: 10px;
    padding: 9px 13px;
}
QLabel#turnBanner {
    color: #ffe08e;
    font-size: 18px;
    font-weight: 900;
    padding: 0 4px;
}
QLabel#chip {
    background: rgba(31, 48, 42, 220);
    color: #dfe6e1;
    border: 1px solid #385247;
    border-radius: 12px;
    padding: 6px 11px;
    font-size: 11px;
    font-weight: 800;
}
QLabel#goldChip {
    background: rgba(91, 65, 18, 160);
    color: #f6d579;
    border: 1px solid #80642c;
    border-radius: 12px;
    padding: 6px 11px;
    font-size: 11px;
    font-weight: 850;
}
QLabel#featureChip {
    background: rgba(17, 40, 32, 210);
    color: #b9c7bf;
    border: 1px solid #29483c;
    border-radius: 12px;
    padding: 7px 12px;
    font-size: 11px;
    font-weight: 750;
}
QLabel#menuNote { color: #7e9188; font-size: 11px; }
QLabel#selectionPreview { color: #9eb4a9; font-size: 12px; padding-left: 16px; }
QLabel#selectionPreview[valid="true"] { color: #ffe394; font-weight: 850; }
QLabel#resultPlaces { color: #f5df9b; font-size: 13px; font-weight: 850; }
QLabel#resultScores { color: #d2e2d6; font-size: 12px; font-weight: 750; }
QLabel#previousTrickLine {
    background: #19362c;
    color: #f5edda;
    border: 1px solid #466a55;
    border-radius: 8px;
    padding: 9px;
}
QLabel#emptyState {
    background: rgba(12, 26, 21, 180);
    color: #8fa097;
    border: 1px dashed #385046;
    border-radius: 16px;
    padding: 32px;
    font-size: 16px;
}
QFrame#panel, QFrame#actionPanel, QFrame#handDock, QFrame#historyPanel {
    background: rgba(16, 29, 25, 236);
    border: 1px solid #2d4339;
    border-radius: 16px;
}
QFrame#actionPanel {
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(26, 41, 35, 248), stop:1 rgba(13, 26, 22, 248)
    );
    border: 1px solid #3c5248;
}
QFrame#handDock {
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(14, 29, 25, 242), stop:1 rgba(7, 17, 15, 248)
    );
    border-color: #2e483d;
    border-radius: 13px;
}
QFrame#hud {
    background: rgba(13, 25, 22, 242);
    border: 1px solid #2d4038;
    border-radius: 13px;
}
QFrame#trickPanel {
    background: rgba(3, 38, 30, 224);
    border: 1px solid #3b886e;
    border-radius: 16px;
}
QFrame#replayTable {
    background: qradialgradient(cx:0.5, cy:0.48, radius:0.82, stop:0 #0a5c47, stop:0.72 #064333, stop:1 #032920);
    border: 2px solid #4c8e73;
    border-radius: 18px;
}
QFrame#replayHand {
    background: rgba(7, 32, 26, 185);
    border: 1px solid rgba(112, 170, 147, 85);
    border-radius: 10px;
}
QFrame#tributeBanner {
    background: rgba(102, 73, 17, 205);
    border: 1px solid #ba913a;
    border-radius: 8px;
}
QLabel#tributeText { color: #ffe59d; font-size: 11px; font-weight: 850; }
QFrame#trickRow {
    background: rgba(5, 61, 47, 175);
    border: 1px solid rgba(104, 167, 143, 42);
    border-radius: 8px;
}
QFrame#trickRow[top="true"] {
    background: rgba(93, 70, 21, 210);
    border: 1px solid #cda548;
}
QFrame#trickRow[turn="true"] { border-right: 3px solid #72d8c1; }
QFrame#trickRow[recent="true"] { border: 2px solid #ffe18a; }
QLabel#trickPhase {
    color: #aab7b0;
    background: rgba(28, 47, 40, 210);
    border: 1px solid #3a584c;
    border-radius: 8px;
    padding: 3px 8px;
    font-size: 10px;
    font-weight: 850;
}
QLabel#trickPhase[phase="active"] {
    color: #8fe8d4;
    background: rgba(18, 75, 63, 220);
    border-color: #3c9a83;
}
QLabel#trickPhase[phase="cleared"] {
    color: #ffe49a;
    background: rgba(91, 66, 20, 220);
    border-color: #b38b37;
}
QFrame#activityRail {
    background: rgba(5, 29, 24, 188);
    border: 1px solid rgba(94, 143, 123, 72);
    border-radius: 10px;
}
QLabel#activityTitle { color: #a9c8bc; font-size: 11px; font-weight: 850; }
QLabel#activityLine {
    color: #899b92;
    background: transparent;
    border: 0;
    border-radius: 5px;
    padding: 2px 4px;
    font-size: 10px;
}
QLabel#activityLine[latest="true"] {
    color: #fff0bc;
    background: rgba(112, 82, 24, 150);
    font-weight: 850;
}
QLabel#activityCounter { color: #70847a; font-size: 9px; }
QFrame#seatPanel {
    background: rgba(10, 25, 21, 225);
    border: 1px solid rgba(119, 153, 137, 100);
    border-radius: 13px;
}
QFrame#seatPanel[active="true"] {
    background: rgba(80, 59, 18, 225);
    border: 2px solid #efc75f;
}
QFrame#seatPanel[human="true"] {
    background: rgba(9, 33, 28, 235);
    border-color: #3b806d;
}
QFrame#seatPanel[human="true"][active="true"] {
    background: rgba(77, 60, 22, 235);
    border: 2px solid #f4cc68;
}
QFrame#seatPanel[recent="true"] { border: 2px solid #ffe18a; }
QLabel#seatAvatar {
    background: #1d332c;
    color: #e8eee9;
    border: 1px solid #506d61;
    border-radius: 21px;
    font-size: 17px;
    font-weight: 900;
}
QLabel#seatAvatar[team="gold"] { background: #40351c; color: #f6d06f; border-color: #8b7136; }
QLabel#seatAvatar[team="cyan"] { background: #143b34; color: #76d9c5; border-color: #3b8171; }
QLabel#seatName { color: #f5f0e5; font-size: 14px; font-weight: 850; }
QLabel#seatMeta { color: #91a198; font-size: 11px; }
QLabel#seatMeta[active="true"] { color: #ffe08e; font-weight: 850; }
QLabel#claimBadge {
    min-width: 42px;
    padding: 5px 7px;
    background: #785514;
    color: #ffebaa;
    border: 1px solid #b98c2e;
    border-radius: 7px;
    font-size: 10px;
    font-weight: 900;
}
QLabel#replayCardsText { color: #d1dad4; font-size: 10px; }
QPushButton {
    min-height: 42px;
    background: #1b2a25;
    color: #e5ebe7;
    border: 1px solid #3b5148;
    border-radius: 10px;
    padding: 0 17px;
    font-weight: 800;
}
QPushButton:hover { background: #253a32; border-color: #668575; color: #ffffff; }
QPushButton:pressed { background: #13221d; }
QPushButton:disabled { color: #5d6963; background: #111b18; border-color: #27342f; }
QPushButton#primaryButton {
    min-height: 46px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #f0c75d, stop:1 #c89028);
    color: #172019;
    border: 1px solid #ffe397;
    font-weight: 900;
}
QPushButton#primaryButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ffe18a, stop:1 #dea840);
}
QPushButton#primaryButton:pressed { background: #c18c2b; }
QPushButton#primaryButton:disabled { background: #25271f; color: #6d6d5e; border-color: #3d3d31; }
QPushButton#menuPrimary {
    min-height: 56px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #f1cc69, stop:1 #c78e28);
    color: #172019;
    border: 1px solid #ffe39c;
    border-radius: 12px;
    font-size: 16px;
    font-weight: 900;
}
QPushButton#menuPrimary:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ffe396, stop:1 #dda33b);
}
QPushButton#infoButton { background: #123a35; color: #83dfce; border-color: #397d6e; }
QPushButton#quietButton { background: rgba(13, 24, 21, 155); color: #aebbb4; border-color: #31463d; }
QPushButton#infoButton:disabled, QPushButton#quietButton:disabled {
    color: #5d6963; background: #111b18; border-color: #27342f;
}
QPushButton#dangerButton { background: #38201f; color: #ffb9b5; border-color: #70413d; }
QPushButton#difficultyCard {
    min-height: 92px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #13231e, stop:1 #101b18);
    color: #edf2ee;
    border: 1px solid #324b40;
    border-radius: 14px;
    padding: 13px 19px;
    text-align: left;
    font-size: 15px;
}
QPushButton#difficultyCard:hover { background: #1a3128; border-color: #66c9af; }
QPushButton#difficultyCard[recommended="true"] {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #46381c, stop:1 #1f251b);
    border: 1px solid #a88438;
    color: #f9dc8b;
}
QTableWidget {
    background: #0b1613;
    alternate-background-color: #101f1a;
    border: 1px solid #30473d;
    border-radius: 13px;
    gridline-color: #24372f;
    selection-background-color: #76571e;
    selection-color: #fff8e7;
}
QHeaderView::section {
    background: #192a24;
    color: #d6dfd9;
    padding: 10px 8px;
    border: 0;
    border-right: 1px solid #30463d;
    font-weight: 850;
}
QTextBrowser {
    background: #0b1613;
    color: #d8dfda;
    border: 1px solid #30473d;
    border-radius: 13px;
    padding: 16px;
    selection-background-color: #71551f;
}
QSlider::groove:horizontal { height: 5px; background: #24372f; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #d5a641; border-radius: 2px; }
QSlider::handle:horizontal {
    width: 17px;
    margin: -6px 0;
    background: #f5d681;
    border: 2px solid #8b692b;
    border-radius: 8px;
}
QScrollBar:vertical { background: #0b1613; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #3d554b; border-radius: 5px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QToolTip { background: #1a2c25; color: #f6f1e5; border: 1px solid #687d72; padding: 6px; }
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
