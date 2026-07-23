"""PySide6 desktop GUI for the local Guandan game."""
from __future__ import annotations

import sys
from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QFont, QKeySequence, QShortcut
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
from ..ui.session import GameSession
from .cards import HandWidget

APP_QSS = """
QWidget {
    font-family: "PingFang SC", "Microsoft YaHei", Arial, sans-serif;
    color: #f4f1de;
}
QMainWindow, QWidget#root {
    background: #0f1713;
}
QFrame#panel {
    background: #16231d;
    border: 1px solid #40594b;
    border-radius: 8px;
}
QFrame#tablePanel {
    background: #123c2c;
    border: 2px solid #d4af37;
    border-radius: 8px;
}
QLabel#title {
    color: #f8d46b;
    font-size: 36px;
    font-weight: 900;
}
QLabel#subtitle, QLabel#muted {
    color: #a7c0ad;
}
QLabel#sectionTitle {
    color: #f8d46b;
    font-size: 20px;
    font-weight: 800;
}
QLabel#statusBar {
    background: #16231d;
    border: 1px solid #40594b;
    border-radius: 8px;
    padding: 10px 14px;
    color: #f4f1de;
}
QPushButton {
    background: #23372e;
    border: 1px solid #587460;
    border-radius: 8px;
    padding: 10px 14px;
    font-weight: 700;
}
QPushButton:hover {
    background: #2d473a;
    border-color: #d4af37;
}
QPushButton:pressed {
    background: #1d2d26;
}
QPushButton:disabled {
    color: #708476;
    background: #17231d;
    border-color: #2f4237;
}
QPushButton#primaryButton {
    background: #d4af37;
    color: #132019;
    border-color: #f8d46b;
}
QPushButton#dangerButton {
    background: #7f1d1d;
    border-color: #ef4444;
}
QTableWidget {
    background: #122019;
    border: 1px solid #40594b;
    gridline-color: #334b3d;
}
QHeaderView::section {
    background: #23372e;
    color: #f8d46b;
    padding: 6px;
    border: 0;
}
QTextBrowser {
    background: #122019;
    border: 1px solid #40594b;
    border-radius: 8px;
    padding: 12px;
}
"""


def button(text: str, callback: Callable[[], None], *, primary: bool = False) -> QPushButton:
    btn = QPushButton(text)
    if primary:
        btn.setObjectName("primaryButton")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.clicked.connect(callback)
    return btn


def make_panel(object_name: str = "panel") -> QFrame:
    frame = QFrame()
    frame.setObjectName(object_name)
    frame.setFrameShape(QFrame.Shape.StyledPanel)
    return frame


class MenuPage(QWidget):
    def __init__(self, window: "GuandanMainWindow") -> None:
        super().__init__()
        self.window = window
        layout = QVBoxLayout(self)
        layout.setContentsMargins(64, 48, 64, 48)
        layout.setSpacing(24)

        title = QLabel("掼蛋")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle = QLabel("本地四人牌局 · 桌面 GUI / TUI / CLI")
        subtitle.setObjectName("subtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        body = QHBoxLayout()
        body.setSpacing(24)
        layout.addLayout(body, 1)

        table_panel = make_panel()
        table_layout = QVBoxLayout(table_panel)
        table_layout.setSpacing(16)
        seat_title = QLabel("座位关系")
        seat_title.setObjectName("sectionTitle")
        seat_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        seat_map = QLabel("西\n\n南          北\n\n东")
        seat_map.setAlignment(Qt.AlignmentFlag.AlignCenter)
        seat_map.setFont(QFont("Menlo", 24, QFont.Weight.Bold))
        note = QLabel("你默认坐东，对家在西，右手为北，左手为南。")
        note.setObjectName("muted")
        note.setWordWrap(True)
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        table_layout.addStretch(1)
        table_layout.addWidget(seat_title)
        table_layout.addWidget(seat_map)
        table_layout.addWidget(note)
        table_layout.addStretch(1)
        body.addWidget(table_panel, 2)

        action_panel = make_panel()
        action_layout = QVBoxLayout(action_panel)
        action_layout.setSpacing(14)
        action_title = QLabel("牌局大厅")
        action_title.setObjectName("sectionTitle")
        action_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        action_layout.addWidget(action_title)
        action_layout.addWidget(button("开始新局", window.show_difficulty, primary=True))
        action_layout.addWidget(button("继续存档", window.show_load))
        action_layout.addWidget(button("历史战绩", window.show_history))
        action_layout.addWidget(button("规则说明", window.show_rules))
        action_layout.addStretch(1)
        action_layout.addWidget(button("退出", window.close))
        body.addWidget(action_panel, 1)


class DifficultyPage(QWidget):
    def __init__(self, window: "GuandanMainWindow") -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(80, 56, 80, 56)
        layout.setSpacing(18)
        title = QLabel("选择 AI 难度")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(self._summary_panel())

        for index, (name, desc) in enumerate(DIFFICULTIES):
            layout.addWidget(
                button(
                    f"{index + 1}. {name}  ·  {desc}",
                    self._difficulty_callback(window, index),
                    primary=index == 1,
                )
            )
        layout.addStretch(1)
        layout.addWidget(button("返回大厅", window.show_menu))

    def _summary_panel(self) -> QFrame:
        panel = make_panel()
        layout = QVBoxLayout(panel)
        info = QLabel("首局级牌 2。更高难度会更重视牌型结构、协作和残局搜索。")
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
        self.window = window
        layout = QVBoxLayout(self)
        layout.setContentsMargins(80, 56, 80, 56)
        layout.setSpacing(16)
        title = QLabel("继续存档")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        self.content = QVBoxLayout()
        layout.addLayout(self.content)
        layout.addStretch(1)
        layout.addWidget(button("返回大厅", window.show_menu))
        self.refresh()

    def refresh(self) -> None:
        while self.content.count():
            item = self.content.takeAt(0)
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
            panel.layout().addWidget(button("删除存档", self._delete_save))
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
        self.window.start_game(
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
        self.window = window
        self.entries: list[dict] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 40, 48, 40)
        layout.setSpacing(16)
        title = QLabel("历史战绩")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        self.table = QTableWidget(0, len(HISTORY_COLUMNS))
        self.table.setHorizontalHeaderLabels(list(HISTORY_COLUMNS))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.cellDoubleClicked.connect(self.open_selected_replay)
        layout.addWidget(self.table, 1)
        layout.addWidget(button("查看回放", self.open_selected_replay, primary=True))
        layout.addWidget(button("返回大厅", window.show_menu))
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
        self.window.show_replay(detail)


class ReplayPage(QWidget):
    """Event-backed historical replay with deterministic step navigation."""

    def __init__(self, window: "GuandanMainWindow", history: dict) -> None:
        super().__init__()
        self.window = window
        self.history = history
        self.events: list[Event] = list(history.get("events", []))
        if not self.events:
            raise ValueError("history has no events")
        try:
            self.cursor = ReplayCursor(self.events)
        except (IllegalPlayError, ValueError) as exc:
            raise ValueError("history event stream cannot be replayed") from exc

        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 40, 48, 40)
        layout.setSpacing(14)
        title = QLabel("对局回放")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

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
        layout.addWidget(button("返回战绩", window.show_history))
        self.refresh()

    def set_event_index(self, index: int) -> None:
        self.cursor.set_index(index)
        self.refresh()

    @property
    def event_index(self) -> int:
        return self.cursor.index

    def refresh(self) -> None:
        state = self.cursor.state
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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 40, 48, 40)
        layout.setSpacing(16)
        title = QLabel("规则说明")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        browser = QTextBrowser()
        browser.setPlainText(RULES_TEXT)
        layout.addWidget(browser, 1)
        layout.addWidget(button("返回大厅", window.show_menu))


class SeatPanel(QFrame):
    def __init__(self, title: str) -> None:
        super().__init__()
        self.setObjectName("panel")
        self.setMinimumHeight(86)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        self.title = QLabel(title)
        self.title.setObjectName("sectionTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail = QLabel("")
        self.detail.setObjectName("muted")
        self.detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title)
        layout.addWidget(self.detail)

    def update_state(self, seat: int, hand_size: int, finished: bool, is_turn: bool, ai_name: str) -> None:
        marker = " · 行动中" if is_turn else ""
        self.title.setText(f"{SEAT_NAMES[seat]}家{marker}")
        done = "已出完" if finished else f"{hand_size} 张"
        self.detail.setText(f"{ai_name} · {done}")


class TablePanel(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("tablePanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)
        self.title = QLabel("当前轮")
        self.title.setObjectName("sectionTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title)
        self.rows: dict[int, QLabel] = {}
        for seat in (0, 3, 2, 1):
            label = QLabel()
            label.setWordWrap(True)
            label.setMinimumHeight(36)
            label.setStyleSheet("background: rgba(255, 255, 255, 0.06); border-radius: 6px; padding: 6px;")
            self.rows[seat] = label
            layout.addWidget(label)
        layout.addStretch(1)

    def update_table(
        self,
        state: GameState,
        actions: dict[int, tuple[str, Pattern | None]],
        table_players: list[int],
    ) -> None:
        top_player = table_players[-1] if state.table and table_players else None
        title = "当前轮"
        if top_player is not None:
            title += f" · 最大 {SEAT_NAMES[top_player]}家"
        self.title.setText(title)
        for seat, label in self.rows.items():
            marker = "最大 · " if seat == top_player else ""
            action = actions.get(seat)
            if action is None:
                label.setText(f"{SEAT_NAMES[seat]}：{marker}--")
                continue
            kind, pattern = action
            if kind == "pass":
                label.setText(f"{SEAT_NAMES[seat]}：{marker}过牌")
            elif pattern is not None:
                cards = " ".join(card_label(card, include_symbol=False) for card in pattern.cards)
                label.setText(f"{SEAT_NAMES[seat]}：{marker}{pattern_type_label(pattern.type)} · {cards}")
            else:
                label.setText(f"{SEAT_NAMES[seat]}：{marker}--")


class GamePage(QWidget):
    def __init__(self, window: "GuandanMainWindow", session: GameSession) -> None:
        super().__init__()
        self.window = window
        self.session = session
        self.selected_indices: set[int] = set()
        self.hand_cards: list[Card] = []
        self._ai_timer_active = False
        self._build()
        self.session.ensure_started()
        self.refresh()
        self.schedule_ai()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)
        self.status = QLabel()
        self.status.setObjectName("statusBar")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        table_grid = QGridLayout()
        table_grid.setSpacing(10)
        self.opposite = SeatPanel("")
        self.left = SeatPanel("")
        self.right = SeatPanel("")
        self.me = SeatPanel("")
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
        layout.addLayout(table_grid, 1)

        hand_panel = make_panel()
        hand_layout = QVBoxLayout(hand_panel)
        hand_head = QHBoxLayout()
        self.hand_title = QLabel("你的手牌")
        self.hand_title.setObjectName("sectionTitle")
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
        actions.setSpacing(10)
        self.play_button = button("出牌", self.play_selected, primary=True)
        self.pass_button = button("过牌", self.pass_turn)
        self.hint_button = button("提示", self.hint)
        self.clear_button = button("清空选择", self.clear_selection)
        self.next_button = button("下一局", self.next_game, primary=True)
        self.back_button = button("返回大厅", self.back_to_menu)
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
        self.log.setObjectName("statusBar")
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
        self.play_button.setEnabled(human_turn)
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
            f"级牌 {rank_value_label(state.level)} · 逢人配 {wild} · 当前 {turn}家 · "
            f"东西 {rank_value_label(levels[0])} / 南北 {rank_value_label(levels[1])} · "
            f"名次 {finished} · {suffix}"
        )

    def _refresh_hand(self, state: GameState) -> None:
        from ..engine.hand import sort_cards

        self.hand_cards = sort_cards(state.hands[self.session.human])
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
        self.session.hint_for_human()
        self.refresh()

    def clear_selection(self) -> None:
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
        if state.finished or state.turn_index == self.session.human or self._ai_timer_active:
            return
        self._ai_timer_active = True
        QTimer.singleShot(260, self._ai_step)

    def _ai_step(self) -> None:
        self._ai_timer_active = False
        state = self.session.ensure_started()
        if state.finished or state.turn_index == self.session.human:
            self.refresh()
            return
        self.session.step_ai()
        self.refresh()
        self.schedule_ai()

    def back_to_menu(self) -> None:
        self.window.save_current_game()
        self.window.show_menu()


class GuandanMainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("掼蛋 GUI · v0.8.0-beta.1")
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
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)
        while self.stack.count() > 3:
            old = self.stack.widget(0)
            if old is page:
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
        self.save_current_game()
        event.accept()


def run_gui() -> int:
    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication(sys.argv)
    app.setStyleSheet(APP_QSS)
    window = GuandanMainWindow()
    window.show()
    if owns_app:
        return int(app.exec())
    return 0
