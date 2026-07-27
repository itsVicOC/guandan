"""Deterministic self-play tuning for the top AI style profile."""
from __future__ import annotations

import argparse
import json
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .arena import (
    ArenaSummary,
    run_arena,
)
from .benchmark import StrategyFactory, _latency_payload
from .strategies.dachangsheng import DaiChangshengStrategy
from .strategies.professional import ProfessionalStrategy
from .strategy import make_strategy

ArenaRunner = Callable[..., ArenaSummary]
TUNING_ITERATIONS = {3: 28, 4: 48}


@dataclass(frozen=True)
class StyleParameters:
    """Search-prior parameters tuned without changing rule semantics."""

    bomb_threshold: float
    teammate_awareness: float
    control_priority: float

    def to_dict(self) -> dict[str, float]:
        return {
            "bomb_threshold": round(self.bomb_threshold, 6),
            "teammate_awareness": round(self.teammate_awareness, 6),
            "control_priority": round(self.control_priority, 6),
        }


@dataclass(frozen=True)
class TuningTrial:
    """One evaluated style candidate."""

    stage: str
    parameters: StyleParameters
    summary: ArenaSummary
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "parameters": self.parameters.to_dict(),
            "score": round(self.score, 6),
            "arena": self.summary.to_dict(),
        }


@dataclass(frozen=True)
class TuningResult:
    """Successive-halving result with an independently evaluated winner."""

    best: StyleParameters
    trials: tuple[TuningTrial, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "best": self.best.to_dict(),
            "trials": [trial.to_dict() for trial in self.trials],
        }


def generate_style_candidates(count: int, *, seed: int) -> tuple[StyleParameters, ...]:
    """Generate a stable population with neutral and conservative anchors."""
    if count <= 0:
        raise ValueError("candidate count must be positive")
    # bomb_threshold=0.25 maps to the Professional bomb prior of 1.0.
    candidates = [StyleParameters(0.25, 0.85, 0.50)]
    if count > 1:
        candidates.append(StyleParameters(0.50, 0.88, 0.65))
    if count > 2:
        candidates.append(StyleParameters(0.80, 0.95, 0.90))
    rng = random.Random(seed)
    while len(candidates) < count:
        candidate = StyleParameters(
            bomb_threshold=rng.uniform(0.20, 0.85),
            teammate_awareness=rng.uniform(0.72, 1.00),
            control_priority=rng.uniform(0.30, 1.00),
        )
        if candidate not in candidates:
            candidates.append(candidate)
    return tuple(candidates)


def tuning_score(summary: ArenaSummary, *, latency_target: float = 0.50) -> float:
    """Rank strength first, then level gain, while penalizing latency overruns."""
    latency = _latency_payload(summary.candidate_decision_seconds)
    p95 = float(latency["p95_seconds"])
    latency_penalty = max(0.0, p95 - latency_target) * 0.10
    incomplete_penalty = summary.incomplete * 0.25
    return (
        summary.candidate_win_rate
        + summary.average_level_margin * 0.02
        - latency_penalty
        - incomplete_penalty
    )


def _strategy_factory(parameters: StyleParameters) -> StrategyFactory:
    def factory(difficulty: int, _player: int):
        if difficulty == 4:
            return DaiChangshengStrategy(
                style_overrides=parameters.to_dict(),
                mcts_overrides={
                    "iterations": TUNING_ITERATIONS[4],
                    "time_budget_ms": 0,
                },
            )
        if difficulty == 3:
            return ProfessionalStrategy(
                iterations=TUNING_ITERATIONS[3],
                time_budget_ms=0,
            )
        return make_strategy(difficulty)

    return factory


def _evaluate(
    parameters: StyleParameters,
    *,
    stage: str,
    deals: int,
    seed_start: int,
    baseline_difficulty: int,
    arena_runner: ArenaRunner,
) -> TuningTrial:
    summary = arena_runner(
        deals=deals,
        seed_start=seed_start,
        candidate_difficulty=4,
        baseline_difficulty=baseline_difficulty,
        strategy_factory=_strategy_factory(parameters),
    )
    return TuningTrial(stage, parameters, summary, tuning_score(summary))


def tune_dai_style(
    *,
    candidate_count: int = 6,
    screening_deals: int = 3,
    finalists: int = 2,
    final_deals: int = 10,
    seed_start: int = 2000,
    baseline_difficulty: int = 3,
    arena_runner: ArenaRunner = run_arena,
) -> TuningResult:
    """Use successive halving and independent seeds to choose style priors."""
    if screening_deals <= 0 or final_deals <= 0:
        raise ValueError("tuning deal counts must be positive")
    if finalists <= 0 or finalists > candidate_count:
        raise ValueError("finalists must be between one and candidate_count")
    if baseline_difficulty == 4:
        raise ValueError("baseline difficulty 4 conflicts with candidate overrides")

    candidates = generate_style_candidates(candidate_count, seed=seed_start)
    screening = [
        _evaluate(
            candidate,
            stage="screening",
            deals=screening_deals,
            seed_start=seed_start,
            baseline_difficulty=baseline_difficulty,
            arena_runner=arena_runner,
        )
        for candidate in candidates
    ]
    selected = sorted(screening, key=lambda trial: trial.score, reverse=True)[:finalists]
    final_seed = seed_start + 100_000
    finals = [
        _evaluate(
            trial.parameters,
            stage="final",
            deals=final_deals,
            seed_start=final_seed,
            baseline_difficulty=baseline_difficulty,
            arena_runner=arena_runner,
        )
        for trial in selected
    ]
    best = max(finals, key=lambda trial: trial.score)
    return TuningResult(best.parameters, tuple([*screening, *finals]))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Tune Dai Changsheng search priors.")
    parser.add_argument("--candidates", type=int, default=6)
    parser.add_argument("--screening-deals", type=int, default=3)
    parser.add_argument("--finalists", type=int, default=2)
    parser.add_argument("--final-deals", type=int, default=10)
    parser.add_argument("--seed-start", type=int, default=2000)
    parser.add_argument("--baseline", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    result = tune_dai_style(
        candidate_count=args.candidates,
        screening_deals=args.screening_deals,
        finalists=args.finalists,
        final_deals=args.final_deals,
        seed_start=args.seed_start,
        baseline_difficulty=args.baseline,
    )
    payload = result.to_dict()
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
