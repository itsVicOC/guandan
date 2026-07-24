"""PySide6 desktop GUI for the local Guandan game."""
from __future__ import annotations

import sys
from typing import Callable

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QFont,
    QKeySequence,
    QPainter,
    QPaintEvent,
    QPen,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..ai import AINotImplementedError, make_strategy
from ..engine.card import Card
from ..engine.events import Event
from ..engine.hand import Pattern
from ..engine.state import SEAT_NAMES, GameState, IllegalPlayError
from ..storage import (
    delete_savegame,
    has_savegame,
    load_game,
    load_history_detail,
    load_history_list,
    restore_game_state,
)
from ..ui.content import DIFFICULTIES, RULES_TEXT
from ..ui.formatting import card_label, pattern_type_label, rank_value_label
from ..ui.history import HISTORY_COLUMNS, history_entry_cells, history_statistics_text
from ..ui.replay import ReplayCursor, replay_event_text, replay_state_text
from ..ui.session import GameSession, card_indices_for_selection
from .cards import CardBackWidget, HandWidget, MiniCardStrip, sort_cards_for_display
from .theme import APP_QSS, CYAN, FELT, FELT_DARK, FELT_LINE, GOLD_BRIGHT, TEXT_MUTED


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


class LobbyTableWidget(QWidget):
    """Painted table preview used by the landing page."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(520, 420)
        self.setObjectName("lobbyTable")

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        outer = self.rect().adjusted(8, 8, -8, -8)
        painter.setPen(QPen(FELT_LINE, 2))
        painter.setBrush(FELT)
        painter.drawRoundedRect(outer, 22, 22)
        inner = outer.adjusted(16, 16, -16, -16)
        painter.setPen(QPen(QColor(117, 197, 174, 115), 1, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(inner, 18, 18)
        center = outer.center()
        painter.setPen(QPen(QColor(117, 197, 174, 125), 1))
        painter.drawEllipse(center, 84, 44)
        painter.setPen(GOLD_BRIGHT)
        painter.setFont(QFont("PingFang SC", 26, QFont.Weight.Black))
        painter.drawText(QRect(center.x() - 90, center.y() - 24, 180, 38), Qt.AlignmentFlag.AlignCenter, "掼蛋")
        painter.setPen(QColor(183, 221, 207))
        painter.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        painter.drawText(QRect(center.x() - 90, center.y() + 15, 180, 22), Qt.AlignmentFlag.AlignCenter, "108 张 · 四人搭档")

        seats = (
            (center.x(), outer.top() + 58, "西", False, "gold"),
            (outer.left() + 96, center.y(), "南", False, "cyan"),
            (outer.right() - 96, center.y(), "北", False, "cyan"),
            (center.x(), outer.bottom() - 58, "东", True, "gold"),
        )
        for x, y, label, human, team in seats:
            color = GOLD_BRIGHT if team == "gold" else CYAN
            painter.setPen(QPen(color, 2))
            painter.setBrush(QColor("#18372f"))
            painter.drawEllipse(x - 28, y - 28, 56, 56)
            painter.setPen(color)
            painter.setFont(QFont("PingFang SC", 20, QFont.Weight.Black))
            painter.drawText(QRect(x - 27, y - 15, 54, 30), Qt.AlignmentFlag.AlignCenter, label)
            painter.setPen(QColor(205, 226, 218))
            painter.setFont(QFont("PingFang SC", 10, QFont.Weight.DemiBold))
            painter.drawText(QRect(x - 60, y + 32, 120, 18), Qt.AlignmentFlag.AlignCenter, "你" if human else "AI")
        painter.end()


class MenuPage(QWidget):
    def __init__(self, window: "GuandanMainWindow") -> None:
        super().__init__()
        self._main_window = window
        self.setObjectName("page")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(52, 38, 52, 34)
        layout.setSpacing(22)

        masthead = QHBoxLayout()
        mark = QLabel("GD")
        mark.setObjectName("brandMark")
        masthead.addWidget(mark)
        masthead.addSpacing(12)
        masthead.addWidget(QLabel("LOCAL TABLE  ·  公测版"), 1)
        version = QLabel("v0.8.0-beta.3")
        version.setObjectName("muted")
        masthead.addWidget(version)
        layout.addLayout(masthead)

        layout.addWidget(page_header("四人搭档牌局", "掼蛋", "一张桌、两副牌。选择难度，坐到东家，开始一局完整的本地对战。"))

        body = QHBoxLayout()
        body.setSpacing(18)
        layout.addLayout(body, 1)

        body.addWidget(LobbyTableWidget(), 3)

        action_panel = make_panel("actionPanel")
        action_layout = QVBoxLayout(action_panel)
        action_layout.setContentsMargins(24, 24, 24, 24)
        action_layout.setSpacing(11)
        action_title = QLabel("牌局大厅")
        action_title.setObjectName("sectionTitle")
        action_layout.addWidget(action_title, 0, Qt.AlignmentFlag.AlignLeft)
        intro = QLabel("从这里开始一局本地掼蛋。\n你的对家是西家。")
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        action_layout.addWidget(intro)
        action_layout.addSpacing(8)
        action_layout.addWidget(button("开始新局", window.show_difficulty, primary=True))
        action_layout.addWidget(button("继续存档", window.show_load, role="quietButton"))
        action_layout.addWidget(button("历史战绩", window.show_history, role="quietButton"))
        action_layout.addWidget(button("规则说明", window.show_rules, role="quietButton"))
        action_layout.addStretch(1)
        action_layout.addWidget(QLabel("东 ↔ 西  ·  南 ↔ 北"), 0, Qt.AlignmentFlag.AlignCenter)
        action_layout.addWidget(button("退出", window.close, role="quietButton"))
        body.addWidget(action_panel, 1)


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
        except AINotImplementedError as exc:
            QMessageBox.warning(self, "AI 档位不可用", str(exc))
            return
        window.start_game(GameSession(difficulty=difficulty, level=2, human=0))


class LoadPage(QWidget):
    def __init__(self, window: "GuandanMainWindow") -> None:
        super().__init__()
        self._main_window = window
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
        except OSError as exc:
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
        state = restore_game_state(savegame)
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
                seed=metadata.get("seed"),
            )
        )

    def _delete_save(self) -> None:
        delete_savegame()
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
        actions.addWidget(button("查看回放", self.open_selected_replay, primary=True))
        actions.addWidget(button("返回大厅", window.show_menu, role="quietButton"))
        layout.addLayout(actions)
        self.refresh()

    def refresh(self) -> None:
        self.table.setRowCount(0)
        try:
            self.entries = load_history_list(limit=50)
        except OSError:
            self.entries = []
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
        detail = load_history_detail(self.entries[row]["game_id"])
        if detail is None:
            QMessageBox.warning(self, "查看回放", "这局历史记录无法读取。")
            return
        self._main_window.show_replay(detail)


class ReplayPage(QWidget):
    """Event-backed historical replay with deterministic step navigation."""

    def __init__(self, window: "GuandanMainWindow", history: dict) -> None:
        super().__init__()
        self._main_window = window
        self.setObjectName("page")
        self.history = history
        self.events: list[Event] = list(history.get("events", []))
        if not self.events:
            raise ValueError("history has no events")
        try:
            self._replay_cursor = ReplayCursor(self.events)
        except (IllegalPlayError, ValueError) as exc:
            raise ValueError("history event stream cannot be replayed") from exc

        layout = QVBoxLayout(self)
        layout.setContentsMargins(52, 40, 52, 32)
        layout.setSpacing(13)
        layout.addWidget(page_header("事件流查看器", "对局回放", "用首步、上一步、下一步和末步逐事件检查这局牌的状态变化。"))

        self.meta = QLabel()
        self.meta.setObjectName("muted")
        self.meta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.meta)

        self.state_summary = QLabel()
        self.state_summary.setObjectName("statusBar")
        self.state_summary.setWordWrap(True)
        layout.addWidget(self.state_summary)

        self.timeline = QTextBrowser()
        self.timeline.setReadOnly(True)
        layout.addWidget(self.timeline, 1)

        controls = QHBoxLayout()
        self.first_button = button("首步", lambda: self.set_event_index(0))
        self.previous_button = button("上一步", lambda: self.set_event_index(self.event_index - 1))
        self.next_button = button("下一步", lambda: self.set_event_index(self.event_index + 1), primary=True)
        self.last_button = button("末步", lambda: self.set_event_index(len(self.events) - 1))
        for item in (self.first_button, self.previous_button, self.next_button, self.last_button):
            controls.addWidget(item)
        layout.addLayout(controls)
        layout.addWidget(button("返回战绩", window.show_history, role="quietButton"))
        self.refresh()

    def set_event_index(self, index: int) -> None:
        self._replay_cursor.set_index(index)
        self.refresh()

    @property
    def event_index(self) -> int:
        return self._replay_cursor.index

    def refresh(self) -> None:
        state = self._replay_cursor.state
        self.meta.setText(
            f"{self.history.get('played_at', '-')[:19]} · "
            f"第 {self.event_index + 1} / {len(self.events)} 个事件\n"
            f"{history_statistics_text(self.history)}"
        )
        self.state_summary.setText(replay_state_text(state))
        lines = []
        for index, event in enumerate(self.events):
            marker = "▶" if index == self.event_index else " "
            lines.append(f"{marker} {index + 1:>3}. {replay_event_text(event)}")
        self.timeline.setPlainText("\n".join(lines))
        self.first_button.setEnabled(self.event_index > 0)
        self.previous_button.setEnabled(self.event_index > 0)
        self.next_button.setEnabled(self.event_index < len(self.events) - 1)
        self.last_button.setEnabled(self.event_index < len(self.events) - 1)

class RulesPage(QWidget):
    def __init__(self, window: "GuandanMainWindow") -> None:
        super().__init__()
        self.setObjectName("page")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(52, 40, 52, 32)
        layout.setSpacing(16)
        layout.addWidget(page_header("桌面规则", "规则说明", "掼蛋的牌型、比较、接风、升级和进贡规则。"))
        browser = QTextBrowser()
        browser.setPlainText(RULES_TEXT)
        layout.addWidget(browser, 1)
        layout.addWidget(button("返回大厅", window.show_menu, role="quietButton"))


class GameArena(QFrame):
    """Painted felt surface behind the four seats and current trick."""

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        outer = self.rect().adjusted(1, 1, -1, -1)
        painter.setPen(QPen(FELT_LINE, 1))
        painter.setBrush(FELT_DARK)
        painter.drawRoundedRect(outer, 18, 18)
        inner = outer.adjusted(12, 12, -12, -12)
        painter.setPen(QPen(QColor(71, 151, 126, 150), 1, Qt.PenStyle.DashLine))
        painter.setBrush(FELT)
        painter.drawRoundedRect(inner, 14, 14)
        center = inner.center()
        painter.setPen(QPen(QColor(126, 205, 181, 95), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, min(150, inner.width() // 5), min(82, inner.height() // 4))
        painter.setPen(QPen(QColor(126, 205, 181, 50), 1, Qt.PenStyle.DotLine))
        painter.drawLine(center.x(), inner.top() + 24, center.x(), inner.bottom() - 24)
        painter.end()


class SeatPanel(QFrame):
    def __init__(self, *, human: bool = False) -> None:
        super().__init__()
        self._human = human
        self.setObjectName("seatPanel")
        self.setMinimumSize(170, 72)
        self.setMaximumHeight(80)
        set_property(self, "human", human)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
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
        labels.addWidget(self.title)
        labels.addWidget(self.detail)
        layout.addLayout(labels, 1)

        self.card_back = CardBackWidget()
        self.card_back.setVisible(not human)
        layout.addWidget(self.card_back)

    def update_state(self, seat: int, hand_size: int, finished: bool, is_turn: bool, ai_name: str) -> None:
        team = "gold" if seat % 2 == 0 else "cyan"
        self.avatar.setText(SEAT_NAMES[seat])
        set_property(self.avatar, "team", team)
        set_property(self, "active", is_turn)
        set_property(self.detail, "active", is_turn)
        self.title.setText(f"{SEAT_NAMES[seat]}家" + (" · 你" if self._human else ""))
        if finished:
            meta = "已出完"
        elif is_turn:
            meta = f"● 行动中 · {hand_size} 张"
        else:
            meta = f"{ai_name} · {hand_size} 张"
        self.detail.setText(meta)
        self.card_back.setVisible(not self._human and not finished)


class TrickRow(QFrame):
    def __init__(self, seat: int) -> None:
        super().__init__()
        self.seat = seat
        self.setObjectName("trickRow")
        self.setFixedHeight(38)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 7, 0)
        layout.setSpacing(8)
        self.seat_label = QLabel(SEAT_NAMES[seat])
        self.seat_label.setFixedWidth(26)
        self.seat_label.setObjectName("muted")
        self.action_label = QLabel("等待")
        self.action_label.setMinimumWidth(78)
        self.cards = MiniCardStrip()
        layout.addWidget(self.seat_label)
        layout.addWidget(self.action_label)
        layout.addWidget(self.cards, 1)

    def update_action(self, action: tuple[str, Pattern | None] | None, *, is_top: bool) -> None:
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


class TablePanel(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("trickPanel")
        self.setMinimumSize(430, 210)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        header = QHBoxLayout()
        self.title = QLabel("当前牌墩")
        self.title.setObjectName("accentTitle")
        self.trick_meta = QLabel("等待先手")
        self.trick_meta.setObjectName("muted")
        header.addWidget(self.title)
        header.addStretch(1)
        header.addWidget(self.trick_meta)
        layout.addLayout(header)
        self.trick_rows: dict[int, TrickRow] = {}
        self.rows: dict[int, QLabel] = {}
        for seat in (0, 3, 2, 1):
            row = TrickRow(seat)
            self.trick_rows[seat] = row
            self.rows[seat] = row.action_label
            layout.addWidget(row)

    def update_table(
        self,
        state: GameState,
        actions: dict[int, tuple[str, Pattern | None]],
        table_players: list[int],
    ) -> None:
        top_player = table_players[-1] if state.table and table_players else None
        self.trick_meta.setText(
            f"最大：{SEAT_NAMES[top_player]}家" if top_player is not None else "等待先手"
        )
        for seat, row in self.trick_rows.items():
            row.update_action(actions.get(seat), is_top=seat == top_player)


class GamePage(QWidget):
    def __init__(self, window: "GuandanMainWindow", session: GameSession) -> None:
        super().__init__()
        self._main_window = window
        self.session = session
        self.selected_indices: set[int] = set()
        self.hand_cards: list[Card] = []
        self._ai_timer = QTimer(self)
        self._ai_timer.setSingleShot(True)
        self._ai_timer.setInterval(260)
        self._ai_timer.timeout.connect(self._ai_step)
        self._build()
        self.session.ensure_started()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(10)

        hud = make_panel("hud")
        hud_layout = QHBoxLayout(hud)
        hud_layout.setContentsMargins(14, 9, 14, 9)
        hud_layout.setSpacing(12)
        brand = QLabel("牌桌")
        brand.setObjectName("brandMark")
        hud_layout.addWidget(brand)
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
        table_grid.setContentsMargins(24, 18, 24, 18)
        table_grid.setSpacing(10)
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
        hand_layout.setContentsMargins(12, 10, 12, 10)
        hand_layout.setSpacing(7)
        hand_head = QHBoxLayout()
        self.hand_title = QLabel("你的手牌")
        self.hand_title.setObjectName("accentTitle")
        self.hand_counter = QLabel("")
        self.hand_counter.setObjectName("muted")
        hand_head.addWidget(self.hand_title)
        hand_head.addStretch(1)
        hand_head.addWidget(self.hand_counter)
        hand_layout.addLayout(hand_head)
        self.hand = HandWidget()
        self.hand.card_clicked.connect(self.toggle_card)
        hand_layout.addWidget(self.hand)
        layout.addWidget(hand_panel)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.play_button = button("出牌", self.play_selected, primary=True)
        self.pass_button = button("过牌", self.pass_turn)
        self.hint_button = button("提示", self.hint, role="infoButton")
        self.clear_button = button("清空选择", self.clear_selection, role="quietButton")
        self.next_button = button("下一局", self.next_game, primary=True)
        self.back_button = button("返回大厅", self.back_to_menu, role="quietButton")
        for item in (
            self.play_button,
            self.pass_button,
            self.hint_button,
            self.clear_button,
            self.next_button,
            self.back_button,
        ):
            actions.addWidget(item)
        layout.addLayout(actions)

        self.log = QLabel("准备开始")
        self.log.setObjectName("muted")
        self.log.setWordWrap(True)
        layout.addWidget(self.log)
        self._install_shortcuts()

    def _install_shortcuts(self) -> None:
        for key, handler in (
            ("Return", self.play_selected),
            ("Enter", self.play_selected),
            ("P", self.pass_turn),
            ("T", self.hint),
            ("N", self.next_game),
            ("Escape", self.back_to_menu),
            ("Backspace", self.clear_selection),
        ):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(handler)

    def refresh(self) -> None:
        state = self.session.ensure_started()
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
                state.turn_index == seat,
                ai_label,
            )
        self.me.update_state(
            self.session.human,
            len(state.hands[self.session.human]),
            self.session.human in state.finish_order,
            state.turn_index == self.session.human,
            "你",
        )
        self._refresh_status(state)
        self._refresh_hand(state)
        self.table.update_table(
            state,
            self.session.table_display_actions(),
            self.session.current_table_players(),
        )
        self.log.setText(self.session.last_action)
        human_turn = state.turn_index == self.session.human and not state.finished
        self.play_button.setEnabled(human_turn and bool(self.selected_indices))
        self.pass_button.setEnabled(human_turn and bool(state.table))
        self.hint_button.setEnabled(human_turn)
        self.clear_button.setEnabled(bool(self.selected_indices))
        self.next_button.setEnabled(state.finished and not state.match_finished)
        self.next_button.setText("比赛已结束" if state.match_finished else "下一局")

    def _refresh_status(self, state: GameState) -> None:
        wild = card_label(state.wild_card) if state.wild_card is not None else "无"
        levels = self.session.visible_team_levels()
        turn = SEAT_NAMES[state.turn_index]
        finished = " > ".join(SEAT_NAMES[p] for p in state.finish_order) or "-"
        if state.finished and state.match_finished and state.winner_team is not None:
            winner = "东西" if state.winner_team == 0 else "南北"
            suffix = f"比赛结束：{winner}方获胜"
        elif state.finished:
            suffix = f"本局结束，下一局级牌 {rank_value_label(self.session.next_round_level(state))}"
        elif state.turn_index == self.session.human:
            suffix = "轮到你行动"
        else:
            suffix = f"等待 {turn}家出牌"
        self.status.setText(
            f"级牌 {rank_value_label(state.level)}  ·  逢人配 {wild}  ·  当前 {turn}家  ·  "
            f"名次 {finished}  ·  {suffix}"
        )
        self.score_label.setText(
            f"东西 {rank_value_label(levels[0])}  /  南北 {rank_value_label(levels[1])}"
        )
        self.turn_label.setText("你的回合" if state.turn_index == self.session.human else f"{turn}家行动")

    def _refresh_hand(self, state: GameState) -> None:
        self.hand_cards = sort_cards_for_display(
            state.hands[self.session.human],
            level=state.level,
        )
        self.selected_indices = {
            index for index in self.selected_indices if index < len(self.hand_cards)
        }
        self.hand.set_cards(
            self.hand_cards,
            wild_card=state.wild_card,
            selected_indices=self.selected_indices,
        )
        self.hand_counter.setText(
            f"{len(self.hand_cards)} 张 · 已选 {len(self.selected_indices)} 张"
        )

    def toggle_card(self, index: int) -> None:
        self.session.reset_hint_cycle()
        if index in self.selected_indices:
            self.selected_indices.remove(index)
        else:
            self.selected_indices.add(index)
        self.refresh()

    def selected_cards(self) -> list:
        return [
            self.hand_cards[index]
            for index in sorted(self.selected_indices)
            if index < len(self.hand_cards)
        ]

    def play_selected(self) -> None:
        result = self.session.play_human_cards(self.selected_cards())
        if result.ok:
            self.selected_indices.clear()
        self.refresh()
        self.schedule_ai()

    def pass_turn(self) -> None:
        result = self.session.pass_human()
        if result.ok:
            self.selected_indices.clear()
        self.refresh()
        self.schedule_ai()

    def hint(self) -> None:
        result = self.session.hint_for_human()
        self.selected_indices = card_indices_for_selection(
            self.hand_cards,
            result.suggested_cards,
        )
        self.refresh()

    def clear_selection(self) -> None:
        self.session.reset_hint_cycle()
        self.selected_indices.clear()
        self.refresh()

    def next_game(self) -> None:
        result = self.session.start_next_game()
        if result.ok:
            self.selected_indices.clear()
        self.refresh()
        self.schedule_ai()

    def schedule_ai(self) -> None:
        state = self.session.ensure_started()
        if (
            self._main_window.stack.currentWidget() is not self
            or state.finished
            or state.turn_index == self.session.human
            or self._ai_timer.isActive()
        ):
            return
        self._ai_timer.start()

    def _ai_step(self) -> None:
        if self._main_window.stack.currentWidget() is not self:
            return
        state = self.session.ensure_started()
        if state.finished or state.turn_index == self.session.human:
            self.refresh()
            return
        result = self.session.step_ai()
        self.refresh()
        if result.ok:
            self.schedule_ai()

    def deactivate(self) -> None:
        """Stop deferred work when this table is no longer visible."""
        self._ai_timer.stop()

    def back_to_menu(self) -> None:
        self.deactivate()
        self._main_window.save_current_game()
        self._main_window.show_menu()


class GuandanMainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("掼蛋 GUI · v0.8.0-beta.3")
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
            old = self.stack.widget(0)
            if old is None or old is page:
                break
            self.stack.removeWidget(old)
            old.deleteLater()

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

    def save_current_game(self) -> None:
        if self.game_page is None:
            return
        state = self.game_page.session.ensure_started()
        if state.finished:
            self.game_page.session.save_finished_if_needed()
        else:
            try:
                self.game_page.session.save_unfinished()
            except Exception as exc:
                QMessageBox.warning(self, "保存失败", str(exc))

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.game_page is not None:
            self.game_page.deactivate()
        self.save_current_game()
        event.accept()


def run_gui() -> int:
    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication(sys.argv)
    assert isinstance(app, QApplication)
    app.setStyleSheet(APP_QSS)
    window = GuandanMainWindow()
    window.show()
    if owns_app:
        return int(app.exec())
    return 0
