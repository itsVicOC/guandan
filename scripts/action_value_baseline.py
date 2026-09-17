"""高精度动作价值基线，供搜索/策略实验复用。

## 为什么需要它

评估一次「选牌是否更好」需要真实标签。做法是：固定一批局面，对每个候选动作
从根玩家视角打完该局（隐藏手牌按公开信息重采样），用胜率作为该动作的真实价值。

问题是所需样本量很大。历史结论（见 README「搜索能力上限」）：

- 每个动作只跑 40 次出牌时，两组**独立**估计选出的「最佳动作」只有 40% 一致
  （6 个候选，随机基线 16.7%）。也就是说任何方法在这套标签下的 top-1 上限约
  40%，此前所有 A/B 得到的 `+0.00` 都属于「测不出来」而非「证明为零」。
- 每个动作 400 次出牌（本工具默认）时，动作间平均价值差 0.118，远高于噪声，
  才能分辨方法优劣。

## 用法

```bash
# 建立基线（约 8 分钟，9 进程；产物可长期复用）
python scripts/action_value_baseline.py build \
    --positions 56 --actions 6 --playouts 400 --out /tmp/baseline.json

# 查看基线的动作价值分布与置信区间
python scripts/action_value_baseline.py show --file /tmp/baseline.json

# 用基线评估若干选牌方法（top-1 命中率与 regret）
python scripts/action_value_baseline.py evaluate --file /tmp/baseline.json
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

from guandan.ai.candidates import observable_key
from guandan.ai.context import opponent_min_cards
from guandan.ai.mcts import information_set as IS
from guandan.ai.mcts.search import simulate_state
from guandan.ai.play import play_or_pass
from guandan.ai.strategies.novice import NoviceStrategy
from guandan.engine.state import make_initial_state

# 独立于搜索所用的随机流，避免标签与待评估方法共享采样
PLAYOUT_SEED = 500_000
PLAYOUT_POLICY_SEED = 700_000

_POSITIONS: dict[int, object] = {}
_CANDIDATES: dict[int, list] = {}


def sample_positions(
    count: int,
    *,
    min_cards: int = 8,
    max_cards: int = 16,
    seed_start: int = 1,
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
                out.append((seed, copy.deepcopy(state)))
                break
            play_or_pass(state, state.current_player(), novice, rng)
            turns += 1
        if len(out) >= count:
            break
    return out


def _playout(job):
    """一次落地：执行动作后由固定策略打完本局，返回根队是否获胜。"""
    seed, action_index, playout_index = job
    state = _POSITIONS[seed]
    action = _CANDIDATES[seed][action_index]
    sampled = IS.determinize(state, 0, random.Random(PLAYOUT_SEED + playout_index))
    if not IS._apply_action(sampled, 0, action):
        return (seed, action_index, None)
    rng = random.Random(PLAYOUT_POLICY_SEED + playout_index)
    novice = NoviceStrategy()
    turns = 0
    while not sampled.finished and turns < 4000:
        play_or_pass(sampled, sampled.current_player(), novice, rng)
        turns += 1
    win = 1 if (sampled.finish_order and sampled.finish_order[0] % 2 == 0) else 0
    return (seed, action_index, win)


def _init_worker(positions, candidates):
    global _POSITIONS, _CANDIDATES
    _POSITIONS = positions
    _CANDIDATES = candidates


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
    sampled = sample_positions(positions, min_cards=min_cards, max_cards=max_cards)
    state_by_seed = {seed: state for seed, state in sampled}
    candidates = {
        seed: IS.enumerate_search_candidates(state, 0, max_candidates=actions)
        for seed, state in sampled
    }
    seeds = [seed for seed, _ in sampled if len(candidates[seed]) >= 3]
    print(
        f"positions: {len(seeds)} | actions each: {actions} | playouts each: {playouts}",
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
                    "type": pattern.type.value,
                    "rank": pattern.rank,
                    "length": pattern.length,
                    "cards": len(pattern.cards),
                    "wild_used": pattern.wild_used,
                    "playouts": n,
                    "wins": w,
                    "win_rate": round(w / n, 4) if n else None,
                    "ci95": [round(low, 4), round(high, 4)],
                }
            )
        payload["positions"].append({"seed": seed, "actions": entries})
    return payload


def _rebuild_position(seed: int, *, min_cards: int, max_cards: int):
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
            return copy.deepcopy(state)
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
    if result.pattern is None:
        return None
    key = observable_key(result.pattern)
    return next(
        (i for i, c in enumerate(candidates) if observable_key(c) == key), None
    )


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
    return max(range(len(means)), key=lambda i: means[i])


def _method_greedy(state, candidates):
    from guandan.ai.candidates import smallest_legal_pattern

    pick = smallest_legal_pattern(state, 0)
    if pick is None:
        return None
    key = observable_key(pick)
    return next((i for i, c in enumerate(candidates) if observable_key(c) == key), None)


METHODS = {
    "greedy": _method_greedy,
    "argmax32": lambda s, c: _method_argmax(s, c, 32),
    "argmax64": lambda s, c: _method_argmax(s, c, 64),
    "search32": lambda s, c: _method_search(s, c, 32),
    "search64": lambda s, c: _method_search(s, c, 64),
    "search128": lambda s, c: _method_search(s, c, 128),
}


def evaluate(payload: dict, method_names: list[str], *, pairwise: bool) -> dict:
    meta = payload["meta"]
    rows = [
        (
            _rebuild_position(
                entry["seed"],
                min_cards=meta.get("min_cards", 8),
                max_cards=meta.get("max_cards", 16),
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
        for index, (state, actions) in enumerate(rows):
            candidates = IS.enumerate_search_candidates(
                state, 0, max_candidates=len(actions)
            )
            if len(candidates) < 3:
                continue
            rates = [a["win_rate"] for a in actions if a["win_rate"] is not None]
            if len(rates) < 3:
                continue
            started = time.perf_counter()
            pick = method(state, candidates)
            seconds.append(time.perf_counter() - started)
            if pick is None or pick >= len(rates):
                continue
            n += 1
            best = max(rates)
            chosen = rates[pick]
            regrets.append(best - chosen)
            per_position[str(index)] = best - chosen
            if abs(chosen - best) < 1e-9:
                hits += 1
        if n == 0:
            continue
        mean_regret = statistics.mean(regrets)
        se = statistics.pstdev(regrets) / math.sqrt(n) if n > 1 else 0.0
        results[name] = {
            "n": n,
            "top1": hits / n,
            "mean_regret": mean_regret,
            "regret_ci95": [mean_regret - 1.96 * se, mean_regret + 1.96 * se],
            "ms_per_decision": round(statistics.mean(seconds) * 1000, 1),
            "per_position": per_position,
        }
        print(
            f"{name:>12}: top1 {hits / n:.3f}  regret {mean_regret:.4f}  "
            f"CI[{mean_regret - 1.96 * se:.3f},{mean_regret + 1.96 * se:.3f}]  "
            f"{results[name]['ms_per_decision']:>8.1f} ms",
            flush=True,
        )

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
                mean_diff = statistics.mean(diffs)
                diff_se = statistics.pstdev(diffs) / math.sqrt(len(diffs))
                t_value = mean_diff / diff_se if diff_se else 0.0
                verdict = "显著" if abs(t_value) > 2.05 else "不显著"
                print(
                    f"  {a:>12} - {b:<12} = {mean_diff:+.4f}  se {diff_se:.4f}  "
                    f"t {t_value:+.2f}  n={len(shared)}  {verdict}"
                )
    return results


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
            f"baseline: {meta['positions']} positions x {meta['actions']} actions "
            f"x {meta['playouts_per_action']} playouts (每动作 se ±{se:.3f})"
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
