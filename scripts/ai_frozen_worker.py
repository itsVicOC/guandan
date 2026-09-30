"""JSON-lines worker importing the complete frozen checkout in isolation."""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.root / "src"))
    import guandan
    from guandan.ai.strategies.dachangsheng import DaiChangshengStrategy
    from guandan.ai.strategies.professional import ProfessionalStrategy
    from guandan.ai.strategy import make_strategy
    from guandan.engine.state import CURRENT_RULESET_VERSION
    from guandan.storage.savegame import _dict_to_state, _pattern_to_dict
    from guandan.storage.serialization import deserialize_events

    if not Path(guandan.__file__).resolve().is_relative_to(args.root.resolve()):
        raise RuntimeError("frozen worker imported an unfrozen dependency")
    print(json.dumps({"ready": True, "source": str(Path(guandan.__file__).resolve()), "ruleset_version": CURRENT_RULESET_VERSION}), flush=True)
    policies = {}
    for line in sys.stdin:
        request = json.loads(line)
        seat, tier = request["player"], request["difficulty"]
        if seat not in policies:
            fixed = request["mode"] == "fixed"
            iterations = request.get("fixed_iterations", 768)
            if tier == 4:
                policy = DaiChangshengStrategy(mcts_overrides={"time_budget_ms": 0, "iterations": iterations} if fixed else None)
            elif tier == 3:
                policy = ProfessionalStrategy(time_budget_ms=0, iterations=iterations) if fixed else ProfessionalStrategy()
            else:
                policy = make_strategy(tier)
            if hasattr(policy, "rng"):
                rng_state = request["rng_state"]
                policy.rng = random.Random()
                policy.rng.setstate((rng_state[0], tuple(rng_state[1]), rng_state[2]))
            policies[seat] = policy
        state = _dict_to_state(request["state"], deserialize_events(request["events"]), request["state"]["ruleset_version"])
        started = time.perf_counter()
        pattern = policies[seat].select_pattern(state, seat)
        print(json.dumps({
            "pattern": _pattern_to_dict(pattern) if pattern else None,
            "elapsed_seconds": time.perf_counter() - started,
            "reason": getattr(policies[seat], "last_decision_reason", "heuristic"),
        }), flush=True)


if __name__ == "__main__":
    main()
