"""Self-play style tuner tests."""
from __future__ import annotations

from guandan.ai.arena import ArenaSummary
from guandan.ai.tuning import (
    StyleParameters,
    _strategy_factory,
    generate_style_candidates,
    tune_dai_style,
    tuning_score,
)


def _summary(win_rate: float, margin: float = 0.0) -> ArenaSummary:
    games = 10
    wins = round(win_rate * games)
    return ArenaSummary(
        candidate_difficulty=4,
        baseline_difficulty=3,
        deals=5,
        legs=(),
        candidate_wins=wins,
        baseline_wins=games - wins,
        incomplete=0,
        candidate_win_rate=win_rate,
        confidence_low=0.0,
        confidence_high=1.0,
        elo_delta=0.0,
        average_level_margin=margin,
        candidate_decision_seconds=(0.1, 0.2),
    )


def test_style_candidates_are_deterministic_and_bounded() -> None:
    first = generate_style_candidates(5, seed=88)
    second = generate_style_candidates(5, seed=88)

    assert first == second
    assert len(set(first)) == 5
    assert first[0] == StyleParameters(0.25, 0.85, 0.50)
    assert all(0.20 <= candidate.bomb_threshold <= 0.85 for candidate in first)


def test_tuning_factory_uses_fixed_iteration_budgets() -> None:
    factory = _strategy_factory(StyleParameters(0.4, 0.8, 0.6))

    candidate = factory(4, 0)
    baseline = factory(3, 1)

    assert candidate.time_budget_ms == 0
    assert candidate.iterations == 48
    assert baseline.time_budget_ms == 0
    assert baseline.iterations == 28


def test_tuning_score_prefers_wins_then_level_margin() -> None:
    assert tuning_score(_summary(0.6, 0.0)) > tuning_score(_summary(0.5, 1.0))
    assert tuning_score(_summary(0.5, 1.0)) > tuning_score(_summary(0.5, 0.0))


def test_tuner_uses_independent_final_stage() -> None:
    calls: list[int] = []

    def fake_runner(**kwargs):
        calls.append(kwargs["seed_start"])
        return _summary(0.5 + len(calls) * 0.01)

    result = tune_dai_style(
        candidate_count=3,
        screening_deals=1,
        finalists=2,
        final_deals=1,
        seed_start=77,
        arena_runner=fake_runner,
    )

    assert len(result.trials) == 5
    assert calls[:3] == [77, 77, 77]
    assert calls[3:] == [100_077, 100_077]
    assert result.best in {trial.parameters for trial in result.trials[-2:]}
