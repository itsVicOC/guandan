"""AI 对战基准工具。

运行方式：
    python -m guandan.ai.benchmark --games 20 --difficulties 0,1,2,3
"""
from __future__ import annotations

import argparse
import random
import time
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from ..engine.state import make_initial_state, team_of
from .play import play_or_pass
from .strategy import DIFFICULTY_NAMES, AIStrategy, make_strategy


@dataclass(frozen=True)
class MatchResult:
    """单局 AI 对战结果。"""

    seed: int
    level: int
    difficulties: tuple[int, int, int, int]
    turns: int
    finished: bool
    finish_order: tuple[int, ...]
    winner_team: Optional[int]
    final_levels: Optional[tuple[int, int]]
    team_bomb_count: tuple[int, int]
    drift: bool
    duration_seconds: float


@dataclass(frozen=True)
class BenchmarkSummary:
    """多局 AI 对战汇总。"""

    games: int
    finished: int
    completion_rate: float
    average_turns: float
    team_wins: tuple[int, int]
    average_bombs: tuple[float, float]
    results: tuple[MatchResult, ...]


def _normalize_difficulties(difficulties: Sequence[int] | int) -> tuple[int, int, int, int]:
    values = (difficulties,) * 4 if isinstance(difficulties, int) else tuple(difficulties)
    if len(values) != 4:
        raise ValueError("difficulties must be one value or exactly four seat values")
    for value in values:
        if value not in DIFFICULTY_NAMES:
            raise ValueError(f"unknown AI difficulty: {value}")
    return (values[0], values[1], values[2], values[3])


def _seed_strategy(strategy: AIStrategy, seed: int, player: int) -> None:
    if hasattr(strategy, "rng"):
        strategy_with_rng: Any = strategy
        strategy_with_rng.rng = random.Random(seed * 31 + player)


def run_match(
    seed: int,
    *,
    level: int = 2,
    difficulties: Sequence[int] | int = (0, 1, 2, 3),
    max_turns: int = 2000,
) -> MatchResult:
    """运行一局 4 AI 对战。"""
    seat_difficulties = _normalize_difficulties(difficulties)
    state = make_initial_state(level=level, first_player=0, seed=seed)
    strategies = [make_strategy(diff) for diff in seat_difficulties]
    for player, strategy in enumerate(strategies):
        _seed_strategy(strategy, seed, player)

    rng = random.Random(seed)
    start = time.perf_counter()
    turns = 0
    while not state.finished and turns < max_turns:
        player = state.turn_index
        play_or_pass(state, player, strategies[player], rng)
        turns += 1

    duration = time.perf_counter() - start
    winner_team = team_of(state.finish_order[0]) if state.finish_order else None
    final_levels = getattr(state, "team_levels_final", None)
    if final_levels is not None:
        final_levels = (int(final_levels[0]), int(final_levels[1]))

    return MatchResult(
        seed=seed,
        level=level,
        difficulties=seat_difficulties,
        turns=turns,
        finished=state.finished,
        finish_order=tuple(state.finish_order),
        winner_team=winner_team,
        final_levels=final_levels,
        team_bomb_count=(state.team_bomb_count[0], state.team_bomb_count[1]),
        drift=state.drift,
        duration_seconds=duration,
    )


def run_benchmark(
    games: int = 10,
    *,
    seed_start: int = 100,
    level: int = 2,
    difficulties: Sequence[int] | int = (0, 1, 2, 3),
    max_turns: int = 2000,
) -> BenchmarkSummary:
    """运行多局 AI 对战并汇总基础指标。"""
    if games <= 0:
        raise ValueError("games must be positive")

    results = tuple(
        run_match(
            seed_start + i,
            level=level,
            difficulties=difficulties,
            max_turns=max_turns,
        )
        for i in range(games)
    )
    finished = sum(1 for result in results if result.finished)
    team_wins = (
        sum(1 for result in results if result.winner_team == 0),
        sum(1 for result in results if result.winner_team == 1),
    )
    average_turns = sum(result.turns for result in results) / games
    average_bombs = (
        sum(result.team_bomb_count[0] for result in results) / games,
        sum(result.team_bomb_count[1] for result in results) / games,
    )
    return BenchmarkSummary(
        games=games,
        finished=finished,
        completion_rate=finished / games,
        average_turns=average_turns,
        team_wins=team_wins,
        average_bombs=average_bombs,
        results=results,
    )


def _parse_difficulties(value: str) -> tuple[int, int, int, int]:
    parts = tuple(int(part.strip()) for part in value.split(",") if part.strip())
    if len(parts) == 1:
        return _normalize_difficulties(parts[0])
    return _normalize_difficulties(parts)


def _format_difficulties(values: Sequence[int]) -> str:
    return ",".join(f"{value}:{DIFFICULTY_NAMES[value]}" for value in values)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run AI-only Guandan benchmark games.")
    parser.add_argument("--games", type=int, default=10, help="number of games to run")
    parser.add_argument("--seed-start", type=int, default=100, help="first random seed")
    parser.add_argument("--level", type=int, default=2, help="starting level rank")
    parser.add_argument(
        "--difficulties",
        type=_parse_difficulties,
        default=_normalize_difficulties((0, 1, 2, 3)),
        help="one difficulty for all seats, or four comma-separated seat difficulties",
    )
    parser.add_argument("--max-turns", type=int, default=2000, help="turn cap per game")
    args = parser.parse_args(argv)

    summary = run_benchmark(
        games=args.games,
        seed_start=args.seed_start,
        level=args.level,
        difficulties=args.difficulties,
        max_turns=args.max_turns,
    )

    print(
        "AI benchmark "
        f"games={summary.games} finished={summary.finished} "
        f"completion={summary.completion_rate:.0%} avg_turns={summary.average_turns:.1f}"
    )
    print(f"difficulties={_format_difficulties(args.difficulties)}")
    print(
        f"team_wins=EW:{summary.team_wins[0]} SN:{summary.team_wins[1]} "
        f"avg_bombs=EW:{summary.average_bombs[0]:.2f} SN:{summary.average_bombs[1]:.2f}"
    )
    for result in summary.results:
        print(
            f"seed={result.seed} turns={result.turns} finished={result.finished} "
            f"winner_team={result.winner_team} order={list(result.finish_order)} "
            f"levels={result.final_levels} bombs={result.team_bomb_count} "
            f"drift={result.drift} time={result.duration_seconds:.3f}s"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
