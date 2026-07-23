"""Frontend-neutral text for event-backed game replay."""
from __future__ import annotations

from ..engine.events import (
    Claim,
    Drift,
    Event,
    GameOver,
    LevelUp,
    Pass,
    ShuffleDeal,
    TributeResisted,
    TributeReturned,
    TributeSent,
    TurnPlayed,
)
from ..engine.replay import replay_event_states
from ..engine.state import SEAT_NAMES, GameState
from .formatting import card_label, pattern_type_label, rank_value_label


class ReplayCursor:
    """Validated replay timeline with O(1) state lookup while navigating."""

    def __init__(self, events: list[Event]) -> None:
        self.events = tuple(events)
        self.states = replay_event_states(self.events)
        self.index = len(self.events) - 1

    @property
    def state(self) -> GameState:
        return self.states[self.index]

    def set_index(self, index: int) -> int:
        self.index = max(0, min(index, len(self.events) - 1))
        return self.index


def replay_event_text(event: Event) -> str:
    """Format one persisted event for a compact replay timeline."""
    if isinstance(event, ShuffleDeal):
        return f"发牌 · 级牌 {rank_value_label(event.level)} · {SEAT_NAMES[event.first_player]}家先手"
    if isinstance(event, TurnPlayed):
        cards = " ".join(card_label(card, include_symbol=False) for card in event.pattern.cards)
        return f"{SEAT_NAMES[event.player]}家出 {pattern_type_label(event.pattern.type)} · {cards}"
    if isinstance(event, Pass):
        return f"{SEAT_NAMES[event.player]}家过牌"
    if isinstance(event, Claim):
        return f"{SEAT_NAMES[event.player]}家报 {event.count} 张"
    if isinstance(event, TributeSent):
        return f"{SEAT_NAMES[event.from_player]}家进贡 {card_label(event.card)} 给 {SEAT_NAMES[event.to_player]}家"
    if isinstance(event, TributeReturned):
        return f"{SEAT_NAMES[event.from_player]}家还贡 {card_label(event.card)} 给 {SEAT_NAMES[event.to_player]}家"
    if isinstance(event, TributeResisted):
        return f"{SEAT_NAMES[event.player]}家抗贡"
    if isinstance(event, Drift):
        return f"{SEAT_NAMES[event.player]}家漂牌"
    if isinstance(event, LevelUp):
        team = "东西" if event.team == 0 else "南北"
        return f"{team}方升级至 {rank_value_label(event.new_level)}"
    if isinstance(event, GameOver):
        order = " > ".join(SEAT_NAMES[player] for player in event.finish_order)
        return f"本局结束 · {order}"
    return type(event).__name__


def replay_state_text(state: GameState) -> str:
    """Summarize the state reconstructed at the current replay event."""
    hands = " / ".join(
        f"{SEAT_NAMES[player]} {len(hand)}" for player, hand in enumerate(state.hands)
    )
    table = "--"
    if state.table:
        top = state.table[-1]
        cards = " ".join(card_label(card, include_symbol=False) for card in top.cards)
        table = f"{pattern_type_label(top.type)} · {cards}"
    finish = " > ".join(SEAT_NAMES[player] for player in state.finish_order) or "--"
    result = "本局进行中"
    if state.finished:
        result = "比赛结束" if state.match_finished else "本局结束"
    return (
        f"{result} · 当前 {SEAT_NAMES[state.turn_index]}家 · 桌面 {table} · "
        f"手牌 {hands} · 名次 {finish}"
    )


__all__ = ["ReplayCursor", "replay_event_text", "replay_state_text"]
