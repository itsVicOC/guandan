"""Paired, seat-swapped AI strength arena.

Each deal is played twice: the candidate controls team 0 in one leg and team 1
in the other.  This cancels most deal and fixed-team bias before reporting a
Wilson confidence interval, Elo estimate and candidate-only decision latency.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from .benchmark import (
    FullMatchResult,
    MatchResult,
    StrategyFactory,
    _latency_payload,
    run_full_match,
    run_match,
)
from .strategies.dachangsheng import DaiChangshengStrategy
from .strategies.professional import ProfessionalStrategy
from .strategy import DIFFICULTY_NAMES, AIStrategy, make_strategy

CALIBRATED_ITERATIONS = {3: 64, 4: 96}


@dataclass(frozen=True)
class ArenaLegResult:
    """One side of a paired deal."""

    seed: int
    candidate_team: int
    match: MatchResult | FullMatchResult

    @property
    def candidate_won(self) -> bool:
        return self.match.finished and self.match.winner_team == self.candidate_team

    @property
    def level_margin(self) -> int:
        if isinstance(self.match, FullMatchResult):
            if not self.match.finished:
                return 0
            return 1 if self.candidate_won else -1
        if self.match.final_levels is None:
            return 0
        opponent = 1 - self.candidate_team
        return (
            self.match.final_levels[self.candidate_team]
            - self.match.final_levels[opponent]
        )

    @property
    def candidate_decision_seconds(self) -> tuple[float, ...]:
        seats = (0, 2) if self.candidate_team == 0 else (1, 3)
        round_results = (
            (self.match,)
            if isinstance(self.match, MatchResult)
            else self.match.round_results
        )
        return tuple(
            duration
            for result in round_results
            for seat in seats
            for duration in result.decision_seconds_by_player[seat]
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "candidate_team": self.candidate_team,
            "candidate_won": self.candidate_won,
            "level_margin": self.level_margin,
            "match": self.match.to_dict(),
        }


@dataclass(frozen=True)
class ArenaSummary:
    """Aggregate paired strength and latency metrics."""

    candidate_difficulty: int
    baseline_difficulty: int
    deals: int
    legs: tuple[ArenaLegResult, ...]
    candidate_wins: int
    baseline_wins: int
    incomplete: int
    candidate_win_rate: float
    confidence_low: float
    confidence_high: float
    elo_delta: float
    average_level_margin: float
    candidate_decision_seconds: tuple[float, ...]
    full_match: bool = False
    deterministic_search: bool = False

    @property
    def games(self) -> int:
        return len(self.legs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_difficulty": self.candidate_difficulty,
            "candidate_name": DIFFICULTY_NAMES[self.candidate_difficulty],
            "baseline_difficulty": self.baseline_difficulty,
            "baseline_name": DIFFICULTY_NAMES[self.baseline_difficulty],
            "deals": self.deals,
            "games": self.games,
            "full_match": self.full_match,
            "deterministic_search": self.deterministic_search,
            "candidate_wins": self.candidate_wins,
            "baseline_wins": self.baseline_wins,
            "incomplete": self.incomplete,
            "candidate_win_rate": round(self.candidate_win_rate, 6),
            "confidence_95": [
                round(self.confidence_low, 6),
                round(self.confidence_high, 6),
            ],
            "elo_delta": round(self.elo_delta, 3),
            "average_level_margin": round(self.average_level_margin, 6),
            "candidate_decision_latency": _latency_payload(
                self.candidate_decision_seconds
            ),
            "legs": [leg.to_dict() for leg in self.legs],
        }


@dataclass(frozen=True)
class ArenaGateResult:
    """Release-gate result for strength, completion and latency."""

    summary: ArenaSummary
    passed: bool
    failures: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = self.summary.to_dict()
        payload["passed"] = self.passed
        payload["failures"] = list(self.failures)
        return payload


def wilson_interval(wins: int, games: int, *, z: float = 1.96) -> tuple[float, float]:
    """Return a Wilson score interval for a Bernoulli win rate."""
    if games <= 0:
        return (0.0, 1.0)
    probability = wins / games
    z_squared = z * z
    denominator = 1.0 + z_squared / games
    centre = (probability + z_squared / (2.0 * games)) / denominator
    spread = (
        z
        * math.sqrt(
            probability * (1.0 - probability) / games
            + z_squared / (4.0 * games * games)
        )
        / denominator
    )
    return (max(0.0, centre - spread), min(1.0, centre + spread))


def elo_from_win_rate(win_rate: float) -> float:
    """Convert an empirical score into an Elo difference."""
    probability = max(1e-6, min(1.0 - 1e-6, win_rate))
    return 400.0 * math.log10(probability / (1.0 - probability))


def fixed_iteration_strategy_factory(difficulty: int, _player: int) -> AIStrategy:
    """Create deterministic searches at each production profile's work ceiling."""
    if difficulty == 3:
        return ProfessionalStrategy(
            iterations=CALIBRATED_ITERATIONS[3],
            time_budget_ms=0,
        )
    if difficulty == 4:
        return DaiChangshengStrategy(
            mcts_overrides={
                "iterations": CALIBRATED_ITERATIONS[4],
                "time_budget_ms": 0,
            }
        )
    return make_strategy(difficulty)


def run_arena(
    *,
    deals: int,
    seed_start: int,
    candidate_difficulty: int,
    baseline_difficulty: int,
    level: int = 2,
    max_turns: int = 2000,
    strategy_factory: StrategyFactory | None = None,
    full_match: bool = False,
    max_rounds: int = 64,
    deterministic_search: bool = False,
) -> ArenaSummary:
    """Run paired deals with candidate and baseline swapping fixed teams."""
    if deals <= 0:
        raise ValueError("deals must be positive")
    for difficulty in (candidate_difficulty, baseline_difficulty):
        if difficulty not in DIFFICULTY_NAMES:
            raise ValueError(f"unknown AI difficulty: {difficulty}")
    if deterministic_search and strategy_factory is not None:
        raise ValueError("deterministic_search cannot be combined with strategy_factory")
    if deterministic_search:
        strategy_factory = fixed_iteration_strategy_factory

    legs: list[ArenaLegResult] = []
    match_runner = run_full_match if full_match else run_match
    for seed in range(seed_start, seed_start + deals):
        common_kwargs: dict[str, Any] = {
            "level": level,
            "max_turns": max_turns,
            "strategy_factory": strategy_factory,
        }
        if full_match:
            common_kwargs["max_rounds"] = max_rounds
        candidate_team0 = match_runner(
            seed,
            difficulties=(
                candidate_difficulty,
                baseline_difficulty,
                candidate_difficulty,
                baseline_difficulty,
            ),
            **common_kwargs,
        )
        legs.append(ArenaLegResult(seed, 0, candidate_team0))

        candidate_team1 = match_runner(
            seed,
            difficulties=(
                baseline_difficulty,
                candidate_difficulty,
                baseline_difficulty,
                candidate_difficulty,
            ),
            **common_kwargs,
        )
        legs.append(ArenaLegResult(seed, 1, candidate_team1))

    completed = [leg for leg in legs if leg.match.finished]
    candidate_wins = sum(leg.candidate_won for leg in completed)
    baseline_wins = len(completed) - candidate_wins
    win_rate = candidate_wins / len(completed) if completed else 0.0
    confidence_low, confidence_high = wilson_interval(candidate_wins, len(completed))
    decision_seconds = tuple(
        duration
        for leg in legs
        for duration in leg.candidate_decision_seconds
    )
    return ArenaSummary(
        candidate_difficulty=candidate_difficulty,
        baseline_difficulty=baseline_difficulty,
        deals=deals,
        legs=tuple(legs),
        candidate_wins=candidate_wins,
        baseline_wins=baseline_wins,
        incomplete=len(legs) - len(completed),
        candidate_win_rate=win_rate,
        confidence_low=confidence_low,
        confidence_high=confidence_high,
        elo_delta=elo_from_win_rate(win_rate) if completed else 0.0,
        average_level_margin=(
            sum(leg.level_margin for leg in completed) / len(completed)
            if completed
            else 0.0
        ),
        candidate_decision_seconds=decision_seconds,
        full_match=full_match,
        deterministic_search=deterministic_search,
    )


def evaluate_arena_gate(
    summary: ArenaSummary,
    *,
    min_win_rate: float = 0.0,
    min_confidence_low: float = 0.0,
    max_p95_seconds: float = float("inf"),
) -> ArenaGateResult:
    failures: list[str] = []
    if summary.incomplete:
        failures.append(f"incomplete_games={summary.incomplete}")
    if summary.candidate_win_rate < min_win_rate:
        failures.append(
            f"candidate_win_rate={summary.candidate_win_rate:.4f} < {min_win_rate:.4f}"
        )
    if summary.confidence_low < min_confidence_low:
        failures.append(
            f"confidence_low={summary.confidence_low:.4f} < {min_confidence_low:.4f}"
        )
    p95 = float(_latency_payload(summary.candidate_decision_seconds)["p95_seconds"])
    if p95 > max_p95_seconds:
        failures.append(f"candidate_p95_seconds={p95:.4f} > {max_p95_seconds:.4f}")
    return ArenaGateResult(summary, not failures, tuple(failures))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run paired Guandan AI strength games.")
    parser.add_argument("--candidate", type=int, default=4)
    parser.add_argument("--baseline", type=int, default=3)
    parser.add_argument("--deals", type=int, default=20)
    parser.add_argument("--seed-start", type=int, default=1000)
    parser.add_argument("--level", type=int, default=2)
    parser.add_argument("--max-turns", type=int, default=2000)
    parser.add_argument("--full-match", action="store_true")
    parser.add_argument("--max-rounds", type=int, default=64)
    parser.add_argument("--deterministic-search", action="store_true")
    parser.add_argument("--min-win-rate", type=float, default=0.0)
    parser.add_argument("--min-confidence-low", type=float, default=0.0)
    parser.add_argument("--max-p95-seconds", type=float, default=float("inf"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    summary = run_arena(
        deals=args.deals,
        seed_start=args.seed_start,
        candidate_difficulty=args.candidate,
        baseline_difficulty=args.baseline,
        level=args.level,
        max_turns=args.max_turns,
        full_match=args.full_match,
        max_rounds=args.max_rounds,
        deterministic_search=args.deterministic_search,
    )
    gate = evaluate_arena_gate(
        summary,
        min_win_rate=args.min_win_rate,
        min_confidence_low=args.min_confidence_low,
        max_p95_seconds=args.max_p95_seconds,
    )
    if args.json:
        print(json.dumps(gate.to_dict(), ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"AI arena {DIFFICULTY_NAMES[args.candidate]} vs "
            f"{DIFFICULTY_NAMES[args.baseline]}: "
            f"wins={summary.candidate_wins}/{summary.games} "
            f"rate={summary.candidate_win_rate:.1%} "
            f"95%CI=[{summary.confidence_low:.1%}, {summary.confidence_high:.1%}] "
            f"elo={summary.elo_delta:+.1f} passed={gate.passed}"
        )
    return 0 if gate.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
