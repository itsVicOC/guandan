"""Partnership, initiative, and terminal-goal regressions across seats/levels."""
from __future__ import annotations

import copy
import json
import random
from dataclasses import replace
from pathlib import Path

import pytest

from guandan.ai.candidates import enumerate_exact_small_hand_patterns, pattern_key
from guandan.ai.context import PublicTacticalContext
from guandan.ai.mcts.endgame_solver import _Budget, _DepthLimit, _minimax, search_endgame
from guandan.ai.mcts.search import _evaluate_result, _rollout_select_pattern
from guandan.ai.strategies.advanced import AdvancedStrategy
from guandan.ai.strategies.dachangsheng import DaiChangshengStrategy
from guandan.ai.strategies.professional import ProfessionalStrategy
from guandan.ai.tactics import select_heuristic_action
from guandan.engine.card import RANK_BIG_JOKER, RANK_SMALL_JOKER, Card, Suit
from guandan.engine.events import Pass, ShuffleDeal, TributeSent, TurnPlayed
from guandan.engine.hand import Pattern, PatternType
from guandan.engine.replay import replay_events
from guandan.engine.state import GameState, _finish_game, clone_state_for_search, pass_turn
from guandan.storage.serialization import deserialize_events


def card(rank: int, suit: Suit = Suit.CLUBS) -> Card:
    return Card(rank, suit)


def rotated(state: GameState, seat: int) -> GameState:
    out = copy.deepcopy(state)
    out.hands = [state.hands[(p - seat) % 4].copy() for p in range(4)]
    out.turn_index = seat
    out.leader = (state.leader + seat) % 4 if state.leader is not None else None
    out.finish_order = [(p + seat) % 4 for p in state.finish_order]
    out.passed_players = {(p + seat) % 4 for p in state.passed_players}
    out.history = [replace(e, player=(e.player + seat) % 4) for e in state.history]
    return out


@pytest.mark.parametrize("level", [2, 9, 14])
@pytest.mark.parametrize("seat", range(4))
@pytest.mark.parametrize("scenario", ["yield_bomb", "cover_partner", "block_single"])
def test_tactical_corpus(level: int, seat: int, scenario: str) -> None:
    """36 positions exercise the same tactical obligations in every seat."""
    if scenario == "yield_bomb":
        top = Pattern(PatternType.BOMB, 3, 4, tuple(card(3, s) for s in list(Suit)[:4]))
        state = GameState(
            level=level, wild_card=None,
            hands=[[card(4, s) for s in list(Suit)[:4]] + [card(7), card(9)],
                   [card(8)] * 22, [card(5)] * 18, [card(10)] * 22],
            turn_index=0, leader=2, table=[top],
            history=[TurnPlayed(2, top, 18)],
        )
        expected = None
    elif scenario == "cover_partner":
        top = Pattern(PatternType.SINGLE, 13, 1, (card(13),))
        state = GameState(
            level=level, wild_card=None,
            hands=[[Card(RANK_BIG_JOKER, Suit.BIG_JOKER), card(3), card(5)],
                   [card(8)] * 8, [card(7)] * 6, [card(10)]],
            turn_index=0, leader=2, table=[top],
            history=[TurnPlayed(2, top, 6)],
        )
        expected = PatternType.SINGLE
    else:
        state = GameState(
            level=level, wild_card=None,
            hands=[[card(3), card(3, Suit.SPADES), card(7), card(9)],
                   [card(8)] * 8, [card(7)] * 6, [card(10)]],
            turn_index=0, leader=0,
        )
        expected = PatternType.PAIR
    state = rotated(state, seat)
    policy = AdvancedStrategy(team_tactics=True)
    action = policy.select_pattern(state, seat)
    if expected is None:
        assert action is None
    else:
        assert action is not None and action.type == expected
        if scenario == "cover_partner":
            assert action.rank == RANK_BIG_JOKER
    # Hidden contents can change while public sizes stay identical.
    altered = copy.deepcopy(state)
    for other in range(4):
        if other != seat:
            altered.hands[other] = [card(12)] * len(altered.hands[other])
    assert policy.select_pattern(altered, seat) == action


@pytest.mark.parametrize("seat", range(4))
def test_control_first_creates_a_two_play_finish(seat: int) -> None:
    state = GameState(
        level=2, wild_card=None,
        hands=[[Card(RANK_BIG_JOKER, Suit.BIG_JOKER), card(3), card(3, Suit.SPADES)],
               [card(8), card(8, Suit.SPADES)], [card(5)] * 8, [card(9)]],
        turn_index=0, leader=0,
    )
    state = rotated(state, seat)
    action = select_heuristic_action(state, seat, 2, team_tactics=True)
    assert action is not None and action.rank == RANK_BIG_JOKER


@pytest.mark.parametrize("level", [2, 9, 14])
@pytest.mark.parametrize("seat", range(4))
def test_head_with_partner_last_respects_a_failure(level: int, seat: int) -> None:
    state = GameState(
        level=level, wild_card=None,
        ruleset_version=2,  # Retain the legacy one-failure utility regression.
        hands=[[], [], [card(3)], []], turn_index=2,
        finish_order=[0, 1, 3],
    )
    state = rotated(state, seat)
    _finish_game(state)
    value = _evaluate_result(state, seat)
    assert value + _evaluate_result(state, (seat + 1) % 4) == pytest.approx(1.0)
    if level == 14:
        assert state.guo_a_failed and value == 0.0
    else:
        assert value > 0.5


def test_placed_a_race_is_success_probability_not_a_head_bonus() -> None:
    state = GameState(
        level=14, wild_card=None,
        ruleset_version=2,
        hands=[[], [card(4)], [card(3)], []], turn_index=2,
        finish_order=[0, 3],
    )
    assert _evaluate_result(state, 0) == pytest.approx(0.5)
    assert _evaluate_result(state, 1) == pytest.approx(0.5)


def human_replay(index: int) -> GameState:
    data = json.loads((Path(__file__).parent / "fixtures/ai-human-partner-replay.json").read_text())
    return replay_events(deserialize_events(data["events"][:index]), allow_incomplete_tail=True)


def test_real_replay_does_not_bomb_partner_without_an_exit_threat() -> None:
    state = human_replay(10)
    assert state.turn_index == 1
    old = select_heuristic_action(state, 1, 2)
    assert old is not None and old.type == PatternType.BOMB
    assert select_heuristic_action(state, 1, 2, team_tactics=True) is None
    assert _rollout_select_pattern(state, 1, rollout_strategy_level=3) is None


def test_public_pass_order_matches_engine_on_legal_replay_prefixes() -> None:
    data = json.loads((Path(__file__).parent / "fixtures/ai-human-partner-replay.json").read_text())
    checked = 0
    for prefix in range(1, len(data["events"])):
        state = replay_events(deserialize_events(data["events"][:prefix]), allow_incomplete_tail=True)
        if not state.table or state.finished:
            continue
        player = state.current_player()
        context = PublicTacticalContext.from_state(state, player)
        expected = list(context.order)
        if context.top_player in expected:
            expected = expected[:expected.index(context.top_player)]
        sim = clone_state_for_search(state)
        pass_turn(sim, player)
        actual = []
        while sim.table:
            actor = sim.current_player()
            actual.append(actor)
            assert actor != context.top_player
            pass_turn(sim, actor)
        assert actual == expected
        checked += 1
    assert checked >= 60


def test_safe_same_family_is_still_a_valid_lead() -> None:
    state = GameState(
        level=2, wild_card=None,
        hands=[[card(3), card(3, Suit.SPADES), card(7), card(9)],
               [card(8)] * 8, [card(7)] * 6, [card(10)]],
        turn_index=0, leader=0,
        history=[TurnPlayed(3, Pattern(PatternType.PAIR, 5, 1, (card(5), card(5, Suit.SPADES))), 1)],
    )
    action = select_heuristic_action(state, 0, 2, team_tactics=True)
    assert action is not None and action.type == PatternType.PAIR


def test_ordinary_two_play_partition_needs_a_controlled_first_play() -> None:
    straight = tuple(card(rank, Suit.CLUBS if rank % 2 else Suit.SPADES) for rank in range(5, 10))
    top = Pattern(PatternType.STRAIGHT, 8, 5, tuple(card(rank) for rank in range(4, 9)))
    state = GameState(
        level=2, wild_card=None,
        hands=[[*straight, card(3), card(3, Suit.DIAMONDS)],
               [card(8)] * 22, [card(5)] * 20, [card(10)] * 22],
        turn_index=0, leader=2, table=[top], history=[TurnPlayed(2, top, 20)],
    )
    assert select_heuristic_action(state, 0, 2, team_tactics=True) is None
    assert _rollout_select_pattern(state, 0, rollout_strategy_level=3) is None


@pytest.mark.parametrize("level", [2, 9, 14])
@pytest.mark.parametrize("seat", range(4))
def test_catch_wind_and_necessary_two_play_takeover(level: int, seat: int) -> None:
    pair = [card(3), card(3, Suit.DIAMONDS)]
    wind = GameState(
        level=level, wild_card=None,
        hands=[[*pair, card(9)], [card(4)], [], [card(5)]],
        turn_index=0, leader=2, finish_order=[2],
    )
    wind = rotated(wind, seat)
    action = select_heuristic_action(wind, seat, 2, team_tactics=True)
    assert action is not None and action.type == PatternType.PAIR
    straight = tuple(card(rank, Suit.SPADES) for rank in range(5, 10))
    top = Pattern(PatternType.STRAIGHT, 8, 5, tuple(card(rank, Suit.HEARTS) for rank in range(4, 9)))
    state = GameState(
        level=level, wild_card=None,
        hands=[[*straight, *pair], [card(8)] * 8, [card(5)] * 15, [card(10)] * 8],
        turn_index=0, leader=2, table=[top], history=[TurnPlayed(2, top, 15)],
    )
    state = rotated(state, seat)
    takeover = select_heuristic_action(state, seat, 2, team_tactics=True)
    assert takeover is not None and takeover.type == PatternType.STRAIGHT


@pytest.mark.parametrize("level", [2, 9, 14])
@pytest.mark.parametrize("seat", range(4))
@pytest.mark.parametrize("top_type", [PatternType.BOMB, PatternType.PAIR])
def test_controlled_bomb_takeover_can_finish_in_two(level, seat, top_type) -> None:
    jokers = [Card(RANK_SMALL_JOKER, Suit.SMALL_JOKER)] * 2 + [Card(RANK_BIG_JOKER, Suit.BIG_JOKER)] * 2
    top_cards = tuple(card(4, s) for s in list(Suit)[:4 if top_type == PatternType.BOMB else 2])
    top = Pattern(top_type, 4, 4 if top_type == PatternType.BOMB else 1, top_cards)
    state = GameState(
        level=level, wild_card=None,
        hands=[[*jokers, card(7), card(7, Suit.DIAMONDS)],
               [card(8)] * 10, [card(9)] * 15, [card(10)] * 10],
        turn_index=0, leader=2, table=[top], history=[TurnPlayed(2, top, 15)],
    )
    state = rotated(state, seat)
    for action in (select_heuristic_action(state, seat, 2, team_tactics=True),
                   _rollout_select_pattern(state, seat, rollout_strategy_level=3)):
        assert action is not None and action.type == PatternType.FOUR_JOKERS


@pytest.mark.parametrize("size", [2, 3])
@pytest.mark.parametrize("seat", range(4))
def test_reported_pair_or_triple_is_not_given_an_immediate_exit(size: int, seat: int) -> None:
    state = GameState(
        level=2, wild_card=None,
        hands=[[card(3, s) for s in list(Suit)[:size]] + [card(7), card(9)],
               [card(8)] * 8, [card(7)] * 6, [card(10)] * size],
        turn_index=0, leader=0,
    )
    state = rotated(state, seat)
    action = select_heuristic_action(state, seat, 2, team_tactics=True)
    assert action is not None and len(action.cards) != size


def test_pass_is_soft_evidence_and_partner_pass_is_not_negative_evidence() -> None:
    state = human_replay(58)
    context = PublicTacticalContext.from_state(state, 2)
    p = Pattern(PatternType.SINGLE, 7, 1, (card(7),))
    assert context.response_risk(p, 1) > 0.0
    state.history.append(Pass(1, state.hand_size(1)))
    assert PublicTacticalContext.from_state(state, 2).response_risk(p, 1) > 0.0
    partner_top = Pattern(PatternType.SINGLE, 7, 1, (card(7),))
    state = GameState(level=2, wild_card=None, hands=[[card(3)] * 6 for _ in range(4)],
                      turn_index=0, leader=3, table=[partner_top],
                      history=[TurnPlayed(3, partner_top, 6)])
    before = PublicTacticalContext.from_state(state, 0).response_risk(p, 1)
    state.history.append(Pass(1, 6))
    assert PublicTacticalContext.from_state(state, 0).response_risk(p, 1) == before


@pytest.mark.parametrize("ruleset", [1, 2])
@pytest.mark.parametrize("seat", range(4))
def test_passed_opponent_reenters_after_an_overplay_only_in_current_rules(ruleset, seat) -> None:
    top = Pattern(PatternType.SINGLE, 12, 1, (card(12),))
    state = GameState(
        level=2, wild_card=None,
        hands=[[card(13), card(14), card(8)], [card(10)], [card(6)] * 6, [card(7)] * 8],
        turn_index=0, leader=3, table=[top], passed_players={1, 2}, ruleset_version=ruleset,
        history=[TurnPlayed(3, top, 8), Pass(2, 6), Pass(1, 1)],
    )
    state = rotated(state, seat)
    context = PublicTacticalContext.from_state(state, seat)
    blocked = (seat + 1) % 4
    assert blocked not in context.order
    assert (blocked in context.opponents) == (ruleset == 2)
    action = select_heuristic_action(state, seat, 2, team_tactics=True)
    assert action is not None and action.rank == (14 if ruleset == 2 else 13)


@pytest.mark.parametrize("ruleset", [1, 2])
def test_public_tribute_card_can_make_passing_safer_than_unlocking_an_opponent(ruleset) -> None:
    top = Pattern(PatternType.SINGLE, 12, 1, (card(12),))
    state = GameState(
        level=2, wild_card=None,
        hands=[[card(13), card(8), card(8, Suit.DIAMONDS)], [card(14)], [card(6)] * 6, [card(7)] * 8],
        turn_index=0, leader=3, table=[top], passed_players={1, 2}, ruleset_version=ruleset,
        history=[TributeSent(2, 1, card(14)), TurnPlayed(3, top, 8), Pass(2, 6), Pass(1, 1)],
    )
    context = PublicTacticalContext.from_state(state, 0)
    assert context.known[1] == (card(14),)
    assert context.current_opponent_min_cards == 8
    action = select_heuristic_action(state, 0, 2, team_tactics=True)
    if ruleset == 2:
        assert action is None
    else:
        assert action is not None and action.rank == 13


@pytest.mark.parametrize("level", [2, 9, 14])
def test_maximum_straight_flush_is_a_controlled_two_play_takeover(level) -> None:
    jokers = [Card(RANK_SMALL_JOKER, Suit.SMALL_JOKER)] * 2 + [Card(RANK_BIG_JOKER, Suit.BIG_JOKER)] * 2
    top = Pattern(PatternType.BOMB, 3, 4, tuple(card(3, s) for s in list(Suit)[:4]))
    state = GameState(
        level=level, wild_card=None,
        hands=[[card(rank, Suit.SPADES) for rank in range(10, 15)] + [card(7), card(7, Suit.DIAMONDS)],
               [card(8)] * 5, [card(9)] * 15, [card(10)] * 5],
        turn_index=0, leader=2, table=[top],
        history=[TurnPlayed(3, Pattern(PatternType.FOUR_JOKERS, 101, 4, tuple(jokers)), 6),
                 Pass(2, 19), Pass(1, 5), Pass(0, 7),
                 TurnPlayed(3, Pattern(PatternType.SINGLE, 3, 1, (card(3),)), 5),
                 TurnPlayed(2, top, 15), Pass(1, 5)], passed_players={1},
    )
    action = select_heuristic_action(state, 0, 2, team_tactics=True)
    assert action is not None and action.type == PatternType.STRAIGHT_FLUSH and action.rank == 14


def test_exact_endgame_keeps_all_pair_suit_materials() -> None:
    state = GameState(
        level=2, wild_card=None,
        hands=[[card(3, s) for s in (Suit.SPADES, Suit.HEARTS, Suit.DIAMONDS)],
               [card(4)], [card(5)], [card(6)]], turn_index=0,
    )
    pairs = [p for p in enumerate_exact_small_hand_patterns(state, 0) if p.type == PatternType.PAIR]
    assert len({pattern_key(p) for p in pairs}) == 3


def test_depth_cutoff_is_never_an_exact_terminal_value() -> None:
    state = human_replay(87)
    with pytest.raises(_DepthLimit):
        _minimax(state, state.turn_index, 0, _Budget(float("inf"), 30000), 0.0, 1.0)


def test_endgame_reports_common_worlds_and_uncertainty() -> None:
    state = human_replay(87)
    result = search_endgame(state, state.turn_index, rng=random.Random(42), deadline=float("inf"))
    assert result.complete and not result.exact
    assert result.common_samples == 8
    assert all(stat.visits == 8 and stat.paired_standard_error is not None for stat in result.actions)


def test_enhanced_search_ignores_actual_hidden_cards_and_deal_seed() -> None:
    state = human_replay(87)
    changed = copy.deepcopy(state)
    player = state.current_player()
    for seat in range(4):
        if seat != player:
            changed.hands[seat] = [card(12)] * state.hand_size(seat)
    changed.history = [replace(e, seed=9999) if isinstance(e, ShuffleDeal) else e for e in changed.history]
    strategies = [DaiChangshengStrategy(rng=random.Random(42), mcts_overrides={
        "time_budget_ms": 0, "team_tactics": 1, "endgame_confidence": 1, "rollout_strategy": 3,
    }) for _ in range(2)]
    assert strategies[0].select_pattern(state, player) == strategies[1].select_pattern(changed, player)
    assert strategies[0].last_endgame.actions == strategies[1].last_endgame.actions


def test_team_switch_keeps_fast_reference_and_continuation_in_sync() -> None:
    professional = ProfessionalStrategy(team_tactics=True)
    highest = DaiChangshengStrategy(mcts_overrides={"team_tactics": 1})
    for strategy in (professional, highest):
        assert strategy._fast_strategy.team_tactics and strategy.rollout_strategy == 3


def test_unfinished_endgame_does_not_claim_completion() -> None:
    state = human_replay(87)
    result = search_endgame(state, state.turn_index, rng=random.Random(42), deadline=float("inf"), max_nodes=2)
    assert not result.complete and not result.exact
    assert result.common_samples == 0 and result.reason == "budget_limited"
    assert result.nodes <= 2


def test_publicly_unique_remaining_world_is_exact_with_one_sample() -> None:
    state = human_replay(94)
    result = search_endgame(state, state.turn_index, rng=random.Random(42), deadline=float("inf"))
    assert result.exact and result.complete and result.common_samples == 1
