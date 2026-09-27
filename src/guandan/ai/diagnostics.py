"""Fixed-position regression gates and production-budget experiments.

Action agreement is a reproducibility/diagnostic metric, not a strength claim.
Run clock experiments serially; never mix their timing with fixed-work gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import random
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Sequence

from ..engine.replay import replay_events
from ..engine.state import (
    CURRENT_RULESET_VERSION,
    GameState,
    clone_state_for_search,
    make_initial_state,
    pass_turn,
    play_pattern,
)
from .arena import AI_POLICY_VERSION
from .candidates import enumerate_legal_patterns, pattern_key
from .hand_plan import _estimate
from .mcts import MCTS_CONFIG
from .play import play_or_pass
from .profiles import load_profile
from .strategies.dachangsheng import DaiChangshengStrategy
from .strategies.professional import ProfessionalStrategy
from .strategy import AIStrategy, make_strategy


def positions() -> list[tuple[str, GameState]]:
    """Six independent, replay-checked positions spanning levels and phases."""
    cases = []
    for level, seed in ((2, 67000), (9, 67001), (14, 67002)):
        state = make_initial_state(level=level, first_player=seed % 4, seed=seed)
        cases.append((f"level{level}-opening", replay_events(state.history)))
        rng = random.Random(seed)
        policy = make_strategy(0)
        for _ in range(1000):
            if state.finished:
                break
            if sum(map(len, state.hands)) <= 24 and len(enumerate_legal_patterns(state, state.turn_index)) > 1:
                cases.append((f"level{level}-endgame", replay_events(state.history)))
                break
            play_or_pass(state, state.turn_index, policy, rng)
        else:
            raise RuntimeError("diagnostic position generation did not finish")
    if len(cases) != 6:
        raise RuntimeError("diagnostic endgame positions changed; inspect the corpus")
    return cases


def strategy(difficulty: int, seed: int, budget_ms: int | None) -> AIStrategy:
    rng = random.Random(seed)
    if difficulty == 3:
        if budget_ms is None:
            return ProfessionalStrategy(rng=rng)
        return ProfessionalStrategy(rng=rng, time_budget_ms=budget_ms, critical_time_budget_ms=budget_ms)
    if difficulty == 4:
        return DaiChangshengStrategy(rng=rng, mcts_overrides=(
            None if budget_ms is None else {"time_budget_ms": budget_ms, "critical_time_budget_ms": budget_ms}
        ))
    return make_strategy(difficulty)


def environment() -> dict[str, Any]:
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        sha = "unknown"
    return {"code_sha": sha, "python": platform.python_version(), "platform": platform.platform(),
            "workers": 1, "cache": "process warm; sequential corpus order"}


def run_diagnostics(mode: str = "fixed", budgets: Sequence[int] = (250, 500, 1000, 2000, 5000)) -> dict[str, Any]:
    config = {"professional": MCTS_CONFIG, "dachangsheng": load_profile("dachangsheng")}
    compatibility = {
        "schema": 1, "corpus": "levels-2-9-A-v1", "policy": AI_POLICY_VERSION,
        "rules": CURRENT_RULESET_VERSION, "mode": mode,
        "config_sha256": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
    }
    records: list[dict[str, Any]] = []
    for case_index, (name, state) in enumerate(positions()):
        for difficulty in (range(5) if mode == "fixed" else (3, 4)):
            for budget in (budgets if mode == "curve" else (0 if mode == "fixed" else None,)):
                policy = strategy(difficulty, 68000 + case_index, budget)
                critical = isinstance(policy, ProfessionalStrategy) and policy._critical_decision(state, state.turn_index)
                allowed_ms = budget or 0
                if budget is None and isinstance(policy, ProfessionalStrategy):
                    allowed_ms = policy.critical_time_budget_ms if critical else policy.time_budget_ms
                before = _estimate.cache_info()
                started = time.perf_counter()
                action = policy.select_pattern(state, state.turn_index)
                elapsed = time.perf_counter() - started
                validation = clone_state_for_search(state)
                if action is None:
                    pass_turn(validation, state.turn_index)
                else:
                    play_pattern(validation, state.turn_index, action)
                result = getattr(policy, "last_search", None)
                after = _estimate.cache_info()
                records.append({
                    "case": name, "difficulty": difficulty, "player": state.turn_index,
                    "critical": critical, "budget_ms": allowed_ms,
                    "action": json.loads(json.dumps(pattern_key(action))) if action else ["pass"],
                    "elapsed_seconds": elapsed,
                    "reason": getattr(policy, "last_decision_reason", "heuristic"),
                    "search": None if result is None else {
                        key: value for key, value in asdict(result).items()
                        if key not in {"pattern", "actions"}
                    },
                    "candidate_count": len(result.actions) if result else 0,
                    "plan_cache_hits": after.hits - before.hits,
                    "plan_cache_misses": after.misses - before.misses,
                    "plan_cache_size": after.currsize,
                })
    return {"compatibility": compatibility, "environment": environment(), "records": records}


def regression_projection(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [{key: row[key] for key in ("case", "difficulty", "player", "action", "reason")}
            for row in report["records"]]


def gate_failures(report: dict[str, Any], baseline: dict[str, Any] | None = None) -> list[str]:
    failures = []
    mode = report["compatibility"]["mode"]
    if baseline is not None:
        if mode != "fixed" or report["compatibility"] != baseline.get("compatibility"):
            failures.append("incompatible baseline: corpus, rules, policy, config or mode differs")
        elif regression_projection(report) != regression_projection(baseline):
            failures.append("fixed-position decisions changed; inspect before accepting a new baseline")
    if mode != "fixed":
        for row in report["records"]:
            # Soft budgets are checked separately for every difficulty and phase.
            allowed = row["budget_ms"] / 1000 * 1.15 + 0.10
            if row["elapsed_seconds"] > allowed:
                failures.append(f"{row['case']} difficulty={row['difficulty']}: {row['elapsed_seconds']:.3f}s > {allowed:.3f}s")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("fixed", "clock", "curve"), default="fixed")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_diagnostics(args.mode)
    baseline = json.loads(args.baseline.read_text()) if args.baseline else None
    report["failures"] = gate_failures(report, baseline)
    report["passed"] = not report["failures"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"{args.mode}: {len(report['records'])} decisions, passed={report['passed']}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
