"""TUI screen for stepping through a completed game's event stream."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

from ...engine.events import Event
from ...engine.state import SEAT_NAMES
from ...ui.formatting import card_label
from ...ui.history import history_statistics_text
from ...ui.replay import ReplayCursor, replay_event_text, replay_state_text


class ReplayScreen(Screen):
    """Show an event timeline and the reconstructed state at each step."""

    CSS = """
    ReplayScreen {
        background: #101512;
        color: #eee8d9;
    }
    #replay-shell {
        width: 100%;
        height: 1fr;
        padding: 1 2;
    }
    #replay-title {
        height: 1;
        text-align: center;
        color: #ffd978;
        text-style: bold;
    }
    #replay-meta { height: 2; text-align: center; color: #9fb7a6; }
    #replay-state {
        height: 3;
        padding: 0 1;
        border: tall #344237;
        background: #121a17;
    }
    #replay-table {
        height: 10;
        padding: 0 1;
        border: tall #60765f;
        background: #111815;
        overflow: auto auto;
    }
    #replay-scroll {
        height: 1fr;
        min-height: 6;
        padding: 0 1;
        border: tall #344237;
    }
    #replay-controls { height: 3; }
    #replay-controls Button { width: 18; margin: 0 1; }
    #btn-replay-back { width: 28; margin-top: 1; }
    """

    BINDINGS = [
        ("left", "previous", "上一步"),
        ("right", "next", "下一步"),
        ("home", "first", "首步"),
        ("end", "last", "末步"),
        ("space", "toggle_auto", "自动播放"),
        ("escape", "back", "返回战绩"),
    ]

    def __init__(self, history: dict) -> None:
        super().__init__()
        self._history = history
        self._events: list[Event] = list(history.get("events", []))
        if not self._events:
            raise ValueError("history has no events")
        self._cursor = ReplayCursor(self._events)
        self._autoplay = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="replay-shell"):
            yield Static("🔁 对局回放", id="replay-title")
            yield Static("", id="replay-meta")
            yield Static("", id="replay-state")
            yield Static("", id="replay-table")
            with VerticalScroll(id="replay-scroll"):
                yield Static("", id="replay-timeline")
            with Center():
                with Horizontal(id="replay-controls"):
                    yield Button("首步", id="btn-replay-first")
                    yield Button("上一步", id="btn-replay-previous")
                    yield Button("自动播放", id="btn-replay-auto")
                    yield Button("下一步", id="btn-replay-next", variant="primary")
                    yield Button("末步", id="btn-replay-last")
            with Center():
                yield Button("← 返回战绩", id="btn-replay-back")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#replay-title", Static).styles.text_style = "bold"
        self.query_one("#replay-title", Static).styles.color = "yellow"
        self._refresh()

    def set_event_index(self, index: int) -> None:
        self._cursor.set_index(index)
        self._refresh()

    @property
    def _event_index(self) -> int:
        return self._cursor.index

    def action_first(self) -> None:
        self.set_event_index(0)

    def action_previous(self) -> None:
        self.set_event_index(self._event_index - 1)

    def action_next(self) -> None:
        self.set_event_index(self._event_index + 1)

    def action_last(self) -> None:
        self.set_event_index(len(self._events) - 1)

    def action_toggle_auto(self) -> None:
        self._autoplay = not self._autoplay
        if self._autoplay:
            if self._event_index == len(self._events) - 1:
                self._cursor.set_index(0)
                self._refresh()
            self.set_timer(0.7, self._auto_step)
        self._refresh()

    def _auto_step(self) -> None:
        if not self._autoplay:
            return
        if self._event_index >= len(self._events) - 1:
            self._autoplay = False
            self._refresh()
            return
        self.set_event_index(self._event_index + 1)
        self.set_timer(0.7, self._auto_step)

    def action_back(self) -> None:
        self.app.pop_screen()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        actions = {
            "btn-replay-first": self.action_first,
            "btn-replay-previous": self.action_previous,
            "btn-replay-auto": self.action_toggle_auto,
            "btn-replay-next": self.action_next,
            "btn-replay-last": self.action_last,
            "btn-replay-back": self.action_back,
        }
        button_id = event.button.id
        if button_id is None:
            return
        action = actions.get(button_id)
        if action is not None:
            action()

    def _refresh(self) -> None:
        state = self._cursor.state
        self.query_one("#replay-meta", Static).update(
            f"{self._history.get('played_at', '-')[:19]} · "
            f"第 {self._event_index + 1} / {len(self._events)} 个事件\n"
            f"{history_statistics_text(self._history)}"
        )
        self.query_one("#replay-state", Static).update(replay_state_text(state))
        hands = []
        for seat, cards in enumerate(state.hands):
            card_text = " ".join(card_label(card) for card in cards) or "已出完"
            hands.append(f"{SEAT_NAMES[seat]}家 {len(cards):2d} 张 | {card_text}")
        table_text = "等待先手"
        if state.table:
            table_text = " ".join(card_label(card) for card in state.table[-1].cards)
        self.query_one("#replay-table", Static).update(
            "四家手牌\n" + "\n".join(hands) + f"\n当前桌面 | {table_text}"
        )
        timeline = "\n".join(
            f"{'▶' if index == self._event_index else ' '} {index + 1:>3}. "
            f"{replay_event_text(event)}"
            for index, event in enumerate(self._events)
        )
        self.query_one("#replay-timeline", Static).update(timeline)
        self.query_one("#btn-replay-first", Button).disabled = self._event_index == 0
        self.query_one("#btn-replay-previous", Button).disabled = self._event_index == 0
        self.query_one("#btn-replay-next", Button).disabled = self._event_index == len(self._events) - 1
        self.query_one("#btn-replay-last", Button).disabled = self._event_index == len(self._events) - 1
        self.query_one("#btn-replay-auto", Button).label = (
            "暂停" if self._autoplay else "自动播放"
        )


__all__ = ["ReplayScreen"]
