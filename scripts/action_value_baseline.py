"""高精度动作价值基线，供搜索/策略实验复用。

## 为什么需要它

评估一次「选牌是否更好」需要可复现的参考标签。做法是：固定一批局面，对每个候选动作
从根玩家视角打完该局（隐藏手牌按公开信息重采样），估算该续局策略下的获胜概率。
标签依赖续局策略与样本量，不是动作的无偏真值。

问题是所需样本量很大。历史结论（见 README「搜索能力上限」）：

- 每个动作只跑 40 次出牌时，两组**独立**估计选出的「最佳动作」只有 40% 一致
  （6 个候选，随机基线 16.7%）。也就是说任何方法在这套标签下的 top-1 上限约
  40%，此前所有 A/B 得到的 `+0.00` 都属于「测不出来」而非「证明为零」。
- 每个动作 400 次出牌（本工具默认）时，动作间平均价值差 0.118，远高于噪声，
  才能分辨方法优劣。

## 用法

```bash
# 建立基线（200 个局面约 28 分钟，9 进程；产物可长期复用）
python scripts/action_value_baseline.py build \
    --positions 200 --actions 6 --playouts 400 --out /tmp/baseline.json

# 查看基线的动作价值分布与置信区间
python scripts/action_value_baseline.py show --file /tmp/baseline.json

# 用基线评估若干选牌方法（top-1、regret、置信区间和配对 t）
python scripts/action_value_baseline.py evaluate --file /tmp/baseline.json \
    --methods greedy,argmax32,search32,search64 --out /tmp/evaluation.json
```

`regret = 基线最佳动作的价值 − 方法所选动作的价值`，0 为完美。regret 比 top-1
更敏感，因为它使用了完整价值而不只是 argmax。`evaluate` 默认输出**配对**比较
（同一批局面上逐局面做差），这比非配对比较显著更灵敏。
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import multiprocessing as mp
import os
import random
import statistics
import sys
import time
from pathlib import Path

from guandan.ai.arena import AI_POLICY_VERSION
from guandan.ai.candidates import (
    enumerate_legal_patterns,
    observable_key,
    pattern_key,
    smallest_legal_pattern,
)
from guandan.ai.context import opponent_min_cards
from guandan.ai.mcts import information_set as IS
from guandan.ai.mcts.information_set import SearchStyle
from guandan.ai.mcts.root_search import root_action_candidates, root_action_search
from guandan.ai.mcts.search import simulate_state
from guandan.ai.play import play_or_pass
from guandan.ai.strategies.novice import NoviceStrategy
from guandan.ai.strategy import make_strategy
from guandan.engine.state import make_initial_state, team_of

# 独立于搜索所用的随机流，避免标签与待评估方法共享采样
PLAYOUT_SEED = 500_000
PLAYOUT_POLICY_SEED = 700_000

_POSITIONS: dict[int, object] = {}
_CANDIDATES: dict[int, list] = {}
_ROOT_PLAYERS: dict[int, int] = {}
_LABEL_DIFFICULTY = 0


def _action_key(pattern) -> tuple:
    return ("pass",) if pattern is None else observable_key(pattern)


def _exact_action_key(pattern) -> tuple:
    return ("pass",) if pattern is None else pattern_key(pattern)


def _baseline_candidates(state, player: int, *, max_candidates: int) -> list:
    """覆盖搜索、过牌和 greedy 实际可能选择的动作。"""
    return root_action_candidates(state, player, max_actions=max_candidates)


def sample_positions(
    count: int,
    *,
    min_cards: int = 8,
    max_cards: int = 16,
    seed_start: int = 1,
    min_candidates: int = 0,
    max_candidates: int = 6,
):
    """可复现的局面集合：根玩家待行动，`min_cards..max_cards` 张手牌。"""
    out = []
    for seed in range(seed_start, seed_start + 6000):
        state = make_initial_state(level=2, first_player=0, seed=seed)
        rng = random.Random(seed)
        novice = NoviceStrategy()
        turns = 0
        while not state.finished and turns < 700:
            if (
                state.turn_index == 0
                and min_cards <= len(state.hands[0]) <= max_cards
                and 0 < opponent_min_cards(state, 0) <= 12
            ):
                sampled = copy.deepcopy(state)
                if min_candidates:
                    candidates = IS.enumerate_search_candidates(
                        sampled, 0, max_candidates=max_candidates
                    )
                    if len(candidates) < min_candidates:
                        play_or_pass(state, state.current_player(), novice, rng)
                        turns += 1
                        continue
                out.append((seed, sampled))
                break
            play_or_pass(state, state.current_player(), novice, rng)
            turns += 1
        if len(out) >= count:
            break
    return out


def _playout(job):
    """执行动作并续局到头游确定；其队伍已决定本局胜负。"""
    seed, action_index, playout_index = job
    state = _POSITIONS[seed]
    action = _CANDIDATES[seed][action_index]
    root_player = _ROOT_PLAYERS.get(seed, 0)
    sampled = IS.determinize(state, root_player, random.Random(PLAYOUT_SEED + playout_index))
    if not IS._apply_action(sampled, root_player, action):
        return (seed, action_index, None)
    rng = random.Random(PLAYOUT_POLICY_SEED + playout_index)
    strategy = make_strategy(_LABEL_DIFFICULTY)
    turns = 0
    while not sampled.finish_order and not sampled.finished and turns < 4000:
        play_or_pass(sampled, sampled.current_player(), strategy, rng)
        turns += 1
    win = int(bool(
        sampled.finish_order
        and team_of(sampled.finish_order[0]) == team_of(root_player)
    ))
    return (seed, action_index, win)


def _init_worker(positions, candidates, root_players=None, label_difficulty=0):
    global _POSITIONS, _CANDIDATES, _ROOT_PLAYERS, _LABEL_DIFFICULTY
    _POSITIONS = positions
    _CANDIDATES = candidates
    _ROOT_PLAYERS = root_players or {}
    _LABEL_DIFFICULTY = label_difficulty


def wilson_interval(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson 95% 区间。"""
    if n <= 0:
        return (0.0, 1.0)
    p = wins / n
    denominator = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return (max(0.0, centre - spread), min(1.0, centre + spread))


def build_baseline(
    positions: int,
    actions: int,
    playouts: int,
    *,
    min_cards: int,
    max_cards: int,
    workers: int,
) -> dict:
    started = time.perf_counter()
    sampled = sample_positions(
        positions,
        min_cards=min_cards,
        max_cards=max_cards,
        min_candidates=3,
        max_candidates=actions,
    )
    if len(sampled) < positions:
        raise RuntimeError(
            f"only found {len(sampled)} eligible positions; requested {positions}"
        )
    state_by_seed = {seed: state for seed, state in sampled}
    candidates = {
        seed: _baseline_candidates(state, 0, max_candidates=actions)
        for seed, state in sampled
    }
    seeds = [seed for seed, _ in sampled]
    print(
        f"positions: {len(seeds)} | search actions: {actions} + pass/greedy "
        f"| playouts each: {playouts}",
        flush=True,
    )

    jobs = [
        (seed, action_index, k)
        for seed in seeds
        for action_index in range(len(candidates[seed]))
        for k in range(playouts)
    ]
    print(f"total playouts: {len(jobs):,}", flush=True)

    wins: dict[tuple[int, int], list[int]] = {}
    done = 0
    report_every = max(1, len(jobs) // 20)
    with mp.Pool(
        workers, initializer=_init_worker, initargs=(state_by_seed, candidates)
    ) as pool:
        for seed, action_index, result in pool.imap_unordered(_playout, jobs, chunksize=64):
            if result is None:
                continue
            wins.setdefault((seed, action_index), []).append(result)
            done += 1
            if done % report_every == 0:
                print(
                    f"  {100.0 * done / len(jobs):5.1f}%  ({done:,}/{len(jobs):,})  "
                    f"{time.perf_counter() - started:.0f}s",
                    flush=True,
                )

    payload = {
        "meta": {
            "positions": len(seeds),
            "actions": actions,
            "min_candidates": 3,
            "candidate_policy": "search+pass+greedy",
            "playouts_per_action": playouts,
            "min_cards": min_cards,
            "max_cards": max_cards,
            "playout_seed": PLAYOUT_SEED,
            "seconds": round(time.perf_counter() - started, 1),
        },
        "positions": [],
    }
    for seed in seeds:
        entries = []
        for action_index, pattern in enumerate(candidates[seed]):
            results = wins.get((seed, action_index), [])
            n = len(results)
            w = sum(results)
            low, high = wilson_interval(w, n)
            entries.append(
                {
                    "action_index": action_index,
                    "type": "pass" if pattern is None else pattern.type.value,
                    "rank": None if pattern is None else pattern.rank,
                    "length": 0 if pattern is None else pattern.length,
                    "cards": 0 if pattern is None else len(pattern.cards),
                    "wild_used": 0 if pattern is None else pattern.wild_used,
                    "playouts": n,
                    "wins": w,
                    "win_rate": round(w / n, 4) if n else None,
                    "ci95": [round(low, 4), round(high, 4)],
                }
            )
        payload["positions"].append({"seed": seed, "actions": entries})
    return payload


def audit_candidate_recall(
    positions: int,
    playouts: int,
    *,
    seed_start: int,
    workers: int,
) -> dict:
    """Compare the root pool with rule-enumerated plays and retained variants.

    All actions at a position use the same hidden worlds and continuation seeds.
    Unlike the cached six-action baseline, this audit can expose both pruning
    misses and card-choice variants collapsed by an observable action key.
    """
    sampled = sample_positions(positions, seed_start=seed_start)
    if len(sampled) < positions:
        raise RuntimeError(f"only found {len(sampled)} eligible positions")
    states = {seed: state for seed, state in sampled}
    candidates: dict[int, list] = {}
    current_keys: dict[int, set[tuple]] = {}
    for seed, state in sampled:
        current = root_action_candidates(state, 0, max_actions=10)
        current_keys[seed] = {_exact_action_key(action) for action in current}
        union = {_exact_action_key(action): action for action in current}
        for action in enumerate_legal_patterns(state, 0):
            union.setdefault(_exact_action_key(action), action)
        if state.table:
            union.setdefault(("pass",), None)
        candidates[seed] = list(union.values())

    jobs = [
        (seed, index, k)
        for seed in states
        for index in range(len(candidates[seed]))
        for k in range(playouts)
    ]
    wins: dict[tuple[int, int], list[int]] = {}
    with mp.Pool(workers, initializer=_init_worker, initargs=(states, candidates)) as pool:
        for seed, index, result in pool.imap_unordered(_playout, jobs, chunksize=64):
            if result is None:
                raise RuntimeError(f"candidate {seed}:{index} became illegal")
            wins.setdefault((seed, index), []).append(result)

    rows = []
    for seed, state in sampled:
        actions = candidates[seed]
        rates = [
            sum(wins[(seed, i)]) / len(wins[(seed, i)])
            for i in range(len(actions))
        ]
        current_indices = [
            i for i, action in enumerate(actions)
            if _exact_action_key(action) in current_keys[seed]
        ]
        best_full = max(rates)
        best_current = max(rates[i] for i in current_indices)
        best_indices = [i for i, rate in enumerate(rates) if rate == best_full]
        rows.append({
            "seed": seed,
            "hand_cards": state.hand_size(0),
            "table_type": state.table[-1].type.value if state.table else "lead",
            "legal_actions": len(actions),
            "current_actions": len(current_indices),
            "best_in_current": any(i in current_indices for i in best_indices),
            "oracle_gap": round(best_full - best_current, 4),
            "best_action_type": (
                "pass" if actions[best_indices[0]] is None
                else actions[best_indices[0]].type.value
            ),
        })
    return {
        "meta": {
            "positions": positions,
            "playouts_per_action": playouts,
            "seed_start": seed_start,
            "pool": "rule-enumerated exact-card actions, retained variants and pass",
            "label_policy": "novice",
        },
        "summary": {
            "best_action_recall": sum(row["best_in_current"] for row in rows) / len(rows),
            "mean_oracle_gap": statistics.mean(row["oracle_gap"] for row in rows),
            "mean_legal_actions": statistics.mean(row["legal_actions"] for row in rows),
            "mean_current_actions": statistics.mean(row["current_actions"] for row in rows),
        },
        "positions": rows,
    }


def sample_diverse_positions(
    count: int, *, seed_start: int, stratify_phases: bool = False
) -> list[dict]:
    """Sample held-out decisions across levels, seats and source policies."""
    recipes = [
        (level, seat, source)
        for level in (2, 9, 14)
        for seat in range(4)
        for source in (0, 2)
    ]
    positions = []
    for index in range(count):
        level, seat, source = recipes[index % len(recipes)]
        phase, minimum, maximum = (
            (("opening", 20, 27), ("middle", 10, 19), ("endgame", 1, 9))[index % 3]
            if stratify_phases else ("middle", 8, 16)
        )
        for attempt in range(100):
            seed = seed_start + index + attempt * max(1, count)
            state = make_initial_state(level=level, first_player=seed % 4, seed=seed)
            rng = random.Random(seed)
            strategy = make_strategy(source)
            for _turn in range(700):
                if state.finished:
                    break
                if (
                    state.current_player() == seat
                    and minimum <= state.hand_size(seat) <= maximum
                    and 0 < opponent_min_cards(state, seat) <= (27 if stratify_phases else 12)
                    and (not stratify_phases or not state.finish_order)
                    and len(root_action_candidates(state, seat, max_actions=6)) >= 2
                ):
                    positions.append({
                        "id": index,
                        "seed": seed,
                        "level": level,
                        "seat": seat,
                        "source_difficulty": source,
                        "phase": phase,
                        "state": copy.deepcopy(state),
                    })
                    break
                play_or_pass(state, state.current_player(), strategy, rng)
            if len(positions) > index:
                break
        else:
            raise RuntimeError(f"could not sample diverse position {index}")
    return positions


def evaluate_diverse_positions(
    positions: int,
    playouts: int,
    *,
    seed_start: int,
    workers: int,
    label_difficulty: int = 2,
) -> dict:
    """Evaluate production actions on a different, stratified position source."""
    if label_difficulty not in (0, 2):
        raise ValueError("label_difficulty must be 0 or 2")
    sampled = sample_diverse_positions(positions, seed_start=seed_start)
    states = {row["id"]: row["state"] for row in sampled}
    roots = {row["id"]: row["seat"] for row in sampled}
    candidates = {
        row["id"]: root_action_candidates(row["state"], row["seat"], max_actions=6)
        for row in sampled
    }
    picks: dict[int, dict[str, tuple]] = {}
    for row in sampled:
        index, state, seat = row["id"], row["state"], row["seat"]
        root32 = root_action_search(
            state, seat, rng=random.Random(11 + index), iterations=32,
            time_budget_ms=0, max_actions=6, rollout_strategy=1,
            rollout_max_turns=40, prior_weight=0.18,
        ).pattern
        root96 = root_action_search(
            state, seat, rng=random.Random(11 + index), iterations=96,
            time_budget_ms=0, max_actions=6, rollout_strategy=1,
            rollout_max_turns=48, prior_weight=0.22,
        ).pattern
        picks[index] = {
            "greedy": _action_key(smallest_legal_pattern(state, seat)),
            "root32": _action_key(root32),
            "root96": _action_key(root96),
        }

    jobs = [
        (index, action_index, k)
        for index, actions in candidates.items()
        for action_index in range(len(actions))
        for k in range(playouts)
    ]
    wins: dict[tuple[int, int], list[int]] = {}
    with mp.Pool(
        workers,
        initializer=_init_worker,
        initargs=(states, candidates, roots, label_difficulty),
    ) as pool:
        for index, action_index, result in pool.imap_unordered(_playout, jobs, chunksize=32):
            if result is None:
                raise RuntimeError(f"candidate {index}:{action_index} became illegal")
            wins.setdefault((index, action_index), []).append(result)

    rows = []
    regrets: dict[str, list[float]] = {name: [] for name in ("greedy", "root32", "root96")}
    for row in sampled:
        index = row["id"]
        actions = candidates[index]
        rates = [sum(wins[index, i]) / len(wins[index, i]) for i in range(len(actions))]
        lookup = {_action_key(action): i for i, action in enumerate(actions)}
        best = max(rates)
        chosen = {}
        for name, key in picks[index].items():
            if key not in lookup:
                raise RuntimeError(f"unlabeled {name} action at position {index}")
            regret = best - rates[lookup[key]]
            regrets[name].append(regret)
            chosen[name] = round(regret, 4)
        rows.append({
            "id": index,
            "seed": row["seed"],
            "level": row["level"],
            "seat": row["seat"],
            "source_difficulty": row["source_difficulty"],
            "hand_cards": row["state"].hand_size(row["seat"]),
            "table_type": (
                row["state"].table[-1].type.value if row["state"].table else "lead"
            ),
            "actions": len(actions),
            "regret": chosen,
        })
    summary = {}
    for name, values in regrets.items():
        mean, _se, low, high = mean_ci95(values)
        summary[name] = {"mean_regret": mean, "ci95": [low, high]}
    for first, second in (("root32", "greedy"), ("root96", "greedy"), ("root96", "root32")):
        diffs = [a - b for a, b in zip(regrets[first], regrets[second])]
        mean, _se, low, high = mean_ci95(diffs)
        summary[f"{first}_minus_{second}"] = {"mean": mean, "ci95": [low, high]}
    return {
        "meta": {
            "positions": positions,
            "playouts_per_action": playouts,
            "seed_start": seed_start,
            "levels": [2, 9, 14],
            "seats": [0, 1, 2, 3],
            "source_difficulties": [0, 2],
            "label_difficulty": label_difficulty,
            "candidate_policy": "production root six plus pass/greedy",
        },
        "summary": summary,
        "positions": rows,
    }


def evaluate_ladder_positions(
    positions: int,
    playouts: int,
    *,
    seed_start: int,
    workers: int,
    label_difficulty: int = 0,
    include_confidence_guard: bool = False,
) -> dict:
    """Audit all five production picks against paired, noisy action labels.

    The candidate pool is the ten-action root pool plus every strategy's
    actual pick.  This lets the audit measure root-pool recall without silently
    dropping legal actions chosen by a policy.
    """
    if positions <= 0 or playouts <= 0:
        raise ValueError("positions and playouts must be positive")
    if label_difficulty not in (0, 2):
        raise ValueError("label_difficulty must be 0 or 2")
    from guandan.ai.strategies.dachangsheng import DaiChangshengStrategy
    from guandan.ai.strategies.professional import ProfessionalStrategy

    started = time.perf_counter()
    methods = [(str(tier), tier, False) for tier in range(5)]
    if include_confidence_guard:
        methods.append(("4_confidence", 4, True))
    sampled = sample_diverse_positions(
        positions, seed_start=seed_start, stratify_phases=True
    )
    states = {row["id"]: row["state"] for row in sampled}
    roots = {row["id"]: row["seat"] for row in sampled}
    candidate_sets: dict[int, list] = {}
    picks: dict[int, dict[str, tuple]] = {}
    core_keys: dict[int, set[tuple]] = {}
    legal_counts: dict[int, int] = {}
    search_work: dict[int, dict[str, dict]] = {}
    for row in sampled:
        index, state, seat = row["id"], row["state"], row["seat"]
        core = root_action_candidates(state, seat, max_actions=10)
        core_keys[index] = {_exact_action_key(action) for action in core}
        legal_keys = {
            pattern_key(pattern) for pattern in enumerate_legal_patterns(state, seat)
        } | core_keys[index]
        union = {_exact_action_key(action): action for action in core}
        chosen = {}
        work = {}
        for name, tier, confidence_guard in methods:
            if tier == 3:
                strategy = ProfessionalStrategy(rng=random.Random(31_000 + index))
            elif tier == 4:
                strategy = DaiChangshengStrategy(
                    rng=random.Random(41_000 + index),
                    mcts_overrides={"confidence_guard": 1} if confidence_guard else None,
                )
            else:
                strategy = make_strategy(tier)
            decision_started = time.perf_counter()
            action = strategy.select_pattern(state, seat)
            search = getattr(strategy, "last_search", None)
            work[name] = {
                "seconds": round(time.perf_counter() - decision_started, 4),
                "root_evaluations": search.simulations if search is not None else None,
                "root_actions": len(search.actions) if search is not None else None,
            }
            key = _exact_action_key(action)
            chosen[name] = key
            union.setdefault(key, action)
        picks[index] = chosen
        search_work[index] = work
        candidate_sets[index] = list(union.values())
        legal_counts[index] = len(legal_keys | union.keys())

    jobs = [
        (index, action_index, k)
        for index, actions in candidate_sets.items()
        for action_index in range(len(actions))
        for k in range(playouts)
    ]
    wins: dict[tuple[int, int], list[int]] = {}
    report_every = max(1, len(jobs) // 20)
    print(f"ladder positions: {positions}; total label playouts: {len(jobs)}", flush=True)
    with mp.Pool(
        workers,
        initializer=_init_worker,
        initargs=(states, candidate_sets, roots, label_difficulty),
    ) as pool:
        for done, (index, action_index, result) in enumerate(pool.imap_unordered(
            _playout, jobs, chunksize=16
        ), 1):
            if result is None:
                raise RuntimeError(f"candidate {index}:{action_index} became illegal")
            wins.setdefault((index, action_index), []).append(result)
            if done % report_every == 0:
                print(f"{done}/{len(jobs)} labels; {time.perf_counter() - started:.0f}s", flush=True)

    rows = []
    regrets: dict[str, list[float]] = {name: [] for name, _, _ in methods}
    recall = 0
    for row in sampled:
        index = row["id"]
        actions = candidate_sets[index]
        rates = [sum(wins[index, i]) / playouts for i in range(len(actions))]
        lookup = {_exact_action_key(action): i for i, action in enumerate(actions)}
        best = max(rates)
        best_keys = {
            _exact_action_key(actions[i]) for i, rate in enumerate(rates) if rate == best
        }
        recall += bool(best_keys & core_keys[index])
        chosen = {}
        for name, key in picks[index].items():
            regret = best - rates[lookup[key]]
            regrets[name].append(regret)
            chosen[name] = round(regret, 4)
        rows.append({
            "id": index,
            "seed": row["seed"],
            "level": row["level"],
            "seat": row["seat"],
            "source_difficulty": row["source_difficulty"],
            "phase": row["phase"],
            "hand_cards": row["state"].hand_size(row["seat"]),
            "candidate_count": len(actions),
            "enumerated_legal_count": legal_counts[index],
            "root_pool_count": len(core_keys[index]),
            "root_pool_fraction": round(len(core_keys[index]) / legal_counts[index], 4),
            "root_pool_has_labeled_best": bool(best_keys & core_keys[index]),
            "regret": chosen,
            "decision_work": search_work[index],
            "selected_action_keys": picks[index],
            "action_values": [
                {
                    "key": _exact_action_key(action),
                    "wins": sum(wins[index, action_index]),
                    "samples": len(wins[index, action_index]),
                    "in_root_pool": _exact_action_key(action) in core_keys[index],
                }
                for action_index, action in enumerate(actions)
            ],
        })
    summary = {
        "root_pool_recall_within_union": round(recall / positions, 4),
        "mean_root_pool_fraction": round(statistics.mean(
            len(core_keys[index]) / legal_counts[index] for index in candidate_sets
        ), 4),
        "mean_candidates": round(statistics.mean(len(v) for v in candidate_sets.values()), 3),
        "mean_regret": {
            name: round(statistics.mean(values), 4)
            for name, values in regrets.items()
        },
    }
    return {
        "meta": {
            "positions": positions,
            "playouts_per_action": playouts,
            "seed_start": seed_start,
            "levels": [2, 9, 14],
            "seats": [0, 1, 2, 3],
            "source_difficulties": [0, 2],
            "phases": ["opening", "middle", "endgame"],
            "head_undetermined_at_sampling": True,
            "policy_version": AI_POLICY_VERSION,
            "methods": [name for name, _, _ in methods],
            "label_difficulty": label_difficulty,
            "candidate_policy": "root ten plus all evaluated policy picks",
            "note": "Exploratory labels; increase playouts before strength claims.",
        },
        "summary": summary,
        "positions": rows,
    }


def _rebuild_position(
    seed: int,
    *,
    min_cards: int,
    max_cards: int,
    min_candidates: int = 3,
    max_candidates: int = 6,
):
    state = make_initial_state(level=2, first_player=0, seed=seed)
    rng = random.Random(seed)
    novice = NoviceStrategy()
    turns = 0
    while not state.finished and turns < 700:
        if (
            state.turn_index == 0
            and min_cards <= len(state.hands[0]) <= max_cards
            and 0 < opponent_min_cards(state, 0) <= 12
        ):
            sampled = copy.deepcopy(state)
            candidates = IS.enumerate_search_candidates(
                sampled, 0, max_candidates=max_candidates
            )
            if len(candidates) >= min_candidates:
                return sampled
        play_or_pass(state, state.current_player(), novice, rng)
        turns += 1
    return copy.deepcopy(state)


def _method_search(state, candidates, iterations: int):
    result = IS.information_set_search(
        state,
        0,
        rng=random.Random(11),
        iterations=iterations,
        time_budget_ms=0,
        max_actions=len(candidates),
        max_tree_depth=4,
        rollout_strategy=1,
        rollout_max_turns=40,
    )
    return result.pattern


def _method_argmax(state, candidates, simulations: int):
    """不做树搜索：把模拟预算平均分给每个动作，取叶子价值最高者。"""
    per_action = max(1, simulations // max(1, len(candidates)))
    means = []
    for candidate in candidates:
        values = []
        for k in range(per_action):
            sampled = IS.determinize(state, 0, random.Random(4000 + k))
            if not IS._apply_action(sampled, 0, candidate):
                continue
            values.append(
                simulate_state(
                    sampled,
                    0,
                    rollout_strategy_level=1,
                    max_turns=40,
                    copy_state=False,
                )
            )
        means.append(statistics.mean(values) if values else -1.0)
    return candidates[max(range(len(means)), key=lambda i: means[i])]


def _method_greedy(state, candidates):
    return smallest_legal_pattern(state, 0)


def _method_root(
    state,
    candidates,
    simulations: int,
    *,
    adaptive: bool,
    rollout_strategy: int = 1,
    rollout_max_turns: int = 40,
    prior_weight: float = 0.0,
):
    result = root_action_search(
        state,
        0,
        rng=random.Random(11),
        iterations=simulations,
        time_budget_ms=0,
        max_actions=len(candidates),
        rollout_strategy=rollout_strategy,
        rollout_max_turns=rollout_max_turns,
        prior_weight=prior_weight,
        style=SearchStyle(),
        adaptive=adaptive,
    )
    return result.pattern


def mean_ci95(values: list[float]) -> tuple[float, float, float, float]:
    """返回均值、样本标准误和正态近似 95% 置信区间。"""
    mean = statistics.mean(values)
    se = statistics.stdev(values) / math.sqrt(len(values)) if len(values) > 1 else 0.0
    return mean, se, mean - 1.96 * se, mean + 1.96 * se


METHODS = {
    "greedy": _method_greedy,
    "argmax32": lambda s, c: _method_argmax(s, c, 32),
    "argmax64": lambda s, c: _method_argmax(s, c, 64),
    "search32": lambda s, c: _method_search(s, c, 32),
    "search64": lambda s, c: _method_search(s, c, 64),
    "search128": lambda s, c: _method_search(s, c, 128),
    "flat32": lambda s, c: _method_root(s, c, 32, adaptive=False),
    "flat64": lambda s, c: _method_root(s, c, 64, adaptive=False),
    "flat96": lambda s, c: _method_root(s, c, 96, adaptive=False),
    "race32": lambda s, c: _method_root(s, c, 32, adaptive=True),
    "race64": lambda s, c: _method_root(s, c, 64, adaptive=True),
    "root32": lambda s, c: _method_root(
        s,
        c,
        32,
        adaptive=False,
        prior_weight=0.18,
    ),
    "flat32prior": lambda s, c: _method_root(
        s,
        c,
        32,
        adaptive=False,
        prior_weight=0.18,
    ),
    "flat96prior": lambda s, c: _method_root(
        s,
        c,
        96,
        adaptive=False,
        prior_weight=0.22,
    ),
    "flat32rollout2": lambda s, c: _method_root(
        s,
        c,
        32,
        adaptive=False,
        rollout_strategy=2,
    ),
    "flat32complex": lambda s, c: _method_root(
        s,
        c,
        32,
        adaptive=False,
        rollout_strategy=3,
    ),
    "root96": lambda s, c: _method_root(
        s,
        c,
        96,
        adaptive=False,
        rollout_max_turns=48,
        prior_weight=0.22,
    ),
}


def evaluate(payload: dict, method_names: list[str], *, pairwise: bool) -> dict:
    evaluation_started = time.perf_counter()
    meta = payload["meta"]
    rows = [
        (
            entry["seed"],
            _rebuild_position(
                entry["seed"],
                min_cards=meta.get("min_cards", 8),
                max_cards=meta.get("max_cards", 16),
                min_candidates=meta.get("min_candidates", 3),
                max_candidates=meta.get("actions", 6),
            ),
            entry["actions"],
        )
        for entry in payload["positions"]
    ]
    results: dict[str, dict] = {}
    for name in method_names:
        method = METHODS.get(name)
        if method is None:
            print(f"unknown method: {name}")
            continue
        hits = 0
        n = 0
        regrets: list[float] = []
        per_position: dict[str, float] = {}
        seconds: list[float] = []
        for seed, state, actions in rows:
            search_candidates = IS.enumerate_search_candidates(
                state, 0, max_candidates=meta.get("actions", 6)
            )
            if len(search_candidates) < 3:
                continue
            rates = [a["win_rate"] for a in actions if a["win_rate"] is not None]
            baseline_candidates = _baseline_candidates(
                state, 0, max_candidates=meta.get("actions", 6)
            )
            if len(rates) != len(baseline_candidates):
                continue
            started = time.perf_counter()
            pick = method(state, search_candidates)
            seconds.append(time.perf_counter() - started)
            if pick is None and not state.table:
                continue
            baseline_index = {
                _action_key(candidate): index
                for index, candidate in enumerate(baseline_candidates)
            }.get(_action_key(pick))
            if baseline_index is None:
                continue
            n += 1
            best = max(rates)
            chosen = rates[baseline_index]
            regrets.append(best - chosen)
            per_position[str(seed)] = best - chosen
            if abs(chosen - best) < 1e-9:
                hits += 1
        if n == 0:
            continue
        mean_regret, se, ci_low, ci_high = mean_ci95(regrets)
        results[name] = {
            "n": n,
            "top1": hits / n,
            "mean_regret": mean_regret,
            "regret_se": se,
            "regret_ci95": [ci_low, ci_high],
            "ms_per_decision": round(statistics.mean(seconds) * 1000, 1),
            "total_seconds": round(sum(seconds), 3),
            "per_position": per_position,
        }
        print(
            f"{name:>12}: top1 {hits / n:.3f}  regret {mean_regret:.4f}  "
            f"CI[{ci_low:.3f},{ci_high:.3f}]  "
            f"{results[name]['ms_per_decision']:>8.1f} ms",
            flush=True,
        )

    comparisons = []
    if pairwise:
        names = list(results)
        print("\n配对 regret 差（负值表示前者更好）：")
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                shared = sorted(
                    set(results[a]["per_position"]) & set(results[b]["per_position"]),
                    key=int,
                )
                if len(shared) < 5:
                    continue
                diffs = [
                    results[a]["per_position"][k] - results[b]["per_position"][k]
                    for k in shared
                ]
                mean_diff, diff_se, ci_low, ci_high = mean_ci95(diffs)
                t_value = mean_diff / diff_se if diff_se else 0.0
                significant = ci_low > 0.0 or ci_high < 0.0
                verdict = "显著" if significant else "不显著"
                comparisons.append(
                    {
                        "first": a,
                        "second": b,
                        "n": len(shared),
                        "mean_regret_diff": mean_diff,
                        "diff_se": diff_se,
                        "diff_ci95": [ci_low, ci_high],
                        "paired_t": t_value,
                        "significant_95": significant,
                    }
                )
                print(
                    f"  {a:>12} - {b:<12} = {mean_diff:+.4f}  se {diff_se:.4f}  "
                    f"CI[{ci_low:+.4f},{ci_high:+.4f}]  "
                    f"t {t_value:+.2f}  n={len(shared)}  {verdict}"
                )
    return {
        "meta": {
            "positions": len(rows),
            "methods": list(results),
            "pairwise": pairwise,
            "ci_level": 0.95,
            "ci_method": "normal approximation with sample standard error",
            "baseline_meta": meta,
            "total_seconds": round(time.perf_counter() - evaluation_started, 3),
        },
        "methods": results,
        "pairwise_comparisons": comparisons,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="建立高精度动作价值基线")
    build.add_argument("--positions", type=int, default=56)
    build.add_argument("--actions", type=int, default=6)
    build.add_argument("--playouts", type=int, default=400)
    build.add_argument("--min-cards", type=int, default=8)
    build.add_argument("--max-cards", type=int, default=16)
    build.add_argument(
        "--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1)
    )
    build.add_argument("--out", default="action-value-baseline.json")

    audit = sub.add_parser("audit-candidates", help="检查十动作根候选池的最优动作召回")
    audit.add_argument("--positions", type=int, default=12)
    audit.add_argument("--playouts", type=int, default=200)
    audit.add_argument("--seed-start", type=int, default=2000)
    audit.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    audit.add_argument("--out", default="candidate-recall-audit.json")

    diverse = sub.add_parser(
        "evaluate-diverse", help="跨级牌、座位与对局来源验证根动作质量"
    )
    diverse.add_argument("--positions", type=int, default=24)
    diverse.add_argument("--playouts", type=int, default=100)
    diverse.add_argument("--seed-start", type=int, default=10_000)
    diverse.add_argument("--label-difficulty", type=int, choices=(0, 2), default=2)
    diverse.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    diverse.add_argument("--out", default="action-value-diverse.json")

    ladder = sub.add_parser(
        "evaluate-ladder", help="比较五档实际选牌的候选覆盖及后悔值"
    )
    ladder.add_argument("--positions", type=int, default=24)
    ladder.add_argument("--playouts", type=int, default=20)
    ladder.add_argument("--seed-start", type=int, default=27_000)
    ladder.add_argument("--label-difficulty", type=int, choices=(0, 2), default=0)
    ladder.add_argument("--include-confidence-guard", action="store_true")
    ladder.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ladder.add_argument("--out", default="action-value-ladder.json")

    show = sub.add_parser("show", help="查看基线分布")
    show.add_argument("--file", required=True)

    evaluate_cmd = sub.add_parser("evaluate", help="用基线评估选牌方法")
    evaluate_cmd.add_argument("--file", required=True)
    evaluate_cmd.add_argument(
        "--methods", default="greedy,argmax32,search32"
    )
    evaluate_cmd.add_argument("--pairwise", action="store_true", default=True)
    evaluate_cmd.add_argument("--out", default=None)

    args = parser.parse_args(argv)

    if args.command == "evaluate-ladder":
        payload = evaluate_ladder_positions(
            args.positions,
            args.playouts,
            seed_start=args.seed_start,
            workers=args.workers,
            label_difficulty=args.label_difficulty,
            include_confidence_guard=args.include_confidence_guard,
        )
        Path(args.out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(payload["summary"], ensure_ascii=False))
        return 0

    if args.command == "evaluate-diverse":
        payload = evaluate_diverse_positions(
            args.positions,
            args.playouts,
            seed_start=args.seed_start,
            workers=args.workers,
            label_difficulty=args.label_difficulty,
        )
        Path(args.out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(payload["summary"], ensure_ascii=False))
        return 0

    if args.command == "audit-candidates":
        payload = audit_candidate_recall(
            args.positions,
            args.playouts,
            seed_start=args.seed_start,
            workers=args.workers,
        )
        Path(args.out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(payload["summary"], ensure_ascii=False))
        return 0

    if args.command == "build":
        payload = build_baseline(
            args.positions,
            args.actions,
            args.playouts,
            min_cards=args.min_cards,
            max_cards=args.max_cards,
            workers=args.workers,
        )
        Path(args.out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nwrote {args.out} in {payload['meta']['seconds']}s")
        return 0

    if args.command == "show":
        payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
        meta = payload["meta"]
        se = math.sqrt(0.25 / meta["playouts_per_action"])
        print(
            f"baseline: {meta['positions']} positions, up to {meta['actions']} search "
            f"actions + pass/greedy, {sum(len(p['actions']) for p in payload['positions'])} "
            f"labeled actions x {meta['playouts_per_action']} playouts "
            f"(每动作 se ±{se:.3f})"
        )
        spreads = []
        for entry in payload["positions"]:
            rates = [a["win_rate"] for a in entry["actions"] if a["win_rate"] is not None]
            if len(rates) < 2:
                continue
            spreads.append(max(rates) - min(rates))
        if spreads:
            print(f"动作间价值差：mean {statistics.mean(spreads):.3f}  "
                  f"min {min(spreads):.3f}  max {max(spreads):.3f}")
            print(f"纯噪声预期的极差约 {2.5 * se:.3f}；明显高于它才说明动作有真实影响")
        return 0

    payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
    names = [n.strip() for n in args.methods.split(",") if n.strip()]
    results = evaluate(payload, names, pairwise=args.pairwise)
    if args.out:
        Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
