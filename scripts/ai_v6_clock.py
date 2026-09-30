"""Serial production-clock gates for the frozen v6 candidate, including cold caches."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from guandan.ai import diagnostics
from guandan.ai.strategies.dachangsheng import DaiChangshengStrategy
from scripts.ai_team_trial import candidate, source_fingerprint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=Path("benchmarks/ai-v6-validation-lock.json"))
    parser.add_argument("--out", type=Path, default=Path("benchmarks/ai-v6-clock.json"))
    args = parser.parse_args()
    recipe = json.loads(args.lock.read_text())
    if recipe["source_sha256"] != source_fingerprint():
        raise RuntimeError("candidate changed after selection lock")
    selected = recipe["selected"]
    original_strategy = diagnostics.strategy

    def selected_strategy(difficulty, seed, budget_ms):
        if difficulty != 4:
            return original_strategy(difficulty, seed, budget_ms)
        policy = candidate(difficulty, selected, "clock")
        policy.rng.seed(seed)
        return policy

    template = candidate(4, selected, "clock")
    overrides = {"team_tactics": int(template.team_tactics), "lead_chain": int(template.lead_chain),
                 "partner_bomb_guard": int(template.partner_bomb_guard),
                 "heterogeneous_rollouts": int(template.heterogeneous_rollouts),
                 "rollout_strategy": template.rollout_strategy,
                 "endgame_confidence": int(template.endgame_confidence), "endgame_policy": int(template.endgame_policy)}

    def selected_dai(*args, mcts_overrides=None, **kwargs):
        return DaiChangshengStrategy(*args, mcts_overrides={**overrides, **(mcts_overrides or {})}, **kwargs)

    diagnostics.strategy = selected_strategy
    diagnostics.DaiChangshengStrategy = selected_dai
    try:
        clock = diagnostics.run_diagnostics("clock")
        print("12 production decisions complete", flush=True)
        cold = diagnostics.run_diagnostics("endgame-clock")
        print("36 cold solver decisions complete", flush=True)
    finally:
        diagnostics.strategy = original_strategy
        diagnostics.DaiChangshengStrategy = DaiChangshengStrategy
    failures = diagnostics.gate_failures(clock) + diagnostics.gate_failures(cold)
    report = {"selected": selected, "source_sha256": source_fingerprint(), "overrides": overrides,
              "execution": "serial after fixed-work trials", "production": clock, "cold_solver": cold,
              "gate_failures": failures, "passed": not failures}
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": not failures, "failures": failures}), flush=True)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
