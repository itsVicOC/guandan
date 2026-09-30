"""Frontend-neutral playable game session.

The engine owns the rules. This layer owns UI-facing orchestration: starting and
continuing games, driving AI turns, applying tribute for the next game, and
persisting save/history records.
"""
from __future__ import annotations

import copy
import random
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

from ..ai import AINotImplementedError, make_strategy, play_or_pass
from ..ai.candidates import enumerate_legal_patterns, greedy_pattern_key
from ..ai.strategy import AIStrategy
from ..ai.tribute import choose_ai_tribute_cards
from ..engine.card import Card, Suit
from ..engine.events import (
    Event,
    Pass,
    ShuffleDeal,
    TributeResisted,
    TributeReturned,
    TributeSent,
    TurnPlayed,
)
from ..engine.hand import Pattern
from ..engine.replay import replay_events
from ..engine.rules.patterns import find_complete_pattern
from ..engine.rules.tributes import (
    TributeFlowResult,
    apply_tribute_flow,
    legal_return_cards,
    legal_tribute_cards,
)
from ..engine.state import (
    LEGACY_RULESET_VERSION,
    SEAT_NAMES,
    GameState,
    IllegalPlayError,
    make_initial_state,
    pass_turn,
    play_pattern,
    team_of,
)
from ..engine.trick import (
    current_table_players,
    last_player_of_pattern,
    locked_passed_players,
)
from ..storage import (
    begin_settlement,
    delete_savegame,
    deserialize_events,
    end_settlement,
    record_match_statistics,
    record_round_statistics,
    restore_game_state,
    save_game,
    save_history,
    serialize_events,
    update_profile,
)
from .formatting import (
    card_label,
    cards_text,
    pattern_type_label,
    play_rejection_message,
    rank_value_label,
)


@dataclass(frozen=True)
class SessionAction:
    """Result of a UI-triggered game action."""

    ok: bool
    message: str
    suggested_cards: tuple[Card, ...] = ()


@dataclass(frozen=True)
class PendingCardChoice:
    """A human decision required before the next round can start."""

    kind: Literal["tribute", "return"]
    cards: tuple[Card, ...]


@dataclass
class PendingNextGame:
    """Prepared next-round state that has not replaced the completed round yet."""

    state: GameState
    display_state: GameState
    finish_order: tuple[int, ...]
    game_id: str
    seed: int
    round_index: int
    started_at: float
    elapsed_seconds: int = 0
    preview: TributeFlowResult | None = None
    human_choice: PendingCardChoice | None = None


def card_indices_for_selection(
    hand_cards: list[Card],
    selected_cards: tuple[Card, ...],
) -> set[int]:
    """Map a card multiset to stable positions in a rendered hand."""
    remaining = Counter(selected_cards)
    indices: set[int] = set()
    for index, card in enumerate(hand_cards):
        if remaining[card] <= 0:
            continue
        indices.add(index)
        remaining[card] -= 1
    return indices


def wild_card_from_hands(level: int, hands: list[list[Card]]) -> Card | None:
    for hand in hands:
        for card in hand:
            if card.rank == level and card.suit == Suit.HEARTS:
                return card
    return None


class GameSession:
    """Mutable UI session wrapped around a `GameState`."""

    def __init__(
        self,
        *,
        difficulty: int = 2,
        level: int = 2,
        human: int = 0,
        existing_state: GameState | None = None,
        game_id: str | None = None,
        match_id: str | None = None,
        round_index: int = 1,
        elapsed_seconds: int = 0,
        seed: int | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.difficulty = difficulty
        self.level = level
        self.human = human
        self.state: GameState | None = existing_state
        try:
            self.strategy: AIStrategy = make_strategy(difficulty)
        except AINotImplementedError:
            self.strategy = make_strategy(1)
            self.difficulty = 1
        self.ai_rng = rng or random.Random()
        self.game_id = game_id or self._new_game_id()
        self.match_id = match_id or self._new_match_id()
        self.round_index = max(1, round_index)
        self.seed = seed if seed is not None else random.randint(1, 10000)
        self.start_time = time.time()
        self._elapsed_before_start = max(0, elapsed_seconds)
        self.game_saved = False
        self.last_action = "准备开始"
        self.displayed_table_actions: dict[int, tuple[str, Pattern | None]] = {}
        self.last_display_turn: int | None = None
        self._trick_history_key: tuple | None = None
        self._completed_tricks: list[list[Event]] = []
        self._active_trick: list[Event] = []
        self._hint_state_key: tuple[object, ...] | None = None
        self._hint_candidates: tuple[Pattern, ...] = ()
        self._hint_index = 0
        self._pending_next_game: PendingNextGame | None = None
        self._save_revision = 0
        self._last_save_error: Exception | None = None

    @classmethod
    def from_savegame(cls, data: dict[str, Any]) -> GameSession:
        """Restore the complete frontend session, including an unconfirmed deal."""
        state = restore_game_state(data)
        metadata = data["metadata"]
        session = cls(
            difficulty=next((d for d in metadata["ai_difficulties"] if d is not None), 2),
            level=state.level, human=metadata["player_seat"], existing_state=state,
            game_id=data["game_id"], match_id=data["match_id"],
            round_index=data["round_index"], elapsed_seconds=data["elapsed_seconds"],
            seed=metadata["seed"],
        )
        session._save_revision = data.get("revision", 0)
        pending = data.get("pending_round")
        if pending is not None:
            previous = replay_events(
                deserialize_events(pending["previous_events"]),
                ruleset_version=state.ruleset_version,
            )
            session._pending_next_game = PendingNextGame(
                state=state, display_state=state, finish_order=tuple(previous.finish_order),
                game_id=session.game_id, seed=session.seed, round_index=session.round_index,
                started_at=time.monotonic(), elapsed_seconds=data["elapsed_seconds"],
            )
            session.state = previous
            session.game_id = pending["previous_game_id"]
            session.round_index -= 1
            session.game_saved = True
            session.last_action = "下一局已恢复，请完成贡还牌"
            if pending["tribute_started"]:
                session.begin_next_game_tribute()
        return session

    @staticmethod
    def _new_game_id() -> str:
        return f"game_{uuid.uuid4().hex}"

    @staticmethod
    def _new_match_id() -> str:
        return f"match_{uuid.uuid4().hex}"

    def current_elapsed_seconds(self) -> int:
        """Return persisted and current-process elapsed time for this round."""
        return self._elapsed_before_start + max(0, int(time.time() - self.start_time))

    def ensure_started(self) -> GameState:
        if self.state is None:
            first_player = random.randint(0, 3)
            self.state = make_initial_state(
                level=self.level,
                first_player=first_player,
                seed=self.seed,
            )
            self.last_action = (
                f"第 {self.round_index} 局开始：本局级牌 {rank_value_label(self.state.level)}，"
                f"{self.tribute_notice()}；{SEAT_NAMES[first_player]}家先手"
            )
        else:
            self.level = self.state.level
        return self.state

    def require_state(self) -> GameState:
        return self.ensure_started()

    def visual_seats(self) -> dict[str, int]:
        """Seats around the table from the human player's point of view."""
        return {
            "left": (self.human + 1) % 4,
            "opposite": (self.human + 2) % 4,
            "right": (self.human - 1) % 4,
        }

    def display_state(self) -> GameState:
        """Return the dealt next round while its tribute phase is pending."""
        if self._pending_next_game is not None:
            return self._pending_next_game.display_state
        return self.require_state()

    def is_next_game_pending(self) -> bool:
        return self._pending_next_game is not None

    def visible_partner_hand(self) -> tuple[Card, ...] | None:
        """Reveal the partner's remaining cards after the human has gone out."""
        if self.is_next_game_pending():
            return None
        state = self.require_state()
        if self.human not in state.finish_order:
            return None
        return tuple(state.hands[self.visual_seats()["opposite"]])

    def current_table_players(self) -> list[int]:
        return current_table_players(self.display_state())

    def locked_passed_players(self) -> list[int]:
        return locked_passed_players(self.display_state())

    def tribute_events(self) -> tuple[Event, ...]:
        """Return public tribute events that remain visible for this round."""
        return tuple(
            event
            for event in self.display_state().history
            if isinstance(event, (TributeSent, TributeReturned, TributeResisted))
        )

    def tribute_notice(self) -> str:
        """Describe the public tribute result, including rounds without an exchange."""
        events = self.tribute_events()
        pending = self.is_next_game_pending()
        if not events:
            if pending:
                return "本局贡还牌 · 正在确认，开局前公布结果"
            if self.round_index == 1:
                return "本局贡还牌 · 首局无需贡还牌"
            return "本局贡还牌 · 本局没有贡还牌"

        resisted = [event for event in events if isinstance(event, TributeResisted)]
        if resisted:
            players = "、".join(f"{SEAT_NAMES[event.player]}家" for event in resisted)
            detail = f"{players}抗贡，本局没有换牌"
            participants = {event.player for event in resisted}
        else:
            actions = []
            participants = set()
            for event in events:
                if isinstance(event, TributeSent):
                    verb = "进贡"
                elif isinstance(event, TributeReturned):
                    verb = "还贡"
                else:
                    continue
                participants.update((event.from_player, event.to_player))
                actions.append(
                    f"{SEAT_NAMES[event.from_player]}家→{SEAT_NAMES[event.to_player]}家"
                    f"{verb} {card_label(event.card)}"
                )
            detail = "；".join(actions)

        if pending:
            return f"本局贡还牌进行中 · {detail}；待确认最终结果"
        participation = "你参与了贡还牌" if self.human in participants else "你未参与贡还牌"
        return f"本局贡还牌 · {detail}；{participation}"

    def table_display_actions(
        self,
        *,
        preserve_completed_trick: bool = False,
    ) -> dict[int, tuple[str, Pattern | None]]:
        """Display public actions; the GUI preserves each seat's latest action.

        The desktop GUI opts into ``preserve_completed_trick`` so a collected
        trick remains readable during the pause before the next lead.  The TUI
        keeps its compact, immediate-clearing behavior.
        """
        if self.is_next_game_pending():
            return {}
        state = self.display_state()
        if preserve_completed_trick:
            self._index_public_tricks()
            events = self._active_trick
            if not events and self._completed_tricks:
                events = self._completed_tricks[-1]
            # Replace the whole snapshot, including on a new lead. A previous
            # pass is historical information, not a lock on the next response.
            return {
                event.player: ("play", event.pattern) if isinstance(event, TurnPlayed)
                else ("pass", None)
                for event in events if isinstance(event, (TurnPlayed, Pass))
            }
        if state.finished:
            self.displayed_table_actions.clear()
            self.last_display_turn = None
            return {}

        if self.last_display_turn != state.turn_index:
            self.displayed_table_actions.pop(state.turn_index, None)
            self.last_display_turn = state.turn_index

        # 新规则中新的压牌会使此前的“过”失效；桌面也不能继续把它显示
        # 成当前桌顶的过牌。旧局回放仍保留旧规则的锁定标记。
        if state.table and state.ruleset_version != LEGACY_RULESET_VERSION:
            for player, (kind, _) in list(self.displayed_table_actions.items()):
                if kind == "pass" and player not in state.passed_players:
                    self.displayed_table_actions.pop(player)

        for player, pattern in zip(self.current_table_players(), state.table):
            self.displayed_table_actions[player] = ("play", pattern)
        for player in self.locked_passed_players():
            self.displayed_table_actions[player] = ("pass", None)

        return dict(self.displayed_table_actions)

    def _index_public_tricks(self) -> None:
        """Index public events without replaying deals or relying on UI refreshes.

        Hand-remaining counts also cover restored/synthetic snapshots whose deal
        cannot be replayed. A trick closes when all unfinished non-top seats have
        passed; a third finisher ends the game without collecting the last trick.
        """
        state = self.require_state()
        finish_events = {
            event.player for event in state.history
            if isinstance(event, TurnPlayed) and event.hand_remaining == 0
        }
        initially_finished = frozenset(
            seat for seat in state.finish_order
            if not state.hands[seat] and seat not in finish_events
        )
        key = (self.game_id, tuple(state.history), state.ruleset_version, initially_finished)
        if key == self._trick_history_key:
            return
        completed: list[list[Event]] = []
        active: list[Event] = []
        finished = set(initially_finished)
        passed: set[int] = set()
        top: int | None = None
        for event in state.history:
            if not isinstance(event, (TurnPlayed, Pass)):
                continue
            active.append(event)
            if isinstance(event, TurnPlayed):
                top = event.player
                if state.ruleset_version != LEGACY_RULESET_VERSION:
                    passed.clear()
                if event.hand_remaining == 0:
                    finished.add(event.player)
            else:
                passed.add(event.player)
            responders = set(range(4)) - finished - {top}
            if top is not None and len(finished) < 3 and responders <= passed:
                completed.append(active)
                active = []
                passed.clear()
                top = None
        self._trick_history_key = key
        self._completed_tricks = completed
        self._active_trick = active

    def previous_completed_trick(self) -> list[Event]:
        """Return the public actions in the last collected trick, including its closing pass."""
        state = self.require_state()
        if state.trick_number < 1:
            return []
        self._index_public_tricks()
        return list(self._completed_tricks[-1]) if self._completed_tricks else []

    def last_player_of(self, pattern: Pattern) -> int:
        return last_player_of_pattern(self.require_state(), pattern, default=0) or 0

    def play_human_cards(self, selected: list[Card]) -> SessionAction:
        state = self.require_state()
        if state.finished:
            return SessionAction(False, "本局已经结束")
        if state.turn_index != self.human:
            return SessionAction(False, f"还没轮到你，当前是 {SEAT_NAMES[state.turn_index]}家")
        if not selected:
            self.last_action = "未选牌"
            return SessionAction(False, self.last_action)

        pattern = find_complete_pattern(selected, state.wild_card)
        if pattern is None:
            self.last_action = f"这组牌不是合法牌型：你选 [{cards_text(selected)}]"
            return SessionAction(False, self.last_action)

        try:
            play_pattern(state, self.human, pattern)
        except IllegalPlayError as exc:
            if state.table:
                self.last_action = play_rejection_message(selected, pattern, state.table[-1], state.level)
            else:
                self.last_action = f"非法：{exc}"
            return SessionAction(False, self.last_action)

        cards = " ".join(card_label(card) for card in pattern.cards)
        self.last_action = f"你出牌：{pattern_type_label(pattern.type)} · {cards}"
        return SessionAction(True, self.last_action)

    def pass_human(self) -> SessionAction:
        state = self.require_state()
        if state.finished:
            return SessionAction(False, "本局已经结束")
        if state.turn_index != self.human:
            return SessionAction(False, f"还没轮到你，当前是 {SEAT_NAMES[state.turn_index]}家")
        try:
            pass_turn(state, self.human)
        except IllegalPlayError as exc:
            self.last_action = f"非法：{exc}"
            return SessionAction(False, self.last_action)

        self.last_action = "你选择过牌"
        return SessionAction(True, self.last_action)

    def hint_for_human(self) -> SessionAction:
        state = self.require_state()
        if state.finished:
            return SessionAction(False, "本局已经结束")
        if state.turn_index != self.human:
            return SessionAction(False, f"还没轮到你，当前是 {SEAT_NAMES[state.turn_index]}家")
        state_key = (
            id(state),
            state.turn_index,
            state.level,
            state.wild_card,
            tuple(state.hands[self.human]),
            tuple(state.table),
        )
        if state_key != self._hint_state_key:
            unique_candidates: list[Pattern] = []
            seen_cards: set[tuple[tuple[int, int, int], ...]] = set()
            table_top = state.table[-1] if state.table else None
            for detected_pattern in enumerate_legal_patterns(state, self.human):
                pattern = find_complete_pattern(detected_pattern.cards, state.wild_card)
                if pattern is None:
                    continue
                if table_top is not None and not pattern.can_be_played_on(
                    table_top,
                    level=state.level,
                ):
                    continue
                card_key = tuple(
                    sorted(
                        (card.rank, int(card.suit), count)
                        for card, count in Counter(pattern.cards).items()
                    )
                )
                if card_key in seen_cards:
                    continue
                seen_cards.add(card_key)
                unique_candidates.append(pattern)
            unique_candidates.sort(
                key=lambda pattern: greedy_pattern_key(pattern, state.level),
            )
            self._hint_state_key = state_key
            self._hint_candidates = tuple(unique_candidates)
            self._hint_index = 0

        if not self._hint_candidates:
            self.last_action = "提示：建议过牌"
            return SessionAction(True, self.last_action)

        pattern = self._hint_candidates[self._hint_index]
        position = self._hint_index + 1
        self._hint_index = (self._hint_index + 1) % len(self._hint_candidates)
        cards = " ".join(card_label(card) for card in pattern.cards)
        self.last_action = (
            f"提示 {position}/{len(self._hint_candidates)}："
            f"{pattern_type_label(pattern.type)} · {cards}"
        )
        return SessionAction(True, self.last_action, pattern.cards)

    def reset_hint_cycle(self) -> None:
        """Restart hints after the player manually changes their selection."""
        self._hint_state_key = None
        self._hint_candidates = ()
        self._hint_index = 0

    def step_ai(self) -> SessionAction:
        state = self.require_state()
        if state.finished:
            self.save_finished_if_needed()
            return SessionAction(False, "本局已经结束")
        if state.turn_index == self.human:
            return SessionAction(False, "轮到你行动")

        player_before = state.turn_index
        history_len_before = len(state.history)
        try:
            play_or_pass(state, player_before, self.strategy, self.ai_rng)
        except IllegalPlayError as exc:
            self.last_action = f"AI 错误：{exc}"
            return SessionAction(False, self.last_action)

        self.last_action = self.describe_player_action(player_before, history_len_before)
        if state.finished:
            self.save_finished_if_needed()
        return SessionAction(True, self.last_action)

    def run_ai_until_human(self, *, limit: int = 12) -> list[str]:
        messages: list[str] = []
        state = self.require_state()
        while not state.finished and state.turn_index != self.human and len(messages) < limit:
            result = self.step_ai()
            messages.append(result.message)
            state = self.require_state()
            if not result.ok and "AI 错误" in result.message:
                break
        return messages

    def describe_player_action(self, player: int, history_len_before: int) -> str:
        state = self.require_state()
        for event in reversed(state.history[history_len_before:]):
            if isinstance(event, TurnPlayed) and event.player == player:
                cards = " ".join(card_label(card) for card in event.pattern.cards)
                return f"{SEAT_NAMES[player]} 出牌：{pattern_type_label(event.pattern.type)} · {cards}"
            if isinstance(event, Pass) and event.player == player:
                return f"{SEAT_NAMES[player]} 过牌"
        return f"{SEAT_NAMES[player]} 过牌"

    def next_round_level(self, state: GameState | None = None) -> int:
        current = state or self.require_state()
        if current.team_levels_final is None or not current.finish_order:
            return current.level
        head_team = current.finish_order[0] % 2
        return int(current.team_levels_final[head_team])

    def next_round_team_levels(self, state: GameState | None = None) -> list[int]:
        current = state or self.require_state()
        if current.team_levels_final is None:
            return list(current.team_levels)
        return list(current.team_levels_final)

    def visible_team_levels(self) -> list[int]:
        state = self.display_state()
        if state.finished and state.team_levels_final is not None:
            return list(state.team_levels_final)
        return list(state.team_levels)

    def pending_next_game_choice(self) -> PendingCardChoice | None:
        pending = self._pending_next_game
        return pending.human_choice if pending is not None else None

    def prepare_next_game(self) -> SessionAction:
        """Deal the next round without starting its tribute phase yet."""
        state = self.require_state()
        if self._pending_next_game is not None:
            return SessionAction(True, self.last_action)
        if not state.finished:
            self.last_action = "本局尚未结束，不能开始下一局"
            return SessionAction(False, self.last_action)
        if state.match_finished:
            self.last_action = "比赛已经结束，不能开始下一局"
            return SessionAction(False, self.last_action)
        if not self.save_finished_if_needed():
            return SessionAction(False, self.last_action)

        next_level = self.next_round_level(state)
        next_team_levels = self.next_round_team_levels(state)
        next_seed = random.randint(1, 10000)

        next_state = make_initial_state(
            level=next_level,
            first_player=self.human,
            seed=next_seed,
            team_levels=next_team_levels,
            ruleset_version=state.ruleset_version,
            a_failure_counts=state.a_failure_counts,
        )
        self._pending_next_game = PendingNextGame(
            state=next_state,
            display_state=next_state,
            finish_order=tuple(state.finish_order),
            game_id=self._new_game_id(),
            seed=next_seed,
            round_index=self.round_index + 1,
            started_at=time.monotonic(),
        )
        self.last_action = (
            f"第 {self.round_index + 1} 局已发牌：本局级牌 {rank_value_label(next_level)}，"
            "请查看手牌"
        )
        return SessionAction(True, self.last_action)

    def begin_next_game_tribute(self) -> SessionAction:
        """Begin tribute only after the newly dealt hands have been displayed."""
        pending = self._pending_next_game
        if pending is None:
            self.last_action = "请先准备下一局"
            return SessionAction(False, self.last_action)
        if pending.preview is not None:
            choice = pending.human_choice
            if choice is not None:
                verb = "进贡" if choice.kind == "tribute" else "还贡"
                return SessionAction(True, f"请选择一张牌{verb}", choice.cards)
            return SessionAction(True, "贡还牌已经准备好")

        next_state = pending.state
        next_level = next_state.level
        preview_hands = [list(hand) for hand in next_state.hands]
        ai_difficulties = [
            None if seat == self.human else self.difficulty for seat in range(4)
        ]
        tribute_choices, return_choices = choose_ai_tribute_cards(
            pending.finish_order,
            next_state.hands,
            level=next_level,
            wild_card=next_state.wild_card,
            difficulties=ai_difficulties,
        )
        preview = apply_tribute_flow(
            list(pending.finish_order),
            preview_hands,
            level=next_state.level,
            wild_card=next_state.wild_card,
            tribute_choices=tribute_choices,
            return_choices=return_choices,
        )
        human_choice: PendingCardChoice | None = None
        if any(exchange.from_player == self.human for exchange in preview.exchanges):
            human_choice = PendingCardChoice(
                "tribute",
                tuple(legal_tribute_cards(next_state.hands[self.human], next_state.wild_card, next_level)),
            )
        elif any(exchange.to_player == self.human for exchange in preview.exchanges):
            hands_after_tribute = [list(hand) for hand in next_state.hands]
            for event in preview.events:
                if isinstance(event, TributeSent):
                    hands_after_tribute[event.from_player].remove(event.card)
                    hands_after_tribute[event.to_player].append(event.card)
            human_choice = PendingCardChoice(
                "return",
                tuple(legal_return_cards(hands_after_tribute[self.human], next_level)),
            )
            display_state = copy.deepcopy(next_state)
            for event in preview.events:
                if not isinstance(event, TributeSent):
                    continue
                display_state.hands[event.from_player].remove(event.card)
                display_state.hands[event.to_player].append(event.card)
                display_state.history.append(event)
            pending.display_state = display_state
        pending.preview = preview
        pending.human_choice = human_choice
        if human_choice is not None:
            verb = "进贡" if human_choice.kind == "tribute" else "还贡"
            self.last_action = f"请选择一张牌{verb}"
            return SessionAction(True, self.last_action, human_choice.cards)
        self.last_action = "下一局已经准备好"
        return SessionAction(True, self.last_action)

    def cancel_next_game(self) -> SessionAction:
        """Discard a prepared round and keep displaying the completed round."""
        if self._pending_next_game is None:
            return SessionAction(False, "没有待确认的下一局")
        pending = self._pending_next_game
        # A saved pending round must not survive a deliberate cancellation.
        try:
            if self._save_revision:
                delete_savegame(expected_game_id=pending.game_id, expected_revision=self._save_revision)
        except OSError as exc:
            self.last_action = f"取消失败：{exc}"
            return SessionAction(False, self.last_action)
        self._pending_next_game = None
        self._save_revision = 0
        self.last_action = "已取消开始下一局"
        return SessionAction(True, self.last_action)

    def finalize_next_game(self, selected_card: Card | None = None) -> SessionAction:
        """Apply tribute choices and atomically replace the completed round."""
        pending = self._pending_next_game
        if pending is None:
            self.last_action = "请先准备下一局"
            return SessionAction(False, self.last_action)
        if pending.preview is None:
            started = self.begin_next_game_tribute()
            if not started.ok:
                return started
        choice = pending.human_choice
        if selected_card is not None and (choice is None or selected_card not in choice.cards):
            self.last_action = "所选牌不符合进贡规则"
            return SessionAction(False, self.last_action)

        try:
            human_choice = (
                (self.human, choice.kind, selected_card)
                if selected_card is not None and choice is not None else None
            )
            ai_difficulties = [
                None if seat == self.human else self.difficulty for seat in range(4)
            ]
            tribute_choices, return_choices = choose_ai_tribute_cards(
                pending.finish_order,
                pending.state.hands,
                level=pending.state.level,
                wild_card=pending.state.wild_card,
                difficulties=ai_difficulties,
                human_choice=human_choice,
            )
            tribute_result = apply_tribute_flow(
                list(pending.finish_order),
                pending.state.hands,
                level=pending.state.level,
                wild_card=pending.state.wild_card,
                tribute_choices=tribute_choices,
                return_choices=return_choices,
            )
        except ValueError as exc:
            self.last_action = f"进贡失败：{exc}"
            return SessionAction(False, self.last_action)

        next_state = pending.state
        next_state.history.extend(tribute_result.events)
        next_state.turn_index = tribute_result.first_player
        next_state.leader = tribute_result.first_player
        if next_state.history and isinstance(next_state.history[0], ShuffleDeal):
            shuffle = next_state.history[0]
            next_state.history[0] = ShuffleDeal(
                level=shuffle.level,
                wild_card=shuffle.wild_card,
                hand_sizes=shuffle.hand_sizes,
                first_player=tribute_result.first_player,
                seed=shuffle.seed,
                team_levels=shuffle.team_levels,
            )

        self.level = next_state.level
        self.seed = pending.seed
        self.game_id = pending.game_id
        self.round_index = pending.round_index
        self.start_time = time.time()
        self._elapsed_before_start = pending.elapsed_seconds + max(
            0, int(time.monotonic() - pending.started_at)
        )
        self.game_saved = False
        self.displayed_table_actions.clear()
        self.last_display_turn = None
        self.state = next_state
        self._pending_next_game = None
        self.last_action = (
            f"第 {self.round_index} 局开始：本局级牌 {rank_value_label(next_state.level)}，"
            f"{self.tribute_notice()}；{SEAT_NAMES[tribute_result.first_player]}家先手"
        )
        return SessionAction(True, self.last_action)

    def start_next_game(self) -> SessionAction:
        """Compatibility entry point that automatically resolves human tribute choices."""
        prepared = self.prepare_next_game()
        if not prepared.ok:
            return prepared
        started = self.begin_next_game_tribute()
        if not started.ok:
            return started
        return self.finalize_next_game()

    def save_finished_if_needed(self) -> bool:
        self._last_save_error = None
        if self.game_saved:
            return True
        state = self.require_state()
        if not state.finished:
            return False
        got_head = state.finish_order[0] == self.human
        match_won = state.winner_team == team_of(self.human) if state.match_finished else None
        try:
            duration = self.current_elapsed_seconds()
            ai_difficulties = [
                None if player == self.human else self.difficulty for player in range(4)
            ]
            # Claim this revision before publishing history/statistics. A stale
            # process must not settle a different ending of the same round.
            # The durable finished checkpoint also repairs a crash before history.
            if state.history and isinstance(state.history[0], ShuffleDeal):
                self._save_revision = save_game(
                    state=state, game_id=self.game_id, player_seat=self.human,
                    ai_difficulties=ai_difficulties, seed=self.seed,
                    match_id=self.match_id, round_index=self.round_index,
                    elapsed_seconds=duration, expected_revision=self._save_revision,
                )
            # Settlement is three independent durable writes (history,
            # statistics, delete save). Log the intent first so a crash in
            # between can be repaired on the next start instead of leaving a
            # history entry that no statistic ever counted.
            begin_settlement(
                game_id=self.game_id,
                got_head=got_head,
                difficulty=self.difficulty,
                match_id=self.match_id if state.match_finished else None,
                match_won=match_won,
            )
            save_history(
                state=state,
                game_id=self.game_id,
                player_seat=self.human,
                ai_difficulties=ai_difficulties,
                seed=self.seed,
                duration_seconds=duration,
                match_id=self.match_id,
                round_index=self.round_index,
            )
            def update_statistics(profile: dict[str, Any]) -> None:
                record_round_statistics(
                    profile,
                    got_head=got_head,
                    difficulty=self.difficulty,
                    game_id=self.game_id,
                )
                if state.match_finished:
                    record_match_statistics(
                        profile,
                        won=bool(match_won),
                        difficulty=self.difficulty,
                        match_id=self.match_id,
                    )

            update_profile(update_statistics)
            delete_savegame(expected_game_id=self.game_id, expected_revision=self._save_revision)
            self._save_revision = 0
            end_settlement(self.game_id)
        except Exception as exc:
            self._last_save_error = exc
            self.game_saved = False
            self.last_action = f"保存失败：{exc}"
            return False
        self.game_saved = True
        return True

    def resumable_round(self) -> tuple[GameState, str, int, int]:
        """Return the round that should be persisted for resume.

        Once `prepare_next_game()` deals a new round we delete the finished
        round's save. Until `finalize_next_game()` runs, `self.state` is still
        that finished round, so saving only ``self.state`` silently dropped the
        freshly dealt round (and its tribute phase) on exit.
        """
        pending = self._pending_next_game
        if pending is not None:
            return pending.state, pending.game_id, pending.round_index, pending.seed
        return self.require_state(), self.game_id, self.round_index, self.seed

    def _round_is_already_saved(self, state: GameState) -> bool:
        """Whether the round to persist was already settled.

        `game_saved` describes the round in ``self.state``. A freshly dealt
        pending round reuses the session but has not been saved yet, so the
        flag must not suppress its first save.
        """
        if self._pending_next_game is not None:
            return False
        return self.game_saved or state.finished

    def save_unfinished(self) -> None:
        state, game_id, round_index, seed = self.resumable_round()
        if self._round_is_already_saved(state):
            return
        ai_difficulties = [
            None if player == self.human else self.difficulty for player in range(4)
        ]
        pending = self._pending_next_game
        checkpoint = None if pending is None else {
            "previous_game_id": self.game_id,
            "previous_events": serialize_events(self.require_state().history),
            "tribute_started": pending.preview is not None,
        }
        elapsed = self.current_elapsed_seconds() if pending is None else (
            pending.elapsed_seconds + max(0, int(time.monotonic() - pending.started_at))
        )
        self._save_revision = save_game(
            state=state,
            game_id=game_id,
            player_seat=self.human,
            ai_difficulties=ai_difficulties,
            seed=seed,
            match_id=self.match_id,
            round_index=round_index,
            elapsed_seconds=elapsed,
            expected_revision=self._save_revision,
            pending_round=checkpoint,
        )

    def save_current(self) -> None:
        """Persist the visible round; pending tribute takes priority over settlement."""
        if not self.is_next_game_pending() and self.require_state().finished:
            if not self.save_finished_if_needed():
                raise self._last_save_error or OSError(self.last_action)
        else:
            self.save_unfinished()

    def autosave_after_ai(self) -> bool:
        """Persist a real dealt round after an AI batch while UI actions are locked."""
        state = self.require_state()
        if state.finished:
            return self.save_finished_if_needed()
        if not state.history or not isinstance(state.history[0], ShuffleDeal):
            return True
        try:
            self.save_unfinished()
        except Exception as exc:
            self.last_action = f"自动保存失败：{exc}"
            return False
        return True
