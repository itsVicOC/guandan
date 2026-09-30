"""One-shot v6 development selection and disjoint fixed-work validation.

Development screens candidates by paired point estimates; the positive 95%
interval gate is reserved for independent validation. No additional
holdout samples are appended to obtain a positive interval.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from scripts.ai_team_trial import source_fingerprint, summarize

VARIANTS = ("value", "takeover", "lead", "endgame", "policy", "mixed", "combined", "guard", "guard_lead")


def run(root, suite, variant, seed, count, workers, output, difficulty=4):
    if output.exists():
        report = json.loads(output.read_text())
        config = report["config"]
        if (config["seed_start"], config["deals"], config["variant"], config["difficulty"]) != (seed, count, variant, difficulty):
            raise RuntimeError("existing validation recipe differs")
        return report
    subprocess.run([sys.executable, "scripts/ai_team_trial.py", "--baseline-root", str(root),
                    "--suite", suite, "--variant", variant, "--seed-start", str(seed),
                    "--deals", str(count), "--difficulty", str(difficulty), "--workers", str(workers),
                    "--match-states", "--out", str(output)], check=True)
    return json.loads(output.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--folder", type=Path, default=Path("benchmarks"))
    parser.add_argument("--stage", choices=("dev", "validation"), default="dev")
    args = parser.parse_args()
    folder = args.folder
    folder.mkdir(parents=True, exist_ok=True)
    lock = folder / "ai-v6-validation-lock.json"
    if args.stage == "dev":
        reports = {variant: run(args.baseline_root, "dev", variant, 120000, 32, args.workers,
                                folder / f"ai-v6-dev-{variant}.json") for variant in VARIANTS}
        baseline_rows = {(r["seed"], r["candidate_team"]): r for r in reports["value"]["observations"]}
        increments = {}
        for variant in VARIANTS[1:]:
            rows = [{**r, "gain": r["gain"] - baseline_rows[r["seed"], r["candidate_team"]]["gain"]}
                    for r in reports[variant]["observations"]]
            increments[variant] = summarize(rows)
        eligible = [v for v in VARIANTS[1:] if increments[v]["mean_paired_gain"] > 0
                    and reports[v]["mean_paired_gain"] > 0 and reports[v]["budget_gate_passed"]]
        selected = max(eligible, key=lambda v: reports[v]["mean_paired_gain"]) if eligible else "value"
        recipe = {"selected": selected, "source_sha256": source_fingerprint(),
                  "baseline_root": str(args.baseline_root.resolve()), "fixed_iterations": 128,
                  "development_source_sha256": {v: r["config"]["source_sha256"] for v, r in reports.items()},
                  "final_review": ["nonurgent risk floors preserve the paired-error requirement",
                                   "actor-local cache uses public events only",
                                   "material LRU operations are atomic across UI threads",
                                   "cold timing clears all relevant enumeration and plan caches"],
                  "selection": "largest positive development paired gain with a positive point increment over value-only; 95% gates apply only to independent validation",
                  "holdout": {"seed_start": 121000, "pairs": 240},
                  "mixed": {"seed_start": 122000, "pairs": 60},
                  "clock": {"production_corpus_decisions": 12, "cold_solver_decisions": 36,
                            "execution": "serial after fixed-work validation"},
                  "full": {"seed_start": 124000, "pairs": 4},
                  "development_increments": increments}
        if lock.exists() and json.loads(lock.read_text()) != recipe:
            raise RuntimeError("validation selection is already locked; do not overwrite")
        lock.write_text(json.dumps(recipe, ensure_ascii=False, indent=2) + "\n")
        print(f"locked candidate: {selected}", flush=True)
    else:
        recipe = json.loads(lock.read_text())
        if recipe["source_sha256"] != source_fingerprint():
            raise RuntimeError("candidate changed after selection lock")
        for suite in ("holdout", "mixed", "full"):
            settings = recipe[suite]
            run(args.baseline_root, suite, recipe["selected"], settings["seed_start"], settings["pairs"],
                args.workers, folder / f"ai-v6-{suite}.json")


if __name__ == "__main__":
    main()
