"""PySide6 desktop GUI for the local Guandan game."""
from __future__ import annotations

import sys
from typing import Callable

from PySide6.QtCore import QObject, QPoint, QRect, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QFont,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPaintEvent,
    QPen,
    QRadialGradient,
    QShortcut,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSlider,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .. import version_label
from ..ai import AINotImplementedError, make_strategy
from ..engine.card import Card
from ..engine.events import Event, Pass, TributeReturned, TributeSent, TurnPlayed
from ..engine.hand import Pattern
from ..engine.rules.patterns import find_complete_pattern
from ..engine.state import SEAT_NAMES, GameState, IllegalPlayError
from ..storage import (
    consume_profile_error,
    delete_savegame,
    has_savegame,
    history_exists,
    load_game,
    load_history_detail,
    load_history_list,
    reconcile_settlements,
    restore_game_state,
)
from ..ui.content import DIFFICULTIES, GAME_RULES_TEXT, GUI_CONTROLS_TEXT
from ..ui.formatting import card_label, pattern_type_label, rank_value_label
from ..ui.hand_organizer import HandOrganizer
from ..ui.history import HISTORY_COLUMNS, history_entry_cells, history_statistics_text
from ..ui.replay import ReplayCursor, replay_event_text, replay_state_text
from ..ui.session import GameSession, PendingCardChoice, card_indices_for_selection
from .cards import HAND_HEIGHT, CardBackWidget, HandWidget, MiniCardStrip, sort_cards_for_display
from .theme import APP_QSS, CYAN, GOLD_BRIGHT, TEXT_MUTED


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


class AIWorkerSignals(QObject):
    completed = Signal(object)


class AIWorker(QRunnable):
    """Run one visible AI turn outside the Qt event thread."""

    def __init__(self, session: GameSession, limit: int = 1) -> None:
        super().__init__()
        self.session = session
        self.limit = limit
        self.signals = AIWorkerSignals()

    def run(self) -> None:
        try:
            messages = self.session.run_ai_until_human(limit=self.limit)
            if not any("AI 错误" in message for message in messages) and not self.session.autosave_after_ai():
                raise OSError(self.session.last_action)
            self.signals.completed.emit((messages, None))
        except Exception as exc:
            self.signals.completed.emit(([], exc))


class LobbyTableWidget(QWidget):
    """Cinematic, vector-painted table preview for the landing page."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(560, 410)
        self.setObjectName("lobbyTable")

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        outer = self.rect().adjusted(10, 10, -10, -12)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 105))
        painter.drawRoundedRect(outer.translated(0, 7), 30, 30)
        rim = QLinearGradient(outer.topLeft(), outer.bottomRight())
        rim.setColorAt(0.0, QColor("#caa044"))
        rim.setColorAt(0.45, QColor("#5d5837"))
        rim.setColorAt(1.0, QColor("#d3ae55"))
        painter.setBrush(rim)
        painter.drawRoundedRect(outer, 30, 30)

        inner = outer.adjusted(5, 5, -5, -5)
        felt = QRadialGradient(inner.center(), max(inner.width(), inner.height()) * 0.72)
        felt.setColorAt(0.0, QColor("#0b7255"))
        felt.setColorAt(0.68, QColor("#07523f"))
        felt.setColorAt(1.0, QColor("#03372c"))
        painter.setBrush(felt)
        painter.setPen(QPen(QColor("#194d3c"), 1))
        painter.drawRoundedRect(inner, 26, 26)

        field = inner.adjusted(16, 16, -16, -16)
        painter.setPen(QPen(QColor(196, 230, 206, 58), 1, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(field, 19, 19)
        center = outer.center()
        painter.setPen(QPen(QColor(202, 173, 100, 70), 1))
        painter.drawEllipse(center, 112, 61)
        painter.drawEllipse(center, 95, 49)
        painter.setPen(QColor("#f3d788"))
        painter.setFont(QFont("Songti SC", 31, QFont.Weight.Black))
        painter.drawText(
            QRect(center.x() - 104, center.y() - 30, 208, 45),
            Qt.AlignmentFlag.AlignCenter,
            "掼 蛋",
        )
        painter.setPen(QColor(206, 226, 215, 185))
        painter.setFont(QFont("PingFang SC", 10, QFont.Weight.DemiBold))
        painter.drawText(
            QRect(center.x() - 100, center.y() + 18, 200, 22),
            Qt.AlignmentFlag.AlignCenter,
            "双 副 竞 技 · 默 契 搭 档",
        )

        self._paint_preview_cards(painter, center.x() - 62, inner.bottom() - 116, face_up=True)
        self._paint_preview_cards(painter, center.x() - 62, inner.top() + 89, face_up=False)

        seats = (
            (center.x(), inner.top() + 41, "西", False, "gold"),
            (inner.left() + 68, center.y(), "南", False, "cyan"),
            (inner.right() - 68, center.y(), "北", False, "cyan"),
            (center.x(), inner.bottom() - 38, "东", True, "gold"),
        )
        for x, y, label, human, team in seats:
            color = GOLD_BRIGHT if team == "gold" else CYAN
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 75))
            painter.drawEllipse(x - 25, y - 22, 50, 50)
            painter.setPen(QPen(color, 2))
            painter.setBrush(QColor("#0c332a"))
            painter.drawEllipse(x - 25, y - 25, 50, 50)
            painter.setPen(color)
            painter.setFont(QFont("PingFang SC", 18, QFont.Weight.Black))
            painter.drawText(QRect(x - 25, y - 14, 50, 28), Qt.AlignmentFlag.AlignCenter, label)
            painter.setPen(QColor(211, 230, 219, 205))
            painter.setFont(QFont("PingFang SC", 9, QFont.Weight.DemiBold))
            painter.drawText(
                QRect(x - 55, y + 28, 110, 17),
                Qt.AlignmentFlag.AlignCenter,
                "你 · 东家" if human else "智能牌手",
            )
        painter.end()

    @staticmethod
    def _paint_preview_cards(painter: QPainter, x: int, y: int, *, face_up: bool) -> None:
        labels = (("A", "♠"), ("K", "♥"), ("Q", "♣"), ("J", "♦"), ("10", "♠"))
        for index, (rank, suit) in enumerate(labels):
            rect = QRect(x + index * 25, y, 38, 54)
            painter.setPen(QPen(QColor("#c8bfae") if face_up else QColor("#79b7a5"), 1))
            painter.setBrush(QColor("#fffaf0") if face_up else QColor("#123e36"))
            painter.drawRoundedRect(rect, 5, 5)
            if face_up:
                painter.setPen(QColor("#cb3b45") if suit in ("♥", "♦") else QColor("#17201d"))
                painter.setFont(QFont("Arial", 10, QFont.Weight.Black))
                painter.drawText(rect.adjusted(5, 3, -2, -2), Qt.AlignmentFlag.AlignTop, rank)
                painter.setFont(QFont("Times New Roman", 14, QFont.Weight.Bold))
                painter.drawText(rect.adjusted(5, 18, -2, -2), Qt.AlignmentFlag.AlignTop, suit)
            else:
                painter.setPen(QPen(QColor(112, 190, 164, 145), 1, Qt.PenStyle.DotLine))
                painter.drawRoundedRect(rect.adjusted(5, 5, -5, -5), 3, 3)


class MenuPage(QWidget):
    def __init__(self, window: "GuandanMainWindow") -> None:
        super().__init__()
        self._main_window = window
        self.setObjectName("page")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(44, 28, 44, 28)
        layout.setSpacing(16)

        masthead = QHBoxLayout()
        mark = QLabel("掼")
        mark.setObjectName("brandMark")
        masthead.addWidget(mark)
        masthead.addSpacing(12)
        masthead_title = QLabel("掼蛋 · 国风竞技牌局")
        masthead_title.setObjectName("mastheadTitle")
        masthead.addWidget(masthead_title)
        masthead.addWidget(QLabel("  本地单机 · 无需联网"), 1)
        version = QLabel(version_label("BETA  "))
        version.setObjectName("versionBadge")
        masthead.addWidget(version)
        layout.addLayout(masthead)

        hero = QHBoxLayout()
        hero.setSpacing(20)
        hero_copy = QVBoxLayout()
        hero_copy.setSpacing(3)
        kicker = QLabel("四 人 搭 档 · 双 副 竞 技")
        kicker.setObjectName("eyebrow")
        title = QLabel("今晚，开一桌")
        title.setObjectName("heroTitle")
        copy = QLabel("和默契并肩，与好牌相逢。坐到东家，打一局完整的本地掼蛋。")
        copy.setObjectName("heroCopy")
        hero_copy.addWidget(kicker)
        hero_copy.addWidget(title)
        hero_copy.addWidget(copy)
        hero.addLayout(hero_copy, 1)
        for text in ("108 张", "四人搭档", "五档 AI"):
            chip = QLabel(text)
            chip.setObjectName("featureChip")
            hero.addWidget(chip, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(hero)

        body = QHBoxLayout()
        body.setSpacing(20)
        layout.addLayout(body, 1)
        body.addWidget(LobbyTableWidget(), 7)

        action_panel = make_panel("actionPanel")
        action_panel.setMinimumWidth(286)
        action_panel.setMaximumWidth(340)
        action_layout = QVBoxLayout(action_panel)
        action_layout.setContentsMargins(22, 22, 22, 20)
        action_layout.setSpacing(10)
        eyebrow = QLabel("QUICK MATCH")
        eyebrow.setObjectName("eyebrow")
        action_layout.addWidget(eyebrow)
        action_title = QLabel("准备开局")
        action_title.setObjectName("sectionTitle")
        action_layout.addWidget(action_title, 0, Qt.AlignmentFlag.AlignLeft)
        intro = QLabel("你坐东家，与西家并肩。\n选好难度，牌局即刻开始。")
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        action_layout.addWidget(intro)
        action_layout.addSpacing(7)
        action_layout.addWidget(button("立即开局  ›", window.show_difficulty, role="menuPrimary"))
        action_layout.addWidget(button("继续上次牌局", window.show_load, role="infoButton"))

        utilities = QGridLayout()
        utilities.setHorizontalSpacing(8)
        utilities.setVerticalSpacing(8)
        utilities.addWidget(button("战绩回放", window.show_history, role="quietButton"), 0, 0)
        utilities.addWidget(button("玩法规则", window.show_rules, role="quietButton"), 0, 1)
        action_layout.addLayout(utilities)
        action_layout.addStretch(1)
        team_note = QLabel("东西一队  ·  南北一队")
        team_note.setObjectName("menuNote")
        action_layout.addWidget(team_note, 0, Qt.AlignmentFlag.AlignCenter)
        action_layout.addWidget(button("退出游戏", window.close, role="quietButton"))
        body.addWidget(action_panel, 3)

        notice = consume_profile_error()
        if notice:
            # A profile that could not be parsed must not be a silent event:
            # its statistics were reset and the original file was set aside.
            banner = QLabel(f"⚠ 玩家数据异常：{notice}")
            banner.setObjectName("storageWarning")
            banner.setWordWrap(True)
            layout.addWidget(banner)


class DifficultyPage(QWidget):
    def __init__(self, window: "GuandanMainWindow") -> None:
        super().__init__()
        self.setObjectName("page")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(60, 44, 60, 36)
        layout.setSpacing(18)
        layout.addWidget(page_header("开始一局", "选择 AI 难度", "难度会影响记牌、牌型判断和残局决策。你可以随时从历史页回看完整事件流。"))
        layout.addWidget(self._summary_panel())

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        for index, (name, desc) in enumerate(DIFFICULTIES):
            difficulty_button = button(
                f"{index + 1:02d}  {name}\n      {desc}",
                self._difficulty_callback(window, index),
                role="difficultyCard",
            )
            if index == 1:
                set_property(difficulty_button, "recommended", True)
            row, column = divmod(index, 2)
            grid.addWidget(difficulty_button, row, column, 1, 2 if index == 4 else 1)
        layout.addLayout(grid)
        layout.addStretch(1)
        layout.addWidget(button("返回大厅", window.show_menu, role="quietButton"))

    def _summary_panel(self) -> QFrame:
        panel = make_panel("actionPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 13, 18, 13)
        info = QLabel("推荐从进阶开始 · 首局级牌 2 · 更高难度会更重视牌型结构、协作和残局搜索。")
        info.setObjectName("muted")
        info.setWordWrap(True)
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(info)
        return panel

    def _difficulty_callback(
        self, window: "GuandanMainWindow", difficulty: int
    ) -> Callable[[], None]:
        def start() -> None:
            self._start(window, difficulty)

        return start

    def _start(self, window: "GuandanMainWindow", difficulty: int) -> None:
        try:
            make_strategy(difficulty)
        except (AINotImplementedError, ImportError, OSError, ValueError) as exc:
            QMessageBox.warning(self, "AI 档位不可用", str(exc))
            return
        if not window.confirm_start_new_game():
            return
        window.start_game(GameSession(difficulty=difficulty, level=2, human=0))


class LoadPage(QWidget):
    def __init__(self, window: "GuandanMainWindow") -> None:
        super().__init__()
        self._main_window = window
        # Identity of the save currently rendered, so "删除存档" cannot remove a
        # save another process wrote after this page was built.
        self._displayed_savegame_id: str | None = None
        self.setObjectName("page")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(60, 44, 60, 36)
        layout.setSpacing(18)
        layout.addWidget(page_header("继续牌局", "继续存档", "未完成的牌局会在离开时保存。损坏的存档可以单独删除，不会影响历史记录。"))
        self.content = QVBoxLayout()
        self.content.setSpacing(12)
        layout.addLayout(self.content)
        layout.addStretch(1)
        layout.addWidget(button("返回大厅", window.show_menu, role="quietButton"))
        self.refresh()

    def refresh(self) -> None:
        while self.content.count():
            item = self.content.takeAt(0)
            if item is None:
                break
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        try:
            has_save = has_savegame()
            savegame = load_game() if has_save else None
            self._displayed_savegame_id = savegame.get("game_id") if savegame else None
        except OSError as exc:
            self._displayed_savegame_id = None
            self.content.addWidget(self._message_panel("无法读取存档", str(exc)))
            return
        if not has_save:
            self.content.addWidget(self._message_panel("暂无存档", "退出未完成对局时会自动保存。"))
            return
        if not savegame:
            panel = self._message_panel("存档文件损坏", "可以删除损坏存档后重新开始。")
            panel_layout = panel.layout()
            if panel_layout is None:
                raise RuntimeError("message panel has no layout")
            panel_layout.addWidget(button("删除存档", self._delete_save))
            self.content.addWidget(panel)
            return

        panel = make_panel()
        layout = QVBoxLayout(panel)
        metadata = savegame.get("metadata", {})
        snapshot = savegame.get("current_state_snapshot", {})
        lines = [
            f"保存时间：{savegame.get('saved_at', '-')[:19]}",
            f"级牌：{metadata.get('level', '-')}",
            f"玩家：{SEAT_NAMES[metadata.get('player_seat', 0)]}家",
            f"当前行动：{SEAT_NAMES[snapshot.get('turn_index', 0)]}家",
            f"手牌剩余：{self._hand_sizes_text(snapshot.get('hand_sizes', []))}",
        ]
        for line in lines:
            label = QLabel(line)
            label.setWordWrap(True)
            layout.addWidget(label)
        layout.addWidget(button("继续游戏", lambda: self._continue(savegame), primary=True))
        danger = button("删除存档", self._delete_save)
        danger.setObjectName("dangerButton")
        layout.addWidget(danger)
        self.content.addWidget(panel)

    def _message_panel(self, title: str, detail: str) -> QFrame:
        panel = make_panel()
        layout = QVBoxLayout(panel)
        head = QLabel(title)
        head.setObjectName("sectionTitle")
        head.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body = QLabel(detail)
        body.setObjectName("muted")
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setWordWrap(True)
        layout.addWidget(head)
        layout.addWidget(body)
        return panel

    def _continue(self, savegame: dict) -> None:
        try:
            state = restore_game_state(savegame)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "无法继续存档", str(exc))
            return
        metadata = savegame.get("metadata", {})
        ai_difficulties = metadata.get("ai_difficulties", [None, 2, 2, 2])
        difficulty = next((d for d in ai_difficulties if d is not None), 2)
        self._main_window.start_game(
            GameSession(
                difficulty=difficulty,
                level=metadata.get("level", state.level),
                human=metadata.get("player_seat", 0),
                existing_state=state,
                game_id=savegame.get("game_id"),
                match_id=savegame.get("match_id"),
                round_index=savegame.get("round_index", 1),
                elapsed_seconds=savegame.get("elapsed_seconds", 0),
                seed=metadata.get("seed"),
            )
        )

    def _delete_save(self) -> None:
        answer = QMessageBox.question(
            self,
            "删除存档",
            "确定删除当前存档？此操作不会删除历史战绩。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            # Delete only the save this page is displaying: a parallel TUI may
            # have written a newer one since the page was built.
            delete_savegame(expected_game_id=self._displayed_savegame_id)
        except OSError as exc:
            QMessageBox.warning(self, "删除失败", str(exc))
            return
        self.refresh()

    def _hand_sizes_text(self, sizes: list[int]) -> str:
        if not sizes:
            return "-"
        return " / ".join(f"{SEAT_NAMES[i]} {size}" for i, size in enumerate(sizes))


class HistoryPage(QWidget):
    def __init__(self, window: "GuandanMainWindow") -> None:
        super().__init__()
        self._main_window = window
        self.entries: list[dict] = []
        self.setObjectName("page")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(52, 40, 52, 32)
        layout.setSpacing(16)
        layout.addWidget(page_header("战绩与回放", "历史战绩", "每一局都保留事件流、行动数、炸弹和进贡标记。双击任意一行查看回放。"))
        self.summary = QLabel("")
        self.summary.setObjectName("muted")
        self.summary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.summary)
        self.empty = QLabel("暂无对局记录\n完成一局后，比赛与小局记录会显示在这里。")
        self.empty.setObjectName("emptyState")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty, 1)
        self.table = QTableWidget(0, len(HISTORY_COLUMNS))
        self.table.setHorizontalHeaderLabels(list(HISTORY_COLUMNS))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(280)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.cellDoubleClicked.connect(self.open_selected_replay)
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        self.replay_button = button("查看回放", self.open_selected_replay, primary=True)
        actions.addWidget(self.replay_button)
        actions.addWidget(button("返回大厅", window.show_menu, role="quietButton"))
        layout.addLayout(actions)
        self.refresh()

    def refresh(self) -> None:
        self.table.setRowCount(0)
        error = ""
        try:
            self.entries = load_history_list(limit=50)
        except OSError as exc:
            self.entries = []
            error = str(exc)
        has_entries = bool(self.entries)
        self.table.setVisible(has_entries)
        self.empty.setVisible(not has_entries)
        self.empty.setText(
            f"无法读取历史记录\n{error}"
            if error
            else "暂无对局记录\n完成一局后，比赛与小局记录会显示在这里。"
        )
        self.replay_button.setEnabled(has_entries)
        match_count = len({entry.get("match_id") for entry in self.entries if entry.get("match_id")})
        self.summary.setText(f"{match_count} 场比赛 · {len(self.entries)} 局记录" if has_entries else "")
        for entry in self.entries:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col, value in enumerate(self._entry_cells(entry)):
                self.table.setItem(row, col, QTableWidgetItem(value))

    def _entry_cells(self, entry: dict) -> tuple[str, ...]:
        return history_entry_cells(entry)

    def open_selected_replay(self, *_: object) -> None:
        row = self.table.currentRow()
        if not 0 <= row < len(self.entries):
            QMessageBox.information(self, "查看回放", "请先选择一局历史战绩。")
            return
        try:
            detail = load_history_detail(self.entries[row]["game_id"])
        except OSError as exc:
            QMessageBox.warning(self, "查看回放", f"无法读取历史记录：{exc}")
            return
        if detail is None:
            QMessageBox.warning(self, "查看回放", "这局历史记录无法读取。")
            return
        self._main_window.show_replay(detail)


class ReplayHandPanel(QFrame):
    def __init__(self, seat: int) -> None:
        super().__init__()
        self.setObjectName("replayHand")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(2)
        self.title = QLabel()
        self.title.setObjectName("seatName")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cards = MiniCardStrip()
        self.card_text = QLabel()
        self.card_text.setObjectName("replayCardsText")
        self.card_text.setWordWrap(True)
        self.card_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title)
        layout.addWidget(self.cards)
        layout.addWidget(self.card_text)
        self.seat = seat

    def update_hand(self, cards: list[Card], finished: bool) -> None:
        suffix = " · 已出完" if finished else f" · {len(cards)} 张"
        self.title.setText(f"{SEAT_NAMES[self.seat]}家{suffix}")
        self.cards.set_cards(cards)
        self.card_text.setText(" ".join(card_label(card) for card in cards) or "-")


class ReplayCenterPanel(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("trickPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        self.title = QLabel("当前桌面")
        self.title.setObjectName("accentTitle")
        self.detail = QLabel("等待先手")
        self.detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cards = MiniCardStrip()
        layout.addWidget(self.title, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.detail)
        layout.addWidget(self.cards)

    def update_state(self, state: GameState) -> None:
        if not state.table:
            self.detail.setText("等待先手")
            self.cards.set_cards(())
            return
        top = state.table[-1]
        self.detail.setText(pattern_type_label(top.type))
        self.cards.set_cards(top.cards)


class ReplayPage(QWidget):
    """Table-shaped event replay with full hands, timeline and autoplay."""

    def __init__(self, window: "GuandanMainWindow", history: dict) -> None:
        super().__init__()
        self._main_window = window
        self.setObjectName("page")
        self.history = history
        self.events: list[Event] = list(history.get("events", []))
        if not self.events:
            raise ValueError("history has no events")
        try:
            self._replay_cursor = ReplayCursor(
                self.events, ruleset_version=history.get("ruleset_version", 1)
            )
        except (IllegalPlayError, ValueError) as exc:
            raise ValueError("history event stream cannot be replayed") from exc
        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(700)
        self._auto_timer.timeout.connect(self._auto_step)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 20)
        layout.setSpacing(9)
        layout.addWidget(page_header("事件流查看器", "对局回放", "四家手牌、当前桌面与事件流同步重建。"))
        self.meta = QLabel()
        self.meta.setObjectName("muted")
        self.meta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.meta)

        body = QHBoxLayout()
        body.setSpacing(10)
        arena = make_panel("replayTable")
        arena_grid = QGridLayout(arena)
        arena_grid.setContentsMargins(12, 10, 12, 10)
        arena_grid.setSpacing(8)
        self.replay_hands = {seat: ReplayHandPanel(seat) for seat in range(4)}
        self.replay_center = ReplayCenterPanel()
        arena_grid.addWidget(self.replay_hands[2], 0, 1)
        arena_grid.addWidget(self.replay_hands[1], 1, 0)
        arena_grid.addWidget(self.replay_center, 1, 1)
        arena_grid.addWidget(self.replay_hands[3], 1, 2)
        arena_grid.addWidget(self.replay_hands[0], 2, 1)
        arena_grid.setColumnStretch(1, 2)
        body.addWidget(arena, 3)
        self.timeline = QTextBrowser()
        self.timeline.setReadOnly(True)
        body.addWidget(self.timeline, 2)
        layout.addLayout(body, 1)

        self.state_summary = QLabel()
        self.state_summary.setObjectName("statusBar")
        self.state_summary.setWordWrap(True)
        layout.addWidget(self.state_summary)
        self.progress = QSlider(Qt.Orientation.Horizontal)
        self.progress.setRange(0, len(self.events) - 1)
        self.progress.valueChanged.connect(self._on_progress_changed)
        layout.addWidget(self.progress)

        controls = QHBoxLayout()
        self.first_button = button("首步", lambda: self.set_event_index(0))
        self.previous_button = button("上一步", lambda: self.set_event_index(self.event_index - 1))
        self.auto_button = button("自动播放", self.toggle_auto_play, role="infoButton")
        self.next_button = button("下一步", lambda: self.set_event_index(self.event_index + 1), primary=True)
        self.last_button = button("末步", lambda: self.set_event_index(len(self.events) - 1))
        for item in (
            self.first_button,
            self.previous_button,
            self.auto_button,
            self.next_button,
            self.last_button,
        ):
            controls.addWidget(item)
        layout.addLayout(controls)
        layout.addWidget(button("返回战绩", self.back_to_history, role="quietButton"))
        self.refresh()

    def _on_progress_changed(self, value: int) -> None:
        if value != self.event_index:
            self.set_event_index(value)

    def set_event_index(self, index: int) -> None:
        self._replay_cursor.set_index(index)
        self.refresh()

    @property
    def event_index(self) -> int:
        return self._replay_cursor.index

    def toggle_auto_play(self) -> None:
        if self._auto_timer.isActive():
            self._auto_timer.stop()
        else:
            if self.event_index == len(self.events) - 1:
                self._replay_cursor.set_index(0)
            self._auto_timer.start()
        self.refresh()

    def _auto_step(self) -> None:
        if self.event_index >= len(self.events) - 1:
            self._auto_timer.stop()
            self.refresh()
            return
        self.set_event_index(self.event_index + 1)

    def back_to_history(self) -> None:
        self._auto_timer.stop()
        self._main_window.show_history()

    def refresh(self) -> None:
        state = self._replay_cursor.state
        self.meta.setText(
            f"{self.history.get('played_at', '-')[:19]} · "
            f"第 {self.event_index + 1} / {len(self.events)} 个事件 · "
            f"{history_statistics_text(self.history)}"
        )
        self.state_summary.setText(replay_state_text(state))
        for seat, panel in self.replay_hands.items():
            panel.update_hand(state.hands[seat], seat in state.finish_order)
        self.replay_center.update_state(state)
        self._refresh_timeline()
        # Block the signal so writing the slider back does not re-enter
        # set_event_index (an infinite refresh loop on every step).
        self.progress.blockSignals(True)
        self.progress.setValue(self.event_index)
        self.progress.blockSignals(False)
        self.first_button.setEnabled(self.event_index > 0)
        self.previous_button.setEnabled(self.event_index > 0)
        self.next_button.setEnabled(self.event_index < len(self.events) - 1)
        self.last_button.setEnabled(self.event_index < len(self.events) - 1)
        self.auto_button.setText("暂停" if self._auto_timer.isActive() else "自动播放")

    def _refresh_timeline(self) -> None:
        """Rebuild the event list and keep the current step visible.

        ``setPlainText`` scrolls back to the top, so the "▶" marker scrolled out
        of view during auto-play and the user could not see where they were.
        """
        lines = []
        for index, event in enumerate(self.events):
            marker = "▶" if index == self.event_index else " "
            lines.append(f"{marker} {index + 1:>3}. {replay_event_text(event)}")
        self.timeline.setPlainText("\n".join(lines))

        cursor = self.timeline.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        cursor.movePosition(
            QTextCursor.MoveOperation.Down,
            QTextCursor.MoveMode.MoveAnchor,
            self.event_index,
        )
        self.timeline.setTextCursor(cursor)
        self.timeline.ensureCursorVisible()

class RulesPage(QWidget):
    def __init__(self, window: "GuandanMainWindow") -> None:
        super().__init__()
        self.setObjectName("page")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(52, 40, 52, 32)
        layout.setSpacing(16)
        layout.addWidget(page_header("桌面规则", "规则说明", "掼蛋的牌型、比较、接风、升级和进贡规则。"))
        browser = QTextBrowser()
        browser.setPlainText(f"{GAME_RULES_TEXT}\n{GUI_CONTROLS_TEXT}")
        layout.addWidget(browser, 1)
        layout.addWidget(button("返回大厅", window.show_menu, role="quietButton"))


class GameArena(QFrame):
    """Painted felt surface behind the four seats and current trick."""

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        outer = self.rect().adjusted(1, 1, -1, -2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 125))
        painter.drawRoundedRect(outer.translated(0, 3), 23, 23)

        rim = QLinearGradient(outer.topLeft(), outer.bottomRight())
        rim.setColorAt(0.0, QColor("#5b724f"))
        rim.setColorAt(0.45, QColor("#af8d43"))
        rim.setColorAt(1.0, QColor("#2c5c49"))
        painter.setBrush(rim)
        painter.drawRoundedRect(outer, 23, 23)

        inner = outer.adjusted(4, 4, -4, -4)
        felt = QRadialGradient(inner.center(), max(inner.width(), inner.height()) * 0.68)
        felt.setColorAt(0.0, QColor("#09654c"))
        felt.setColorAt(0.7, QColor("#064633"))
        felt.setColorAt(1.0, QColor("#032c23"))
        painter.setPen(QPen(QColor("#174c3c"), 1))
        painter.setBrush(felt)
        painter.drawRoundedRect(inner, 20, 20)

        field = inner.adjusted(12, 12, -12, -12)
        painter.setPen(QPen(QColor(147, 203, 179, 58), 1, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(field, 15, 15)
        center = inner.center()
        painter.setPen(QPen(QColor(224, 196, 123, 42), 1))
        painter.drawEllipse(center, min(190, inner.width() // 4), min(105, inner.height() // 3))
        painter.drawEllipse(center, min(168, inner.width() // 5), min(84, inner.height() // 4))
        painter.setPen(QColor(235, 216, 166, 28))
        painter.setFont(QFont("Songti SC", 52, QFont.Weight.Black))
        painter.drawText(
            QRect(center.x() - 100, center.y() - 38, 200, 76),
            Qt.AlignmentFlag.AlignCenter,
            "掼",
        )
        painter.end()


class SeatPanel(QFrame):
    def __init__(self, *, human: bool = False) -> None:
        super().__init__()
        self._human = human
        self.setObjectName("seatPanel")
        self.setMinimumSize(174, 62)
        self.setMaximumHeight(68)
        set_property(self, "human", human)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(9)

        self.avatar = QLabel("-")
        self.avatar.setObjectName("seatAvatar")
        self.avatar.setFixedSize(40, 40)
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.avatar)

        labels = QVBoxLayout()
        labels.setSpacing(2)
        self.title = QLabel("")
        self.title.setObjectName("seatName")
        self.detail = QLabel("")
        self.detail.setObjectName("seatMeta")
        self.claim_badge = QLabel("")
        self.claim_badge.setObjectName("claimBadge")
        self.claim_badge.hide()
        labels.addWidget(self.title)
        labels.addWidget(self.detail)
        layout.addLayout(labels, 1)
        layout.addWidget(self.claim_badge)

        self.card_back = CardBackWidget()
        self.card_back.setVisible(not human)
        layout.addWidget(self.card_back)

    def update_state(
        self, seat: int, hand_size: int, finished: bool, is_turn: bool,
        ai_name: str, *, thinking: bool = False,
    ) -> None:
        team = "gold" if seat % 2 == 0 else "cyan"
        self.avatar.setText(SEAT_NAMES[seat])
        set_property(self.avatar, "team", team)
        set_property(self, "active", is_turn)
        set_property(self.detail, "active", is_turn)
        self.title.setText(f"{SEAT_NAMES[seat]}家" + (" · 你" if self._human else ""))
        if finished:
            meta = "已出完"
        elif is_turn:
            meta = f"● {'思考中' if thinking else '行动中'} · {hand_size} 张"
        else:
            meta = f"{ai_name} · {hand_size} 张"
        self.detail.setText(meta)
        claim = self._claim_text(hand_size) if not finished else ""
        self.claim_badge.setText(claim)
        self.claim_badge.setVisible(bool(claim))
        self.card_back.setVisible(not self._human and not finished)

    @staticmethod
    def _claim_text(hand_size: int) -> str:
        if hand_size == 1:
            return "报单"
        if hand_size == 2:
            return "报双"
        if 0 < hand_size <= 10:
            return f"报{hand_size}张"
        return ""


class TrickRow(QFrame):
    def __init__(self, seat: int) -> None:
        super().__init__()
        self.seat = seat
        self.setObjectName("trickRow")
        self.setFixedHeight(40)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 7, 0)
        layout.setSpacing(8)
        self.seat_label = QLabel(SEAT_NAMES[seat])
        self.seat_label.setFixedWidth(26)
        self.seat_label.setObjectName("muted")
        self.action_label = QLabel("等待")
        self.action_label.setFixedWidth(82)
        self.cards = MiniCardStrip(card_width=27, card_height=32, minimum_width=126)
        layout.addWidget(self.seat_label)
        layout.addWidget(self.action_label)
        layout.addWidget(self.cards, 1)

    def update_action(
        self,
        action: tuple[str, Pattern | None] | None,
        *,
        is_top: bool,
        is_turn: bool,
    ) -> None:
        prefix = "最大 · " if is_top else ""
        if action is None:
            self.action_label.setText("等待")
            self.cards.set_cards(())
        else:
            kind, pattern = action
            if kind == "pass":
                self.action_label.setText("过牌")
                self.cards.set_cards(())
            elif pattern is not None:
                self.action_label.setText(prefix + pattern_type_label(pattern.type))
                self.cards.set_cards(pattern.cards)
            else:
                self.action_label.setText("等待")
                self.cards.set_cards(())
        color = GOLD_BRIGHT.name() if is_top else TEXT_MUTED.name()
        self.seat_label.setStyleSheet(f"color: {color}; font-weight: 800;")
        self.action_label.setStyleSheet(f"color: {color}; font-weight: 750;")
        set_property(self, "top", is_top)
        set_property(self, "turn", is_turn)


class ActivityRail(QFrame):
    """Compact public action trail that keeps the flow of play readable."""

    _MAX_VISIBLE = 5

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("activityRail")
        self.setMinimumWidth(164)
        self.setMaximumWidth(190)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 7, 9, 7)
        layout.setSpacing(3)
        title = QLabel("最近行动")
        title.setObjectName("activityTitle")
        layout.addWidget(title)
        self.lines: list[QLabel] = []
        for _ in range(self._MAX_VISIBLE):
            line = QLabel("—")
            line.setObjectName("activityLine")
            line.setMinimumHeight(20)
            line.setWordWrap(False)
            layout.addWidget(line)
            self.lines.append(line)
        layout.addStretch(1)
        self.counter = QLabel("尚未出牌")
        self.counter.setObjectName("activityCounter")
        layout.addWidget(self.counter)

    def update_events(self, events: list[Event]) -> None:
        public_actions = [
            event for event in events if isinstance(event, (TurnPlayed, Pass))
        ]
        recent = public_actions[-self._MAX_VISIBLE :]
        empty_count = self._MAX_VISIBLE - len(recent)
        rows: list[tuple[str, bool]] = [("—", False)] * empty_count
        first_number = len(public_actions) - len(recent) + 1
        for offset, event in enumerate(recent):
            number = first_number + offset
            if isinstance(event, Pass):
                text = f"{number:02}  {SEAT_NAMES[event.player]}家 · 过牌"
            else:
                cards = " ".join(card_label(card) for card in event.pattern.cards)
                if len(cards) > 12:
                    cards = cards[:11] + "…"
                text = (
                    f"{number:02}  {SEAT_NAMES[event.player]}家 · "
                    f"{pattern_type_label(event.pattern.type)} {cards}"
                )
            rows.append((text, offset == len(recent) - 1))

        for label, (text, latest) in zip(self.lines, rows):
            label.setText(text)
            label.setToolTip(text if text != "—" else "")
            set_property(label, "latest", latest)
        self.counter.setText(f"本局共 {len(public_actions)} 次公开行动" if public_actions else "尚未出牌")


class TablePanel(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("trickPanel")
        self.setMinimumSize(530, 226)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(3)
        header = QHBoxLayout()
        self.title = QLabel("当前牌墩")
        self.title.setObjectName("accentTitle")
        self.phase_badge = QLabel("等待")
        self.phase_badge.setObjectName("trickPhase")
        self.trick_meta = QLabel("等待先手")
        self.trick_meta.setObjectName("muted")
        header.addWidget(self.title)
        header.addWidget(self.phase_badge)
        header.addStretch(1)
        header.addWidget(self.trick_meta)
        layout.addLayout(header)
        self.tribute_banner = QFrame()
        self.tribute_banner.setObjectName("tributeBanner")
        tribute_layout = QHBoxLayout(self.tribute_banner)
        tribute_layout.setContentsMargins(8, 2, 8, 2)
        tribute_layout.setSpacing(8)
        self.tribute_text = QLabel()
        self.tribute_text.setObjectName("tributeText")
        self.tribute_text.setWordWrap(True)
        self.tribute_cards = MiniCardStrip()
        tribute_layout.addWidget(self.tribute_text, 1)
        tribute_layout.addWidget(self.tribute_cards)
        self.tribute_banner.hide()
        layout.addWidget(self.tribute_banner)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)
        rows_layout = QVBoxLayout()
        rows_layout.setContentsMargins(0, 0, 0, 0)
        rows_layout.setSpacing(3)
        self.trick_rows: dict[int, TrickRow] = {}
        self.rows: dict[int, QLabel] = {}
        for seat in (0, 3, 2, 1):
            row = TrickRow(seat)
            self.trick_rows[seat] = row
            self.rows[seat] = row.action_label
            rows_layout.addWidget(row)
        body.addLayout(rows_layout, 1)
        self.activity = ActivityRail()
        body.addWidget(self.activity)
        layout.addLayout(body, 1)

    def update_table(
        self,
        state: GameState,
        actions: dict[int, tuple[str, Pattern | None]],
        table_players: list[int],
        tribute_events: tuple[Event, ...],
        tribute_notice: str,
    ) -> None:
        self._update_tribute(tribute_events, tribute_notice)
        top_player = table_players[-1] if state.table and table_players else self._last_top_player(state)
        if state.table:
            self.title.setText(f"第 {state.trick_number + 1} 墩")
            self.phase_badge.setText("进行中")
            set_property(self.phase_badge, "phase", "active")
            self.trick_meta.setText(
                f"最大：{SEAT_NAMES[top_player]}家" if top_player is not None else "等待先手"
            )
        elif actions and top_player is not None:
            self.title.setText(f"第 {max(1, state.trick_number)} 墩")
            self.phase_badge.setText("已收牌")
            set_property(self.phase_badge, "phase", "cleared")
            starter = state.next_trick_starter if state.next_trick_starter is not None else state.turn_index
            if starter == top_player:
                self.trick_meta.setText(f"{SEAT_NAMES[top_player]}家收牌并先手")
            else:
                self.trick_meta.setText(
                    f"{SEAT_NAMES[top_player]}家收牌 · {SEAT_NAMES[starter]}家接风"
                )
        else:
            self.title.setText(f"第 {state.trick_number + 1} 墩")
            self.phase_badge.setText("等待")
            set_property(self.phase_badge, "phase", "waiting")
            self.trick_meta.setText(f"等待 {SEAT_NAMES[state.turn_index]}家先手")
        for seat, row in self.trick_rows.items():
            row.update_action(
                actions.get(seat),
                is_top=seat == top_player and actions.get(seat, (None,))[0] == "play",
                is_turn=not state.finished and seat == state.turn_index,
            )
        self.activity.update_events(state.history)

    @staticmethod
    def _last_top_player(state: GameState) -> int | None:
        for event in reversed(state.history):
            if isinstance(event, TurnPlayed):
                return event.player
        return None

    def _update_tribute(self, events: tuple[Event, ...], notice: str) -> None:
        cards: list[Card] = []
        for event in events:
            if isinstance(event, (TributeSent, TributeReturned)):
                cards.append(event.card)
        self.tribute_text.setText(notice)
        self.tribute_cards.set_cards(cards)
        self.tribute_banner.show()


class GamePage(QWidget):
    def __init__(self, window: "GuandanMainWindow", session: GameSession) -> None:
        super().__init__()
        self.setObjectName("page")
        self._main_window = window
        self.session = session
        self.selected_indices: set[int] = set()
        self.hand_cards: list[Card] = []
        self.hand_organizer = HandOrganizer()
        self._ai_timer = QTimer(self)
        self._ai_timer.setSingleShot(True)
        # Give every public action enough dwell time to be perceived before the
        # next AI starts thinking.  The worker itself performs exactly one turn.
        self._ai_timer.setInterval(650)
        self._ai_timer.timeout.connect(self._start_ai_worker)
        self._tribute_timer = QTimer(self)
        self._tribute_timer.setSingleShot(True)
        self._tribute_timer.setInterval(500)
        self._tribute_timer.timeout.connect(self._begin_next_game_tribute)
        self._ai_running = False
        self._ai_worker: AIWorker | None = None
        self._recent_actor: int | None = None
        self._last_public_count = 0
        self._action_round_id = session.game_id
        self._action_flash_timer = QTimer(self)
        self._action_flash_timer.setSingleShot(True)
        self._action_flash_timer.setInterval(850)
        self._action_flash_timer.timeout.connect(self._clear_action_flash)
        self._build()
        self.session.ensure_started()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 10)
        layout.setSpacing(8)

        hud = make_panel("hud")
        hud_layout = QHBoxLayout(hud)
        hud_layout.setContentsMargins(12, 7, 12, 7)
        hud_layout.setSpacing(12)
        brand = QLabel("掼")
        brand.setObjectName("brandMark")
        hud_layout.addWidget(brand)
        round_info = make_panel("roundInfo")
        round_layout = QVBoxLayout(round_info)
        round_layout.setContentsMargins(11, 5, 11, 5)
        round_layout.setSpacing(0)
        self.round_phase = QLabel()
        self.round_phase.setObjectName("roundPhase")
        self.round_level = QLabel()
        self.round_level.setObjectName("roundLevel")
        round_layout.addWidget(self.round_phase)
        round_layout.addWidget(self.round_level)
        hud_layout.addWidget(round_info)
        self.status = QLabel()
        self.status.setObjectName("statusText")
        self.status.setWordWrap(True)
        hud_layout.addWidget(self.status, 1)
        self.turn_label = QLabel("等待行动")
        self.turn_label.setObjectName("turnBanner")
        hud_layout.addWidget(self.turn_label)
        self.score_label = QLabel()
        self.score_label.setObjectName("goldChip")
        hud_layout.addWidget(self.score_label)
        layout.addWidget(hud)

        arena = GameArena()
        self.arena = arena
        table_grid = QGridLayout(arena)
        table_grid.setContentsMargins(18, 10, 18, 10)
        table_grid.setHorizontalSpacing(12)
        table_grid.setVerticalSpacing(4)
        self.opposite = SeatPanel()
        self.left = SeatPanel()
        self.right = SeatPanel()
        self.me = SeatPanel(human=True)
        self.table = TablePanel()
        table_grid.addWidget(self.opposite, 0, 1)
        table_grid.addWidget(self.left, 1, 0)
        table_grid.addWidget(self.table, 1, 1)
        table_grid.addWidget(self.right, 1, 2)
        table_grid.addWidget(self.me, 2, 1)
        table_grid.setColumnStretch(0, 1)
        table_grid.setColumnStretch(1, 3)
        table_grid.setColumnStretch(2, 1)
        table_grid.setRowStretch(1, 1)
        layout.addWidget(arena, 1)

        hand_panel = make_panel("handDock")
        hand_layout = QVBoxLayout(hand_panel)
        hand_layout.setContentsMargins(12, 8, 12, 8)
        hand_layout.setSpacing(5)
        hand_head = QHBoxLayout()
        self.hand_title = QLabel("我的手牌")
        self.hand_title.setObjectName("accentTitle")
        self.hand_counter = QLabel("")
        self.hand_counter.setObjectName("muted")
        hand_head.addWidget(self.hand_title)
        self.selection_preview = QLabel("选择手牌查看牌型")
        self.selection_preview.setObjectName("selectionPreview")
        hand_head.addWidget(self.selection_preview, 1)
        hand_head.addStretch(1)
        self.organize_button = button("切换理牌", self.organize_hand, role="infoButton")
        hand_head.addWidget(self.organize_button)
        self.organize_menu_button = button("方式 ▾", self.show_organize_menu, role="quietButton")
        hand_head.addWidget(self.organize_menu_button)
        hand_head.addWidget(self.hand_counter)
        hand_layout.addLayout(hand_head)
        self.hand = HandWidget()
        self.hand.card_clicked.connect(self.toggle_card)
        self.hand.group_double_clicked.connect(self.toggle_group)
        self.hand_stack = QStackedWidget()
        self.hand_stack.setFixedHeight(HAND_HEIGHT)
        self.hand_stack.addWidget(self.hand)
        self.result_panel = QWidget()
        result_layout = QHBoxLayout(self.result_panel)
        result_layout.setContentsMargins(5, 2, 5, 2)
        result_layout.setSpacing(16)
        self.result_places = QLabel()
        self.result_places.setObjectName("resultPlaces")
        self.result_places.setWordWrap(True)
        result_layout.addWidget(self.result_places, 2)
        self.result_scores = QLabel()
        self.result_scores.setObjectName("resultScores")
        self.result_scores.setWordWrap(True)
        result_layout.addWidget(self.result_scores, 2)
        self.next_button = button("下一局", self.next_game, primary=True)
        self.next_button.setMinimumWidth(170)
        result_layout.addWidget(self.next_button, 1)
        self.hand_stack.addWidget(self.result_panel)
        hand_layout.addWidget(self.hand_stack)
        layout.addWidget(hand_panel)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.play_button = button("出  牌", self.play_selected, primary=True)
        self.play_button.setMinimumWidth(145)
        self.pass_button = button("过  牌", self.pass_turn)
        self.hint_button = button("智能提示", self.hint, role="infoButton")
        self.clear_button = button("取消选择", self.clear_selection, role="quietButton")
        self.cancel_tribute_button = button("取消换牌", self.cancel_tribute, role="quietButton")
        self.previous_trick_button = button("回看上一墩", self.show_previous_trick, role="quietButton")
        self.back_button = button("返回大厅", self.back_to_menu, role="quietButton")
        for item in (
            self.play_button,
            self.pass_button,
            self.hint_button,
            self.clear_button,
            self.cancel_tribute_button,
            self.previous_trick_button,
        ):
            actions.addWidget(item)
        actions.addStretch(1)
        actions.addWidget(self.back_button)
        layout.addLayout(actions)

        self.log = QLabel("准备开始")
        self.log.setObjectName("menuNote")
        self.log.setWordWrap(True)
        layout.addWidget(self.log)
        self._install_shortcuts()

    def _install_shortcuts(self) -> None:
        for key, handler in (
            ("Return", self.play_selected),
            ("Enter", self.play_selected),
            ("P", self.pass_turn),
            ("T", self.hint),
            ("S", self.organize_hand),
            ("Shift+S", self.show_organize_menu),
            ("N", self.next_game),
            ("R", self.show_previous_trick),
            ("Escape", self.back_to_menu),
            ("Backspace", self.clear_selection),
        ):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(handler)

    def refresh(self) -> None:
        state = self.session.display_state()
        tribute_pending = self.session.is_next_game_pending()
        seats = self.session.visual_seats()
        ai_label = f"AI·{self.session.strategy.name}"
        for seat, panel in (
            (seats["left"], self.left),
            (seats["opposite"], self.opposite),
            (seats["right"], self.right),
        ):
            panel.update_state(
                seat,
                len(state.hands[seat]),
                seat in state.finish_order,
                not tribute_pending and state.turn_index == seat,
                ai_label,
                thinking=self._ai_running or self._ai_timer.isActive(),
            )
        self.me.update_state(
            self.session.human,
            len(state.hands[self.session.human]),
            self.session.human in state.finish_order,
            not tribute_pending and state.turn_index == self.session.human,
            "你",
        )
        self._refresh_status(state)
        self._refresh_hand(state)
        self.table.update_table(
            state,
            self.session.table_display_actions(preserve_completed_trick=True),
            self.session.current_table_players(),
            self.session.tribute_events(),
            self.session.tribute_notice(),
        )
        public_actions = [
            event for event in state.history if isinstance(event, (TurnPlayed, Pass))
        ]
        if self._action_round_id != self.session.game_id:
            self._action_round_id = self.session.game_id
            self._last_public_count = 0
            self._recent_actor = None
            self._action_flash_timer.stop()
        if len(public_actions) > self._last_public_count:
            self._recent_actor = public_actions[-1].player
            self._action_flash_timer.start()
        self._last_public_count = len(public_actions)
        for seat, panel in (
            (seats["left"], self.left),
            (seats["opposite"], self.opposite),
            (seats["right"], self.right),
            (self.session.human, self.me),
        ):
            set_property(panel, "recent", seat == self._recent_actor)
            set_property(self.table.trick_rows[seat], "recent", seat == self._recent_actor)
        self.log.setText(self.session.last_action)
        choice = self.session.pending_next_game_choice()
        choosing = tribute_pending and choice is not None
        human_turn = (
            not tribute_pending
            and state.turn_index == self.session.human
            and not state.finished
        )
        playable, preview = self._selection_status(state, human_turn, choice)
        self.selection_preview.setText(preview)
        set_property(self.selection_preview, "valid", playable)
        if choosing and choice is not None:
            self.play_button.setText(f"确认{'进贡' if choice.kind == 'tribute' else '还贡'}")
        else:
            self.play_button.setText("出  牌")
        self.play_button.setVisible(human_turn or choosing)
        self.play_button.setEnabled(playable)
        self.pass_button.setVisible(human_turn and bool(state.table))
        self.pass_button.setEnabled(human_turn and bool(state.table))
        self.hint_button.setVisible(human_turn)
        self.hint_button.setEnabled(human_turn)
        self.organize_button.setEnabled(
            not tribute_pending and not state.finished
            and bool(self.hand_cards) and self.hand_organizer.available
        )
        self.organize_menu_button.setEnabled(self.organize_button.isEnabled())
        self.clear_button.setVisible((human_turn or choosing) and bool(self.selected_indices))
        self.clear_button.setEnabled(bool(self.selected_indices))
        self.cancel_tribute_button.setVisible(choosing)
        self.previous_trick_button.setVisible(
            not tribute_pending and state.trick_number > 0
        )
        self.next_button.setEnabled(
            not tribute_pending and state.finished and not state.match_finished
        )
        if tribute_pending:
            self.next_button.setText("已发牌")
        elif state.match_finished:
            self.next_button.setText("比赛已结束")
        elif state.finished:
            next_level = rank_value_label(self.session.next_round_level(state))
            self.next_button.setText(f"下一局 · 级牌 {next_level}")
        else:
            self.next_button.setText("下一局")
        self.back_button.setEnabled(not self._ai_running and not tribute_pending)
        self.back_button.setVisible(not tribute_pending)
        self.hand_stack.setCurrentWidget(self.result_panel if state.finished and not tribute_pending else self.hand)
        title = "本局结算" if state.finished and not tribute_pending else "我的手牌"
        if not tribute_pending and not state.finished and self.hand_organizer.status:
            title += f" · {self.hand_organizer.status}"
        self.hand_title.setText(title)
        self.hand_counter.setVisible(not state.finished or tribute_pending)
        if state.finished and not tribute_pending:
            self._refresh_result(state)

    def _selection_status(
        self, state: GameState, human_turn: bool, choice: PendingCardChoice | None
    ) -> tuple[bool, str]:
        cards = self.selected_cards()
        if choice is not None:
            verb = "进贡" if choice.kind == "tribute" else "还贡"
            if not cards:
                return False, f"{verb}阶段 · 请选择一张高亮手牌"
            return len(cards) == 1, f"已选 {card_label(cards[0])} · 点击确认{verb}"
        if not cards:
            current = self.hand_organizer.current
            if current is not None:
                suffix = " · 双击成组手牌可整组选中" if current.kind == "pattern" else ""
                return False, current.summary + suffix
            return False, "选择手牌查看牌型" if human_turn else ""
        pattern = find_complete_pattern(cards, state.wild_card)
        if pattern is None:
            return False, f"已选 {len(cards)} 张 · 不是完整牌型"
        description = f"{pattern_type_label(pattern.type)} · {rank_value_label(pattern.rank)}"
        if not human_turn:
            return False, description
        if self.session.human in state.passed_players:
            return False, f"{description} · 已对当前桌顶过牌"
        if state.table and not pattern.can_be_played_on(state.table[-1], level=state.level):
            return False, f"{description} · 压不过桌面"
        return True, f"{description} · 可出牌"

    def _refresh_result(self, state: GameState) -> None:
        order = list(state.finish_order)
        order.extend(seat for seat in range(4) if seat not in order)
        labels = ("头游", "二游", "三游", "末游")
        self.result_places.setText(
            "名次\n" + "   ".join(
                f"{label} {SEAT_NAMES[seat]}家{'（你）' if seat == self.session.human else ''}"
                for label, seat in zip(labels, order)
            )
        )
        final_levels = state.team_levels_final or state.team_levels
        score_lines = []
        for team, name in enumerate(("东西", "南北")):
            before = state.team_levels[team]
            after = final_levels[team]
            delta = after - before
            change = f"升级 {delta} 级" if delta > 0 else "级牌不变" if delta == 0 else "重置级牌"
            score_lines.append(
                f"{name}队  {rank_value_label(before)} → {rank_value_label(after)}  ·  {change}"
            )
        result_title = "本局升级"
        if state.match_finished and state.winner_team is not None:
            winner = "东西" if state.winner_team == 0 else "南北"
            result_title = f"比赛结束 · {winner}队过 A 获胜"
        self.result_scores.setText(result_title + "\n" + "\n".join(score_lines))
        self.next_button.setVisible(not state.match_finished)

    def _refresh_status(self, state: GameState) -> None:
        wild = card_label(state.wild_card) if state.wild_card is not None else "无"
        levels = self.session.visible_team_levels()
        round_index = self.session.round_index + int(self.session.is_next_game_pending())
        has_played = any(isinstance(event, (TurnPlayed, Pass)) for event in state.history)
        opening = not state.finished and not has_played
        set_property(self.status, "opening", opening)
        if self.session.is_next_game_pending():
            phase = "发牌中"
        elif state.finished:
            phase = "比赛结束" if state.match_finished else "本局结束"
        elif has_played:
            phase = "进行中"
        else:
            phase = "本局开始"
        self.round_phase.setText(f"第 {round_index} 局 · {phase}")
        self.round_level.setText(f"本局级牌 {rank_value_label(state.level)}")
        if self.session.is_next_game_pending():
            choice = self.session.pending_next_game_choice()
            if choice is None:
                phase = "手牌已发放，即将开始贡还牌"
            else:
                verb = "进贡" if choice.kind == "tribute" else "还贡"
                phase = f"贡还牌阶段：请选择{verb}牌"
            self.status.setText(
                f"{self.session.tribute_notice()}\n{phase}  ·  逢人配 {wild}"
            )
            self.score_label.setText(
                f"东西 {rank_value_label(levels[0])}  /  南北 {rank_value_label(levels[1])}"
            )
            self.turn_label.setText("贡还牌阶段")
            return
        turn = SEAT_NAMES[state.turn_index]
        finished = " > ".join(SEAT_NAMES[p] for p in state.finish_order) or "-"
        if state.finished and state.match_finished and state.winner_team is not None:
            winner = "东西" if state.winner_team == 0 else "南北"
            suffix = f"本局级牌 {rank_value_label(state.level)}  ·  {winner}方获胜"
        elif state.finished:
            suffix = (
                f"本局级牌 {rank_value_label(state.level)}  ·  "
                f"下一局级牌 {rank_value_label(self.session.next_round_level(state))}"
            )
        elif state.turn_index == self.session.human:
            suffix = "轮到你行动"
        else:
            suffix = f"等待 {turn}家出牌"
        if opening:
            self.status.setText(
                f"{self.session.tribute_notice()}\n逢人配 {wild}  ·  {suffix}"
            )
        elif state.finished:
            self.status.setText(f"逢人配 {wild}  ·  名次 {finished}  ·  {suffix}")
        else:
            self.status.setText(
                f"逢人配 {wild}  ·  当前 {turn}家  ·  名次 {finished}  ·  {suffix}"
            )
        self.score_label.setText(
            f"东西 {rank_value_label(levels[0])}  /  南北 {rank_value_label(levels[1])}"
        )
        if state.match_finished:
            self.turn_label.setText("比赛结束")
        elif state.finished:
            self.turn_label.setText("本局结束")
        elif state.turn_index == self.session.human:
            self.turn_label.setText("你的回合")
        else:
            self.turn_label.setText(
                f"{turn}家思考中…" if self._ai_running or self._ai_timer.isActive()
                else f"{turn}家行动"
            )

    def _refresh_hand(self, state: GameState) -> None:
        previously_selected = self.selected_cards()
        base_cards = sort_cards_for_display(
            state.hands[self.session.human],
            level=state.level,
        )
        self.hand_organizer.sync(base_cards, state.wild_card, state.level)
        arranged = not self.session.is_next_game_pending() and not state.finished
        self.hand_cards = list(self.hand_organizer.cards) if arranged else base_cards
        self.selected_indices = card_indices_for_selection(
            self.hand_cards, tuple(previously_selected)
        )
        choice = self.session.pending_next_game_choice()
        eligible_indices = (
            {index for index, card in enumerate(self.hand_cards) if card in choice.cards}
            if choice is not None else None
        )
        if eligible_indices is not None:
            self.selected_indices.intersection_update(eligible_indices)
            if len(self.selected_indices) > 1:
                self.selected_indices = {min(self.selected_indices)}
        self.hand.set_cards(
            self.hand_cards,
            wild_card=state.wild_card,
            selected_indices=self.selected_indices,
            eligible_indices=eligible_indices,
            groups=(self.hand_organizer.current.groups
                    if arranged and self.hand_organizer.current is not None else None),
        )
        self.hand_counter.setText(
            f"{len(self.hand_cards)} 张 · 可选 {len(eligible_indices)} 张"
            if eligible_indices is not None else
            f"{len(self.hand_cards)} 张 · 已选 {len(self.selected_indices)} 张"
        )

    def toggle_card(self, index: int) -> None:
        choice = self.session.pending_next_game_choice()
        if choice is not None:
            if index >= len(self.hand_cards) or self.hand_cards[index] not in choice.cards:
                return
            self.selected_indices = set() if index in self.selected_indices else {index}
            self.refresh()
            return
        state = self.session.display_state()
        if state.finished or state.turn_index != self.session.human or self.session.is_next_game_pending():
            return
        self.session.reset_hint_cycle()
        if index in self.selected_indices:
            self.selected_indices.remove(index)
        else:
            self.selected_indices.add(index)
        self.refresh()

    def toggle_group(self, index: int) -> None:
        state = self.session.display_state()
        if state.finished or state.turn_index != self.session.human or self.session.is_next_game_pending():
            return
        result = self.hand_organizer.playable_group_at(index)
        if result is None:
            return
        start, end, _ = result
        indices = set(range(start, end))
        self.selected_indices = set() if self.selected_indices == indices else indices
        self.session.reset_hint_cycle()
        self.refresh()

    def selected_cards(self) -> list:
        return [
            self.hand_cards[index]
            for index in sorted(self.selected_indices)
            if index < len(self.hand_cards)
        ]

    def play_selected(self) -> None:
        choice = self.session.pending_next_game_choice()
        if choice is not None:
            cards = self.selected_cards()
            if len(cards) == 1 and cards[0] in choice.cards:
                self._finish_next_game(cards[0])
            return
        if not self.play_button.isEnabled():
            return
        result = self.session.play_human_cards(self.selected_cards())
        if result.ok:
            self.selected_indices.clear()
        self.refresh()
        self.schedule_ai()

    def pass_turn(self) -> None:
        if not self.pass_button.isEnabled():
            return
        result = self.session.pass_human()
        if result.ok:
            self.selected_indices.clear()
        self.refresh()
        self.schedule_ai()

    def hint(self) -> None:
        if not self.hint_button.isEnabled():
            return
        result = self.session.hint_for_human()
        self.selected_indices = card_indices_for_selection(
            self.hand_cards,
            result.suggested_cards,
        )
        self.refresh()

    def organize_hand(self) -> None:
        if not self.organize_button.isEnabled():
            return
        if self.hand_organizer.advance():
            self.refresh()

    def choose_organization(self, index: int) -> None:
        if self.organize_menu_button.isEnabled() and self.hand_organizer.select(index):
            self.refresh()

    def reset_organization(self) -> None:
        if self.organize_menu_button.isEnabled():
            self.hand_organizer.reset()
            self.refresh()

    def show_organize_menu(self) -> None:
        if not self.organize_menu_button.isEnabled():
            return
        menu = QMenu(self.organize_menu_button)
        menu.addAction("恢复默认顺序", self.reset_organization)
        menu.addSeparator()
        for index, arrangement in enumerate(self.hand_organizer.arrangements):
            action = menu.addAction(f"{index + 1}. {arrangement.name} · {arrangement.summary}")
            action.setCheckable(True)
            action.setChecked(arrangement is self.hand_organizer.current)
            action.triggered.connect(
                lambda checked=False, position=index: self.choose_organization(position)
            )
        menu.exec(self.organize_menu_button.mapToGlobal(
            QPoint(0, self.organize_menu_button.height())
        ))

    def clear_selection(self) -> None:
        self.session.reset_hint_cycle()
        self.selected_indices.clear()
        self.refresh()

    def next_game(self) -> None:
        if self.session.is_next_game_pending():
            return
        prepared = self.session.prepare_next_game()
        if not prepared.ok:
            self.refresh()
            return
        self.selected_indices.clear()
        self.refresh()
        self._tribute_timer.start()

    def _begin_next_game_tribute(self) -> None:
        self._tribute_timer.stop()
        if (
            self._main_window.stack.currentWidget() is not self
            or not self.session.is_next_game_pending()
        ):
            return
        started = self.session.begin_next_game_tribute()
        if not started.ok:
            self.refresh()
            return
        self.refresh()
        choice = self.session.pending_next_game_choice()
        if choice is not None:
            return
        self._finish_next_game(None)

    def cancel_tribute(self) -> None:
        if self.session.is_next_game_pending():
            self.session.cancel_next_game()
            self.selected_indices.clear()
            self.refresh()

    def _finish_next_game(self, selected_card: Card | None) -> None:
        result = self.session.finalize_next_game(selected_card)
        if result.ok:
            self.selected_indices.clear()
        self.refresh()
        self.schedule_ai()

    def schedule_ai(self) -> None:
        state = self.session.ensure_started()
        if (
            self._main_window.stack.currentWidget() is not self
            or self.session.is_next_game_pending()
            or state.finished
            or state.turn_index == self.session.human
            or self._ai_timer.isActive()
            or self._ai_running
        ):
            return
        self._ai_timer.start()
        self.refresh()

    def _start_ai_worker(self) -> None:
        if self._main_window.stack.currentWidget() is not self:
            return
        state = self.session.ensure_started()
        if state.finished or state.turn_index == self.session.human or self._ai_running:
            self.refresh()
            return
        self._ai_running = True
        self.refresh()
        worker = AIWorker(self.session)
        self._ai_worker = worker
        worker.signals.completed.connect(self._ai_finished)
        QThreadPool.globalInstance().start(worker)

    def _ai_finished(self, payload: object) -> None:
        if not isinstance(payload, tuple) or len(payload) != 2:
            messages: list[str] = []
            error: Exception | None = RuntimeError("invalid AI worker result")
        else:
            raw_messages, raw_error = payload
            messages = raw_messages if isinstance(raw_messages, list) else []
            error = raw_error if isinstance(raw_error, Exception) else None
        self._ai_running = False
        self._ai_worker = None
        if error is not None:
            self.session.last_action = f"后台操作失败：{error}"
        elif messages:
            self.session.last_action = "；".join(messages[-4:])
        if self._main_window.stack.currentWidget() is self:
            self.refresh()
            if not any("AI 错误" in message for message in messages):
                self.schedule_ai()

    def is_ai_running(self) -> bool:
        return self._ai_running

    def deactivate(self) -> None:
        """Stop deferred work when this table is no longer visible."""
        self._ai_timer.stop()
        self._tribute_timer.stop()
        self._action_flash_timer.stop()

    def _clear_action_flash(self) -> None:
        self._recent_actor = None
        if self._main_window.stack.currentWidget() is self:
            self.refresh()

    def show_previous_trick(self) -> None:
        if not self.previous_trick_button.isVisible():
            return
        try:
            events = self.session.previous_completed_trick()
        except ValueError:
            events = []
        if not events:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"回看第 {self.session.require_state().trick_number} 墩")
        dialog.setMinimumWidth(460)
        layout = QVBoxLayout(dialog)
        heading = QLabel(f"第 {self.session.require_state().trick_number} 墩 · 公开行动")
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        for event in events:
            line = QLabel(replay_event_text(event))
            line.setObjectName("previousTrickLine")
            line.setWordWrap(True)
            layout.addWidget(line)
        layout.addWidget(button("返回牌桌", dialog.close, role="quietButton"))
        self._previous_trick_dialog = dialog
        dialog.show()

    def back_to_menu(self) -> None:
        self.deactivate()
        if self._main_window.save_current_game():
            self._main_window.show_menu()


class GuandanMainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"掼蛋 GUI · {version_label()}")
        self.resize(1280, 860)
        self.setMinimumSize(1080, 760)
        self.stack = QStackedWidget()
        root = QWidget()
        root.setObjectName("root")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(self.stack)
        self.setCentralWidget(root)
        self.game_page: GamePage | None = None
        self.show_menu()

    def _replace_page(self, page: QWidget) -> None:
        current = self.stack.currentWidget()
        if isinstance(current, GamePage) and current is not page:
            current.deactivate()
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)
        while self.stack.count() > 3:
            evicted = self.stack.widget(0)
            if evicted is None or evicted is page:
                break
            # Never keep a pointer to an evicted table: save_current_game()
            # and closeEvent() both call into self.game_page, and an evicted
            # page's Qt objects can already be gone.
            evicts_game_page = evicted is self.game_page
            self.stack.removeWidget(evicted)
            evicted.deleteLater()
            if evicts_game_page:
                self.game_page = None

    def show_menu(self) -> None:
        self._replace_page(MenuPage(self))

    def show_difficulty(self) -> None:
        self._replace_page(DifficultyPage(self))

    def show_load(self) -> None:
        self._replace_page(LoadPage(self))

    def show_history(self) -> None:
        self._replace_page(HistoryPage(self))

    def show_replay(self, history: dict) -> None:
        try:
            self._replace_page(ReplayPage(self, history))
        except ValueError as exc:
            QMessageBox.warning(self, "查看回放", f"回放数据无效：{exc}")

    def show_rules(self) -> None:
        self._replace_page(RulesPage(self))

    def start_game(self, session: GameSession) -> None:
        self.game_page = GamePage(self, session)
        self._replace_page(self.game_page)
        self.game_page.schedule_ai()

    def confirm_start_new_game(self) -> bool:
        """Resolve the single-save conflict before replacing an unfinished round."""
        try:
            existing = load_game() if has_savegame() else None
        except OSError as exc:
            QMessageBox.warning(self, "无法检查存档", str(exc))
            return False
        if existing is None and not has_savegame():
            return True
        choice = QMessageBox.warning(
            self,
            "已有未完成存档",
            "继续旧存档、覆盖并开始新局，或取消？",
            QMessageBox.StandardButton.Open
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Open,
        )
        if choice == QMessageBox.StandardButton.Open:
            self.show_load()
            return False
        if choice == QMessageBox.StandardButton.Discard:
            try:
                # Only discard the save the user was just shown; a parallel
                # process may have written a newer one.
                delete_savegame(
                    expected_game_id=existing.get("game_id") if existing else None
                )
            except OSError as exc:
                QMessageBox.warning(self, "无法覆盖存档", str(exc))
                return False
            return True
        return False

    def save_current_game(self) -> bool:
        if self.game_page is None:
            return True
        if self.game_page.is_ai_running():
            QMessageBox.information(self, "AI 行动中", "请等待当前 AI 行动完成后再离开。")
            return False
        state = self.game_page.session.ensure_started()
        if state.finished:
            if self.game_page.session.save_finished_if_needed():
                return True
            QMessageBox.warning(self, "保存失败", self.game_page.session.last_action)
            return False
        try:
            self.game_page.session.save_unfinished()
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return False
        return True

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.game_page is not None:
            self.game_page.deactivate()
        if self.save_current_game():
            event.accept()
        else:
            event.ignore()


def repair_interrupted_settlements() -> int:
    """Finish settlements a previous run could not complete.

    Settling a round writes history, then statistics, then removes the save.
    A crash in between used to leave a history entry that no statistic ever
    counted; the pending marker makes it repairable at startup. Returns how
    many settlements were closed.
    """
    try:
        return int(reconcile_settlements(history_has_game=history_exists))
    except (OSError, ValueError):
        return 0


def run_gui() -> int:
    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication(sys.argv)
    assert isinstance(app, QApplication)
    app.setStyleSheet(APP_QSS)
    repair_interrupted_settlements()
    window = GuandanMainWindow()
    window.show()
    if owns_app:
        return int(app.exec())
    return 0
