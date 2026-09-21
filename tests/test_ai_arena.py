"""Paired AI arena tests."""
from __future__ import annotations

import json

import pytest

from guandan.ai.arena import (
    elo_from_win_rate,
    evaluate_arena_gate,
    main,
    run_arena,
    wilson_interval,
)


def test_wilson_interval_and_elo_are_well_formed() -> None:
    low, high = wilson_interval(60, 100)

    assert 0.0 < low < 0.60 < high < 1.0
    assert elo_from_win_rate(0.5) == pytest.approx(0.0)
    assert elo_from_win_rate(0.6) > 0.0


def test_run_arena_swaps_candidate_team_on_same_deal() -> None:
    summary = run_arena(
        deals=1,
        seed_start=1200,
        candidate_difficulty=0,
        baseline_difficulty=0,
    )

    assert summary.games == 2
    assert [leg.seed for leg in summary.legs] == [1200, 1200]
    assert [leg.candidate_team for leg in summary.legs] == [0, 1]
    assert summary.candidate_wins + summary.baseline_wins == 2
    assert summary.incomplete == 0
    assert summary.candidate_decision_seconds
    assert 0.0 <= summary.confidence_low <= summary.confidence_high <= 1.0


def test_run_arena_supports_full_matches_through_ace() -> None:
    summary = run_arena(
        deals=1,
        seed_start=1210,
        candidate_difficulty=0,
        baseline_difficulty=0,
        full_match=True,
    )

    assert summary.full_match is True
    assert summary.games == 2
    assert summary.incomplete == 0
    assert all(leg.match.finished for leg in summary.legs)
    assert all(leg.match.winner_team in (0, 1) for leg in summary.legs)
    assert all(leg.level_margin in (-1, 1) for leg in summary.legs)


def test_deterministic_arena_marks_fixed_iteration_mode() -> None:
    summary = run_arena(
        deals=1,
        seed_start=1211,
        candidate_difficulty=0,
        baseline_difficulty=0,
        deterministic_search=True,
    )

    assert summary.deterministic_search is True


def test_fixed_iteration_factory_uses_the_documented_ceilings() -> None:
    """The 32/96 branch must exercise both production root-search ceilings.

    docs/ai.md advertises 32 evaluations for Professional and 96 for Dai
    Changsheng in `--deterministic-search` mode; without an assertion the
    branch could be deleted and the whole suite stayed green.
    """
    from guandan.ai.arena import CALIBRATED_ITERATIONS, fixed_iteration_strategy_factory

    assert CALIBRATED_ITERATIONS == {3: 32, 4: 96}

    professional = fixed_iteration_strategy_factory(3, 0)
    assert professional.iterations == 32
    assert professional.time_budget_ms == 0
    assert professional.search_mode == "root"

    dai = fixed_iteration_strategy_factory(4, 0)
    assert dai.iterations == 96
    assert dai.time_budget_ms == 0

    # Lower tiers fall through to the production factory unchanged.
    novice = fixed_iteration_strategy_factory(0, 0)
    assert novice.difficulty == 0


def test_production_budgets_match_the_documented_values() -> None:
    """docs/ai.md claims 240ms for level 3 and 420ms for level 4."""
    from guandan.ai.mcts import MCTS_CONFIG
    from guandan.ai.profiles import load_profile

    assert MCTS_CONFIG["time_budget_ms"] == 240
    assert MCTS_CONFIG["iterations"] == 32
    assert MCTS_CONFIG["search_mode"] == "root"
    assert MCTS_CONFIG["rollout_strategy"] == 1
    assert MCTS_CONFIG["top_actions"] == 6

    profile = load_profile("dachangsheng")
    assert profile["mcts"]["time_budget_ms"] == 420
    assert profile["mcts"]["iterations"] == 96
    assert profile["mcts"]["search_mode"] == "root"
    assert profile["mcts"]["rollout_strategy"] == 1
    assert profile["mcts"]["top_actions"] == 6
    assert profile["mcts"]["max_depth"] == 14


def test_arena_gate_checks_completion_strength_and_latency() -> None:
    summary = run_arena(
        deals=1,
        seed_start=1201,
        candidate_difficulty=0,
        baseline_difficulty=0,
    )

    gate = evaluate_arena_gate(summary, min_win_rate=1.1, max_p95_seconds=0.0)

    assert gate.passed is False
    assert any("candidate_win_rate" in failure for failure in gate.failures)
    assert any("candidate_p95_seconds" in failure for failure in gate.failures)

    # A reachable threshold must be evaluated too, otherwise the assertions
    # above only prove that "impossible" always fails.
    reachable = evaluate_arena_gate(
        summary, min_win_rate=0.0, min_confidence_low=0.0, max_p95_seconds=float("inf")
    )
    assert reachable.passed is True
    assert reachable.failures == ()


def test_arena_cli_json_is_parseable(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(
        [
            "--candidate",
            "0",
            "--baseline",
            "0",
            "--deals",
            "1",
            "--seed-start",
            "1202",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["games"] == 2
    assert payload["passed"] is True


class TestActionValueBaselineTool:
    """The baseline tool's statistics must be right, since every measurement
    below it depends on the interval being honest."""

    def test_wilson_interval_brackets_the_point_estimate(self):
        from scripts.action_value_baseline import wilson_interval

        for wins, n in ((0, 400), (100, 400), (200, 400), (399, 400), (400, 400)):
            low, high = wilson_interval(wins, n)
            assert 0.0 <= low <= wins / n <= high <= 1.0

    def test_wilson_interval_narrows_with_more_samples(self):
        from scripts.action_value_baseline import wilson_interval

        narrow = wilson_interval(200, 400)
        wide = wilson_interval(20, 40)
        assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])

    def test_wilson_interval_handles_zero_samples(self):
        from scripts.action_value_baseline import wilson_interval

        assert wilson_interval(0, 0) == (0.0, 1.0)

    def test_playout_is_reproducible_for_a_fixed_seed(self):
        """Ground-truth labels must be reproducible, or the baseline is useless."""
        from guandan.ai.mcts import information_set as IS
        from scripts.action_value_baseline import (
            _init_worker,
            _playout,
            sample_positions,
        )

        sampled = sample_positions(1, min_cards=10, max_cards=16)
        assert sampled, "no position sampled"
        seed, state = sampled[0]
        positions = {seed: state}
        candidates = {
            seed: IS.enumerate_search_candidates(state, 0, max_candidates=3)
        }
        assert candidates[seed], "no candidates"
        _init_worker(positions, candidates)

        first = [_playout((seed, 0, k)) for k in range(5)]
        second = [_playout((seed, 0, k)) for k in range(5)]
        assert first == second
        assert all(r[2] in (0, 1, None) for r in first)

    def test_baseline_candidates_cover_pass_and_greedy(self):
        """Paired evaluation must not drop actions a measured policy can choose."""
        from guandan.ai.candidates import smallest_legal_pattern
        from scripts.action_value_baseline import (
            _action_key,
            _baseline_candidates,
            sample_positions,
        )

        _, state = sample_positions(
            1,
            min_candidates=3,
            max_candidates=6,
        )[0]
        candidates = _baseline_candidates(state, 0, max_candidates=6)
        keys = [_action_key(candidate) for candidate in candidates]

        assert len(keys) == len(set(keys))
        if state.table:
            assert _action_key(None) in keys
        greedy = smallest_legal_pattern(state, 0)
        assert greedy is not None
        assert _action_key(greedy) in keys
