"""PySide6 desktop GUI for the local Guandan game."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QTextCursor,
)
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..engine.card import Card
from ..engine.events import Event
from ..engine.state import SEAT_NAMES, GameState, IllegalPlayError
from ..ui.content import GAME_RULES_TEXT, GUI_CONTROLS_TEXT
from ..ui.formatting import card_label, pattern_type_label
from ..ui.history import history_statistics_text
from ..ui.replay import ReplayCursor, replay_event_text, replay_state_text
from .cards import MiniCardStrip
from .widgets import button, make_panel, page_header

if TYPE_CHECKING:
    from .window import GuandanMainWindow


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
