"""Predeclared v7 paired screens and one-shot independent acceptance.

Run development, validation, full, and clock in that order. Clock runs are
serial and must not overlap fixed-work experiments. Reports/checkpoints are
reused only when their complete source/config fingerprint still matches.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

from guandan.ai import diagnostics
from guandan.engine.state import clone_state_for_search, pass_turn, play_pattern
from scripts.ai_team_trial import candidate, source_fingerprint

VARIANTS = ("adaptive", "chain", "partner_combined")
DEV = {3: (200000, 200100), 4: (200032, 200132)}
HOLDOUT = {3: (202000, 203000), 4: (202240, 203240)}
FULL = {3: 204000, 4: 204024}


def run(root, folder, tier, variant, suite, seed, count, iterations):
    output = folder / f"ai-v7-{suite}-{tier}-{variant}.json"
    if output.exists():
        report = json.loads(output.read_text())
        config = report["config"]
        expected = (seed, count, variant, tier, iterations, source_fingerprint())
        actual = tuple(
            config[k]
            for k in (
                "seed_start",
                "deals",
                "variant",
                "difficulty",
                "fixed_iterations",
                "source_sha256",
            )
        )
        if expected != actual:
            raise RuntimeError(f"existing report is from a different recipe/source: {output}")
        return report
    subprocess.run(
        [
            sys.executable,
            "scripts/ai_team_trial.py",
            "--baseline-root",
            str(root),
            "--suite",
            "full" if suite == "full" else "mixed" if "mixed" in suite else "dev",
            "--variant",
            variant,
            "--difficulty",
            str(tier),
            "--seed-start",
            str(seed),
            "--deals",
            str(count),
            "--fixed-iterations",
            str(iterations),
            "--match-states",
            "--workers",
            str(run.workers),
            "--out",
            str(output),
        ],
        check=True,
    )
    return json.loads(output.read_text())


def paired_gate(team, mixed):
    return (
        team["pairs"] == 240
        and mixed["pairs"] == 240
        and team["gain_confidence_95"][0] > 0
        and mixed["gain_confidence_95"][0] > 0
        and len(mixed["by_companion"]) == 3
        and all(row["mean_paired_gain"] >= 0 for row in mixed["by_companion"].values())
    )


def clock_tier_passed(clock, tier):
    records = [row for row in clock["records"] if row["tier"] == tier]
    consecutive = [row for row in clock["consecutive_actions"] if row["tier"] == tier]
    return (
        bool(records)
        and len(consecutive) == 3
        and all(row["passed"] for row in records + consecutive)
    )


def clock_check(selected):
    records = []
    corpus = diagnostics.positions()
    cold = diagnostics.endgame_positions()
    for tier in (3, 4):
        for condition, cases in (("warm", corpus), ("cold", cold)):
            for index, (name, state) in enumerate(cases):
                if condition == "cold":
                    diagnostics._exact_material_cache.clear()
                    diagnostics._estimate.cache_clear()
                    diagnostics._patterns_in_hand.cache_clear()
                    diagnostics._complete_pattern_cache.clear()
                    diagnostics._holding_chance.cache_clear()
                policy = candidate(tier, selected[str(tier)], "clock")
                policy.rng.seed(205000 + tier * 100 + index)
                critical = policy._critical_decision(state, state.current_player())
                budget = policy.critical_time_budget_ms if critical else policy.time_budget_ms
                started = time.perf_counter()
                action = policy.select_pattern(state, state.current_player())
                elapsed = time.perf_counter() - started
                validation = clone_state_for_search(state)
                if action is None:
                    pass_turn(validation, state.current_player())
                else:
                    play_pattern(validation, state.current_player(), action)
                result = policy.last_search
                records.append(
                    {
                        "tier": tier,
                        "case": name,
                        "cache": condition,
                        "budget_ms": budget,
                        "elapsed_seconds": elapsed,
                        "passed": elapsed <= budget / 1000 * 1.15 + 0.1,
                        "reason": policy.last_decision_reason,
                        "search": asdict(result) if result else None,
                    }
                )
    consecutive = []
    for tier in (3, 4):
        state = clone_state_for_search(corpus[0][1])
        total = 0.0
        for step in range(3):
            actor = state.current_player()
            policy = candidate(tier, selected[str(tier)], "clock")
            policy.rng.seed(206000 + step)
            budget = (
                policy.critical_time_budget_ms
                if policy._critical_decision(state, actor)
                else policy.time_budget_ms
            )
            started = time.perf_counter()
            action = policy.select_pattern(state, actor)
            elapsed = time.perf_counter() - started
            total += elapsed
            if action is None:
                pass_turn(state, actor)
            else:
                play_pattern(state, actor, action)
            consecutive.append(
                {
                    "tier": tier,
                    "step": step,
                    "seat": actor,
                    "budget_ms": budget,
                    "elapsed_seconds": elapsed,
                    "cumulative_seconds": total,
                    "passed": elapsed <= budget / 1000 * 1.15 + 0.1,
                }
            )
    return {
        "records": records,
        "consecutive_actions": consecutive,
        "passed": all(row["passed"] for row in records + consecutive),
        "workers": 1,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--folder", type=Path, default=Path("benchmarks"))
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument(
        "--stage", choices=("dev", "validation", "full", "clock", "report"), required=True
    )
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("positive workers required")
    run.workers = args.workers
    args.folder.mkdir(parents=True, exist_ok=True)
    lock_path = args.folder / "ai-v7-validation-lock.json"
    if args.stage == "dev":
        selection = {}
        screens = {}
        for tier in (3, 4):
            variants = {}
            for variant in VARIANTS:
                team = run(
                    args.baseline_root,
                    args.folder,
                    tier,
                    variant,
                    "dev-team",
                    DEV[tier][0],
                    32,
                    128,
                )
                mixed = run(
                    args.baseline_root,
                    args.folder,
                    tier,
                    variant,
                    "dev-mixed",
                    DEV[tier][1],
                    32,
                    128,
                )
                variants[variant] = {
                    "team": team["mean_paired_gain"],
                    "mixed": mixed["mean_paired_gain"],
                    "selection_score": min(team["mean_paired_gain"], mixed["mean_paired_gain"]),
                }
            # Selection is a development ranking, never a strength claim.
            selection[str(tier)] = max(VARIANTS, key=lambda v: variants[v]["selection_score"])
            screens[str(tier)] = variants
        recipe = {
            "source_sha256": source_fingerprint(),
            "baseline_root": str(args.baseline_root.resolve()),
            "baseline": json.loads((args.baseline_root / "policy-snapshot.json").read_text()),
            "selected": selection,
            "screens": screens,
            "development_pairs_per_suite": 32,
            "holdout": {
                str(t): {
                    "team_start": s[0],
                    "mixed_start": s[1],
                    "pairs_each": 240,
                    "iterations": 256 if t == 3 else 768,
                }
                for t, s in HOLDOUT.items()
            },
            "full": {str(t): {"seed_start": s, "pairs": 24} for t, s in FULL.items()},
            "promotion": "both independent paired 95% lower bounds > 0 and each mixed companion mean >= 0; serial clock and complete-match legality gates",
            "sampling": "fixed once; no appended holdout seeds",
        }
        if lock_path.exists() and json.loads(lock_path.read_text()) != recipe:
            raise RuntimeError("selection is already locked")
        lock_path.write_text(json.dumps(recipe, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(selection), flush=True)
        return
    recipe = json.loads(lock_path.read_text())
    if recipe["source_sha256"] != source_fingerprint():
        raise RuntimeError("source changed after selection lock")
    selected = recipe["selected"]
    if args.stage == "validation":
        for tier in (3, 4):
            for suite, seed in zip(("holdout", "mixed"), HOLDOUT[tier]):
                run(
                    args.baseline_root,
                    args.folder,
                    tier,
                    selected[str(tier)],
                    suite,
                    seed,
                    240,
                    256 if tier == 3 else 768,
                )
    elif args.stage == "full":
        for tier in (3, 4):
            run(
                args.baseline_root,
                args.folder,
                tier,
                selected[str(tier)],
                "full",
                FULL[tier],
                24,
                256 if tier == 3 else 768,
            )
    elif args.stage == "clock":
        report = {
            "source_sha256": source_fingerprint(),
            "selected": selected,
            **clock_check(selected),
        }
        (args.folder / "ai-v7-clock.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"
        )
        print(json.dumps({"clock_passed": report["passed"]}), flush=True)
    else:
        clock = json.loads((args.folder / "ai-v7-clock.json").read_text())
        results = {}
        for tier in (3, 4):
            variant = selected[str(tier)]
            team = json.loads((args.folder / f"ai-v7-holdout-{tier}-{variant}.json").read_text())
            mixed = json.loads((args.folder / f"ai-v7-mixed-{tier}-{variant}.json").read_text())
            full = json.loads((args.folder / f"ai-v7-full-{tier}-{variant}.json").read_text())
            results[str(tier)] = {
                "selected": variant,
                "clock_passed": clock_tier_passed(clock, tier),
                "team": {k: v for k, v in team.items() if k != "observations"},
                "mixed": {k: v for k, v in mixed.items() if k != "observations"},
                "full": {k: v for k, v in full.items() if k != "observations"},
                "eligible_for_default": bool(
                    paired_gate(team, mixed)
                    and clock_tier_passed(clock, tier)
                    and full["pairs"] == 24
                ),
            }
        output = {
            "recipe": recipe,
            "results": results,
            "clock_passed": clock["passed"],
            "interpretation": "single-round continuation utility and observed full-match results are distinct; mixed agents are human execution proxies",
        }
        (args.folder / "ai-v7-validation.json").write_text(
            json.dumps(output, ensure_ascii=False, indent=2) + "\n"
        )
        print(
            json.dumps({tier: row["eligible_for_default"] for tier, row in results.items()}),
            flush=True,
        )


if __name__ == "__main__":
    main()
