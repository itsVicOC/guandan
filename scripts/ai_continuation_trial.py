"""Gated v9 continuation trials against an isolated workspace snapshot.

Development chooses between horizon120 and paired expert refinement. Previously
observed v8 labels are exploratory and never serve as a new strength holdout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import time
from collections import Counter
from pathlib import Path

from guandan.ai import diagnostics
from guandan.ai.arena import paired_score_interval
from guandan.ai.strategy import make_strategy
from guandan.engine.state import clone_state_for_search, pass_turn, play_pattern
from scripts import ai_team_trial as trial
from scripts.ai_action_ranker_validation import validate_pairs
from scripts.ai_continuation_diagnostic import policy, seed_for
from scripts.ai_partner_validation import paired_gate
from scripts.fit_action_ranker import snapshot_fingerprint

METHODS = ("horizon120", "refined")
COUNTS = {"dev-team": 32, "dev-mixed": 32, "holdout": 240, "mixed": 240, "full": 48}


def fingerprint():
    digest = hashlib.sha256(trial.source_fingerprint().encode())
    for name in ("ai_continuation_diagnostic.py", "ai_continuation_trial.py"):
        digest.update(name.encode())
        digest.update(Path(__file__).with_name(name).read_bytes())
    return digest.hexdigest()


def trial_pair(job):
    """Install a process-local factory, preserving the existing paired protocol."""
    original_factory, original_measured, original_full = trial.candidate, trial.MeasuredCandidate, trial.run_full_match
    captured = []

    class Measured(original_measured):
        def __init__(self, *args):
            super().__init__(*args)
            captured.append(self)

        def select_pattern(self, state, player):
            self.team = player % 2
            action = super().select_pattern(state, player)
            result = self.strategy.last_search
            self.decisions[-1]["refinement"] = result.reference_refinement if result else None
            return action

    def factory(tier, variant, mode, fixed_iterations):
        return policy(tier, variant, fixed_iterations, clock=mode == "clock")

    def full(master, **kwargs):
        kwargs["round_seed_factory"] = lambda seed, offset: seed_for("full-deal", seed, offset)
        return original_full(master, **kwargs)

    trial.candidate, trial.MeasuredCandidate, trial.run_full_match = factory, Measured, full
    try:
        rows = trial.pair(job)
        for leg, row in enumerate(rows):
            reports = [decision["refinement"] for strategy in captured if getattr(strategy, "team", None) == leg
                       for decision in strategy.decisions if decision["refinement"]]
            row["refinement_reasons"] = dict(Counter(report["reason"] for report in reports))
            row["refinement_evaluations"] = sum(report["refinement_simulations"] for report in reports)
    finally:
        trial.candidate, trial.MeasuredCandidate, trial.run_full_match = original_factory, original_measured, original_full
    return rows


def run_trial(root, folder, tier, method, suite, workers):
    config = {"baseline_root": str(root.resolve()), "baseline_sha": snapshot_fingerprint(root),
              "suite": "full" if suite == "full" else "mixed" if "mixed" in suite else "dev",
              "experiment_suite": suite, "variant": method, "mode": "fixed", "difficulty": tier,
              "deals": COUNTS[suite], "match_states": True,
              "fixed_iterations": 128 if suite.startswith("dev") else 256 if tier == 3 else 768,
              "source_sha256": fingerprint(), "seed_schedule": "continuation-v9"}
    # Both development candidates share seeds; all subsequent stages are disjoint.
    seeds = [seed_for(f"{suite}-{tier}", i) for i in range(COUNTS[suite])]
    path = folder / f"{suite}-{tier}-{method}.json"
    if path.exists():
        report = json.loads(path.read_text())
        if report["config"] != config:
            raise ValueError("trial source/recipe differs; use a new folder")
        validate_pairs(report["observations"], seeds)
        return report
    progress = path.with_suffix(".progress.jsonl")
    rows = []
    if progress.exists():
        for line in progress.read_text().splitlines():
            item = json.loads(line)
            if item["config"] != config:
                raise ValueError("checkpoint source/recipe differs")
            rows.extend(item["rows"])
    done = {r["seed"] for r in rows}
    with mp.get_context("spawn").Pool(workers, maxtasksperchild=4) as pool:
        for new_rows in pool.imap_unordered(trial_pair, [(i, seed, config) for i, seed in enumerate(seeds) if seed not in done]):
            rows.extend(new_rows)
            with progress.open("a") as stream:
                stream.write(json.dumps({"config": config, "rows": new_rows}) + "\n")
            print(f"{suite}-{tier}-{method}: {len(rows)//2}/{len(seeds)} pairs", flush=True)
    validate_pairs(rows, seeds)
    report = {"config": config, "workers": workers, **trial.summarize(rows),
              "observations": sorted(rows, key=lambda r: (r["seed"], r["candidate_team"]))}
    if suite == "full":
        scores = [sum(r["utility"] for r in rows if r["seed"] == seed) / 2 for seed in seeds]
        report.update(match_win_rate=sum(scores) / len(scores),
                      match_win_confidence_95=paired_score_interval(scores, samples=5000))
    path.write_text(json.dumps(report, indent=2) + "\n")
    progress.unlink(missing_ok=True)
    return report


def clock_check(method):
    records = []
    corpus = diagnostics.positions()
    for tier in (3, 4):
        for condition, cases in (("warm", corpus), ("cold", diagnostics.endgame_positions())):
            for index, (name, state) in enumerate(cases):
                if condition == "cold":
                    diagnostics._exact_material_cache.clear()
                    diagnostics._estimate.cache_clear()
                    diagnostics._patterns_in_hand.cache_clear()
                    diagnostics._complete_pattern_cache.clear()
                    diagnostics._holding_chance.cache_clear()
                records.append(clock_decision(tier, method, condition, name, state, index))
        state = clone_state_for_search(corpus[0][1])
        human = make_strategy(2).select_pattern(state, state.current_player())
        apply_action(state, human)
        for step in range(3):
            row = clock_decision(tier, method, "consecutive", f"step-{step}", state, step)
            records.append(row)
            from guandan.storage.serialization import _dict_to_pattern

            apply_action(state, _dict_to_pattern(row["action"]) if row["action"] else None)
    return {"source_sha256": fingerprint(), "method": method, "workers": 1,
            "records": records, "passed": all(row["passed"] for row in records)}


def apply_action(state, action):
    actor = state.current_player()
    if action is None:
        pass_turn(state, actor)
    else:
        play_pattern(state, actor, action)


def clock_decision(tier, method, condition, name, state, index):
    from guandan.storage.savegame import _pattern_to_dict

    strategy = policy(tier, method, 128, clock=True)
    actor = state.current_player()
    strategy.rng.seed(seed_for(f"clock-{tier}-{method}-{condition}", index))
    budget = strategy.critical_time_budget_ms if strategy._critical_decision(state, actor) else strategy.time_budget_ms
    started = time.perf_counter()
    action = strategy.select_pattern(state, actor)
    elapsed = time.perf_counter() - started
    apply_action(clone_state_for_search(state), action)
    result = strategy.last_search
    return {"tier": tier, "method": method, "cache": condition, "case": name,
            "budget_ms": budget, "elapsed_seconds": elapsed,
            "reason": strategy.last_decision_reason, "action": _pattern_to_dict(action) if action else None,
            "simulations": result.simulations if result else 0,
            "refinement": result.reference_refinement if result else None,
            "passed": elapsed <= budget / 1000 * 1.15 + 0.1}


def tier_clock_passed(report, tier):
    records = [row for row in report["records"] if row["tier"] == tier]
    return len(records) == 21 and all(row["passed"] for row in records)


def development_gate(team, mixed, clock, tier):
    return team["pairs"] == mixed["pairs"] == 32 and team["mean_paired_gain"] > 0 and mixed["mean_paired_gain"] > 0 and tier_clock_passed(clock, tier)


def replay_check(root, tier, method):
    """Public human prefixes with legal hypothetical continuations, not human wins."""
    import random
    from dataclasses import replace

    from guandan.ai.candidates import pattern_key
    from guandan.ai.mcts.determinize import determinize
    from guandan.ai.mcts.information_set import _apply_action
    from guandan.engine.replay import replay_events
    from guandan.storage.serialization import deserialize_events
    from scripts.fit_action_ranker import frozen_playout

    fixture = Path(__file__).resolve().parents[1] / "tests/fixtures/ai-human-partner-replay.json"
    data = json.loads(fixture.read_text())
    rows = []
    for index in data["decision_events"]:
        events = deserialize_events(data["events"][:index])
        events[0] = replace(events[0], a_failure_counts=(0, 0))
        state = replay_events(events, allow_incomplete_tail=True, ruleset_version=3)
        actor = state.current_player()
        client = trial.FrozenClient(root)
        work = 256 if tier == 3 else 768
        try:
            old = trial.FrozenStrategy(client, tier, "fixed", work)
            new = policy(tier, method, work)
            old.rng = random.Random(seed_for(f"replay-action-{tier}", index))
            new.rng = random.Random(seed_for(f"replay-action-{tier}", index))
            actions = (old.select_pattern(state, actor), new.select_pattern(state, actor))
        finally:
            client.close()
        styles = []
        policies = [make_strategy(tier) for tier in range(3)]
        memo, value_memo = {}, {}
        for style in range(3):
            values = [[], []]
            for sample in range(32):
                world = determinize(state, actor, random.Random(seed_for("replay-world", index, sample)))
                for branch, action in enumerate(actions):
                    simulated = clone_state_for_search(world)
                    if not _apply_action(simulated, actor, action):
                        raise ValueError("illegal replay action")
                    values[branch].append(frozen_playout(simulated, actor, style, policies, memo, value_memo))
            styles.append({"companion": style, "worlds": 32, "old_values": values[0], "new_values": values[1]})
        rows.append({"prefix": index, "player": actor,
                     "old_action": pattern_key(actions[0]) if actions[0] else ("pass",),
                     "new_action": pattern_key(actions[1]) if actions[1] else ("pass",),
                     "styles": styles})
        print(f"replay-{tier}: prefix {index} complete", flush=True)
    return {"source_sha256": fingerprint(), "baseline_sha256": snapshot_fingerprint(root),
            "fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
            "tier": tier, "method": method, "fixture_ruleset": data.get("ruleset_version", 2),
            "ruleset_projection": 3, "completed_branches": len(rows) * 3 * 32 * 2,
            "positions": rows, "passed": len(rows) == 6}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--folder", type=Path, default=Path("benchmarks/continuation-v9"))
    parser.add_argument("--stage", choices=("clock", "dev", "validation", "full", "replay", "report"), required=True)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    args.folder.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((args.baseline_root / "snapshot-manifest.json").read_text())
    if snapshot_fingerprint(args.baseline_root) != manifest["source_sha256"]:
        raise ValueError("baseline snapshot has changed")
    recipe = {"source_sha256": fingerprint(), "baseline_sha256": manifest["source_sha256"],
              "counts": COUNTS, "methods": METHODS, "namespace": "continuation-v9",
              "selection": "largest minimum of team/mixed dev mean; both positive and serial clock must pass",
              "promotion": "both 240-pair intervals >0, all partners >=0, 48 full-pair interval >50%, replay and clock pass"}
    path = args.folder / "recipe.json"
    if path.exists() and json.loads(path.read_text()) != json.loads(json.dumps(recipe)):
        raise ValueError("frozen recipe changed; use a new experiment folder")
    path.write_text(json.dumps(recipe, indent=2) + "\n")
    if args.stage == "clock":
        for method in METHODS:
            report = clock_check(method)
            (args.folder / f"clock-{method}.json").write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps({"method": method, "passed": report["passed"], "reasons": dict(Counter(r["reason"] for r in report["records"]))}), flush=True)
        return
    if args.stage == "dev":
        selected = {}
        for tier in (3, 4):
            scores = []
            for method in METHODS:
                team = run_trial(args.baseline_root, args.folder, tier, method, "dev-team", args.workers)
                mixed = run_trial(args.baseline_root, args.folder, tier, method, "dev-mixed", args.workers)
                clock = json.loads((args.folder / f"clock-{method}.json").read_text())
                if clock["source_sha256"] != fingerprint():
                    raise ValueError("serial clock source differs")
                scores.append((min(team["mean_paired_gain"], mixed["mean_paired_gain"]), method,
                               development_gate(team, mixed, clock, tier)))
            score, method, passed = max([item for item in scores if item[2]] or scores)
            selected[str(tier)] = {"method": method, "selection_score": score, "development_passed": passed}
        (args.folder / "validation-lock.json").write_text(json.dumps({**recipe, "selected": selected}, indent=2) + "\n")
        return
    lock = json.loads((args.folder / "validation-lock.json").read_text())
    if lock["source_sha256"] != fingerprint():
        raise ValueError("locked candidate source differs")
    if args.stage in ("validation", "full"):
        for tier in (3, 4):
            item = lock["selected"][str(tier)]
            if not item["development_passed"]:
                print(f"tier {tier}: independent acceptance not run; development failed", flush=True)
                continue
            for suite in ("holdout", "mixed") if args.stage == "validation" else ("full",):
                run_trial(args.baseline_root, args.folder, tier, item["method"], suite, args.workers)
        return
    if args.stage == "replay":
        for tier in (3, 4):
            method = lock["selected"][str(tier)]["method"]
            report = replay_check(args.baseline_root, tier, method)
            (args.folder / f"replay-{tier}.json").write_text(json.dumps(report, indent=2) + "\n")
        return
    records = []
    for tier in (3, 4):
        item = lock["selected"][str(tier)]
        eligible = False
        if item["development_passed"]:
            reports = [json.loads((args.folder / f"{suite}-{tier}-{item['method']}.json").read_text())
                       for suite in ("holdout", "mixed", "full")]
            for suite, report in zip(("holdout", "mixed", "full"), reports):
                if report["config"]["source_sha256"] != fingerprint():
                    raise ValueError("acceptance source differs")
                validate_pairs(report["observations"], [seed_for(f"{suite}-{tier}", i) for i in range(COUNTS[suite])])
            eligible = (reports[0]["pairs"] == reports[1]["pairs"] == 240
                        and paired_gate(reports[0], reports[1])
                        and reports[2]["pairs"] == 48 and reports[2]["match_win_confidence_95"][0] > 0.5)
            replay = json.loads((args.folder / f"replay-{tier}.json").read_text())
            clock = json.loads((args.folder / f"clock-{item['method']}.json").read_text())
            eligible = (eligible and replay["source_sha256"] == clock["source_sha256"] == fingerprint()
                        and replay["passed"] and replay["completed_branches"] == 1152
                        and tier_clock_passed(clock, tier))
        records.append({"tier": tier, **item, "eligible_for_default": eligible,
                        "independent_acceptance": "completed" if item["development_passed"] else "not_run_development_failed"})
    (args.folder / "validation.json").write_text(json.dumps({**recipe, "tiers": records}, indent=2) + "\n")
    print(json.dumps(records, indent=2))


if __name__ == "__main__":
    main()
