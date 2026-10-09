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
import tracemalloc
from collections import Counter
from pathlib import Path

from guandan.ai.candidates import pattern_key
from guandan.ai.hand_plan import _estimate
from guandan.ai.mcts import root_search
from guandan.ai.strategies.dachangsheng import DaiChangshengStrategy
from guandan.ai.strategies.professional import ProfessionalStrategy
from guandan.ai.tactics import select_heuristic_action
from guandan.engine.state import pass_turn, play_pattern
from guandan.storage.savegame import _dict_to_state
from guandan.storage.serialization import deserialize_events
from scripts.ai_manifest import evaluation_manifest
from scripts.fit_action_ranker import _continuation_key

METHODS = ("baseline", "ranker", "horizon120", "complete", "reference8", "reference_complete", "refined")


def seed_for(stage: str, index: int, round_index: int = 0, *, namespace: str = "continuation-v9") -> int:
    return int.from_bytes(hashlib.sha256(
        f"{namespace}/{stage}/{index}/{round_index}".encode()).digest()[:8], "big")


def key(action):
    return json.dumps(pattern_key(action) if action is not None else ("pass",))


def policy(tier, method, iterations, *, clock=False):
    options = {} if clock else {"time_budget_ms": 0, "iterations": iterations}
    if method == "ranker":
        options["action_ranker"] = True
    if method in ("horizon120", "complete", "reference8", "reference_complete"):
        options["rollout_max_turns"] = 120 if method in ("horizon120", "reference8") else 4000
    if method.startswith("reference"):
        options["reference_rollout_turns"] = 8 if method == "reference8" else 4000
    if method == "refined":
        options["reference_refinement"] = True
    if tier == 3:
        return ProfessionalStrategy(**options)
    return DaiChangshengStrategy(mcts_overrides=options)


def reference_continuation(branch, root, *, rollout_strategy_level, max_turns,
                           reference_turns, memo, **_kwargs):
    """Exploratory actor-local tier-2 continuation, with an exact decision memo."""
    from guandan.ai.mcts.search import (
        _evaluate_result,
        _rollout_select_pattern,
        planned_position_value,
    )

    for turn in range(max_turns):
        if branch.finished:
            break
        actor = branch.current_player()
        if turn < reference_turns:
            public = _continuation_key(branch)
            memo_key = (actor, tuple(sorted(branch.hands[actor])), public)
            if memo_key not in memo:
                memo[memo_key] = select_heuristic_action(branch, actor, 2)
            action = memo[memo_key]
        else:
            action = _rollout_select_pattern(branch, actor, rollout_strategy_level=rollout_strategy_level)
        if action is None:
            pass_turn(branch, actor)
        else:
            play_pattern(branch, actor, action)
    if rollout_strategy_level >= 2 and not branch.finish_order:
        return planned_position_value(branch, root)
    return _evaluate_result(branch, root)


def diagnose(job):
    filename, iterations, methods, *options = job
    namespace, measure_memory = options if options else ("continuation-v9", False)
    deal = json.loads(gzip.decompress(Path(filename).read_bytes()))
    rows = []
    for position in deal["positions"]:
        state = _dict_to_state(position["state"], deserialize_events(position["events"]), 3)
        player = position["player"]
        labels = {json.dumps(action["key"]): sum(map(sum, action["values"])) / 96
                  for action in position["actions"]}
        oracle = max(labels.values())
        for tier in (3, 4):
            for method in methods:
                counts = Counter()
                memo = {}
                simulate = root_search.simulate_state

                def measured(branch, *args, method=method, memo=memo, simulate=simulate, counts=counts, **kwargs):
                    if method.startswith("reference"):
                        value = reference_continuation(branch, *args, **kwargs,
                            reference_turns=8 if method == "reference8" else 4000, memo=memo)
                    else:
                        value = simulate(branch, *args, **kwargs)
                    counts["rollouts"] += 1
                    counts["terminal"] += branch.finished
                    counts["head_placed"] += bool(branch.finish_order)
                    counts["remaining_cards"] += sum(map(len, branch.hands))
                    return value

                root_search.simulate_state = measured
                before = _estimate.cache_info()
                peak_bytes = None
                if measure_memory:
                    tracemalloc.start()
                try:
                    strategy = policy(tier, method, iterations)
                    strategy.rng = random.Random(seed_for("diagnostic", deal["index"], namespace=namespace))
                    action = strategy.select_pattern(state, player)
                finally:
                    root_search.simulate_state = simulate
                    if measure_memory:
                        peak_bytes = tracemalloc.get_traced_memory()[1]
                        tracemalloc.stop()
                after = _estimate.cache_info()
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
                    "common_samples_per_second": result.common_samples / max(1e-9, result.elapsed_seconds) if result else None,
                    "terminal_common_samples": result.terminal_common_samples if result else None,
                    "terminal_common_samples_per_second": result.terminal_common_samples / max(1e-9, result.elapsed_seconds) if result else None,
                    "cutoff_fraction": result.cutoff_rollouts / max(1, result.simulations) if result else None,
                    "root_final_disagree": search_key != selected,
                    "plan_cache_hits": after.hits - before.hits,
                    "plan_cache_misses": after.misses - before.misses,
                    "peak_traced_bytes": peak_bytes,
                    "ranker": result.action_ranker if result else None,
                    "refinement": result.reference_refinement if result else None,
                    "continuations": dict(counts),
                    "actions": [{"key": key(stat.pattern), "mean": stat.mean_value,
                                 "visits": stat.visits, "paired_error": stat.paired_standard_error,
                                 "label": labels.get(key(stat.pattern))}
                                for stat in result.actions] if result else [],
                })
    return rows


def summarize(rows, methods=METHODS):
    summaries = []
    for tier in (3, 4):
        for method in methods:
            group = [row for row in rows if row["tier"] == tier and row["method"] == method]
            baseline = {(row["index"], row["phase"]): row for row in rows
                        if row["tier"] == tier and row["method"] == "baseline"}
            counts = Counter()
            for row in group:
                counts.update(row["continuations"])
            record = {"tier": tier, "method": method, "positions": len(group),
                      "reasons": dict(Counter(row["reason"] for row in group)),
                      "selection_changes": sum(row["selected_key"] != baseline[row["index"], row["phase"]]["selected_key"] for row in group),
                      "nominations": sum(bool((row["ranker"] or {}).get("candidate_replaced")) for row in group),
                      "rollouts": counts["rollouts"],
                      "terminal_fraction": counts["terminal"] / max(1, counts["rollouts"]),
                      "head_placed_fraction": counts["head_placed"] / max(1, counts["rollouts"])}
            for field in ("regret", "pool_regret", "search_regret", "reference_regret", "elapsed_seconds", "common_samples",
                          "common_samples_per_second", "terminal_common_samples", "terminal_common_samples_per_second",
                          "cutoff_fraction", "plan_cache_hits", "plan_cache_misses", "peak_traced_bytes"):
                values = [row[field] for row in group if row[field] is not None]
                record[field] = statistics.mean(values) if values else None
                record[f"{field}_count"] = len(values)
            matched = [(row, baseline[row["index"], row["phase"]]) for row in group
                       if row["regret"] is not None and baseline[row["index"], row["phase"]]["regret"] is not None]
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
    parser.add_argument("--methods", default=",".join(METHODS))
    parser.add_argument("--seed-namespace", default="review-diagnostic-20261009")
    parser.add_argument("--measure-memory", action="store_true", help="instrumented timings are not production latency")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    methods = tuple(args.methods.split(","))
    if "baseline" not in methods or any(method not in METHODS for method in methods):
        parser.error("methods must contain baseline and supported variants")
    if not 1 <= args.positions <= 96 or min(args.iterations, args.workers) < 1:
        parser.error("invalid positions, work limit or workers")
    files = [args.labels / f"{5 + 6 * i:04d}.json.gz" for i in range(args.positions)]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with mp.get_context("spawn").Pool(args.workers, maxtasksperchild=4) as pool:
        for result in pool.imap_unordered(diagnose, [(str(p), args.iterations, methods, args.seed_namespace, args.measure_memory) for p in files]):
            rows.extend(result)
            print(f"diagnostic: {len(rows)//(2*len(methods))}/{len(files)} positions", flush=True)
    report = {"schema": 1, "purpose": "exploratory previously observed v8 diagnostic labels",
              "seed_namespace": args.seed_namespace, "memory_instrumented": args.measure_memory,
              "iterations_per_decision": args.iterations, "methods": list(methods),
              "labels_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "evaluation_manifest": evaluation_manifest(Path(__file__).resolve().parents[1],
                  {"namespace": args.seed_namespace, "iterations": args.iterations, "methods": list(methods),
                   "positions": args.positions, "workers": args.workers, "memory_instrumented": args.measure_memory}),
              "summary": summarize(rows, methods), "observations": sorted(rows, key=lambda r: (r["index"], r["tier"], r["method"]))}
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
