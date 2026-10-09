"""Collect frozen-policy labels, fit a small pairwise model, and diagnose it.

Collection runs in spawned workers importing ONLY the frozen policy source.
Artifacts contain actor-public snapshots and paired utilities, never hidden hands.
NumPy is an offline fitting dependency only; the game uses standard-library JSON.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import multiprocessing as mp
import random
import sys
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path

RECIPE = {
    "schema": 1, "name": "action-ranker-v1", "deals": 576,
    "splits": {"train": 384, "tune": 96, "diagnostic": 96},
    "positions_per_deal": 3, "actions_per_position": 16,
    "sampled_positions_per_deal": 1, "phase_sampling": "balanced-one-prefix-per-deal",
    "worlds": 32, "companions": [0, 1, 2], "other_policy": 2,
    "regularization": [0.001, 0.01, 0.1], "epochs": 160,
    "objective": "full-round-ranks-frozen-match-continuation",
    "seed_schedule": "sha256-action-ranker-v1-stage-index-round",
}
LEVEL_PAIRS = ((2, 2), (9, 9), (14, 14), (14, 9), (9, 14),
               (13, 11), (11, 13), (14, 13), (13, 14))


def derived_seed(stage: str, index: int, round_index: int = 0) -> int:
    text = f"action-ranker-v1/{stage}/{index}/{round_index}"
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")


def split_for(index: int) -> str:
    if not 0 <= index < RECIPE["deals"]:
        raise ValueError("deal index outside frozen recipe")
    # Interleave the splits so every split sees all levels/seats/A counters.
    return "train" if index % 6 < 4 else "tune" if index % 6 == 4 else "diagnostic"


def snapshot_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((root / "src").rglob("*.py")) + sorted((root / "src").rglob("*.json")):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def label_recipe(root: Path) -> dict:
    manifest = json.loads((root / "policy-snapshot.json").read_text())
    actual = snapshot_fingerprint(root)
    if actual != manifest["source_sha256"]:
        raise ValueError("frozen baseline has changed")
    model_sha = hashlib.sha256((root / "src/guandan/ai/profiles/match_value.json").read_bytes()).hexdigest()
    if model_sha != manifest["match_value_sha256"]:
        raise ValueError("frozen match-value model has changed")
    return {**RECIPE, "baseline_sha256": actual, "value_model_sha256": model_sha,
            "collector_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def _init_collection(root: str) -> None:
    sys.path.insert(0, str(Path(root) / "src"))
    import guandan

    if not Path(guandan.__file__).resolve().is_relative_to(Path(root).resolve()):
        raise RuntimeError("label worker imported an unfrozen policy")


def _key(action):
    from guandan.ai.candidates import pattern_key

    return ("pass",) if action is None else pattern_key(action)


def _public_position(state, player):
    from guandan.engine.events import ShuffleDeal
    from guandan.storage.savegame import _state_to_dict
    from guandan.storage.serialization import serialize_events

    snapshot = _state_to_dict(state)
    for seat in range(4):
        if seat != player:
            snapshot["hands"][seat] = [{"rank": 2, "suit": 3}] * state.hand_size(seat)
    events = [replace(e, seed=0) if isinstance(e, ShuffleDeal) else e for e in state.history]
    return {"state": snapshot, "events": serialize_events(events), "player": player}


def _continuation_key(state):
    """Exact sufficient state for the frozen, non-team-tactics 0/1/2 policies.

    Those policies use played rank totals, current top ownership and their own
    cards, not the order of older plays/passes. The engine uses the last table
    pattern, pass locks, initiative and finish order. This is confined to label
    collection, with the complete frozen source fingerprint verified first.
    """
    from guandan.engine.events import TurnPlayed
    from guandan.engine.trick import current_top_player

    played = Counter(card.rank for event in state.history if isinstance(event, TurnPlayed)
                     for card in event.pattern.cards)
    return (state.level, state.wild_card, tuple(state.team_levels), tuple(state.a_failure_counts),
            tuple(map(len, state.hands)), state.turn_index, state.leader, state.next_trick_starter,
            state.table[-1] if state.table else None, current_top_player(state),
            tuple(sorted(state.passed_players)), tuple(state.finish_order), tuple(sorted(played.items())),
            tuple(state.team_bomb_count), tuple(state.has_played_ace), state.ruleset_version,
            state.drift, state.drift_flag, state.finished)


def frozen_playout(branch, player, companion, policies, policy_memo, value_memo):
    """Reuse deterministic suffixes without changing any frozen policy choice."""
    from guandan.ai.match_value import terminal_match_value
    from guandan.engine.state import partner_of, pass_turn, play_pattern

    path = []
    for _ in range(4000):
        if branch.finished:
            value = terminal_match_value(branch, player % 2)
            break
        public = _continuation_key(branch)
        # Once the companion has finished, all remaining actors use tier 2.
        profile = companion if branch.hand_size(partner_of(player)) else 2
        key = (profile, tuple(tuple(sorted(hand)) for hand in branch.hands), public)
        if key in value_memo:
            value = value_memo[key]
            break
        path.append(key)
        actor = branch.current_player()
        tier = companion if actor == partner_of(player) else RECIPE["other_policy"]
        policy_key = (tier, actor, tuple(branch.hands[actor]), public)
        if policy_key not in policy_memo:
            if len(policy_memo) >= 20000:
                policy_memo.clear()
            policy_memo[policy_key] = policies[tier].select_pattern(branch, actor)
        action = policy_memo[policy_key]
        if action is None:
            pass_turn(branch, actor)
        else:
            play_pattern(branch, actor, action)
    else:
        raise RuntimeError("label continuation did not finish")
    if len(value_memo) + len(path) >= 20000:
        value_memo.clear()
    for key in path:
        value_memo[key] = value
    return value


def _label_position(state, player, index, phase):
    from guandan.ai.candidates import enumerate_legal_patterns
    from guandan.ai.mcts.determinize import determinize
    from guandan.ai.mcts.information_set import _apply_action
    from guandan.ai.mcts.root_search import root_action_candidates
    from guandan.ai.strategy import make_strategy
    from guandan.engine.state import clone_state_for_search
    from guandan.storage.savegame import _pattern_to_dict

    reference = make_strategy(2).select_pattern(state, player)
    actions = root_action_candidates(state, player, max_actions=10, reference_actions=(reference,))
    core = {_key(p) for p in actions}
    core3 = {_key(p) for p in root_action_candidates(state, player, max_actions=6,
                                                   reference_actions=(reference,))}
    legal = enumerate_legal_patterns(state, player)
    rng = random.Random(derived_seed("label-candidates", index, phase))
    rng.shuffle(legal)
    by_type = {}
    for action in legal:
        if _key(action) not in core:
            by_type.setdefault(action.type, []).append(action)
    while len(actions) < RECIPE["actions_per_position"] and by_type:
        for kind in list(by_type):
            if len(actions) >= RECIPE["actions_per_position"]:
                break
            actions.append(by_type[kind].pop())
            if not by_type[kind]:
                del by_type[kind]
    if len(actions) > RECIPE["actions_per_position"]:
        raise RuntimeError("baseline root candidates exceeded declared label cap")
    values = [[[] for _ in RECIPE["companions"]] for _ in actions]
    policies = [make_strategy(tier) for tier in range(3)]
    if any(policy.uses_stochastic_pass or getattr(policy, "team_tactics", False)
           or getattr(policy, "lead_chain", False) for policy in policies):
        raise ValueError("suffix reuse requires the frozen deterministic baseline policies")
    memo, value_memo = {}, {}
    for world in range(RECIPE["worlds"]):
        world_seed = derived_seed("label-world", index, phase * RECIPE["worlds"] + world)
        sampled = determinize(state, player, random.Random(world_seed))
        for action_index, action in enumerate(actions):
            for companion in RECIPE["companions"]:
                branch = clone_state_for_search(sampled)
                if not _apply_action(branch, player, action):
                    raise RuntimeError("illegal label action")
                values[action_index][companion].append(
                    frozen_playout(branch, player, companion, policies, memo, value_memo))
        if (world + 1) % 8 == 0:
            print(f"deal {index} phase {phase}: {world + 1}/{RECIPE['worlds']} paired worlds", flush=True)
    return {**_public_position(state, player), "phase": ("opening", "middle", "placed_or_endgame")[phase],
            "reference_key": _key(reference),
            "actions": [{"pattern": _pattern_to_dict(action) if action else None,
                         "key": _key(action), "in_root_3": _key(action) in core3,
                         "in_root_4": _key(action) in core, "values": values[i]}
                        for i, action in enumerate(actions)],
            "legal_action_count": len(legal) + int(bool(state.table))}


def collect_deal(index: int) -> dict:
    from guandan.ai.candidates import enumerate_legal_patterns
    from guandan.ai.play import play_or_pass
    from guandan.ai.strategy import make_strategy
    from guandan.ai.tribute import choose_ai_tribute_cards
    from guandan.engine.events import ShuffleDeal
    from guandan.engine.replay import replay_events
    from guandan.engine.rules.tributes import apply_tribute_flow
    from guandan.engine.state import clone_state_for_search, make_initial_state

    started = time.perf_counter()
    seed = derived_seed("dataset", index)
    levels = LEVEL_PAIRS[(index // 6 + index % 6) % len(LEVEL_PAIRS)]
    failures = [(index // (6 * (team + 1))) % 3 if levels[team] == 14 else 0 for team in (0, 1)]
    player = (index // 6 + index % 6) % 4
    state = make_initial_state(seed=seed, level=levels[index % 2], team_levels=levels,
                               a_failure_counts=failures, first_player=player)
    # Include actual public tribute/return information in three quarters of deals.
    if (index // 6) % 4:
        head = index % 2
        place = 2 + (index // 24) % 3
        orders = {2: [head, head + 2, 1 - head],
                  3: [head, 1 - head, head + 2],
                  4: [head, 1 - head, 3 - head]}
        tiers = tuple((index + seat) % 3 for seat in range(4))
        paid, returned = choose_ai_tribute_cards(orders[place], state.hands, level=state.level,
                                                wild_card=state.wild_card, difficulties=tiers)
        flow = apply_tribute_flow(orders[place], state.hands, level=state.level,
                                  wild_card=state.wild_card, tribute_choices=paid, return_choices=returned)
        state.history.extend(flow.events)
        state.turn_index = state.leader = flow.first_player
        event = state.history[0]
        assert isinstance(event, ShuffleDeal)
        state.history[0] = replace(event, first_player=flow.first_player)
    rng = random.Random(derived_seed("trajectory", index))
    source = make_strategy((index // 6) % 2 * 2)
    samples = {}
    for _ in range(4000):
        if state.finished:
            break
        total = sum(map(len, state.hands))
        if state.current_player() == player and len(enumerate_legal_patterns(state, player)) >= 2:
            phase = (0 if total >= 80 and not state.finish_order else
                     2 if state.finish_order or total <= 24 else 1 if total <= 60 else None)
            if phase is not None and phase not in samples:
                if replay_events(state.history) != state:
                    raise RuntimeError("training prefix failed exact replay")
                samples[phase] = clone_state_for_search(state)
        play_or_pass(state, state.current_player(), source, rng)
    if not state.finished:
        raise RuntimeError("sampling trajectory did not finish")
    # The plan allows up to three prefixes per deal. Use one balanced prefix
    # per independent deal rather than overweighting correlated trajectories.
    preferred = (index // 6) % 3
    chosen = preferred if preferred in samples else max(samples, default=None)
    positions = [] if chosen is None else [_label_position(samples[chosen], player, index, chosen)]
    return {"index": index, "seed": seed, "split": split_for(index),
            "positions": positions, "seconds": time.perf_counter() - started}


def collect(root: Path, folder: Path, workers: int, indices: list[int]) -> None:
    recipe = label_recipe(root)
    folder.mkdir(parents=True, exist_ok=True)
    lock = folder / "recipe.json"
    if lock.exists() and json.loads(lock.read_text()) != recipe:
        raise ValueError("collection recipe/source differs; use a new output folder")
    lock.write_text(json.dumps(recipe, indent=2) + "\n")
    raw = folder / "labels"
    raw.mkdir(exist_ok=True)
    jobs = [index for index in indices if not (raw / f"{index:04d}.json.gz").exists()]
    started = time.perf_counter()
    with mp.get_context("spawn").Pool(workers, initializer=_init_collection,
                                      initargs=(str(root),), maxtasksperchild=4) as pool:
        for row in pool.imap_unordered(collect_deal, jobs):
            target = raw / f"{row['index']:04d}.json.gz"
            temporary = target.with_suffix(".tmp")
            with gzip.open(temporary, "wt", encoding="utf-8") as stream:
                json.dump(row, stream)
            temporary.replace(target)
            done = len(list(raw.glob("*.json.gz")))
            print(f"labels {done}/{RECIPE['deals']}; deal {row['index']}, "
                  f"{len(row['positions'])} positions, {row['seconds']:.1f}s; "
                  f"elapsed {time.perf_counter()-started:.0f}s", flush=True)


def read_labels(folder: Path) -> tuple[dict, list[dict]]:
    recipe = json.loads((folder / "recipe.json").read_text())
    if any(recipe.get(k) != v for k, v in RECIPE.items()):
        raise ValueError("incompatible action-label recipe")
    paths = sorted((folder / "labels").glob("*.json.gz"))
    if len(paths) != RECIPE["deals"]:
        raise ValueError(f"need all {RECIPE['deals']} declared deals before fitting")
    rows = []
    for index, path in enumerate(paths):
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            row = json.load(stream)
        if row["index"] != index or row["split"] != split_for(index) or row["seed"] != derived_seed("dataset", index):
            raise ValueError("label lineage or split mismatch")
        rows.append(row)
    return recipe, rows


def position_features(row):
    from guandan.ai.action_ranker import ActionObservation, action_features
    from guandan.storage.savegame import _dict_to_state
    from guandan.storage.serialization import _dict_to_pattern, deserialize_events

    state = _dict_to_state(row["state"], deserialize_events(row["events"]), 3)
    observation = ActionObservation.from_state(state, row["player"])
    return [action_features(observation, _dict_to_pattern(a["pattern"]) if a["pattern"] else None)
            for a in row["actions"]]


def mean_values(row):
    return [sum(sum(group) for group in action["values"]) / (RECIPE["worlds"] * 3)
            for action in row["actions"]]


def pair_examples(deals):
    """Soft paired comparisons; ties remain 0.5 rather than hard noisy winners."""
    import numpy as np

    differences, targets = [], []
    for deal in deals:
        for row in deal["positions"]:
            features = np.asarray(position_features(row), dtype=np.float64)
            for left in range(len(features)):
                for right in range(left):
                    paired = [sum(row["actions"][left]["values"][c][world]
                                  - row["actions"][right]["values"][c][world]
                                  for c in RECIPE["companions"]) / 3
                              for world in range(RECIPE["worlds"])]
                    mean = sum(paired) / len(paired)
                    se = math.sqrt(sum((x - mean) ** 2 for x in paired) / (len(paired) * max(1, len(paired) - 1)))
                    # Smooth noisy labels instead of discarding uncertainty or
                    # equating a predicted ranking score to a game probability.
                    z = max(-30, min(30, mean / max(0.01, 2 * se)))
                    targets.append(1 / (1 + math.exp(-z)))
                    differences.append(features[left] - features[right])
    return np.asarray(differences), np.asarray(targets)


def fit_weights(x, targets, regularization):
    import numpy as np

    weights = np.zeros(x.shape[1])
    # Fixed full-batch gradient descent; step bound from ||X||_F is conservative.
    step = 1 / (0.25 * float(np.mean(np.sum(x * x, axis=1))) + regularization)
    for _ in range(RECIPE["epochs"]):
        logits = np.clip(x @ weights, -30, 30)
        gradient = x.T @ (1 / (1 + np.exp(-logits)) - targets) / len(targets)
        weights -= step * (gradient + regularization * weights)
    return weights


def ranking_metrics(deals, weights):
    import numpy as np

    from guandan.ai.action_ranker import FEATURE_NAMES

    rows = []
    for deal in deals:
        for row in deal["positions"]:
            features = np.asarray(position_features(row))
            values = mean_values(row)
            selected = int(np.argmax(features @ weights))
            reference = next(i for i, action in enumerate(row["actions"])
                             if action["key"] == row["reference_key"])
            rows.append({"deal": deal["index"], "phase": row["phase"],
                         "model_regret": max(values) - values[selected],
                         "reference_regret": max(values) - values[reference],
                         "selected_key": row["actions"][selected]["key"],
                         "reference_key": row["reference_key"]})
    return {"positions": len(rows), "feature_count": len(FEATURE_NAMES),
            "model_regret": sum(r["model_regret"] for r in rows) / len(rows),
            "reference_regret": sum(r["reference_regret"] for r in rows) / len(rows), "rows": rows}


def fit(folder: Path, model_path: Path) -> dict:
    from guandan.ai.action_ranker import FEATURE_NAMES, FEATURE_VERSION

    recipe, deals = read_labels(folder)
    grouped = {split: [d for d in deals if d["split"] == split] for split in RECIPE["splits"]}
    x, targets = pair_examples(grouped["train"])
    scores, candidates = {}, {}
    for coefficient in RECIPE["regularization"]:
        weights = fit_weights(x, targets, coefficient)
        metrics = ranking_metrics(grouped["tune"], weights)
        scores[str(coefficient)] = {k: v for k, v in metrics.items() if k != "rows"}
        candidates[coefficient] = weights
        print(f"lambda {coefficient}: tune regret {metrics['model_regret']:.6f}", flush=True)
    selected = min(RECIPE["regularization"], key=lambda c: scores[str(c)]["model_regret"])
    weights = candidates[selected]
    dataset_sha = hashlib.sha256()
    for path in sorted((folder / "labels").glob("*.json.gz")):
        dataset_sha.update(path.name.encode())
        dataset_sha.update(path.read_bytes())
    payload = {"schema": 1, "ruleset_version": 3, "feature_version": FEATURE_VERSION,
               "feature_names": list(FEATURE_NAMES), "objective": "paired-action-ranking",
               "weights": weights.tolist(), "meta": {"recipe": recipe,
                   "label_sha256": dataset_sha.hexdigest(), "regularization": selected,
                   "training_pairs": len(targets), "split_deals": RECIPE["splits"],
                   "interpretation": "relative action ranking, not observed human win probability"}}
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text(json.dumps(payload, indent=2) + "\n")
    diagnostic = ranking_metrics(grouped["diagnostic"], weights)
    report = {"recipe": recipe, "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
              "label_sha256": dataset_sha.hexdigest(), "tuning": scores,
              "selected_regularization": selected, "diagnostic": diagnostic,
              "diagnostic_improved": diagnostic["model_regret"] < diagnostic["reference_regret"],
              "phase_coverage": dict(Counter(row["phase"] for d in deals for row in d["positions"]))}
    (folder / "fit.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("collect", "fit"), required=True)
    parser.add_argument("--baseline-root", type=Path)
    parser.add_argument("--folder", type=Path, default=Path("benchmarks/action-ranker-v1"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=RECIPE["deals"])
    parser.add_argument("--model", type=Path, default=Path("src/guandan/ai/profiles/action_ranker_v1.json"))
    args = parser.parse_args()
    if args.workers < 1 or args.start < 0 or args.count < 1 or args.start + args.count > RECIPE["deals"]:
        parser.error("positive workers/count and a range within the fixed 576-deal recipe required")
    if args.stage == "collect":
        if args.baseline_root is None:
            parser.error("--baseline-root required for frozen-policy labels")
        collect(args.baseline_root.resolve(), args.folder, args.workers,
                list(range(args.start, args.start + args.count)))
    else:
        report = fit(args.folder, args.model)
        print(json.dumps({k: v for k, v in report.items() if k not in ("diagnostic", "tuning")}, indent=2))


if __name__ == "__main__":
    main()
