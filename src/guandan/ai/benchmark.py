"""AI 对战基准工具。

运行方式：
    python -m guandan.ai.benchmark --games 20 --difficulties 0,1,2,3
"""
from __future__ import annotations

import argparse
import json
import math
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Optional, Sequence

from ..engine.events import ShuffleDeal, TributeSent
from ..engine.replay import replay_events
from ..engine.rules.tributes import apply_tribute_flow
from ..engine.state import GameState, make_initial_state, team_of
from .play import play_or_pass
from .strategy import DIFFICULTY_NAMES, AIStrategy, make_strategy

StrategyFactory = Callable[[int, int], AIStrategy]


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
    decision_seconds_by_player: tuple[
        tuple[float, ...],
        tuple[float, ...],
        tuple[float, ...],
        tuple[float, ...],
    ] = ((), (), (), ())

    @property
    def decision_seconds(self) -> tuple[float, ...]:
        return tuple(
            duration
            for seat_durations in self.decision_seconds_by_player
            for duration in seat_durations
        )

    def to_dict(self) -> dict[str, Any]:
        """转换为稳定的 JSON 友好结构。"""
        return {
            "seed": self.seed,
            "level": self.level,
            "difficulties": list(self.difficulties),
            "turns": self.turns,
            "finished": self.finished,
            "finish_order": list(self.finish_order),
            "winner_team": self.winner_team,
            "final_levels": list(self.final_levels) if self.final_levels else None,
            "team_bomb_count": list(self.team_bomb_count),
            "drift": self.drift,
            "duration_seconds": round(self.duration_seconds, 6),
            "decision_latency": _latency_payload(self.decision_seconds),
            "seat_decision_latency": [
                _latency_payload(durations)
                for durations in self.decision_seconds_by_player
            ],
        }


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]


def _latency_payload(values: Sequence[float]) -> dict[str, float | int]:
    return {
        "count": len(values),
        "average_seconds": round(sum(values) / len(values), 6) if values else 0.0,
        "p50_seconds": round(_percentile(values, 0.50), 6),
        "p95_seconds": round(_percentile(values, 0.95), 6),
        "max_seconds": round(max(values), 6) if values else 0.0,
    }


def _freeze_decision_seconds(
    values: Sequence[Sequence[float]],
) -> tuple[
    tuple[float, ...],
    tuple[float, ...],
    tuple[float, ...],
    tuple[float, ...],
]:
    if len(values) != 4:
        raise ValueError("decision timings require exactly four seats")
    return (tuple(values[0]), tuple(values[1]), tuple(values[2]), tuple(values[3]))


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

    def to_dict(self) -> dict[str, Any]:
        """转换为稳定的 JSON 友好结构。"""
        return {
            "games": self.games,
            "finished": self.finished,
            "completion_rate": self.completion_rate,
            "average_turns": self.average_turns,
            "team_wins": list(self.team_wins),
            "average_bombs": list(self.average_bombs),
            "results": [result.to_dict() for result in self.results],
        }


@dataclass(frozen=True)
class FullMatchResult:
    """A continuous AI match spanning deals, tribute and the successful pass of A."""

    seed: int
    difficulties: tuple[int, int, int, int]
    rounds: int
    turns: int
    finished: bool
    winner_team: Optional[int]
    final_levels: tuple[int, int]
    tribute_rounds: int
    round_results: tuple[MatchResult, ...]
    duration_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "difficulties": list(self.difficulties),
            "rounds": self.rounds,
            "turns": self.turns,
            "finished": self.finished,
            "winner_team": self.winner_team,
            "final_levels": list(self.final_levels),
            "tribute_rounds": self.tribute_rounds,
            "round_results": [result.to_dict() for result in self.round_results],
            "duration_seconds": round(self.duration_seconds, 6),
        }


@dataclass(frozen=True)
class BenchmarkComparison:
    """两份 benchmark JSON 的差异摘要。"""

    baseline_games: int
    current_games: int
    completion_rate_delta: float
    team0_win_rate_delta: float
    team1_win_rate_delta: float
    average_turns_delta: float
    average_duration_delta: float
    average_bombs_delta: tuple[float, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_games": self.baseline_games,
            "current_games": self.current_games,
            "completion_rate_delta": self.completion_rate_delta,
            "team0_win_rate_delta": self.team0_win_rate_delta,
            "team1_win_rate_delta": self.team1_win_rate_delta,
            "average_turns_delta": self.average_turns_delta,
            "average_duration_delta": self.average_duration_delta,
            "average_bombs_delta": list(self.average_bombs_delta),
        }


@dataclass(frozen=True)
class BenchmarkGateResult:
    """benchmark 对比门禁结果。"""

    comparison: BenchmarkComparison
    passed: bool
    failures: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = self.comparison.to_dict()
        payload["passed"] = self.passed
        payload["failures"] = list(self.failures)
        return payload


def _as_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    return float(value)


def _average_duration(payload: dict[str, Any]) -> float:
    results = payload.get("results", [])
    if not results:
        return 0.0
    return sum(_as_float(result.get("duration_seconds")) for result in results) / len(results)


def _team_win_rate(payload: dict[str, Any], team: int) -> float:
    games = int(payload.get("games", 0))
    if games <= 0:
        return 0.0
    team_wins = payload.get("team_wins", [0, 0])
    return _as_float(team_wins[team]) / games


def compare_benchmark_payloads(
    baseline: dict[str, Any],
    current: dict[str, Any],
) -> BenchmarkComparison:
    """比较两份 `BenchmarkSummary.to_dict()` payload。"""
    baseline_bombs = baseline.get("average_bombs", [0.0, 0.0])
    current_bombs = current.get("average_bombs", [0.0, 0.0])
    return BenchmarkComparison(
        baseline_games=int(baseline.get("games", 0)),
        current_games=int(current.get("games", 0)),
        completion_rate_delta=_as_float(current.get("completion_rate"))
        - _as_float(baseline.get("completion_rate")),
        team0_win_rate_delta=_team_win_rate(current, 0) - _team_win_rate(baseline, 0),
        team1_win_rate_delta=_team_win_rate(current, 1) - _team_win_rate(baseline, 1),
        average_turns_delta=_as_float(current.get("average_turns"))
        - _as_float(baseline.get("average_turns")),
        average_duration_delta=_average_duration(current) - _average_duration(baseline),
        average_bombs_delta=(
            _as_float(current_bombs[0]) - _as_float(baseline_bombs[0]),
            _as_float(current_bombs[1]) - _as_float(baseline_bombs[1]),
        ),
    )


def load_benchmark_payload(path: str | Path) -> dict[str, Any]:
    """读取 benchmark JSON payload。"""
    with Path(path).open(encoding="utf-8") as fp:
        payload = json.load(fp)
    if not isinstance(payload, dict):
        raise ValueError("benchmark payload must be a JSON object")
    return payload


def evaluate_benchmark_gate(
    comparison: BenchmarkComparison,
    *,
    max_completion_drop: Optional[float] = None,
    max_duration_increase: Optional[float] = None,
    max_turn_increase: Optional[float] = None,
) -> BenchmarkGateResult:
    """按阈值判断 benchmark 对比是否通过。"""
    failures: list[str] = []
    if (
        max_completion_drop is not None
        and comparison.completion_rate_delta < -max_completion_drop
    ):
        failures.append(
            "completion_rate_drop "
            f"{-comparison.completion_rate_delta:.3f} > {max_completion_drop:.3f}"
        )
    if (
        max_duration_increase is not None
        and comparison.average_duration_delta > max_duration_increase
    ):
        failures.append(
            "average_duration_increase "
            f"{comparison.average_duration_delta:.3f} > {max_duration_increase:.3f}"
        )
    if (
        max_turn_increase is not None
        and comparison.average_turns_delta > max_turn_increase
    ):
        failures.append(
            "average_turns_increase "
            f"{comparison.average_turns_delta:.3f} > {max_turn_increase:.3f}"
        )
    return BenchmarkGateResult(
        comparison=comparison,
        passed=not failures,
        failures=tuple(failures),
    )


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
    strategy_factory: StrategyFactory | None = None,
) -> MatchResult:
    """运行一局 4 AI 对战。"""
    seat_difficulties = _normalize_difficulties(difficulties)
    state = make_initial_state(level=level, first_player=0, seed=seed)
    factory = strategy_factory or (lambda difficulty, _player: make_strategy(difficulty))
    strategies = [
        factory(difficulty, player)
        for player, difficulty in enumerate(seat_difficulties)
    ]
    for player, strategy in enumerate(strategies):
        _seed_strategy(strategy, seed, player)

    rng = random.Random(seed)
    start = time.perf_counter()
    turns = 0
    decision_seconds: list[list[float]] = [[], [], [], []]
    while not state.finished and turns < max_turns:
        player = state.turn_index
        decision_started = time.perf_counter()
        play_or_pass(state, player, strategies[player], rng)
        decision_seconds[player].append(time.perf_counter() - decision_started)
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
        decision_seconds_by_player=_freeze_decision_seconds(decision_seconds),
    )


def _prepare_next_round(previous: GameState, seed: int) -> GameState:
    if not previous.finished or previous.match_finished:
        raise ValueError("previous state must be a completed non-final round")
    if previous.team_levels_final is None or len(previous.finish_order) != 3:
        raise ValueError("previous round has no valid settlement")

    levels = list(previous.team_levels_final)
    head_team = team_of(previous.finish_order[0])
    state = make_initial_state(
        level=levels[head_team],
        first_player=previous.finish_order[0],
        seed=seed,
        team_levels=levels,
    )
    tribute = apply_tribute_flow(
        list(previous.finish_order),
        state.hands,
        level=state.level,
        wild_card=state.wild_card,
    )
    state.history.extend(tribute.events)
    state.turn_index = tribute.first_player
    state.leader = tribute.first_player
    shuffle = state.history[0]
    if not isinstance(shuffle, ShuffleDeal):
        raise ValueError("next round event stream has no deal")
    state.history[0] = replace(shuffle, first_player=tribute.first_player)
    return state


def run_full_match(
    seed: int,
    *,
    level: int = 2,
    difficulties: Sequence[int] | int = (0, 1, 2, 3),
    max_rounds: int = 64,
    max_turns: int = 2000,
    strategy_factory: StrategyFactory | None = None,
) -> FullMatchResult:
    """Run consecutive AI rounds, including tribute, until one team passes A."""
    if max_rounds <= 0:
        raise ValueError("max_rounds must be positive")
    if max_turns <= 0:
        raise ValueError("max_turns must be positive")

    seat_difficulties = _normalize_difficulties(difficulties)
    factory = strategy_factory or (lambda difficulty, _player: make_strategy(difficulty))
    strategies = [
        factory(difficulty, player)
        for player, difficulty in enumerate(seat_difficulties)
    ]
    for player, strategy in enumerate(strategies):
        _seed_strategy(strategy, seed, player)
    rng = random.Random(seed)
    state = make_initial_state(level=level, first_player=0, seed=seed)
    round_results: list[MatchResult] = []
    total_turns = 0
    tribute_rounds = 0
    match_started = time.perf_counter()

    for round_offset in range(max_rounds):
        round_started = time.perf_counter()
        round_turns = 0
        decision_seconds: list[list[float]] = [[], [], [], []]
        while not state.finished and round_turns < max_turns:
            player = state.turn_index
            decision_started = time.perf_counter()
            play_or_pass(state, player, strategies[player], rng)
            decision_seconds[player].append(time.perf_counter() - decision_started)
            round_turns += 1
        total_turns += round_turns
        round_duration = time.perf_counter() - round_started
        final_levels = state.team_levels_final
        normalized_levels = (
            (int(final_levels[0]), int(final_levels[1]))
            if final_levels is not None
            else None
        )
        round_results.append(
            MatchResult(
                seed=seed + round_offset,
                level=state.level,
                difficulties=seat_difficulties,
                turns=round_turns,
                finished=state.finished,
                finish_order=tuple(state.finish_order),
                winner_team=team_of(state.finish_order[0]) if state.finish_order else None,
                final_levels=normalized_levels,
                team_bomb_count=(state.team_bomb_count[0], state.team_bomb_count[1]),
                drift=state.drift,
                duration_seconds=round_duration,
                decision_seconds_by_player=_freeze_decision_seconds(decision_seconds),
            )
        )
        if not state.finished:
            break
        if replay_events(state.history) != state:
            raise RuntimeError(f"round {round_offset + 1} failed exact event replay")
        if any(isinstance(event, TributeSent) for event in state.history):
            tribute_rounds += 1
        if state.match_finished:
            break
        state = _prepare_next_round(state, seed + round_offset + 1)

    levels = state.team_levels_final or state.team_levels
    return FullMatchResult(
        seed=seed,
        difficulties=seat_difficulties,
        rounds=len(round_results),
        turns=total_turns,
        finished=state.match_finished,
        winner_team=state.winner_team if state.match_finished else None,
        final_levels=(int(levels[0]), int(levels[1])),
        tribute_rounds=tribute_rounds,
        round_results=tuple(round_results),
        duration_seconds=time.perf_counter() - match_started,
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
    parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("BASELINE_JSON", "CURRENT_JSON"),
        help="compare two benchmark JSON files and exit",
    )
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
    parser.add_argument(
        "--full-match",
        action="store_true",
        help="run one continuous match through the successful pass of A",
    )
    parser.add_argument("--max-rounds", type=int, default=64, help="round cap for --full-match")
    parser.add_argument(
        "--json",
        action="store_true",
        help="print machine-readable JSON instead of text summary",
    )
    parser.add_argument(
        "--fail-completion-drop",
        type=float,
        default=None,
        help="with --compare, fail if completion rate drops by more than this value",
    )
    parser.add_argument(
        "--fail-duration-increase",
        type=float,
        default=None,
        help="with --compare, fail if average duration increases by more than seconds",
    )
    parser.add_argument(
        "--fail-turn-increase",
        type=float,
        default=None,
        help="with --compare, fail if average turns increase by more than this value",
    )
    args = parser.parse_args(argv)

    if args.compare:
        baseline = load_benchmark_payload(args.compare[0])
        current = load_benchmark_payload(args.compare[1])
        comparison = compare_benchmark_payloads(baseline, current)
        gate = evaluate_benchmark_gate(
            comparison,
            max_completion_drop=args.fail_completion_drop,
            max_duration_increase=args.fail_duration_increase,
            max_turn_increase=args.fail_turn_increase,
        )
        if args.json:
            print(json.dumps(gate.to_dict(), ensure_ascii=False, sort_keys=True))
        else:
            _print_comparison(gate)
        return 0 if gate.passed else 1

    if args.full_match:
        full_result = run_full_match(
            args.seed_start,
            level=args.level,
            difficulties=args.difficulties,
            max_rounds=args.max_rounds,
            max_turns=args.max_turns,
        )
        if args.json:
            print(json.dumps(full_result.to_dict(), ensure_ascii=False, sort_keys=True))
        else:
            print(
                "AI full match "
                f"seed={full_result.seed} rounds={full_result.rounds} turns={full_result.turns} "
                f"finished={full_result.finished} winner_team={full_result.winner_team} "
                f"tribute_rounds={full_result.tribute_rounds} levels={full_result.final_levels} "
                f"time={full_result.duration_seconds:.3f}s"
            )
            print(f"difficulties={_format_difficulties(args.difficulties)}")
        return 0 if full_result.finished else 1

    summary = run_benchmark(
        games=args.games,
        seed_start=args.seed_start,
        level=args.level,
        difficulties=args.difficulties,
        max_turns=args.max_turns,
    )

    if args.json:
        print(json.dumps(summary.to_dict(), ensure_ascii=False, sort_keys=True))
        return 0

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


def _print_comparison(gate: BenchmarkGateResult) -> None:
    comparison = gate.comparison
    print(
        "AI benchmark comparison "
        f"baseline_games={comparison.baseline_games} current_games={comparison.current_games}"
    )
    print(
        f"completion_delta={comparison.completion_rate_delta:+.1%} "
        f"team0_win_delta={comparison.team0_win_rate_delta:+.1%} "
        f"team1_win_delta={comparison.team1_win_rate_delta:+.1%}"
    )
    print(
        f"avg_turns_delta={comparison.average_turns_delta:+.1f} "
        f"avg_duration_delta={comparison.average_duration_delta:+.3f}s "
        f"avg_bombs_delta=EW:{comparison.average_bombs_delta[0]:+.2f} "
        f"SN:{comparison.average_bombs_delta[1]:+.2f}"
    )
    if gate.passed:
        print("gate=pass")
    else:
        print("gate=fail")
        for failure in gate.failures:
            print(f"failure={failure}")


if __name__ == "__main__":
    raise SystemExit(main())
