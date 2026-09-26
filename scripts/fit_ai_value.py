"""Fit a symmetric continuation-value model; hold out complete deal seeds."""
from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
from pathlib import Path

from guandan.ai.mcts.information_set import _apply_action
from guandan.ai.mcts.search import (
    _evaluate_result,
    _evaluate_unfinished,
    _rollout_select_pattern,
    planned_position_features,
)
from guandan.engine.state import make_initial_state


def collect(job):
    index, seed = job
    level = (2, 9, 14)[index % 3]
    state = make_initial_state(seed=seed, level=level, first_player=index % 4)
    rows = []
    for turn in range(600):
        if state.finished:
            target = _evaluate_result(state, 0)
            for row in rows:
                row['target'] = target
            return rows
        if not state.finish_order and turn >= 16 and turn % 8 == 0:
            rows.append({
                'seed': seed, 'level': level, 'turn': turn,
                'holdout': (index // 4) % 4 == 3,
                'features': planned_position_features(state, 0),
                'old_estimate': _evaluate_unfinished(state, 0),
            })
        seat = state.current_player()
        pattern = _rollout_select_pattern(state, seat, rollout_strategy_level=1)
        if not _apply_action(state, seat, pattern):
            raise RuntimeError('illegal training continuation')
    raise RuntimeError('training game did not complete')


def probability(weights, features):
    logit = max(-30.0, min(30.0, sum(w * x for w, x in zip(weights, features))))
    return 1.0 / (1.0 + math.exp(-logit))


def fit(rows):
    weights = [0.0] * len(rows[0]['features'])
    for _ in range(1500):
        gradient = [0.0] * len(weights)
        for row in rows:
            error = probability(weights, row['features']) - row['target']
            for i, feature in enumerate(row['features']):
                gradient[i] += error * feature
        for i in range(len(weights)):
            weights[i] -= 0.8 * (gradient[i] / len(rows) + 0.0005 * weights[i])
    return weights


def loss(rows, predict):
    return sum(
        -row['target'] * math.log(max(1e-9, predict(row)))
        - (1.0 - row['target']) * math.log(max(1e-9, 1.0 - predict(row)))
        for row in rows
    ) / len(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deals', type=int, default=768)
    parser.add_argument('--seed-start', type=int, default=40000)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.deals < 16 or args.workers < 1:
        parser.error('at least 16 deals and a positive worker count are required')
    rows = []
    with mp.Pool(args.workers) as pool:
        for index, new_rows in enumerate(pool.imap_unordered(
            collect, enumerate(range(args.seed_start, args.seed_start + args.deals))
        ), 1):
            rows.extend(new_rows)
            if index % 64 == 0:
                print(f'{index}/{args.deals} training deals', flush=True)
    rows.sort(key=lambda row: (row['seed'], row['turn']))
    train = [row for row in rows if not row['holdout']]
    holdout = [row for row in rows if row['holdout']]
    weights = fit(train)
    unplanned_indices = (2, 3, 4, 5, 7)
    unplanned = [
        {**row, 'features': [row['features'][i] for i in unplanned_indices]}
        for row in rows
    ]
    unplanned_weights = fit([row for row in unplanned if not row['holdout']])
    result = {
        'meta': {
            'deals': args.deals, 'seed_start': args.seed_start,
            'levels': [2, 9, 14], 'holdout': 'every fourth block of four whole deals; balanced starting seats',
            'target': 'terminal team utility under the current level-1 rollout policy',
            'intercept': 0.0, 'ridge': 0.0005,
        },
        'weights': weights,
        'summary': {
            'training_positions': len(train), 'holdout_positions': len(holdout),
            'old_holdout_loss': loss(holdout, lambda row: row['old_estimate']),
            'new_holdout_loss': loss(holdout, lambda row: probability(weights, row['features'])),
        },
        'positions': rows,
        'ablation_without_plans': {
            'features': unplanned_indices,
            'weights': unplanned_weights,
            'holdout_loss': loss(
                [row for row in unplanned if row['holdout']],
                lambda row: probability(unplanned_weights, row['features']),
            ),
        },
    }
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'weights': weights, **result['summary']}), flush=True)


if __name__ == '__main__':
    main()
