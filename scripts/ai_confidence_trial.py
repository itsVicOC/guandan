"""Paired production-clock evaluation of Dai's confidence guard."""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
from pathlib import Path

from ai_head_race import run_head_race, summarize

from guandan.ai.arena import AI_POLICY_VERSION
from guandan.ai.strategies.dachangsheng import DaiChangshengStrategy
from guandan.ai.strategy import make_strategy


def factory(tier, player):
    return (
        DaiChangshengStrategy(mcts_overrides={"confidence_guard": 1})
        if tier == 4 else make_strategy(tier)
    )


def pair(seed):
    rows = []
    for team in (0, 1):
        tiers = tuple(4 if seat % 2 == team else 3 for seat in range(4))
        row = run_head_race(seed, difficulties=tiers, strategy_factory=factory)
        row.update(candidate_team=team, candidate_won=row["winner_team"] == team)
        rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deals", type=int, default=16)
    parser.add_argument("--seed-start", type=int, default=49000)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if min(args.deals, args.workers) < 1:
        parser.error("deals and workers must be positive")
    rows = []
    args.out.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = args.out.with_suffix(".progress.json")
    with mp.Pool(args.workers) as pool:
        for index, result in enumerate(pool.imap_unordered(
            pair, range(args.seed_start, args.seed_start + args.deals)
        ), 1):
            rows.extend(result)
            checkpoint.write_text(json.dumps(rows, indent=2) + "\n")
            print(f"{index}/{args.deals} paired seeds", flush=True)
    result = {
        "base_policy_version": AI_POLICY_VERSION,
        "candidate_difficulty": 4,
        "baseline_difficulty": 3,
        "candidate_override": {"confidence_guard": True},
        "deterministic_search": False,
        "note": "Production-clock paired evaluation. Head-place win only.",
        **summarize(rows),
        "observations": sorted(rows, key=lambda row: (row["seed"], row["candidate_team"])),
    }
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    checkpoint.unlink()
    print(json.dumps({k: v for k, v in result.items() if k != "observations"}))


if __name__ == "__main__":
    main()
