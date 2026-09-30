"""Fit rank probabilities and an empirical three-A match continuation table."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import multiprocessing as mp
from collections import Counter
from dataclasses import replace
from pathlib import Path

from guandan.ai.match_value import MODEL_PATH, OUTCOMES, build_continuation_table
from guandan.ai.mcts.information_set import _apply_action
from guandan.ai.mcts.search import _rollout_select_pattern, rank_position_features
from guandan.ai.tribute import choose_ai_tribute_cards
from guandan.engine.events import ShuffleDeal
from guandan.engine.rules.tributes import apply_tribute_flow
from guandan.engine.state import make_initial_state

LEVEL_PAIRS = ((2, 2), (9, 9), (14, 14), (14, 9), (9, 14), (13, 11), (11, 13), (14, 13), (13, 14))


def collect(job):
    index, seed = job
    levels = LEVEL_PAIRS[index % len(LEVEL_PAIRS)]
    previous_head = (index // len(LEVEL_PAIRS)) % 2
    previous_place = 2 + (index // (2 * len(LEVEL_PAIRS))) % 3
    level = levels[previous_head]
    counts = [((index // 6) + team) % 3 if levels[team] == 14 else 0 for team in (0, 1)]
    state = make_initial_state(seed=seed, level=level, team_levels=levels, a_failure_counts=counts, first_player=index % 4)
    tribute_row = (index // 54) % 4 != 0
    if tribute_row:
        partner, enemy = (previous_head + 2) % 4, 1 - previous_head
        orders = {2: [previous_head, partner, enemy], 3: [previous_head, enemy, partner], 4: [previous_head, enemy, (enemy + 2) % 4]}
        difficulties = tuple((index + seat) % 3 for seat in range(4))
        paid, returned = choose_ai_tribute_cards(orders[previous_place], state.hands, level=level, wild_card=state.wild_card, difficulties=difficulties)
        tribute = apply_tribute_flow(orders[previous_place], state.hands, level=level, wild_card=state.wild_card, tribute_choices=paid, return_choices=returned)
        state.history.extend(tribute.events)
        state.turn_index = state.leader = tribute.first_player
        event = state.history[0]
        assert isinstance(event, ShuffleDeal)
        state.history[0] = replace(event, first_player=tribute.first_player)
    rows = []
    for turn in range(1000):
        if state.finished:
            order = list(state.finish_order)
            order.extend(seat for seat in range(4) if seat not in order)
            head, place = order[0] % 2, order.index((order[0] + 2) % 4) + 1
            target = OUTCOMES.index((head, place))
            for row in rows:
                row["outcome"] = target
            band = 0 if level <= 6 else 1 if level <= 10 else 2
            return {"seed": seed, "holdout": (index // 4) % 4 == 3, "positions": rows,
                    "levels": levels, "a_failures": counts, "tribute": tribute_row,
                    "transition_key": f"{band},{previous_place}",
                    "relative_outcome": OUTCOMES.index((head ^ previous_head, place))}
        if not state.finish_order and turn >= 8 and turn % 8 == 0:
            rows.append({"seed": seed, "features": rank_position_features(state, 0), "turn": turn})
        seat = state.current_player()
        # Mixed local policies provide multiple execution styles, with no
        # perfect-information partner choice and no online training.
        pattern = _rollout_select_pattern(state, seat, rollout_strategy_level=1 + (index + seat) % 2,
                                          style=("balanced", "conservative", "shedding")[(index + seat) % 3])
        if not _apply_action(state, seat, pattern):
            raise RuntimeError("illegal value-training continuation")
    raise RuntimeError("value-training round did not finish")


def probabilities(weights, features):
    x = (1.0, *features)
    logits = [sum(w * value for w, value in zip(row, x)) for row in weights]
    offset = max(logits)
    values = [math.exp(value - offset) for value in logits]
    return [v / sum(values) for v in values]


def fit(rows, epochs=600):
    width = len(rows[0]["features"]) + 1
    weights = [[0.0] * width for _ in OUTCOMES]
    # Every position is explicitly paired with its team-exchanged counterpart.
    examples = [(row["features"], row["outcome"]) for row in rows]
    examples += [(tuple(-x for x in row["features"]), (row["outcome"] + 3) % 6) for row in rows]
    for _ in range(epochs):
        gradient = [[0.0] * width for _ in OUTCOMES]
        for features, target in examples:
            prediction = probabilities(weights, features)
            for k in range(6):
                error = prediction[k] - float(k == target)
                for j, value in enumerate((1.0, *features)):
                    gradient[k][j] += error * value
        for k in range(6):
            for j in range(width):
                weights[k][j] -= 0.6 * (gradient[k][j] / len(examples) + 0.001 * weights[k][j])
    return weights


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deals", type=int, default=768)
    parser.add_argument("--seed-start", type=int, default=110000)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--epochs", type=int, default=600)
    parser.add_argument("--model", type=Path, default=MODEL_PATH)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.deals < 64 or args.workers < 1 or args.epochs < 1:
        parser.error("at least 64 deals and positive workers/epochs required")
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in [*sorted((root / "src/guandan/ai").rglob("*.py")), Path(__file__).resolve()]:
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    with mp.get_context("spawn").Pool(args.workers) as pool:
        deals = list(pool.imap(collect, enumerate(range(args.seed_start, args.seed_start + args.deals))))
    train = [row for deal in deals if not deal["holdout"] for row in deal["positions"]]
    holdout = [row for deal in deals if deal["holdout"] for row in deal["positions"]]
    weights = fit(train, args.epochs)
    transitions = {}
    coverage = {}
    for band in range(3):
        for place in (2, 3, 4):
            key = f"{band},{place}"
            counts = Counter(deal["relative_outcome"] for deal in deals if not deal["holdout"] and deal["tribute"] and deal["transition_key"] == key)
            coverage[key] = sum(counts.values())
            # Symmetric Dirichlet smoothing keeps every outcome possible in
            # sparse cells. Holdout games never affect transition fitting.
            transitions[key] = [(counts[i] + 4.0) / (sum(counts.values()) + 24.0) for i in range(6)]
    table, iterations, residual = build_continuation_table(transitions)
    loss = sum(-math.log(max(1e-12, probabilities(weights, row["features"])[row["outcome"]])) for row in holdout) / len(holdout)
    summary = {"train_deals": sum(not d["holdout"] for d in deals), "holdout_deals": sum(d["holdout"] for d in deals),
               "training_positions": len(train), "holdout_positions": len(holdout),
               "rank_holdout_log_loss": loss, "uniform_rank_log_loss": math.log(6),
               "transition_training_games": coverage, "bellman_iterations": iterations, "bellman_residual": residual}
    model = {"schema": 1, "ruleset_version": 3, "meta": {"seed_start": args.seed_start, "deals": args.deals,
             "source_sha256": digest.hexdigest(), "target": "six full-round rank outcomes and empirical future match utility",
             "level_pairs": LEVEL_PAIRS, "a_failures": [0, 1, 2], "holdout": "every fourth block of four whole deals", **summary},
             "transitions": transitions, "rank_weights": weights, "continuation": table}
    args.model.write_text(json.dumps(model, indent=2) + "\n")
    args.out.write_text(json.dumps({"meta": model["meta"], "summary": summary, "deals": deals}, indent=2) + "\n")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
