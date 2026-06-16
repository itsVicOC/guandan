"""AI benchmark 工具测试。"""
from __future__ import annotations

import json

import pytest

from guandan.ai.benchmark import main, run_benchmark, run_match


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


def test_run_benchmark_requires_positive_games() -> None:
    with pytest.raises(ValueError):
        run_benchmark(games=0)
