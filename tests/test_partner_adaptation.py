"""Public behaviour and real counterplay, rather than cooperative appearances."""

from __future__ import annotations

import copy
import random
import time
from dataclasses import replace

import pytest

from guandan.ai.candidates import enumerate_legal_patterns
from guandan.ai.mcts.root_search import root_action_search
from guandan.ai.mcts.search import _rollout_select_pattern
from guandan.ai.partner_model import sample_styles, style_distribution, style_probabilities
from guandan.ai.response_chain import action_key, chain_candidates, evaluate_responses
from guandan.ai.strategies.dachangsheng import DaiChangshengStrategy
from guandan.ai.strategies.professional import ProfessionalStrategy
from guandan.engine.card import Card, Suit
from guandan.engine.events import Pass, ShuffleDeal, TurnPlayed
from guandan.engine.hand import Pattern, PatternType
from guandan.engine.state import GameState, clone_state_for_search, make_initial_state, play_pattern


def cards(rank, count=2):
    return [
        Card(rank, suit) for suit in (Suit.CLUBS, Suit.SPADES, Suit.HEARTS, Suit.DIAMONDS)[:count]
    ]


def pattern(rank, count=2):
    return Pattern(
        PatternType.PAIR if count == 2 else PatternType.SINGLE, rank, 1, tuple(cards(rank, count))
    )


def fixed_worlds(monkeypatch):
    monkeypatch.setattr(
        "guandan.ai.response_chain.determinize", lambda s, p, rng: clone_state_for_search(s)
    )


def test_recent_actions_replace_old_style_evidence():
    state = make_initial_state(seed=200000)
    state.history = [TurnPlayed(2, pattern(3, 1), 26) for _ in range(16)]
    before = style_probabilities(state, 2)
    straight = Pattern(PatternType.STRAIGHT, 7, 5, tuple(Card(r, Suit.CLUBS) for r in range(3, 8)))
    state.history.extend(TurnPlayed(2, straight, 10) for _ in range(5))
    after = style_probabilities(state, 2)
    assert after[2] > before[2]
    assert all(p > 0 for p in after) and sum(after) == pytest.approx(1)
    older = copy.deepcopy(state)
    older.history[:5] = [TurnPlayed(2, long, 26) for long in [straight] * 5]
    assert style_probabilities(older, 2) == pytest.approx(after)


def test_style_ignores_partner_courtesy_and_urgent_blocks():
    state = make_initial_state(seed=200001)
    state.history = [TurnPlayed(0, pattern(3), 20), Pass(2, 27)]
    assert style_probabilities(state, 2) == pytest.approx((0.5, 0.25, 0.25))
    state.history = [TurnPlayed(1, pattern(3), 1), Pass(2, 27)]
    assert style_probabilities(state, 2) == pytest.approx((0.5, 0.25, 0.25))
    state.history.append(TurnPlayed(2, Pattern(PatternType.BOMB, 8, 4, tuple(cards(8, 4))), 10))
    assert style_probabilities(state, 2) == pytest.approx((0.5, 0.25, 0.25))


def test_lead_and_follow_are_different_evidence():
    long = Pattern(PatternType.STRAIGHT, 7, 5, tuple(Card(r, Suit.CLUBS) for r in range(3, 8)))
    lead = make_initial_state(seed=200002)
    lead.history = [TurnPlayed(2, long, 20)]
    follow = copy.deepcopy(lead)
    follow.history.insert(0, TurnPlayed(1, pattern(3), 20))
    assert style_probabilities(lead, 2)[2] > style_probabilities(follow, 2)[2]


def test_style_distribution_does_not_use_hidden_hands_or_shuffle_seed():
    state = make_initial_state(seed=200003)
    changed = copy.deepcopy(state)
    for seat in (1, 2, 3):
        changed.hands[seat] = cards(12, 1) * state.hand_size(seat)
    changed.history = [
        replace(e, seed=999) if isinstance(e, ShuffleDeal) else e for e in changed.history
    ]
    assert style_distribution(changed) == style_distribution(state)
    probs = style_distribution(state)
    assert sample_styles(state, random.Random(8), probs) == sample_styles(
        changed, random.Random(8), probs
    )


@pytest.mark.parametrize("level", [2, 9, 14])
@pytest.mark.parametrize("seat", range(4))
def test_available_reply_is_not_recovered_control(monkeypatch, level, seat):
    fixed_worlds(monkeypatch)
    # 33 -> enemy TT -> our JJ -> enemy QQ out. The old four-action
    # chain stopped at our turn and incorrectly recorded recovery=1.
    hands = [cards(3) + cards(11), cards(5), cards(4), cards(10) + cards(12)]
    hands = [hands[(s - seat) % 4] for s in range(4)]
    state = GameState(level=level, wild_card=None, hands=hands, turn_index=seat, leader=seat)
    report, diagnostic = evaluate_responses(
        state, seat, [pattern(3)], rng=random.Random(1), worlds=4
    )
    row = report[action_key(pattern(3))]
    assert row.own_control == 0.0
    assert row.opponent_control + row.unresolved > 0.0 or row.value < 0.5
    assert diagnostic["completed_worlds"] == 4
    assert state.hands[seat] == cards(3) + cards(11)


def test_actual_resolved_trick_proves_control(monkeypatch):
    fixed_worlds(monkeypatch)
    state = GameState(
        level=2,
        wild_card=None,
        hands=[cards(12) + cards(7, 1), cards(5), cards(4), cards(8)],
        turn_index=0,
        leader=0,
    )
    report, _ = evaluate_responses(state, 0, [pattern(12)], rng=random.Random(1), worlds=4)
    assert report[action_key(pattern(12))].own_control == 1.0


@pytest.mark.parametrize("style", ["balanced", "conservative", "shedding"])
def test_courtesy_does_not_block_necessary_cover(style):
    top = pattern(3, 1)
    state = GameState(
        level=2,
        wild_card=None,
        hands=[cards(14, 1) + cards(5), cards(4) * 4, cards(6) * 3, cards(7, 1)],
        turn_index=0,
        leader=2,
        table=[top],
        history=[TurnPlayed(2, top, 6)],
    )
    action = _rollout_select_pattern(
        state, 0, rollout_strategy_level=2, style=style, partner_adaptation=True
    )
    assert action is not None and action.type == PatternType.SINGLE


def test_style_changes_ordinary_costly_reply_and_pass():
    top = pattern(4, 1)
    state = GameState(
        level=2,
        wild_card=None,
        hands=[cards(8, 4) + cards(3), cards(6) * 4, cards(7) * 4, cards(9) * 4],
        turn_index=0,
        leader=1,
        table=[top],
        history=[TurnPlayed(1, top, 8)],
    )
    assert (
        _rollout_select_pattern(
            state, 0, rollout_strategy_level=2, style="conservative", partner_adaptation=True
        )
        is None
    )
    assert (
        _rollout_select_pattern(
            state, 0, rollout_strategy_level=2, style="shedding", partner_adaptation=True
        )
        is not None
    )


@pytest.mark.parametrize("kind", [PatternType.STRAIGHT_FLUSH, PatternType.BOMB])
def test_style_cannot_change_legal_finish(kind):
    material = (
        tuple(cards(8, 4))
        if kind == PatternType.BOMB
        else tuple(Card(r, Suit.CLUBS) for r in range(3, 8))
    )
    state = GameState(
        level=2,
        wild_card=None,
        hands=[list(material), cards(9) * 4, cards(10) * 4, cards(11) * 4],
        turn_index=0,
        leader=0,
    )
    actions = [
        _rollout_select_pattern(
            state, 0, rollout_strategy_level=2, style=style, partner_adaptation=True
        )
        for style in ("balanced", "conservative", "shedding")
    ]
    assert all(action is not None and len(action.cards) == len(material) for action in actions)


def test_interrupted_common_round_is_discarded(monkeypatch):
    fixed_worlds(monkeypatch)
    state = make_initial_state(seed=200004)
    actions = enumerate_legal_patterns(state, 0)[:2]
    report, diagnostic = evaluate_responses(
        state, 0, actions, rng=random.Random(1), worlds=4, deadline=time.perf_counter() - 1
    )
    assert (
        not report
        and diagnostic["completed_worlds"] == 0
        and diagnostic["reason"] == "budget_limited"
    )
    ticks = iter([0.0] * 5 + [2.0] * 100)
    monkeypatch.setattr("guandan.ai.response_chain.time.perf_counter", lambda: next(ticks))
    report, diagnostic = evaluate_responses(
        state, 0, actions, rng=random.Random(1), worlds=4, deadline=1.0
    )
    assert not report and diagnostic["completed_worlds"] == 0


def test_expired_chain_budget_skips_candidate_preparation(monkeypatch):
    state = make_initial_state(seed=200004)
    reference = enumerate_legal_patterns(state, 0)[0]

    def forbidden(*args, **kwargs):
        raise AssertionError("candidate preparation started after the deadline")

    monkeypatch.setattr("guandan.ai.response_chain.enumerate_legal_patterns", forbidden)
    assert chain_candidates(state, 0, [reference], limit=6, deadline=time.perf_counter() - 1) == [
        reference
    ]


def test_root_style_distribution_is_computed_once(monkeypatch):
    import guandan.ai.mcts.root_search as root

    state = make_initial_state(seed=200005)
    original = root.style_distribution
    calls = []

    def measure(s):
        calls.append(s)
        return original(s)

    monkeypatch.setattr(root, "style_distribution", measure)
    result = root_action_search(
        state, 0, rng=random.Random(4), iterations=24, partner_adaptation=True, response_chain=True
    )
    assert len(calls) == 1 and len(result.partner_probabilities) == 4
    assert result.response_chain is not None and result.response_chain["completed_worlds"] == 4


def test_new_switches_default_off_and_do_not_reach_lower_tiers():
    assert not ProfessionalStrategy().partner_adaptation
    assert not ProfessionalStrategy().response_chain
    policy = DaiChangshengStrategy()
    assert not policy.partner_adaptation and not policy.response_chain


@pytest.mark.parametrize("tier", [3, 4])
def test_experimental_root_decision_uses_no_real_hidden_cards(tier):
    state = make_initial_state(seed=200006)
    changed = copy.deepcopy(state)
    for seat in (1, 2, 3):
        changed.hands[seat] = cards(12, 1) * state.hand_size(seat)
    changed.history = [
        replace(e, seed=12345) if isinstance(e, ShuffleDeal) else e for e in changed.history
    ]

    def choose(s):
        policy = (
            ProfessionalStrategy(
                iterations=24,
                time_budget_ms=0,
                rng=random.Random(10),
                partner_adaptation=True,
                response_chain=True,
            )
            if tier == 3
            else DaiChangshengStrategy(
                rng=random.Random(10),
                mcts_overrides={
                    "iterations": 24,
                    "time_budget_ms": 0,
                    "partner_adaptation": 1,
                    "response_chain": 1,
                },
            )
        )
        return policy.select_pattern(s, 0), policy.last_search

    first, first_report = choose(state)
    second, second_report = choose(changed)
    assert first == second
    assert first_report.actions == second_report.actions
    assert first_report.response_chain["ownership"] == second_report.response_chain["ownership"]


def test_passing_hands_control_to_the_partner(monkeypatch):
    fixed_worlds(monkeypatch)
    top = pattern(14)
    state = GameState(
        level=2,
        wild_card=None,
        hands=[cards(3), cards(4), cards(5), cards(6)],
        turn_index=0,
        leader=2,
        table=[top],
        history=[TurnPlayed(2, top, 2)],
    )
    report, _ = evaluate_responses(state, 0, [None], rng=random.Random(1), worlds=4)
    assert report[action_key(None)].partner_control == 1.0


def test_jiefeng_records_the_finished_players_partner_as_owner(monkeypatch):
    fixed_worlds(monkeypatch)
    top = pattern(14)
    state = GameState(
        level=2,
        wild_card=None,
        hands=[[], cards(4), cards(5), cards(6)],
        turn_index=3,
        leader=0,
        table=[top],
        finish_order=[0],
        history=[TurnPlayed(0, top, 0)],
    )
    report, _ = evaluate_responses(state, 3, [None], rng=random.Random(1), worlds=4)
    assert report[action_key(None)].opponent_control == 1.0


def test_completed_worlds_survive_a_later_interrupted_round(monkeypatch):
    fixed_worlds(monkeypatch)
    state = GameState(
        level=2,
        wild_card=None,
        hands=[cards(12) + cards(11) + cards(3, 1), cards(4), cards(5), cards(6)],
        turn_index=0,
        leader=0,
    )
    now = [0.0]
    calls = []

    def reply(s, actor, **kwargs):
        calls.append(actor)
        # Two candidates, three passes each: world four starts at call 19.
        if len(calls) == 19:
            now[0] = 2.0
        return None

    monkeypatch.setattr("guandan.ai.response_chain.time.perf_counter", lambda: now[0])
    monkeypatch.setattr("guandan.ai.mcts.search._rollout_select_pattern", reply)
    reports, diagnostic = evaluate_responses(
        state, 0, [pattern(12), pattern(11)], rng=random.Random(1), worlds=4, deadline=1.0
    )
    assert diagnostic["completed_worlds"] == 3
    assert diagnostic["used"] and diagnostic["reason"] == "budget_limited"
    assert len(reports) == 2
    assert all(row.samples == 3 and row.own_control == 1.0 for row in reports.values())


@pytest.mark.parametrize("style", ["balanced", "conservative", "shedding"])
def test_courtesy_retains_a_short_partners_safe_pair_lead(style):
    top = pattern(10)
    state = GameState(
        level=2,
        wild_card=None,
        hands=[cards(12) + cards(3), cards(4) * 4, cards(5, 1), cards(6) * 4],
        turn_index=0,
        leader=2,
        table=[top],
        history=[TurnPlayed(2, top, 1)],
    )
    assert (
        _rollout_select_pattern(
            state, 0, rollout_strategy_level=2, style=style, partner_adaptation=True
        )
        is None
    )


@pytest.mark.parametrize("size", [1, 2])
def test_partner_cover_handles_single_and_pair_exit_threats(size):
    top = pattern(3, size)
    state = GameState(
        level=2,
        wild_card=None,
        hands=[cards(14, size) + cards(5), cards(4) * 4, cards(6) * 3, cards(7, size)],
        turn_index=0,
        leader=2,
        table=[top],
        history=[TurnPlayed(2, top, 6)],
    )
    action = _rollout_select_pattern(
        state, 0, rollout_strategy_level=2, style="conservative", partner_adaptation=True
    )
    assert action is not None and len(action.cards) == size


def test_chain_styles_are_shared_by_all_candidates_in_each_world(monkeypatch):
    fixed_worlds(monkeypatch)
    state = GameState(
        level=2,
        wild_card=None,
        hands=[cards(12) + cards(11) + cards(3, 1), cards(4), cards(5), cards(6)],
        turn_index=0,
        leader=0,
    )
    draws = []
    replies = []

    def styles(s, rng, probabilities):
        row = ("balanced", "conservative", "shedding", "balanced")
        draws.append(row)
        return row

    def reply(s, actor, **kwargs):
        replies.append((len(draws), actor, kwargs["style"], kwargs["partner_adaptation"]))
        return None

    monkeypatch.setattr("guandan.ai.response_chain.sample_styles", styles)
    monkeypatch.setattr("guandan.ai.mcts.search._rollout_select_pattern", reply)
    reports, _ = evaluate_responses(
        state,
        0,
        [pattern(12), pattern(11)],
        rng=random.Random(1),
        worlds=4,
        partner_adaptation=True,
        probabilities=style_distribution(state),
    )
    assert len(draws) == 4 and len(reports) == 2
    for world in range(1, 5):
        calls = [row for row in replies if row[0] == world]
        assert len(calls) == 6
        assert calls[:3] == calls[3:]
        assert all(
            style == draws[world - 1][actor] and adaptation for _, actor, style, adaptation in calls
        )


@pytest.mark.parametrize("style", ["balanced", "conservative", "shedding"])
@pytest.mark.parametrize("leading", [False, True])
def test_each_simulated_actor_uses_only_own_cards_and_public_information(style, leading):
    straight = Pattern(
        PatternType.STRAIGHT, 7, 5, tuple(Card(rank, Suit.CLUBS) for rank in range(3, 8))
    )
    state = GameState(
        level=2,
        wild_card=None,
        hands=[
            [Card(rank, Suit.SPADES) for rank in range(4, 9)] + cards(12),
            cards(4) * 4,
            cards(5) * 4,
            cards(6) * 4,
        ],
        turn_index=0,
        leader=0 if leading else 1,
        table=[] if leading else [straight],
        history=[] if leading else [TurnPlayed(1, straight, 8)],
    )
    changed = copy.deepcopy(state)
    for seat in (1, 2, 3):
        changed.hands[seat] = cards(14, 1) * state.hand_size(seat)
    first = _rollout_select_pattern(
        state, 0, rollout_strategy_level=2, style=style, partner_adaptation=True
    )
    second = _rollout_select_pattern(
        changed, 0, rollout_strategy_level=2, style=style, partner_adaptation=True
    )
    assert first == second


def test_wildcard_response_is_legal():
    wild = Card(2, Suit.HEARTS)
    top = pattern(7)
    state = GameState(
        level=2,
        wild_card=wild,
        hands=[[*cards(8, 1), wild, *cards(3, 1)], cards(4) * 4, cards(5) * 4, cards(6) * 4],
        turn_index=0,
        leader=1,
        table=[top],
        history=[TurnPlayed(1, top, 8)],
    )
    action = _rollout_select_pattern(
        state, 0, rollout_strategy_level=2, style="shedding", partner_adaptation=True
    )
    assert action is not None
    play_pattern(clone_state_for_search(state), 0, action)
