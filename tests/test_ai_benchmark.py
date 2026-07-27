"""AI benchmark 工具测试。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from guandan.ai.benchmark import (
    compare_benchmark_payloads,
    evaluate_benchmark_gate,
    load_benchmark_payload,
    main,
    run_benchmark,
    run_full_match,
    run_match,
)
from guandan.engine.state import team_of


def test_run_match_returns_reusable_result() -> None:
    result = run_match(
        123,
        level=2,
        difficulties=(0, 0, 0, 0),
        max_turns=2000,
    )

    assert result.seed == 123
    assert result.difficulties == (0, 0, 0, 0)
    assert result.turns > 0
    assert result.finished is True
    assert result.winner_team in (0, 1)
    assert len(result.finish_order) == 3


def test_run_benchmark_summarizes_games() -> None:
    summary = run_benchmark(
        games=2,
        seed_start=200,
        level=2,
        difficulties=0,
        max_turns=2000,
    )

    assert summary.games == 2
    assert summary.finished == 2
    assert summary.completion_rate == 1.0
    assert len(summary.results) == 2
    assert sum(summary.team_wins) == 2
    assert summary.average_turns > 0


def test_run_full_match_from_two_through_successful_ace() -> None:
    result = run_full_match(
        314,
        level=2,
        difficulties=0,
        max_rounds=64,
        max_turns=2000,
    )

    assert result.finished is True
    assert result.winner_team in (0, 1)
    assert 2 <= result.rounds <= 64
    assert result.turns > result.rounds
    assert result.tribute_rounds > 0
    assert len(result.round_results) == result.rounds
    assert all(round_result.finished for round_result in result.round_results)
    for previous, current in zip(result.round_results, result.round_results[1:]):
        assert previous.final_levels is not None
        head_team = team_of(previous.finish_order[0])
        assert current.level == previous.final_levels[head_team]

    payload = result.to_dict()
    assert payload["finished"] is True
    assert len(payload["round_results"]) == result.rounds
    json.dumps(payload)


def test_full_match_cli_reports_unfinished_limit_as_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "--full-match",
            "--seed-start",
            "315",
            "--difficulties",
            "0",
            "--max-rounds",
            "1",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["finished"] is False
    assert payload["rounds"] == 1


def test_benchmark_summary_to_dict_is_json_friendly() -> None:
    summary = run_benchmark(
        games=1,
        seed_start=210,
        level=2,
        difficulties=0,
        max_turns=2000,
    )

    payload = summary.to_dict()

    assert payload["games"] == 1
    assert isinstance(payload["team_wins"], list)
    assert isinstance(payload["results"][0]["difficulties"], list)
    json.dumps(payload)


def test_main_json_outputs_parseable_payload(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(
        [
            "--games",
            "1",
            "--seed-start",
            "220",
            "--difficulties",
            "0",
            "--max-turns",
            "2000",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["games"] == 1
    assert payload["results"][0]["seed"] == 220


def test_compare_benchmark_payloads_summarizes_deltas() -> None:
    baseline = {
        "games": 10,
        "completion_rate": 0.8,
        "team_wins": [3, 5],
        "average_turns": 160.0,
        "average_bombs": [1.0, 2.0],
        "results": [{"duration_seconds": 1.0}, {"duration_seconds": 3.0}],
    }
    current = {
        "games": 10,
        "completion_rate": 1.0,
        "team_wins": [6, 4],
        "average_turns": 140.0,
        "average_bombs": [1.5, 1.5],
        "results": [{"duration_seconds": 0.5}, {"duration_seconds": 1.5}],
    }

    comparison = compare_benchmark_payloads(baseline, current)

    assert comparison.completion_rate_delta == pytest.approx(0.2)
    assert comparison.team0_win_rate_delta == pytest.approx(0.3)
    assert comparison.team1_win_rate_delta == pytest.approx(-0.1)
    assert comparison.average_turns_delta == pytest.approx(-20.0)
    assert comparison.average_duration_delta == pytest.approx(-1.0)
    assert comparison.average_bombs_delta == pytest.approx((0.5, -0.5))


def test_evaluate_benchmark_gate_passes_within_thresholds() -> None:
    comparison = compare_benchmark_payloads(
        {
            "games": 10,
            "completion_rate": 0.9,
            "team_wins": [5, 4],
            "average_turns": 120.0,
            "average_bombs": [1.0, 1.0],
            "results": [{"duration_seconds": 2.0}],
        },
        {
            "games": 10,
            "completion_rate": 0.85,
            "team_wins": [4, 4],
            "average_turns": 125.0,
            "average_bombs": [1.0, 1.0],
            "results": [{"duration_seconds": 2.2}],
        },
    )

    gate = evaluate_benchmark_gate(
        comparison,
        max_completion_drop=0.10,
        max_duration_increase=0.50,
        max_turn_increase=10,
    )

    assert gate.passed is True
    assert gate.failures == ()


def test_evaluate_benchmark_gate_reports_failures() -> None:
    comparison = compare_benchmark_payloads(
        {
            "games": 10,
            "completion_rate": 1.0,
            "team_wins": [5, 5],
            "average_turns": 100.0,
            "average_bombs": [1.0, 1.0],
            "results": [{"duration_seconds": 1.0}],
        },
        {
            "games": 10,
            "completion_rate": 0.7,
            "team_wins": [4, 3],
            "average_turns": 130.0,
            "average_bombs": [1.0, 1.0],
            "results": [{"duration_seconds": 3.0}],
        },
    )

    gate = evaluate_benchmark_gate(
        comparison,
        max_completion_drop=0.10,
        max_duration_increase=0.50,
        max_turn_increase=10,
    )

    assert gate.passed is False
    assert len(gate.failures) == 3
    assert "completion_rate_drop" in gate.failures[0]


def test_load_benchmark_payload_requires_object(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError):
        load_benchmark_payload(path)


def test_main_compare_json_outputs_parseable_payload(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = run_benchmark(
        games=1,
        seed_start=230,
        level=2,
        difficulties=0,
        max_turns=2000,
    ).to_dict()
    current = run_benchmark(
        games=1,
        seed_start=231,
        level=2,
        difficulties=0,
        max_turns=2000,
    ).to_dict()
    baseline_path = tmp_path / "baseline.json"
    current_path = tmp_path / "current.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    current_path.write_text(json.dumps(current), encoding="utf-8")

    exit_code = main(
        [
            "--compare",
            str(baseline_path),
            str(current_path),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["baseline_games"] == 1
    assert payload["current_games"] == 1
    assert "average_duration_delta" in payload
    assert payload["passed"] is True


def test_main_compare_json_returns_failure_for_gate_regression(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline_path = tmp_path / "baseline.json"
    current_path = tmp_path / "current.json"
    baseline_path.write_text(
        json.dumps(
            {
                "games": 1,
                "completion_rate": 1.0,
                "team_wins": [1, 0],
                "average_turns": 100.0,
                "average_bombs": [0.0, 0.0],
                "results": [{"duration_seconds": 1.0}],
            }
        ),
        encoding="utf-8",
    )
    current_path.write_text(
        json.dumps(
            {
                "games": 1,
                "completion_rate": 0.0,
                "team_wins": [0, 0],
                "average_turns": 150.0,
                "average_bombs": [0.0, 0.0],
                "results": [{"duration_seconds": 4.0}],
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--compare",
            str(baseline_path),
            str(current_path),
            "--fail-completion-drop",
            "0.1",
            "--fail-duration-increase",
            "1.0",
            "--fail-turn-increase",
            "10",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 1
    assert payload["passed"] is False
    assert len(payload["failures"]) == 3


def test_run_benchmark_requires_positive_games() -> None:
    with pytest.raises(ValueError):
        run_benchmark(games=0)


@pytest.mark.parametrize("max_rounds,max_turns", [(0, 2000), (64, 0)])
def test_run_full_match_requires_positive_limits(max_rounds: int, max_turns: int) -> None:
    with pytest.raises(ValueError):
        run_full_match(1, difficulties=0, max_rounds=max_rounds, max_turns=max_turns)


def test_checked_in_mixed_baseline_has_stable_configuration() -> None:
    baseline_path = Path(__file__).parents[1] / "benchmarks" / "v0.8.0b1-mixed-20.json"
    payload = load_benchmark_payload(baseline_path)

    assert payload["games"] == 20
    assert payload["finished"] == 20
    assert payload["completion_rate"] == 1.0
    assert [result["seed"] for result in payload["results"]] == list(range(800, 820))
    assert all(result["difficulties"] == [0, 1, 2, 3] for result in payload["results"])
