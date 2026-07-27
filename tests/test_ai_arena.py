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
