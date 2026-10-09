"""Public-only ranking, atomic nomination, and conservative research boundaries."""
from __future__ import annotations

import copy
import hashlib
import json
import random
import time
from dataclasses import replace

import pytest

from guandan.ai import action_ranker as ranker
from guandan.ai.candidates import enumerate_legal_patterns, pattern_key, smallest_legal_pattern
from guandan.ai.mcts.root_search import (
    ranked_candidates,
    root_action_candidates,
    root_action_search,
)
from guandan.ai.play import play_or_pass
from guandan.ai.strategies.dachangsheng import DaiChangshengStrategy
from guandan.ai.strategies.professional import ProfessionalStrategy
from guandan.ai.strategy import make_strategy
from guandan.engine.card import Card, Suit
from guandan.engine.events import ShuffleDeal, TurnPlayed
from guandan.engine.hand import Pattern, PatternType
from guandan.engine.state import GameState, make_initial_state, pass_turn


def model(weights=None):
    return ranker.ActionRankerModel(tuple(weights or [0.0] * len(ranker.FEATURE_NAMES)), "test-model")


@pytest.mark.parametrize("level", [2, 9, 14])
@pytest.mark.parametrize("seat", range(4))
def test_observation_and_scores_ignore_hidden_hands_and_seed(level, seat):
    state = make_initial_state(level=level, first_player=seat, seed=281100 + seat)
    original = ranker.ActionObservation.from_state(state, seat)
    changed = copy.deepcopy(state)
    for other in range(4):
        if other != seat:
            changed.hands[other] = [Card(3, Suit.CLUBS)] * state.hand_size(other)
    changed.history = [replace(e, seed=987654321) if isinstance(e, ShuffleDeal) else e
                       for e in state.history]
    assert ranker.ActionObservation.from_state(changed, seat) == original
    weights = [random.Random(i).uniform(-1, 1) for i in range(len(ranker.FEATURE_NAMES))]
    actions = enumerate_legal_patterns(state, seat)[:12]
    assert ranker.score_actions(original, actions, model=model(weights)) == ranker.score_actions(
        ranker.ActionObservation.from_state(changed, seat), actions, model=model(weights))
    assert not hasattr(original, "history") and not hasattr(original, "seed")
    assert not hasattr(original, "hands")


def test_private_replacement_stays_invariant_after_public_plays():
    state = make_initial_state(seed=281113)
    policy = make_strategy(2)
    for _ in range(24):
        play_or_pass(state, state.current_player(), policy, random.Random(7))
    player = state.current_player()
    observation = ranker.ActionObservation.from_state(state, player)
    actions = enumerate_legal_patterns(state, player)
    changed = copy.deepcopy(state)
    for seat in range(4):
        if seat != player:
            changed.hands[seat] = [Card(101, Suit.BIG_JOKER)] * state.hand_size(seat)
    changed.history = [replace(event, seed=-999) if isinstance(event, ShuffleDeal) else event
                       for event in changed.history]
    other = ranker.ActionObservation.from_state(changed, player)
    assert other == observation
    weights = [0.2] * len(ranker.FEATURE_NAMES)
    assert ranker.score_actions(observation, actions, model=model(weights)) == ranker.score_actions(
        other, actions, model=model(weights))


def test_features_distinguish_material_suits_and_wild_consumption(monkeypatch):
    state = make_initial_state(level=9, seed=281102)
    state.hands[0] = [Card(5, Suit.CLUBS), Card(5, Suit.SPADES), Card(5, Suit.HEARTS),
                      Card(6, Suit.CLUBS), Card(7, Suit.CLUBS), Card(8, Suit.CLUBS),
                      Card(9, Suit.HEARTS)]
    pair = Pattern(PatternType.PAIR, 5, 1, (state.hands[0][0], state.hands[0][1]))
    variant = Pattern(PatternType.PAIR, 5, 1, (state.hands[0][1], state.hands[0][2]))
    wild_pair = Pattern(PatternType.PAIR, 5, 1, (state.hands[0][0], state.hands[0][-1]), wild_used=1)
    observation = ranker.ActionObservation.from_state(state, 0)

    def forbidden(*args, **kwargs):
        raise AssertionError("ranking must not plan or enumerate patterns")

    monkeypatch.setattr("guandan.ai.hand_plan.estimate_remaining_plays", forbidden)
    monkeypatch.setattr("guandan.engine.rules.patterns.detect_patterns", forbidden)
    first = ranker.action_features(observation, pair)
    assert len(first) == len(ranker.FEATURE_NAMES)
    assert first != ranker.action_features(observation, variant)
    assert ranker.action_features(observation, wild_pair)[ranker.FEATURE_NAMES.index("wild_used")] == 0.5


@pytest.mark.parametrize("own_a,enemy_a", [(14, 9), (9, 14), (14, 14)])
def test_a_failure_counts_interact_with_the_action(own_a, enemy_a):
    state = make_initial_state(level=14, team_levels=(own_a, enemy_a), seed=281103)
    action = enumerate_legal_patterns(state, 0)[0]
    previous = ranker.action_features(ranker.ActionObservation.from_state(state, 0), action)
    state.a_failure_counts = [2 if own_a == 14 else 0, 2 if enemy_a == 14 else 0]
    assert previous != ranker.action_features(ranker.ActionObservation.from_state(state, 0), action)


def test_nomination_preserves_reference_minimum_pass_and_finishes(monkeypatch):
    state = make_initial_state(seed=281104)
    player = state.current_player()
    legal = enumerate_legal_patterns(state, player)
    reference = make_strategy(2).select_pattern(state, player)
    baseline = root_action_candidates(state, player, max_actions=6, reference_actions=(reference,))
    existing = {pattern_key(p) for p in baseline if p}
    preferred = next(p for p in legal if pattern_key(p) not in existing)
    monkeypatch.setattr(ranker, "load_model", model)
    monkeypatch.setattr(ranker, "score_actions", lambda o, actions, **kw: [int(p == preferred) for p in actions])
    before = copy.deepcopy(state)
    new, report = ranked_candidates(state, player, baseline, (reference,), deadline=None)
    assert len(new) == len(baseline) and new is not baseline
    assert preferred in new and reference in new
    assert smallest_legal_pattern(state, player) in new
    assert report["candidate_replaced"] and report["reason"] == "nominated"
    assert baseline == root_action_candidates(state, player, max_actions=6, reference_actions=(reference,))
    assert state == before
    protected, no_space = ranked_candidates(state, player, [reference, None], (reference,), deadline=None)
    assert protected == [reference, None] and no_space["reason"] == "protected_pool"


@pytest.mark.parametrize("failure", [FileNotFoundError, ValueError, KeyError, TypeError, RuntimeError])
def test_bad_model_keeps_the_complete_original_pool(monkeypatch, failure):
    state = make_initial_state(seed=281105)
    pool = root_action_candidates(state, 0, max_actions=6)

    def broken():
        raise failure("bad research model")

    monkeypatch.setattr(ranker, "load_model", broken)
    returned, report = ranked_candidates(state, 0, pool, (), deadline=None)
    assert returned is pool and report["reason"] == "model_fallback"


def test_timeout_after_partial_scoring_does_not_apply_any_nomination(monkeypatch):
    state = make_initial_state(seed=281106)
    pool = root_action_candidates(state, 0, max_actions=6)
    monkeypatch.setattr(ranker, "load_model", model)

    def interrupted(*args, **kwargs):
        raise ranker.RankingTimeout("partial scoring")

    monkeypatch.setattr(ranker, "score_actions", interrupted)
    result, report = ranked_candidates(state, 0, pool, (), deadline=None)
    assert result is pool and report["reason"] == "budget_fallback"
    assert not report["candidate_replaced"]
    with pytest.raises(ranker.RankingTimeout):
        ranker.score_actions(ranker.ActionObservation.from_state(state, 0), [], deadline=0)


def test_disabled_ranking_does_not_load_model_or_change_rng(monkeypatch):
    state = make_initial_state(seed=281107)

    def forbidden():
        raise AssertionError("disabled ranking loaded weights")

    monkeypatch.setattr(ranker, "load_model", forbidden)
    rng = random.Random(88)
    other_rng = random.Random(88)
    result = root_action_search(state, 0, rng=rng, iterations=16, rollout_max_turns=4)
    other = root_action_search(state, 0, rng=other_rng, iterations=16,
                               rollout_max_turns=4, action_ranker=False)
    assert result.actions == other.actions and result.pattern == other.pattern
    assert rng.getstate() == other_rng.getstate()
    assert result.action_ranker is None
    assert not ProfessionalStrategy().action_ranker and not DaiChangshengStrategy().action_ranker
    with pytest.raises(ValueError, match="root search"):
        ProfessionalStrategy(search_mode="tree", action_ranker=True)


def test_model_compatibility_and_nonfinite_scores(tmp_path):
    payload = {"schema": 1, "ruleset_version": 3, "feature_version": ranker.FEATURE_VERSION,
               "feature_names": list(ranker.FEATURE_NAMES), "objective": "paired-action-ranking",
               "weights": [0.0] * len(ranker.FEATURE_NAMES),
               "meta": {"recipe": {"value_model_sha256": hashlib.sha256(
                   (ranker.MODEL_PATH.parent / "match_value.json").read_bytes()).hexdigest()}}}
    path = tmp_path / "model.json"
    path.write_text(json.dumps(payload))
    loaded = ranker.load_model(str(path))
    assert loaded.weights == model().weights
    ranker.load_model.cache_clear()
    payload["weights"][0] = float("nan")
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="coefficients"):
        ranker.load_model(str(path))
    ranker.load_model.cache_clear()
    payload["weights"][0] = 0
    payload["ruleset_version"] = 2
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="incompatible"):
        ranker.load_model(str(path))
    ranker.load_model.cache_clear()
    payload["ruleset_version"] = 3
    payload["meta"]["recipe"]["value_model_sha256"] = "changed"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="value model"):
        ranker.load_model(str(path))
    state = make_initial_state(seed=281108)
    with pytest.raises(ValueError, match="non-finite"):
        ranker.score_actions(ranker.ActionObservation.from_state(state, 0), [None],
                             model=model([float("nan")] * len(ranker.FEATURE_NAMES)))


@pytest.mark.parametrize("failure", ["empty", "nonfinite"])
def test_invalid_score_output_preserves_pool(monkeypatch, failure):
    state = make_initial_state(seed=281112)
    pool = root_action_candidates(state, 0, max_actions=6)
    monkeypatch.setattr(ranker, "load_model", model)
    monkeypatch.setattr(ranker, "score_actions", lambda o, actions, **kw:
                        [] if failure == "empty" else [float("nan")] * len(actions))
    result, report = ranked_candidates(state, 0, pool, (), deadline=None)
    assert result is pool and report["reason"] == "model_fallback"


def test_partner_top_and_urgent_cover_are_distinct_features():
    state = make_initial_state(seed=281109)
    top = Pattern(PatternType.SINGLE, 3, 1, (Card(3, Suit.CLUBS),))
    state.table = [top]
    state.history = [TurnPlayed(2, top, 20)]
    action = Pattern(PatternType.SINGLE, 14, 1, (Card(14, Suit.CLUBS),))
    state.hands[0] = [*action.cards, Card(5, Suit.CLUBS)]
    safe = ranker.action_features(ranker.ActionObservation.from_state(state, 0), action)
    state.hands[3] = state.hands[3][:1]
    urgent = ranker.action_features(ranker.ActionObservation.from_state(state, 0), action)
    assert safe != urgent
    assert urgent[ranker.FEATURE_NAMES.index("cards*enemy_one")] > 0


def test_features_can_rank_courtesy_and_necessary_cover_oppositely():
    # Synthetic coefficients check representability, not trained playing strength.
    top = Pattern(PatternType.SINGLE, 3, 1, (Card(3, Suit.CLUBS),))
    cover = Pattern(PatternType.SINGLE, 14, 1, (Card(14, Suit.CLUBS),))
    state = GameState(level=2, wild_card=None,
                      hands=[[*cover.cards, Card(5, Suit.CLUBS)], [Card(4, Suit.CLUBS)] * 8,
                             [Card(7, Suit.CLUBS)] * 2, [Card(6, Suit.CLUBS)] * 8],
                      table=[top], turn_index=0, leader=2, history=[TurnPlayed(2, top, 2)])
    weights = [0.0] * len(ranker.FEATURE_NAMES)
    weights[ranker.FEATURE_NAMES.index("pass")] = 1
    weights[ranker.FEATURE_NAMES.index("strength*enemy_one")] = 4
    safe = ranker.score_actions(ranker.ActionObservation.from_state(state, 0), [None, cover], model=model(weights))
    state.hands[3] = state.hands[3][:1]
    urgent = ranker.score_actions(ranker.ActionObservation.from_state(state, 0), [None, cover], model=model(weights))
    assert safe[0] > safe[1] and urgent[1] > urgent[0]


def test_ranking_observes_catch_wind_after_head_is_placed():
    top = Pattern(PatternType.SINGLE, 14, 1, (Card(14, Suit.CLUBS),))
    state = GameState(level=2, wild_card=None,
                      hands=[[Card(3, Suit.CLUBS), Card(5, Suit.CLUBS)], [Card(4, Suit.CLUBS)],
                             [], [Card(6, Suit.CLUBS)]], turn_index=3, leader=2,
                      table=[top], finish_order=[2], history=[TurnPlayed(2, top, 0)])
    for actor in (3, 1, 0):
        assert state.current_player() == actor
        pass_turn(state, actor)
    assert state.current_player() == 0 and not state.table
    observation = ranker.ActionObservation.from_state(state, 0)
    assert observation.top_relation == 0 and observation.finish_order == (2,)
    actions = enumerate_legal_patterns(state, 0)
    assert len(ranker.score_actions(observation, actions, model=model())) == len(actions)
    features = ranker.action_features(observation, actions[0])
    assert features[ranker.FEATURE_NAMES.index("cards*head_placed")] > 0


def test_short_hand_finish_is_never_replaced(monkeypatch):
    card = Card(5, Suit.CLUBS)
    state = GameState(level=2, wild_card=None, hands=[[card], [card], [card], [card]], turn_index=0)
    finish = Pattern(PatternType.SINGLE, 5, 1, (card,))
    monkeypatch.setattr(ranker, "load_model", model)
    new, report = ranked_candidates(state, 0, [finish], (finish,), deadline=None)
    assert new == [finish] and not report["candidate_replaced"]


def test_new_recommendation_cannot_evict_minimum_pass_or_full_hand(monkeypatch):
    hand = tuple(Card(rank, Suit.CLUBS) for rank in range(3, 8))
    top = Pattern(PatternType.SINGLE, 2, 1, (Card(2, Suit.DIAMONDS),))
    state = GameState(level=9, wild_card=None,
                      hands=[list(hand), [Card(8, Suit.CLUBS)], [Card(10, Suit.CLUBS)], [Card(11, Suit.CLUBS)]],
                      turn_index=0, leader=3, table=[top], history=[TurnPlayed(3, top, 1)])
    minimum = smallest_legal_pattern(state, 0)
    finish = Pattern(PatternType.STRAIGHT, 7, 5, hand)
    preferred = next(action for action in enumerate_legal_patterns(state, 0)
                     if action.type == PatternType.SINGLE and action.rank == 7)
    monkeypatch.setattr(ranker, "load_model", model)
    monkeypatch.setattr(ranker, "score_actions", lambda o, actions, **kw: [int(action == preferred) for action in actions])
    pool = [minimum, None, finish]
    new, report = ranked_candidates(state, 0, pool, (None,), deadline=None)
    assert new is pool and report["reason"] == "protected_pool"


def test_model_scores_have_a_cancellable_budget():
    state = make_initial_state(seed=281110)
    actions = enumerate_legal_patterns(state, 0)
    with pytest.raises(ranker.RankingTimeout):
        ranker.score_actions(ranker.ActionObservation.from_state(state, 0), actions,
                             model=model(), deadline=time.perf_counter() - 1)
