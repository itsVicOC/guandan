"""Extend paired round-win estimates by stopping when head place is known.

Guandan's round winner is irrevocably the head player's team. This runner defaults
to fixed-work Arena policies; --clock uses production budgets. It uses the same
initial deals and RNG seeds up to head place, and does NOT measure completion,
level gain, passing A or full-game latency.
Those metrics still require the ordinary Arena / full-match benchmark.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import random
import time
from pathlib import Path

from guandan.ai.arena import (
    AI_POLICY_VERSION,
    CALIBRATED_ITERATIONS,
    fixed_iteration_strategy_factory,
    paired_score_interval,
)
from guandan.ai.benchmark import StrategyFactory, _seed_strategy
from guandan.ai.play import play_or_pass
from guandan.ai.strategy import make_strategy
from guandan.engine.state import make_initial_state, team_of


def run_head_race(
    seed: int,
    *,
    difficulties: tuple[int, int, int, int],
    level: int = 2,
    max_turns: int = 2000,
    strategy_factory: StrategyFactory = fixed_iteration_strategy_factory,
) -> dict:
    state = make_initial_state(level=level, first_player=0, seed=seed)
    strategies = [strategy_factory(tier, seat) for seat, tier in enumerate(difficulties)]
    for seat, strategy in enumerate(strategies):
        _seed_strategy(strategy, seed, seat)
    rng = random.Random(seed)
    turns = 0
    started = time.perf_counter()
    while not state.finish_order and turns < max_turns:
        seat = state.current_player()
        play_or_pass(state, seat, strategies[seat], rng)
        turns += 1
    head = state.finish_order[0] if state.finish_order else None
    return {
        "seed": seed,
        "level": level,
        "difficulties": difficulties,
        "head_player": head,
        "winner_team": team_of(head) if head is not None else None,
        "head_determined": head is not None,
        "turns_until_head": turns,
        "duration_seconds": time.perf_counter() - started,
        "observation": "head place only",
    }


def _clock_factory(difficulty, player):
    return make_strategy(difficulty)


def _pair(job: tuple[int, int, int, bool]) -> list[dict]:
    seed, candidate, baseline, clock = job
    pair = []
    for team in (0, 1):
        difficulties = tuple(candidate if seat % 2 == team else baseline for seat in range(4))
        result = run_head_race(
            seed, difficulties=difficulties,
            strategy_factory=_clock_factory if clock else fixed_iteration_strategy_factory,
        )
        result["candidate_team"] = team
        result["candidate_won"] = result["winner_team"] == team
        pair.append(result)
    return pair


def summarize(rows: list[dict]) -> dict:
    paired: dict[int, list[dict]] = {}
    for row in rows:
        paired.setdefault(row["seed"], []).append(row)
    for seed, pair in paired.items():
        if len(pair) != 2 or {row["candidate_team"] for row in pair} != {0, 1}:
            raise ValueError(f"seed {seed} must have exactly one leg per team")
        if not all(row["head_determined"] for row in pair):
            raise ValueError(f"seed {seed} has an undetermined winner")
    scores = [sum(row["candidate_won"] for row in paired[seed]) / 2 for seed in sorted(paired)]
    wins = sum(row["candidate_won"] for row in rows)
    return {
        "deals": len(paired),
        "games": len(rows),
        "candidate_wins": wins,
        "baseline_wins": len(rows) - wins,
        "candidate_win_rate": wins / len(rows) if rows else 0.0,
        "confidence_95": paired_score_interval(scores),
        "confidence_method": "paired seed bootstrap",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=int, choices=range(5), default=4)
    parser.add_argument("--baseline", type=int, choices=range(5), default=3)
    parser.add_argument("--deals", type=int, default=40)
    parser.add_argument("--seed-start", type=int, default=36040)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--clock", action="store_true", help="use production time budgets; results depend on CPU scheduling")
    parser.add_argument("--prior", type=Path, help="completed fixed-work Arena JSON to extend")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.deals < 1 or args.workers < 1:
        parser.error("deals and workers must be positive")
    if args.clock and args.prior:
        parser.error("production-clock results cannot be merged with a fixed-work prior")
    rows = []
    if args.prior:
        prior = json.loads(args.prior.read_text())
        if (
            prior["candidate_difficulty"] != args.candidate
            or prior["baseline_difficulty"] != args.baseline
            or not prior["deterministic_search"]
            or prior["full_match"]
            or prior.get("policy_version") != AI_POLICY_VERSION
            or prior.get("fixed_root_evaluations") != {
                str(tier): count for tier, count in CALIBRATED_ITERATIONS.items()
            }
            or any(leg["match"]["level"] != 2 for leg in prior["legs"])
        ):
            parser.error("prior must compare the same tiers in fixed-work single rounds")
        for leg in prior["legs"]:
            rows.append({
                "seed": leg["seed"],
                "candidate_team": leg["candidate_team"],
                "candidate_won": leg["candidate_won"],
                "head_determined": leg["match"]["finished"],
                "observation": "completed round (see prior)",
            })
    seeds = range(args.seed_start, args.seed_start + args.deals)
    if set(seeds) & {row["seed"] for row in rows}:
        parser.error("new seeds must not overlap the prior")
    if rows:
        summarize(rows)  # Reject incomplete prior pairs before the costly run.
    args.out.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = args.out.with_suffix(".progress.json")
    with mp.Pool(args.workers) as pool:
        jobs = [(seed, args.candidate, args.baseline, args.clock) for seed in seeds]
        for index, pair in enumerate(pool.imap_unordered(_pair, jobs), 1):
            rows.extend(pair)
            checkpoint.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
            print(f"{index}/{args.deals} new paired seeds", flush=True)
    result = {
        "candidate_difficulty": args.candidate,
        "policy_version": AI_POLICY_VERSION,
        "baseline_difficulty": args.baseline,
        "deterministic_search": not args.clock,
        "fixed_root_evaluations": None if args.clock else CALIBRATED_ITERATIONS,
        "prior": str(args.prior) if args.prior else None,
        "note": "Round-win evidence only. Newly added rounds stop at head place; do not infer level gain, completed games, pass-A rate or production latency.",
        **summarize(rows),
        "observations": sorted(rows, key=lambda row: (row["seed"], row["candidate_team"])),
    }
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    checkpoint.unlink()
    print(json.dumps({key: value for key, value in result.items() if key != "observations"}), flush=True)


if __name__ == "__main__":
    main()
