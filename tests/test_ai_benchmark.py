"""AI benchmark 工具测试。"""
from __future__ import annotations

import pytest

from guandan.ai.benchmark import run_benchmark, run_match


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


def test_run_benchmark_requires_positive_games() -> None:
    with pytest.raises(ValueError):
        run_benchmark(games=0)
