"""Predeclared action-ranker experiment with gated independent acceptance.

Development can reject the model. Rejected tiers never spend or reuse holdout
seeds. Fixed-work strength experiments and serial production clocks are separate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import subprocess
import sys
import time
from pathlib import Path

from guandan.ai import diagnostics
from guandan.ai.action_ranker import MODEL_PATH, load_model
from guandan.ai.arena import paired_score_interval
from guandan.ai.strategy import make_strategy
from guandan.engine.state import clone_state_for_search, pass_turn, play_pattern
from scripts.ai_partner_validation import clock_tier_passed, paired_gate
from scripts.ai_team_trial import candidate, pair, source_fingerprint, summarize
from scripts.fit_action_ranker import derived_seed, label_recipe

COUNTS = {"dev-team": 32, "dev-mixed": 32, "holdout": 240, "mixed": 240, "full": 48}


def validate_pairs(rows: list[dict], seeds: list[int]) -> None:
    """Require exactly one completed game per side of every declared seed pair."""
    groups: dict[int, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["seed"], []).append(row)
    if set(groups) != set(seeds):
        raise ValueError("trial seed set differs from the predeclared recipe")
    for group in groups.values():
        if (len(group) != 2 or {row["candidate_team"] for row in group} != {0, 1}
                or not all(row["result"]["finished"] for row in group)):
            raise ValueError("trial needs two completed swapped-team games per seed")


def trial_config(root: Path, tier: int, suite: str) -> dict:
    return {"baseline_root": str(root.resolve()), "baseline_sha": label_recipe(root)["baseline_sha256"],
            "suite": "full" if suite == "full" else "mixed" if "mixed" in suite else "dev",
            "experiment_suite": suite, "variant": "action_ranker", "mode": "fixed",
            "difficulty": tier, "deals": COUNTS[suite], "match_states": True,
            "fixed_iterations": 128 if suite.startswith("dev") else 256 if tier == 3 else 768,
            "source_sha256": source_fingerprint(), "seed_schedule": "action-ranker-v1",
            "model_sha256": hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest()}


def run_trial(root: Path, folder: Path, tier: int, suite: str, workers: int) -> dict:
    config = trial_config(root, tier, suite)
    seeds = [derived_seed(f"{suite}-{tier}", i) for i in range(COUNTS[suite])]
    path = folder / f"{suite}-{tier}.json"
    if path.exists():
        report = json.loads(path.read_text())
        if report["config"] != config:
            raise ValueError("trial recipe/source differs; use a new folder")
        validate_pairs(report["observations"], seeds)
        return report
    progress = path.with_suffix(".progress.jsonl")
    rows = []
    if progress.exists():
        for line in progress.read_text().splitlines():
            item = json.loads(line)
            if item["config"] != config:
                raise ValueError("checkpoint recipe/source differs")
            rows.extend(item["rows"])
    done = {r["seed"] for r in rows}
    jobs = [(i, seed, config) for i, seed in enumerate(seeds) if seed not in done]
    started = time.perf_counter()
    with mp.get_context("spawn").Pool(workers, maxtasksperchild=4) as pool:
        for new_rows in pool.imap_unordered(pair, jobs):
            rows.extend(new_rows)
            with progress.open("a") as stream:
                stream.write(json.dumps({"config": config, "rows": new_rows}) + "\n")
            print(f"{suite}-{tier}: {len(rows)//2}/{COUNTS[suite]} pairs", flush=True)
    validate_pairs(rows, seeds)
    report = {"config": config, "workers": workers, "elapsed_seconds": time.perf_counter() - started,
              **summarize(rows), "observations": sorted(rows, key=lambda r: (r["seed"], r["candidate_team"]))}
    if suite == "full":
        scores = [(sum(r["utility"] for r in rows if r["seed"] == seed) / 2) for seed in seeds]
        report["match_win_rate"] = sum(scores) / len(scores)
        report["match_win_confidence_95"] = paired_score_interval(scores, samples=5000)
    path.write_text(json.dumps(report, indent=2) + "\n")
    progress.unlink(missing_ok=True)
    return report


def clock_check() -> dict:
    records, consecutive = [], []
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
                    load_model.cache_clear()
                policy = candidate(tier, "action_ranker", "clock")
                policy.rng.seed(derived_seed(f"clock-{tier}-{condition}", index))
                critical = policy._critical_decision(state, state.current_player())
                budget = policy.critical_time_budget_ms if critical else policy.time_budget_ms
                started = time.perf_counter()
                action = policy.select_pattern(state, state.current_player())
                elapsed = time.perf_counter() - started
                check = clone_state_for_search(state)
                if action is None:
                    pass_turn(check, state.current_player())
                else:
                    play_pattern(check, state.current_player(), action)
                ranking = policy.last_search.action_ranker if policy.last_search else None
                records.append({"tier": tier, "case": name, "cache": condition, "budget_ms": budget,
                                "elapsed_seconds": elapsed, "reason": policy.last_decision_reason,
                                "action_ranker": ranking,
                                "passed": elapsed <= budget / 1000 * 1.15 + 0.1
                                and (ranking is None or ranking["elapsed_seconds"] <= budget / 1000 * 0.05)})
        state = clone_state_for_search(corpus[0][1])
        human_action = make_strategy(2).select_pattern(state, state.current_player())
        if human_action is None:
            pass_turn(state, state.current_player())
        else:
            play_pattern(state, state.current_player(), human_action)
        total = 0.0
        for step in range(3):
            actor = state.current_player()
            policy = candidate(tier, "action_ranker", "clock")
            policy.rng.seed(derived_seed(f"consecutive-{tier}", step))
            budget = policy.critical_time_budget_ms if policy._critical_decision(state, actor) else policy.time_budget_ms
            started = time.perf_counter()
            action = policy.select_pattern(state, actor)
            elapsed = time.perf_counter() - started
            total += elapsed
            if action is None:
                pass_turn(state, actor)
            else:
                play_pattern(state, actor, action)
            ranking = policy.last_search.action_ranker if policy.last_search else None
            consecutive.append({"tier": tier, "step": step, "seat": actor, "budget_ms": budget,
                                "elapsed_seconds": elapsed, "cumulative_seconds": total,
                                "action_ranker": ranking,
                                "passed": elapsed <= budget / 1000 * 1.15 + 0.1
                                and (ranking is None or ranking["elapsed_seconds"] <= budget / 1000 * 0.05)})
    return {"source_sha256": source_fingerprint(), "workers": 1,
            "records": records, "consecutive_actions": consecutive,
            "passed": all(row["passed"] for row in records + consecutive)}


def development_gate(team: dict, mixed: dict, diagnostic: dict, clock: dict, tier: int) -> bool:
    return (team["pairs"] == 32 and mixed["pairs"] == 32
            and team["mean_paired_gain"] > 0 and mixed["mean_paired_gain"] > 0
            and diagnostic["diagnostic_improved"] and clock_tier_passed(clock, tier))


def promotion_gate(team: dict, mixed: dict, full: dict, clock: dict, tier: int) -> bool:
    return (paired_gate(team, mixed) and clock_tier_passed(clock, tier)
            and full["pairs"] == 48 and full["games"] == 96
            and full["match_win_confidence_95"][0] > 0.5
            and all(row["result"]["finished"] for row in full["observations"]))


def summarize_experiment(folder: Path, lock: dict) -> dict:
    clock = json.loads((folder / "clock.json").read_text())
    tiers = {}
    for tier in (3, 4):
        entered = lock["development_passed"][str(tier)]
        reports = {}
        for suite in COUNTS:
            path = folder / f"{suite}-{tier}.json"
            if path.exists():
                reports[suite] = json.loads(path.read_text())
                report = reports[suite]
                expected = [derived_seed(f"{suite}-{tier}", i) for i in range(COUNTS[suite])]
                validate_pairs(report["observations"], expected)
                if (report["config"]["source_sha256"] != lock["source_sha256"]
                        or report["config"]["model_sha256"] != lock["model_sha256"]):
                    raise ValueError("report source/model differs from the development lock")
        replay_path = folder / f"replay-{tier}.json"
        replay = json.loads(replay_path.read_text()) if replay_path.exists() else None
        replay_passed = bool(replay and replay["source_sha256"] == lock["source_sha256"]
                             and replay["difficulty"] == tier and replay["ruleset_override"] == 3
                             and replay["worlds"] == 32 and len(replay["positions"]) == 6
                             and all(len(row["styles"]) == 3
                                     and all(len(style["paired_differences"]) == 32
                                             for style in row["styles"])
                                     for row in replay["positions"]))
        eligible = (entered and all(s in reports for s in ("holdout", "mixed", "full"))
                    and replay_passed
                    and promotion_gate(reports["holdout"], reports["mixed"], reports["full"], clock, tier))
        tiers[str(tier)] = {"development_passed": entered,
                           "independent_acceptance": "completed" if all(s in reports for s in ("holdout", "mixed", "full"))
                           else "not_run_development_failed" if not entered else "pending",
                           "eligible_for_default": bool(eligible),
                           "clock_passed": clock_tier_passed(clock, tier),
                           "public_replay_passed": replay_passed,
                           "reports": {s: {k: v for k, v in r.items() if k != "observations"}
                                       for s, r in reports.items()}}
    return {"recipe": lock, "results": tiers, "clock_passed": clock["passed"],
            "interpretation": "Mixed agents are execution proxies; action labels and round utility use a frozen empirical continuation model. Full-match results record actual winners."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("dev", "clock", "validation", "full", "replay", "report"), required=True)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--folder", type=Path, default=Path("benchmarks/action-ranker-v1"))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("positive workers required")
    args.folder.mkdir(parents=True, exist_ok=True)
    lock_path = args.folder / "validation-lock.json"
    if args.stage == "clock":
        report = clock_check()
        (args.folder / "clock.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
        print(json.dumps({"clock_passed": report["passed"]}), flush=True)
        return
    if args.stage == "dev":
        fit_report = json.loads((args.folder / "fit.json").read_text())
        if fit_report["model_sha256"] != hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest():
            raise ValueError("trained model changed before development")
        clock = json.loads((args.folder / "clock.json").read_text())
        if clock["source_sha256"] != source_fingerprint():
            raise ValueError("clock source differs from candidate")
        passed, scores = {}, {}
        for tier in (3, 4):
            team = run_trial(args.baseline_root, args.folder, tier, "dev-team", args.workers)
            mixed = run_trial(args.baseline_root, args.folder, tier, "dev-mixed", args.workers)
            passed[str(tier)] = development_gate(team, mixed, fit_report, clock, tier)
            scores[str(tier)] = {"team": team["mean_paired_gain"], "mixed": mixed["mean_paired_gain"]}
        lock = {"source_sha256": source_fingerprint(), "model_sha256": fit_report["model_sha256"],
                "baseline": label_recipe(args.baseline_root), "development_passed": passed,
                "development_scores": scores, "counts": COUNTS,
                "iterations": {"development": 128, "3": 256, "4": 768},
                "seed_schedule": "sha256-action-ranker-v1-stage-index-round",
                "sampling": "predeclared once; never append seeds after looking at results"}
        if lock_path.exists() and json.loads(lock_path.read_text()) != lock:
            raise ValueError("development selection already locked")
        lock_path.write_text(json.dumps(lock, indent=2) + "\n")
        print(json.dumps({"development_passed": passed}), flush=True)
        return
    lock = json.loads(lock_path.read_text())
    if lock["source_sha256"] != source_fingerprint():
        raise ValueError("source changed after development lock")
    if lock["baseline"] != label_recipe(args.baseline_root):
        raise ValueError("baseline or label recipe changed after development lock")
    if args.stage == "replay":
        for tier in (3, 4):
            subprocess.run([sys.executable, "-m", "scripts.ai_replay_trial", "--baseline-root", str(args.baseline_root),
                            "--variant", "action_ranker", "--difficulty", str(tier), "--ruleset", "3", "--worlds", "32",
                            "--fixed-iterations", str(256 if tier == 3 else 768),
                            "--out", str(args.folder / f"replay-{tier}.json")], check=True)
    elif args.stage in ("validation", "full"):
        for tier in (3, 4):
            if lock["development_passed"][str(tier)]:
                for suite in (("holdout", "mixed") if args.stage == "validation" else ("full",)):
                    run_trial(args.baseline_root, args.folder, tier, suite, args.workers)
            else:
                print(f"tier {tier}: independent seeds reserved; development gate failed", flush=True)
    else:
        report = summarize_experiment(args.folder, lock)
        (args.folder / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({tier: r["eligible_for_default"] for tier, r in report["results"].items()}))


if __name__ == "__main__":
    main()
