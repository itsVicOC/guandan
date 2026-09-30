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
from ..engine.rules.patterns import _complete_pattern_cache
from ..engine.state import (
    CURRENT_RULESET_VERSION,
    GameState,
    clone_state_for_search,
    make_initial_state,
    pass_turn,
    play_pattern,
)
from .arena import AI_POLICY_VERSION
from .candidates import (
    _exact_material_cache,
    _patterns_in_hand,
    enumerate_legal_patterns,
    pattern_key,
)
from .context import _holding_chance
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


def endgame_positions() -> list[tuple[str, GameState]]:
    """Replay-valid <=12-card cases for every level/seat and A counter."""
    cases = []
    for level in (2, 9, 14):
        for seat in range(4):
            for offset in range(200):
                seed = 125000 + level * 1000 + seat * 200 + offset
                counts = (seat % 3, (seat + 1) % 3) if level == 14 else (0, 0)
                state = make_initial_state(level=level, first_player=seat, seed=seed, a_failure_counts=counts)
                policy = make_strategy(offset % 3)
                rng = random.Random(seed)
                for _ in range(1000):
                    if state.finished:
                        break
                    if (state.current_player() == seat and sum(map(len, state.hands)) <= 12
                            and len(enumerate_legal_patterns(state, seat)) >= 2):
                        cases.append((f"level{level}-seat{seat}-solver", replay_events(state.history)))
                        break
                    play_or_pass(state, state.current_player(), policy, rng)
                if len(cases) == (0 if level == 2 else 4 if level == 9 else 8) + seat + 1:
                    break
            else:
                raise RuntimeError("could not generate cold solver position")
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
    ai_root = Path(__file__).parent
    digest = hashlib.sha256()
    for path in sorted(ai_root.rglob("*.py")) + sorted((ai_root / "profiles").glob("*.json")):
        digest.update(path.relative_to(ai_root).as_posix().encode())
        digest.update(path.read_bytes())
    return {"code_sha": sha, "ai_source_sha256": digest.hexdigest(),
            "python": platform.python_version(), "platform": platform.platform(),
            "workers": 1, "cache": "process warm; sequential corpus order"}


def run_diagnostics(mode: str = "fixed", budgets: Sequence[int] = (250, 500, 1000, 2000, 5000)) -> dict[str, Any]:
    config = {"professional": MCTS_CONFIG, "dachangsheng": load_profile("dachangsheng")}
    compatibility = {
        "schema": 1, "corpus": "levels-2-9-A-v1", "policy": AI_POLICY_VERSION,
        "rules": CURRENT_RULESET_VERSION, "mode": mode,
        "config_sha256": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
    }
    records: list[dict[str, Any]] = []
    corpus = endgame_positions() if mode == "endgame-clock" else positions()
    if mode == "endgame-clock":
        compatibility["corpus"] = "cold-12-cards-levels-seats-v1"
    for case_index, (name, state) in enumerate(corpus):
        for difficulty in (range(5) if mode == "fixed" else (4,) if mode == "endgame-clock" else (3, 4)):
            variants = ("default", "confidence", "policy") if mode == "endgame-clock" else ("default",)
            for budget, variant in ((b, v) for b in (budgets if mode == "curve" else (0 if mode == "fixed" else None,))
                                    for v in variants):
                policy = strategy(difficulty, 68000 + case_index, budget)
                if mode == "endgame-clock":
                    _exact_material_cache.clear()
                    _estimate.cache_clear()
                    _patterns_in_hand.cache_clear()
                    _complete_pattern_cache.clear()
                    _holding_chance.cache_clear()
                    policy = DaiChangshengStrategy(rng=random.Random(68000 + case_index), mcts_overrides={
                        "endgame_confidence": 1, "endgame_policy": int(variant == "policy"),
                    } if variant != "default" else None)
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
                endgame = getattr(policy, "last_endgame", None)
                after = _estimate.cache_info()
                records.append({
                    "case": name, "difficulty": difficulty, "player": state.turn_index,
                    "variant": variant, "total_cards": sum(map(len, state.hands)),
                    "team_levels": list(state.team_levels), "a_failure_counts": list(state.a_failure_counts),
                    "critical": critical, "budget_ms": allowed_ms,
                    "action": json.loads(json.dumps(pattern_key(action))) if action else ["pass"],
                    "elapsed_seconds": elapsed,
                    "reason": getattr(policy, "last_decision_reason", "heuristic"),
                    "search": None if result is None else {
                        key: value for key, value in asdict(result).items()
                        if key not in {"pattern", "actions"}
                    },
                    "candidate_count": len(result.actions) if result else 0,
                    "guard": getattr(policy, "last_guard", None),
                    "endgame": None if endgame is None else {
                        key: value for key, value in asdict(endgame).items()
                        if key not in {"pattern", "actions"}
                    },
                    "plan_cache_hits": after.hits - before.hits,
                    "plan_cache_misses": after.misses - before.misses,
                    "plan_cache_size": after.currsize,
                })
    env = environment()
    if mode == "endgame-clock":
        env["cache"] = "exact material, hand pattern, complete pattern, hand plan and holding probability caches cleared before every decision"
    return {"compatibility": compatibility, "environment": env, "records": records}


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
    parser.add_argument("--mode", choices=("fixed", "clock", "curve", "endgame-clock"), default="fixed")
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
