"""Independent data lineage and rejection gates are part of model correctness."""
from __future__ import annotations

import json
import random
from collections import Counter

import pytest

from scripts.ai_action_ranker_validation import (
    COUNTS,
    development_gate,
    promotion_gate,
    validate_pairs,
)
from scripts.fit_action_ranker import RECIPE, derived_seed, label_recipe, split_for


def clock(passed=True):
    return {"records": [{"tier": 3, "passed": passed}],
            "consecutive_actions": [{"tier": 3, "passed": passed} for _ in range(3)]}


def test_deal_splits_and_all_experiment_seed_namespaces_are_disjoint():
    assert dict(Counter(split_for(i) for i in range(576))) == RECIPE["splits"]
    seeds = {derived_seed("dataset", i) for i in range(576)}
    count = len(seeds)
    for tier in (3, 4):
        for suite, pairs in COUNTS.items():
            block = {derived_seed(f"{suite}-{tier}", i) for i in range(pairs)}
            assert not seeds & block
            seeds.update(block)
            count += pairs
            if suite == "full":
                for master in block:
                    deals = {derived_seed("full-deal", master, offset) for offset in range(64)}
                    assert len(deals) == 64 and not seeds & deals
                    seeds.update(deals)
                    count += 64
    assert len(seeds) == count
    with pytest.raises(ValueError):
        split_for(576)


@pytest.mark.parametrize("field", ["team", "mixed", "diagnostic", "clock", "size"])
def test_each_development_condition_is_required(field):
    team = {"pairs": 32, "mean_paired_gain": 0.01}
    mixed = dict(team)
    diagnostic = {"diagnostic_improved": True}
    assert development_gate(team, mixed, diagnostic, clock(), 3)
    if field == "team":
        team["mean_paired_gain"] = 0
    elif field == "mixed":
        mixed["mean_paired_gain"] = -0.01
    elif field == "size":
        team["pairs"] = 31
    elif field == "diagnostic":
        diagnostic["diagnostic_improved"] = False
    assert not development_gate(team, mixed, diagnostic, clock(field != "clock"), 3)


def test_promotion_requires_actual_full_match_interval_and_completion():
    team = {"pairs": 240, "gain_confidence_95": [0.01, 0.1]}
    mixed = {**team, "by_companion": {str(i): {"mean_paired_gain": 0.01} for i in range(3)}}
    full = {"pairs": 48, "games": 96, "match_win_confidence_95": [0.51, 0.7],
            "observations": [{"result": {"finished": True}} for _ in range(96)]}
    assert promotion_gate(team, mixed, full, clock(), 3)
    full["match_win_confidence_95"][0] = 0.5
    assert not promotion_gate(team, mixed, full, clock(), 3)
    full["match_win_confidence_95"][0] = 0.51
    full["observations"][0]["result"]["finished"] = False
    assert not promotion_gate(team, mixed, full, clock(), 3)


def test_frozen_baseline_is_verified_before_labeling(tmp_path):
    from scripts.fit_action_ranker import snapshot_fingerprint

    source = tmp_path / "src/guandan/ai/profiles"
    source.mkdir(parents=True)
    value = source / "match_value.json"
    value.write_text("{}")
    import hashlib

    manifest = {"source_sha256": snapshot_fingerprint(tmp_path),
                "match_value_sha256": hashlib.sha256(value.read_bytes()).hexdigest()}
    (tmp_path / "policy-snapshot.json").write_text(json.dumps(manifest))
    assert label_recipe(tmp_path)["baseline_sha256"] == manifest["source_sha256"]
    value.write_text('{"changed": true}')
    with pytest.raises(ValueError, match="baseline has changed"):
        label_recipe(tmp_path)


@pytest.mark.parametrize("corruption", ["missing", "duplicate_team", "unfinished", "extra"])
def test_raw_trial_pairs_require_exact_predeclared_swaps(corruption):
    rows = [{"seed": 321, "candidate_team": team, "result": {"finished": True}} for team in (0, 1)]
    validate_pairs(rows, [321])
    if corruption == "missing":
        rows.pop()
    elif corruption == "duplicate_team":
        rows[1]["candidate_team"] = 0
    elif corruption == "unfinished":
        rows[1]["result"]["finished"] = False
    else:
        rows.append({"seed": 322, "candidate_team": 0, "result": {"finished": True}})
    with pytest.raises(ValueError, match="trial"):
        validate_pairs(rows, [321])


def test_pair_labels_use_common_world_differences_and_companion_mean(monkeypatch):
    from scripts import fit_action_ranker as trainer

    np = pytest.importorskip("numpy")
    monkeypatch.setattr(trainer, "position_features", lambda row: [[0.0], [1.0]])
    base = [0.1 if world % 2 else 0.6 for world in range(32)]
    preferred = [value + 0.1 for value in base]
    row = {"actions": [{"values": [base, base, base]},
                       {"values": [preferred, preferred, preferred]}]}
    differences, targets = trainer.pair_examples([{"positions": [row]}])
    assert differences.tolist() == [[1.0]]
    assert targets[0] > 0.99  # Shared world noise cancels exactly.
    row["actions"][1]["values"] = [preferred, base, [value - 0.1 for value in base]]
    _, targets = trainer.pair_examples([{"positions": [row]}])
    assert np.isclose(targets[0], 0.5)


def test_regularized_pair_fit_learns_order_and_does_not_reward_ties():
    from scripts.fit_action_ranker import fit_weights

    np = pytest.importorskip("numpy")
    x = np.array([[1.0, 0.0], [-1.0, 0.0], [0.0, 1.0]])
    targets = np.array([0.9, 0.1, 0.5])
    small = fit_weights(x, targets, 0.001)
    large = fit_weights(x, targets, 0.1)
    assert small[0] > large[0] > 0 and small[1] == large[1] == 0


@pytest.mark.parametrize("before", [0, 2])
def test_label_utility_distinguishes_third_failed_ace_attempt(before):
    from guandan.ai.match_value import continuation_value
    from guandan.engine.card import Card, Suit
    from guandan.engine.state import GameState, _finish_game
    from scripts.fit_action_ranker import frozen_playout

    state = GameState(level=14, wild_card=None, team_levels=[14, 9],
                      a_failure_counts=[before, 0], hands=[[], [], [Card(3, Suit.CLUBS)], []],
                      finish_order=[0, 1, 3], turn_index=2)
    _finish_game(state)
    expected_level, expected_failures = (2, 0) if before == 2 else (14, 1)
    assert state.team_levels_final == [expected_level, 9]
    assert state.a_failure_counts == [expected_failures, 0]
    expected = continuation_value(state.team_levels_final, state.a_failure_counts, 0, 4, 0)
    assert frozen_playout(state, 0, 2, [], {}, {}) == expected


@pytest.mark.parametrize("companion", [0, 1, 2])
@pytest.mark.parametrize("level", [2, 9, 14])
def test_suffix_reuse_matches_complete_frozen_policy_execution(companion, level):
    from guandan.ai.candidates import enumerate_legal_patterns
    from guandan.ai.match_value import terminal_match_value
    from guandan.ai.mcts.information_set import _apply_action
    from guandan.ai.play import play_or_pass
    from guandan.ai.strategy import make_strategy
    from guandan.engine.state import clone_state_for_search, make_initial_state
    from scripts.fit_action_ranker import frozen_playout

    state = make_initial_state(level=level, seed=283100 + companion)
    policies = [make_strategy(tier) for tier in range(3)]
    rng = random.Random(83)
    for _ in range(40):
        if state.finished:
            break
        actor = state.current_player()
        play_or_pass(state, actor, policies[2], rng)
    if state.finished:
        return
    player = state.current_player()
    actions = enumerate_legal_patterns(state, player)[:3]
    memo, values = {}, {}
    for action in actions:
        branch = clone_state_for_search(state)
        assert _apply_action(branch, player, action)
        direct = clone_state_for_search(branch)
        while not direct.finished:
            actor = direct.current_player()
            play_or_pass(direct, actor, policies[companion if actor == (player + 2) % 4 else 2], rng)
        expected = terminal_match_value(direct, player % 2)
        assert frozen_playout(branch, player, companion, policies, memo, values) == expected
        # The second run must hit the suffix cache and produce the same value.
        again = clone_state_for_search(state)
        assert _apply_action(again, player, action)
        assert frozen_playout(again, player, companion, policies, memo, values) == expected
