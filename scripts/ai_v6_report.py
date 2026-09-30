"""Assemble v6 validation provenance and gate results without adding samples."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from guandan.ai.diagnostics import gate_failures
from guandan.ai.profiles import load_profile
from scripts.ai_team_trial import source_fingerprint


def read(folder, name):
    return json.loads((folder / f"ai-v6-{name}.json").read_text())


def metrics(report):
    return {k: report[k] for k in ("pairs", "games", "mean_paired_gain", "gain_confidence_95",
                                  "strength_gate_passed", "head_win_rate", "by_level", "by_companion")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, default=Path("benchmarks"))
    args = parser.parse_args()
    folder = args.folder
    lock = read(folder, "validation-lock")
    holdout, mixed, full = (read(folder, name) for name in ("holdout", "mixed", "full"))
    clock = read(folder, "clock")
    production = read(folder, "production-clock")
    checks = read(folder, "checks")
    reports = (holdout, mixed, full)
    if any(r["config"]["source_sha256"] != lock["source_sha256"] for r in reports):
        raise RuntimeError("validation source hashes differ")
    if clock["source_sha256"] != lock["source_sha256"]:
        raise RuntimeError("clock tested a different candidate")
    full_ok = full["pairs"] == 4 and all(r["result"]["finished"] for r in full["observations"])
    ready = holdout["strength_gate_passed"] and mixed["strength_gate_passed"] and clock["passed"] and full_ok and not gate_failures(production) and checks["passed"]
    cold = {}
    for variant in ("default", "confidence", "policy"):
        rows = [r for r in clock["cold_solver"]["records"] if r["variant"] == variant]
        cold[variant] = {"decisions": len(rows),
                         "complete": sum(bool(r["endgame"] and r["endgame"]["complete"]) for r in rows),
                         "exact": sum(bool(r["endgame"] and r["endgame"]["exact"]) for r in rows),
                         "common_samples": dict(Counter(str(r["endgame"]["common_samples"]) for r in rows if r["endgame"])),
                         "reasons": dict(Counter(r["endgame"]["reason"] for r in rows if r["endgame"])),
                         "max_nodes": max((r["endgame"]["nodes"] for r in rows if r["endgame"]), default=0)}
    full_resets = 0
    for observation in full["observations"]:
        for rd in observation["result"]["round_results"]:
            full_resets += sum(rd["initial_levels"][t] == 14 and not rd["match_finished"]
                               and rd["final_levels"][t] == 2 for t in (0, 1))
    counters = Counter()
    for r in holdout["observations"]:
        if r["a_attempted"]:
            counters[f"before_{r['a_failure_before']}"] += 1
            counters["successful"] += bool(r["a_succeeded"])
            counters["reset_to_2"] += bool(r["a_reset"])
    report = {"schema": 1, "ruleset": 3, "selected": lock["selected"], "lock": lock,
              "candidate_sha256": lock["source_sha256"], "production_sha256": source_fingerprint(),
              "score": "empirical successor match utility; not observed full-match win probability",
              "holdout": metrics(holdout), "mixed": metrics(mixed), "full": metrics(full),
              "full_third_failure_resets": full_resets,
              "full_tribute_rounds": sum(r["result"]["tribute_rounds"] for r in full["observations"]),
              "full_rounds": sum(r["result"]["rounds"] for r in full["observations"]),
              "clock_passed": clock["passed"], "clock_failures": clock["gate_failures"],
              "candidate_clock_decisions": len(clock["production"]["records"]),
              "production_decisions": len(production["records"]),
              "production_clock_passed": not gate_failures(production),
              "checks": checks,
              "default_flags": {k: load_profile("dachangsheng")["mcts"][k] for k in
                                ("partner_bomb_guard", "lead_chain", "team_tactics", "heterogeneous_rollouts",
                                 "endgame_confidence", "endgame_policy", "confidence_guard")},
              "enablement_reason": "both independent gains and timing must pass; mixed-partner gain did not pass" if not ready else "all predeclared gates passed",
              "cold_solver_decisions": len(clock["cold_solver"]["records"]),
              "cold_endgame": cold, "a_counters": dict(counters), "experiment_ready_for_default": ready,
              "fixed_work_iterations": 128, "sample_extension": False,
              "replay_contract": "all rounds strictly replayed during trial; divergent human branches use legal proxies"}
    (folder / "ai-v6-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"selected": lock["selected"], "ready": ready, "clock_passed": clock["passed"]}))


if __name__ == "__main__":
    main()
