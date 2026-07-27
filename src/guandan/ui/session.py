"""Frontend-neutral playable game session.

The engine owns the rules. This layer owns UI-facing orchestration: starting and
continuing games, driving AI turns, applying tribute for the next game, and
persisting save/history records.
"""
from __future__ import annotations

import random
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

from ..ai import AINotImplementedError, make_strategy, play_or_pass
from ..ai.candidates import enumerate_legal_patterns, greedy_pattern_key
from ..ai.strategy import AIStrategy
from ..engine.card import Card, Suit
from ..engine.events import Pass, ShuffleDeal, TributeSent, TurnPlayed
from ..engine.hand import Pattern
from ..engine.rules.patterns import find_complete_pattern
from ..engine.rules.tributes import (
    TributeFlowResult,
    apply_tribute_flow,
    legal_return_cards,
    legal_tribute_cards,
)
from ..engine.state import (
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
    delete_savegame,
    record_match_statistics,
    record_round_statistics,
    save_game,
    save_history,
    update_profile,
)
from .formatting import card_label, cards_text, pattern_type_label, play_rejection_message


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
    finish_order: tuple[int, ...]
    game_id: str
    seed: int
    round_index: int
    preview: TributeFlowResult
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
        self._hint_state_key: tuple[object, ...] | None = None
        self._hint_candidates: tuple[Pattern, ...] = ()
        self._hint_index = 0
        self._pending_next_game: PendingNextGame | None = None

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

    def current_table_players(self) -> list[int]:
        return current_table_players(self.require_state())

    def locked_passed_players(self) -> list[int]:
        return locked_passed_players(self.require_state())

    def table_display_actions(self) -> dict[int, tuple[str, Pattern | None]]:
        """Keep each seat's last visible action until that seat is asked to act again."""
        state = self.require_state()
        if state.finished:
            self.displayed_table_actions.clear()
            self.last_display_turn = None
            return {}

        if self.last_display_turn != state.turn_index:
            self.displayed_table_actions.pop(state.turn_index, None)
            self.last_display_turn = state.turn_index

        for player, pattern in zip(self.current_table_players(), state.table):
            self.displayed_table_actions[player] = ("play", pattern)
        for player in self.locked_passed_players():
            self.displayed_table_actions[player] = ("pass", None)

        return dict(self.displayed_table_actions)

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
        state = self.require_state()
        if state.finished and state.team_levels_final is not None:
            return list(state.team_levels_final)
        return list(state.team_levels)

    def pending_next_game_choice(self) -> PendingCardChoice | None:
        pending = self._pending_next_game
        return pending.human_choice if pending is not None else None

    def prepare_next_game(self) -> SessionAction:
        """Prepare a round and expose any human tribute decision without committing it."""
        state = self.require_state()
        if self._pending_next_game is not None:
            choice = self._pending_next_game.human_choice
            if choice is not None:
                verb = "进贡" if choice.kind == "tribute" else "还贡"
                return SessionAction(True, f"请选择一张牌{verb}", choice.cards)
            return SessionAction(True, "下一局已经准备好")
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
        )
        preview_hands = [list(hand) for hand in next_state.hands]
        preview = apply_tribute_flow(
            list(state.finish_order),
            preview_hands,
            level=next_state.level,
            wild_card=next_state.wild_card,
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
        self._pending_next_game = PendingNextGame(
            state=next_state,
            finish_order=tuple(state.finish_order),
            game_id=self._new_game_id(),
            seed=next_seed,
            round_index=self.round_index + 1,
            preview=preview,
            human_choice=human_choice,
        )
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
        self._pending_next_game = None
        self.last_action = "已取消开始下一局"
        return SessionAction(True, self.last_action)

    def finalize_next_game(self, selected_card: Card | None = None) -> SessionAction:
        """Apply tribute choices and atomically replace the completed round."""
        pending = self._pending_next_game
        if pending is None:
            self.last_action = "请先准备下一局"
            return SessionAction(False, self.last_action)
        choice = pending.human_choice
        if selected_card is not None and (choice is None or selected_card not in choice.cards):
            self.last_action = "所选牌不符合进贡规则"
            return SessionAction(False, self.last_action)

        tribute_choices: dict[int, Card] = {}
        return_choices: dict[int, Card] = {}
        if selected_card is not None and choice is not None:
            target = tribute_choices if choice.kind == "tribute" else return_choices
            target[self.human] = selected_card
        try:
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
        self._elapsed_before_start = 0
        self.game_saved = False
        self.displayed_table_actions.clear()
        self.last_display_turn = None
        self.state = next_state
        self._pending_next_game = None
        tribute_note = self._tribute_summary(tribute_result)
        self.last_action = (
            f"第 {self.round_index} 局开始：级牌 {next_state.level}，"
            f"{tribute_note}{SEAT_NAMES[tribute_result.first_player]}家先手"
        )
        return SessionAction(True, self.last_action)

    def start_next_game(self) -> SessionAction:
        """Compatibility entry point that automatically resolves human tribute choices."""
        prepared = self.prepare_next_game()
        if not prepared.ok:
            return prepared
        return self.finalize_next_game()

    @staticmethod
    def _tribute_summary(result: TributeFlowResult) -> str:
        if result.resisted:
            return "抗贡，"
        if not result.exchanges:
            return ""
        exchanges = []
        for exchange in result.exchanges:
            returned = card_label(exchange.return_card) if exchange.return_card is not None else "-"
            exchanges.append(
                f"{SEAT_NAMES[exchange.from_player]}贡{card_label(exchange.tribute_card)}给"
                f"{SEAT_NAMES[exchange.to_player]}，还{returned}"
            )
        return "；".join(exchanges) + "；"

    def save_finished_if_needed(self) -> bool:
        if self.game_saved:
            return True
        state = self.require_state()
        if not state.finished:
            return False
        try:
            duration = self.current_elapsed_seconds()
            ai_difficulties = [
                None if player == self.human else self.difficulty for player in range(4)
            ]
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
                    got_head=state.finish_order[0] == self.human,
                    difficulty=self.difficulty,
                    game_id=self.game_id,
                )
                if state.match_finished:
                    record_match_statistics(
                        profile,
                        won=state.winner_team == team_of(self.human),
                        difficulty=self.difficulty,
                        match_id=self.match_id,
                    )

            update_profile(update_statistics)
            delete_savegame(expected_game_id=self.game_id)
        except Exception as exc:
            self.game_saved = False
            self.last_action = f"保存失败：{exc}"
            return False
        self.game_saved = True
        return True

    def save_unfinished(self) -> None:
        state = self.require_state()
        if state.finished or self.game_saved:
            return
        ai_difficulties = [
            None if player == self.human else self.difficulty for player in range(4)
        ]
        save_game(
            state=state,
            game_id=self.game_id,
            player_seat=self.human,
            ai_difficulties=ai_difficulties,
            seed=self.seed,
            match_id=self.match_id,
            round_index=self.round_index,
            elapsed_seconds=self.current_elapsed_seconds(),
        )

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
