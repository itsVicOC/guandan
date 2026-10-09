"""Trace candidate coverage, guards and cutoff bias on existing research labels.

These previously observed labels are exploratory, never an independent strength
test. All variants share the same root-world random stream and work limit.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import multiprocessing as mp
import random
import statistics
from collections import Counter
from pathlib import Path

from guandan.ai.candidates import pattern_key
from guandan.ai.mcts import root_search
from guandan.ai.strategies.dachangsheng import DaiChangshengStrategy
from guandan.ai.strategies.professional import ProfessionalStrategy
from guandan.storage.savegame import _dict_to_state
from guandan.storage.serialization import deserialize_events

METHODS = ("baseline", "ranker", "horizon120", "complete")


def seed_for(stage: str, index: int, round_index: int = 0) -> int:
    return int.from_bytes(hashlib.sha256(
        f"continuation-v9/{stage}/{index}/{round_index}".encode()).digest()[:8], "big")


def key(action):
    return json.dumps(pattern_key(action) if action is not None else ("pass",))


def policy(tier, method, iterations, *, clock=False):
    options = {} if clock else {"time_budget_ms": 0, "iterations": iterations}
    if method == "ranker":
        options["action_ranker"] = True
    if method in ("horizon120", "complete"):
        options["rollout_max_turns"] = 120 if method == "horizon120" else 4000
    if tier == 3:
        return ProfessionalStrategy(**options)
    return DaiChangshengStrategy(mcts_overrides=options)


def diagnose(job):
    filename, iterations = job
    deal = json.loads(gzip.decompress(Path(filename).read_bytes()))
    rows = []
    for position in deal["positions"]:
        state = _dict_to_state(position["state"], deserialize_events(position["events"]), 3)
        player = position["player"]
        labels = {json.dumps(action["key"]): sum(map(sum, action["values"])) / 96
                  for action in position["actions"]}
        oracle = max(labels.values())
        for tier in (3, 4):
            for method in METHODS:
                counts = Counter()
                simulate = root_search.simulate_state

                def measured(branch, *args, **kwargs):
                    value = simulate(branch, *args, **kwargs)
                    counts["rollouts"] += 1
                    counts["terminal"] += branch.finished
                    counts["head_placed"] += bool(branch.finish_order)
                    counts["remaining_cards"] += sum(map(len, branch.hands))
                    return value

                root_search.simulate_state = measured
                try:
                    strategy = policy(tier, method, iterations)
                    strategy.rng = random.Random(seed_for("diagnostic", deal["index"]))
                    action = strategy.select_pattern(state, player)
                finally:
                    root_search.simulate_state = simulate
                result = strategy.last_search
                selected = key(action)
                search_key = key(result.pattern) if result else selected
                reference_key = json.dumps(position["reference_key"])
                covered = [labels[key(stat.pattern)] for stat in result.actions
                           if key(stat.pattern) in labels] if result else []
                rows.append({
                    "index": deal["index"], "phase": position["phase"], "tier": tier,
                    "method": method, "selected_key": selected, "search_key": search_key,
                    "reason": strategy.last_decision_reason, "guard": strategy.last_guard,
                    "regret": oracle - labels[selected] if selected in labels else None,
                    "reference_regret": oracle - labels[reference_key],
                    "pool_regret": oracle - max(covered) if covered else None,
                    "search_regret": oracle - labels[search_key] if search_key in labels else None,
                    "elapsed_seconds": result.elapsed_seconds if result else None,
                    "common_samples": result.common_samples if result else None,
                    "ranker": result.action_ranker if result else None,
                    "continuations": dict(counts),
                    "actions": [{"key": key(stat.pattern), "mean": stat.mean_value,
                                 "visits": stat.visits, "paired_error": stat.paired_standard_error,
                                 "label": labels.get(key(stat.pattern))}
                                for stat in result.actions] if result else [],
                })
    return rows


def summarize(rows):
    summaries = []
    for tier in (3, 4):
        for method in METHODS:
            group = [row for row in rows if row["tier"] == tier and row["method"] == method]
            baseline = {row["index"]: row for row in rows
                        if row["tier"] == tier and row["method"] == "baseline"}
            counts = Counter()
            for row in group:
                counts.update(row["continuations"])
            record = {"tier": tier, "method": method, "positions": len(group),
                      "reasons": dict(Counter(row["reason"] for row in group)),
                      "selection_changes": sum(row["selected_key"] != baseline[row["index"]]["selected_key"] for row in group),
                      "nominations": sum(bool((row["ranker"] or {}).get("candidate_replaced")) for row in group),
                      "rollouts": counts["rollouts"],
                      "terminal_fraction": counts["terminal"] / max(1, counts["rollouts"]),
                      "head_placed_fraction": counts["head_placed"] / max(1, counts["rollouts"])}
            for field in ("regret", "pool_regret", "search_regret", "reference_regret", "elapsed_seconds", "common_samples"):
                values = [row[field] for row in group if row[field] is not None]
                record[field] = statistics.mean(values) if values else None
                record[f"{field}_count"] = len(values)
            matched = [(row, baseline[row["index"]]) for row in group
                       if row["regret"] is not None and baseline[row["index"]]["regret"] is not None]
            record["paired_regret_improvement"] = statistics.mean(
                base["regret"] - row["regret"] for row, base in matched) if matched else None
            record["paired_regret_count"] = len(matched)
            summaries.append(record)
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, default=Path("benchmarks/action-ranker-v1/labels"))
    parser.add_argument("--positions", type=int, default=32)
    parser.add_argument("--iterations", type=int, default=128)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.positions <= 96 or min(args.iterations, args.workers) < 1:
        parser.error("invalid positions, work limit or workers")
    files = [args.labels / f"{5 + 6 * i:04d}.json.gz" for i in range(args.positions)]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with mp.get_context("spawn").Pool(args.workers, maxtasksperchild=4) as pool:
        for result in pool.imap_unordered(diagnose, [(str(p), args.iterations) for p in files]):
            rows.extend(result)
            print(f"diagnostic: {len(rows)//8}/{len(files)} positions", flush=True)
    report = {"schema": 1, "purpose": "exploratory previously observed v8 diagnostic labels",
              "iterations_per_decision": args.iterations, "methods": list(METHODS),
              "labels_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "summary": summarize(rows), "observations": sorted(rows, key=lambda r: (r["index"], r["tier"], r["method"]))}
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
