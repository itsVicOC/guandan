"""Symmetric isolated policy worker for production-clock short-hand trials."""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--weight', type=float, default=0)
    args = parser.parse_args()
    sys.path.insert(0, str(args.root / 'src'))
    import guandan
    from guandan.ai import diagnostics
    from guandan.ai.strategies.dachangsheng import DaiChangshengStrategy
    from guandan.ai.strategies.professional import ProfessionalStrategy
    from guandan.ai.strategy import make_strategy
    from guandan.ai.valuation import _structure_score_memo
    from guandan.engine.state import clone_state_for_search, pass_turn, play_pattern
    from guandan.storage.savegame import _dict_to_state, _pattern_to_dict
    from guandan.storage.serialization import deserialize_events

    if not Path(guandan.__file__).resolve().is_relative_to(args.root.resolve()):
        raise RuntimeError('worker imported an unfrozen policy')
    print(json.dumps({'ready': True, 'source': str(Path(guandan.__file__).resolve())}), flush=True)
    policies = {}
    for line in sys.stdin:
        request = json.loads(line)
        if request.get('clear_caches'):
            diagnostics._exact_material_cache.clear()
            diagnostics._estimate.cache_clear()
            diagnostics._patterns_in_hand.cache_clear()
            diagnostics._complete_pattern_cache.clear()
            diagnostics._holding_chance.cache_clear()
            _structure_score_memo.clear()
        seat, tier, mode = request['player'], request['difficulty'], request['mode']
        key = (seat, tier, mode, request.get('fixed_iterations', 0))
        if key not in policies:
            options = ({'time_budget_ms': 0, 'iterations': request['fixed_iterations']}
                       if mode == 'fixed' else {})
            if args.weight and tier >= 3:
                options.update(urgent_blocking=True, urgent_blocking_weight=args.weight)
            if tier == 4:
                policy = DaiChangshengStrategy(mcts_overrides=options)
            elif tier == 3:
                policy = ProfessionalStrategy(**options)
            else:
                policy = make_strategy(tier)
            policies[key] = policy
        policy = policies[key]
        if hasattr(policy, 'rng'):
            policy.rng = random.Random()
            raw = request['rng_state']
            policy.rng.setstate((raw[0], tuple(raw[1]), raw[2]))
        state = _dict_to_state(request['state'], deserialize_events(request['events']), 3)
        started = time.perf_counter()
        budget = (policy.critical_time_budget_ms if policy._critical_decision(state, seat)
                  else policy.time_budget_ms) if tier >= 3 and mode == 'clock' else 0
        action = policy.select_pattern(state, seat)
        elapsed = time.perf_counter() - started
        # Validate the raw selection instead of letting play_or_pass conceal
        # a spurious pass on a lead. Both sides receive only public inputs.
        check = clone_state_for_search(state)
        if action is None:
            pass_turn(check, seat)
        else:
            play_pattern(check, seat, action)
        result = getattr(policy, 'last_search', None)
        endgame = getattr(policy, 'last_endgame', None)
        print(json.dumps({
            'request_id': request.get('request_id'),
            'pattern': _pattern_to_dict(action) if action else None,
            'elapsed_seconds': elapsed, 'budget_ms': budget,
            'budget_passed': not budget or elapsed <= budget / 1000 * 1.15 + .1,
            'rng_state': policy.rng.getstate() if hasattr(policy, 'rng') else request['rng_state'],
            'reason': getattr(policy, 'last_decision_reason', 'heuristic'),
            'urgent': getattr(policy, 'last_urgent_blocking', None),
            'guard': getattr(policy, 'last_guard', None),
            'simulations': result.simulations if result else 0,
            'common_samples': result.common_samples if result else 0,
            'endgame_reason': endgame.reason if endgame else None,
        }), flush=True)


if __name__ == '__main__':
    main()
