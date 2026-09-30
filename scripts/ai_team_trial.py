"""Predeclared paired A/B trials against an isolated, immutable old checkout."""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import os
import platform
import random
import subprocess
import sys
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path

from guandan.ai.benchmark import _latency_payload, run_full_match, run_match
from guandan.ai.strategies.advanced import AdvancedStrategy
from guandan.ai.strategies.dachangsheng import DaiChangshengStrategy
from guandan.ai.strategies.professional import ProfessionalStrategy
from guandan.engine.events import ShuffleDeal
from guandan.storage.savegame import _state_to_dict
from guandan.storage.serialization import _dict_to_pattern, serialize_events

SUITES = {"dev": (32, 91000), "holdout": (240, 92000), "mixed": (60, 93000), "clock": (8, 94000), "full": (4, 95000)}
BASELINE_SHA = "3f687c8d14189bfc99df6b61e23cd5c2716ef91f"


def source_fingerprint():
    root = Path(__file__).resolve().parents[1]
    paths = sorted((root / "src/guandan/ai").rglob("*.py")) + sorted((root / "src/guandan/ai/profiles").glob("*.json"))
    paths += [Path(__file__).resolve(), Path(__file__).with_name("ai_frozen_worker.py")]
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def public_request(state, player, ruleset_version=2):
    """Strip all hidden cards and private deal seeds before crossing the RPC."""
    snapshot = _state_to_dict(state)
    # The isolated 3f687c8 baseline knows rulesets 1/2 but not the new
    # across-round A counter. Its within-round pass rules are identical in 2/3.
    if state.ruleset_version >= 3 and ruleset_version < 3:
        snapshot["ruleset_version"] = 2
    if ruleset_version < 3:
        snapshot.pop("a_failure_counts", None)
    for seat in range(4):
        if seat != player:
            snapshot["hands"][seat] = [{"rank": 2, "suit": 3}] * state.hand_size(seat)
    events = [replace(e, seed=0) if isinstance(e, ShuffleDeal) else e for e in state.history]
    public_events = serialize_events(events)
    if ruleset_version < 3:
        for event in public_events:
            event.pop("a_failure_counts", None)
    return {"state": snapshot, "events": public_events, "player": player}


def companion_difficulty(index):
    # 60 pairs: 20 per style and 20 per level, with every style/level cell.
    return (index + index // 3) % 3


class FrozenClient:
    def __init__(self, root):
        self.process = subprocess.Popen(
            [sys.executable, "-u", "-B", str(Path(__file__).with_name("ai_frozen_worker.py")), "--root", str(root)],
            cwd=root, env={**os.environ, "PYTHONPATH": str(Path(root) / "src"), "PYTHONDONTWRITEBYTECODE": "1"},
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        ready = self.process.stdout.readline()
        if not ready or not json.loads(ready).get("ready"):
            raise RuntimeError("frozen worker failed to start: " + self.process.stderr.read())
        self.ruleset_version = json.loads(ready).get("ruleset_version", 2)

    def query(self, request):
        self.process.stdin.write(json.dumps(request) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("frozen worker failed: " + self.process.stderr.read())
        return json.loads(line)

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=5)
        self.process.stdout.close()
        self.process.stderr.close()


class FrozenStrategy:
    name = "frozen"
    uses_stochastic_pass = False

    def __init__(self, client, tier, mode, fixed_iterations=128):
        self.client, self.difficulty, self.mode = client, tier, mode
        self.fixed_iterations = fixed_iterations
        self.rng = random.Random(0)
        self.intrinsic_seconds = []

    def select_pattern(self, state, player):
        request = public_request(state, player, self.client.ruleset_version)
        request.update(difficulty=self.difficulty, mode=self.mode, rng_state=self.rng.getstate(),
                       fixed_iterations=self.fixed_iterations)
        result = self.client.query(request)
        self.intrinsic_seconds.append(result["elapsed_seconds"])
        return _dict_to_pattern(result["pattern"]) if result["pattern"] else None


class MeasuredCandidate:
    uses_stochastic_pass = False

    def __init__(self, strategy, mode):
        self.strategy, self.mode = strategy, mode
        self.name, self.difficulty = strategy.name, strategy.difficulty
        self.decisions = []

    @property
    def rng(self):
        return self.strategy.rng

    @rng.setter
    def rng(self, value):
        self.strategy.rng = value

    def select_pattern(self, state, player):
        started = time.perf_counter()
        critical = self.strategy._critical_decision(state, player) if self.difficulty >= 3 else False
        budget = (self.strategy.critical_time_budget_ms if critical else self.strategy.time_budget_ms) if self.difficulty >= 3 else 0
        action = self.strategy.select_pattern(state, player)
        elapsed = time.perf_counter() - started
        result = getattr(self.strategy, "last_search", None)
        endgame = getattr(self.strategy, "last_endgame", None)
        self.decisions.append({
            "budget_ms": budget, "elapsed_seconds": elapsed,
            "reason": getattr(self.strategy, "last_decision_reason", "heuristic"),
            "common_samples": result.common_samples if result else endgame.common_samples if endgame else 0,
            "endgame_reason": endgame.reason if endgame else None,
            "endgame_common_samples": endgame.common_samples if endgame else None,
            "endgame_complete": endgame.complete if endgame else None,
            "endgame_exact": endgame.exact if endgame else None,
            "endgame_nodes": endgame.nodes if endgame else None,
            "endgame_cache_hits": endgame.cache_hits if endgame else None,
            "endgame_continuation": endgame.continuation if endgame else None,
            "guard": getattr(self.strategy, "last_guard", None),
            "endgame_elapsed_seconds": endgame.elapsed_seconds if endgame else None,
            "budget_passed": self.mode != "clock" or budget == 0 or elapsed <= budget / 1000 * 1.15 + 0.1,
        })
        return action


def candidate(tier, variant, mode, fixed_iterations=128):
    team = variant in ("team", "takeover", "combined")
    endgame = variant in ("endgame", "policy", "combined")
    lead = variant in ("lead", "guard_lead", "combined")
    guard = variant in ("guard", "guard_lead")
    mixed = variant in ("mixed", "combined")
    if tier == 2:
        return AdvancedStrategy(team_tactics=team, lead_chain=lead, partner_bomb_guard=guard)
    if tier == 3:
        return ProfessionalStrategy(
            team_tactics=team, rollout_strategy=3 if team else 1,
            lead_chain=lead, heterogeneous_rollouts=mixed, partner_bomb_guard=guard,
            **({"time_budget_ms": 0, "iterations": fixed_iterations} if mode == "fixed" else {}),
        )
    return DaiChangshengStrategy(mcts_overrides={
        "team_tactics": int(team), "endgame_confidence": int(endgame),
        "lead_chain": int(lead), "heterogeneous_rollouts": int(mixed), "partner_bomb_guard": int(guard),
        "endgame_policy": int(variant in ("policy", "combined")),
        "rollout_strategy": 3 if team else 2,
        **({"time_budget_ms": 0, "iterations": fixed_iterations} if mode == "fixed" else {}),
    })


def canonical_utility(result, team):
    """One shared score table; its proxy match probability is not a solved value."""
    if not result.finished:
        raise RuntimeError("incomplete trial cannot be scored")
    order = list(result.finish_order)
    order.extend(seat for seat in range(4) if seat not in order)
    won_head = order[0] % 2 == team
    partner_place = order.index((order[0] + 2) % 4) + 1
    if result.ruleset_version >= 3 and (getattr(result, "initial_levels", None) is not None
                                      or hasattr(result, "team_levels")):
        from guandan.ai.match_value import continuation_value

        if hasattr(result, "team_levels"):
            from guandan.ai.match_value import terminal_match_value

            return terminal_match_value(result, team)
        if result.match_finished:
            return float(result.match_winner_team == team)
        levels = getattr(result, "final_levels", None) or result.team_levels_final
        counts = getattr(result, "final_a_failures", None)
        if counts is None:
            counts = result.a_failure_counts
        return continuation_value(levels, counts, order[0] % 2, partner_place, team)
    if result.level == 14:
        return float((partner_place != 4) == won_head)
    magnitude = min(0.5, 0.1 + {2: 3, 3: 2, 4: 1}[partner_place] / 6.0)
    return 0.5 + (magnitude if won_head else -magnitude)


def match_state(index, candidate_team):
    """Fix cards, scores and initiative across legs; swap only policy seats.

    Moving the higher score with the candidate would grant a starting-value
    advantage even when the two policies are identical.
    """
    level = (2, 9, 14)[index % 3]
    other = level if (index // 3) % 2 == 0 else 9 if level == 14 else 2
    levels = [level, other]
    counts = [(index // 6) % 3 if level == 14 else 0,
              (index // 18 + 1) % 3 if other == 14 else 0]
    return {"team_levels": levels, "a_failure_counts": counts, "first_player": index % 4}


def pair(job):
    index, seed, config = job
    mode = config["mode"]
    full = config["suite"] == "full"
    level = 2 if full else (2, 9, 14)[index % 3]
    rows = []
    for team in (0, 1):
        client = FrozenClient(config["baseline_root"])
        adapters = []
        measured = []
        try:
            def factory(_difficulty, seat, client=client, adapters=adapters, measured=measured, team=team):
                if config["suite"] == "mixed" and seat >= 2:
                    adapter = FrozenStrategy(client, companion_difficulty(index), mode, config["fixed_iterations"])
                    adapters.append(adapter)
                    return adapter
                if seat % 2 == team:
                    strategy = MeasuredCandidate(candidate(config["difficulty"], config["variant"], mode,
                                                           config["fixed_iterations"]), mode)
                    measured.append(strategy)
                    return strategy
                adapter = FrozenStrategy(client, config["difficulty"], mode, config["fixed_iterations"])
                adapters.append(adapter)
                return adapter

            result = (run_full_match if full else run_match)(
                seed, level=level, strategy_factory=factory,
                difficulties=tuple(companion_difficulty(index) if config["suite"] == "mixed" and seat >= 2
                                   else config["difficulty"] for seat in range(4)),
                **(match_state(index, team) if config.get("match_states") and not full else {}),
            )
            utility = float(result.winner_team == team) if full else canonical_utility(result, team)
            if not result.finished:
                raise RuntimeError("trial failed to finish")
            rounds = result.round_results if full else (result,)
            timings = [duration for r in rounds for seat in range(4) if seat % 2 == team
                       and (config["suite"] != "mixed" or seat < 2) for duration in r.decision_seconds_by_player[seat]]
            decisions = [row for strategy in measured for row in strategy.decisions]
            order = list(rounds[0].finish_order)
            order.extend(seat for seat in range(4) if seat not in order)
            won_head = order[0] % 2 == team
            head_passed_a = (order[0] + 2) % 4 != order[-1]
            own_levels = rounds[0].initial_levels or (level, level)
            own_a = own_levels[team] == 14 and not full
            enemy_a = own_levels[1 - team] == 14 and not full
            rows.append({
                "seed": seed, "level": level, "candidate_team": team,
                "companion_difficulty": companion_difficulty(index) if config["suite"] == "mixed" else None,
                "utility": utility, "gain": 2 * utility - 1,
                "head_won": rounds[0].winner_team == team if full else result.winner_team == team,
                "a_succeeded": won_head and head_passed_a if own_a else None,
                "a_attempted": own_a,
                "opponent_a_failed": not (not won_head and head_passed_a) if enemy_a else None,
                "a_utility_won": result.match_finished and result.match_winner_team == team if own_a else None,
                "a_failure_before": rounds[0].initial_a_failures[team] if own_a else None,
                "a_failure_after": rounds[0].final_a_failures[team] if own_a else None,
                "a_reset": own_a and not result.match_finished and rounds[0].final_levels[team] == 2,
                "candidate_latency": _latency_payload(timings),
                "baseline_intrinsic_latency": _latency_payload([d for a in adapters for d in a.intrinsic_seconds]),
                "decision_reasons": dict(Counter(row["reason"] for row in decisions)),
                "budget_failures": [row for row in decisions if not row["budget_passed"]],
                "clock_decisions": decisions if mode == "clock" else None,
                "endgame_reasons": dict(Counter(row["endgame_reason"] for row in decisions if row["endgame_reason"])),
                "endgame_samples": dict(Counter(str(row["endgame_common_samples"]) for row in decisions if row["endgame_reason"])),
                "endgame_completions": dict(Counter(
                    "exact" if row["endgame_exact"] else "sampled" if row["endgame_complete"] else "incomplete"
                    for row in decisions if row["endgame_reason"])),
                "endgame_max_nodes": max((row["endgame_nodes"] for row in decisions if row["endgame_reason"]), default=0),
                "result": result.to_dict(),
            })
        finally:
            client.close()
    return rows


def summarize(rows, *, include_styles=True):
    groups = {}
    for row in rows:
        groups.setdefault(row["seed"], []).append(row)
    gains = [round(sum(r["gain"] for r in groups[seed]) / 2, 12)
             for seed in sorted(groups) if len(groups[seed]) == 2]
    rng = random.Random(731)
    if len(gains) >= 10:
        samples = sorted(sum(rng.choice(gains) for _ in gains) / len(gains) for _ in range(5000))
        interval = [round(samples[124], 12), round(samples[4874], 12)]
    else:
        interval = [-1.0, 1.0]
    return {
        "pairs": len(gains), "games": len(rows),
        "mean_paired_gain": round(sum(gains) / len(gains), 12) if gains else 0.0,
        "gain_confidence_95": interval, "strength_gate_passed": interval[0] > 0,
        "head_win_rate": sum(r["head_won"] for r in rows) / len(rows) if rows else 0.0,
        "budget_gate_passed": all(not r["budget_failures"] for r in rows),
        "by_level": {str(level): {
            "games": len(part := [r for r in rows if r["level"] == level]),
            "mean_gain": round(sum(r["gain"] for r in part) / len(part), 12) if part else None,
            "head_win_rate": sum(r["head_won"] for r in part) / len(part) if part else None,
            "a_attempts": sum(bool(r.get("a_attempted")) for r in part) if level == 14 else None,
            "a_successes": sum(bool(r["a_succeeded"]) for r in part) if level == 14 else None,
            "a_success_rate": sum(bool(r["a_succeeded"]) for r in part) / attempts
                if level == 14 and (attempts := sum(bool(r.get("a_attempted")) for r in part)) else None,
            "opponent_a_failures": sum(bool(r.get("opponent_a_failed")) for r in part) if level == 14 else None,
            "a_utility_win_rate": sum(bool(r.get("a_utility_won")) for r in part) / len(part)
                if level == 14 and part else None,
        } for level in (2, 9, 14)},
        "by_companion": {str(style): summarize(part, include_styles=False)
                         for style in (0, 1, 2)
                         if include_styles and (part := [r for r in rows if r.get("companion_difficulty") == style])},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--suite", choices=SUITES, default="dev")
    parser.add_argument("--variant", choices=("corrected", "value", "team", "takeover", "lead", "endgame", "policy", "mixed", "combined", "guard", "guard_lead"), default="combined")
    parser.add_argument("--match-states", action="store_true", help="stratify asymmetric levels and all A counters")
    parser.add_argument("--mode", choices=("fixed", "clock"), default="fixed")
    parser.add_argument("--difficulty", type=int, choices=(2, 3, 4), default=4)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--fixed-iterations", type=int, default=128,
                        help="equal offline work for both policies; clock mode keeps production settings")
    parser.add_argument("--deals", type=int)
    parser.add_argument("--seed-start", type=int)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "clock" and args.workers != 1:
        parser.error("production clock trials must be serial")
    deals = args.deals or SUITES[args.suite][0]
    seed_start = args.seed_start or SUITES[args.suite][1]
    if deals < 1 or args.workers < 1 or args.fixed_iterations < 1:
        parser.error("positive deals and workers required")
    manifest = args.baseline_root / "policy-snapshot.json"
    if manifest.exists():
        snapshot = json.loads(manifest.read_text())
        digest = hashlib.sha256()
        paths = [*sorted((args.baseline_root / "src").rglob("*.py")), *sorted((args.baseline_root / "src").rglob("*.json"))]
        for path in paths:
            digest.update(str(path.relative_to(args.baseline_root)).encode())
            digest.update(path.read_bytes())
        actual_sha = digest.hexdigest()
        if actual_sha != snapshot["source_sha256"]:
            parser.error("frozen policy snapshot changed")
    else:
        actual_sha = subprocess.check_output(["git", "-C", str(args.baseline_root), "rev-parse", "HEAD"], text=True).strip()
        if actual_sha != BASELINE_SHA or subprocess.check_output(["git", "-C", str(args.baseline_root), "status", "--porcelain"], text=True).strip():
            parser.error("baseline must be an unchanged 3f687c8 checkout or verified policy snapshot")
    config = {"baseline_root": str(args.baseline_root.resolve()), "baseline_sha": actual_sha,
              "suite": args.suite, "variant": args.variant, "mode": args.mode, "difficulty": args.difficulty,
              "deals": deals, "seed_start": seed_start, "source_sha256": source_fingerprint(),
              "fixed_iterations": args.fixed_iterations}
    config["match_states"] = args.match_states
    config["objective"] = "ruleset3-match-continuation-v1"
    config["score_interpretation"] = "empirical proxy future-match utility; not observed full-match win rate"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    print(f"trial process {os.getpid()}: {args.suite}/{args.variant}", flush=True)
    progress = args.out.with_suffix(".progress.jsonl")
    rows = []
    if progress.exists():
        for line in progress.read_text().splitlines():
            item = json.loads(line)
            if item["config"] != config:
                parser.error("checkpoint config/source differs; choose a new output")
            rows.extend(item["rows"])
    done = {r["seed"] for r in rows}
    jobs = [(i, seed, config) for i, seed in enumerate(range(seed_start, seed_start + deals)) if seed not in done]
    started = time.perf_counter()
    with mp.get_context("spawn").Pool(args.workers, maxtasksperchild=8) as pool:
        for new_rows in pool.imap_unordered(pair, jobs):
            rows.extend(new_rows)
            with progress.open("a") as stream:
                stream.write(json.dumps({"config": config, "rows": new_rows}) + "\n")
            print(f"{args.suite}/{args.variant}: {len(rows)//2}/{deals} pairs", flush=True)
    report = {"config": config, "workers": args.workers, "python": platform.python_version(),
              "platform": platform.platform(), "elapsed_seconds": time.perf_counter() - started,
              **summarize(rows), "observations": sorted(rows, key=lambda r: (r["seed"], r["candidate_team"]))}
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    progress.unlink()
    print(json.dumps({k: v for k, v in report.items() if k != "observations"}), flush=True)


if __name__ == "__main__":
    main()
