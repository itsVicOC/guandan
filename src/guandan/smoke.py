"""M0a smoke test：跑 N 局 AI 对局，确保能完成且无异常。"""
from __future__ import annotations

import sys

from .cli import _ai_play
from .engine.state import make_initial_state


def run_one(seed: int, level: int = 2) -> dict:
    state = make_initial_state(level=level, first_player=0, seed=seed)
    turns = 0
    max_turns = 2000
    while not state.finished and turns < max_turns:
        _ai_play(state, state.turn_index)
        turns += 1
    return {
        "seed": seed,
        "turns": turns,
        "finished": state.finished,
        "finish_order": list(state.finish_order),
        "levels": getattr(state, "team_levels_final", None),
        "drift": getattr(state, "drift_flag", None),
    }


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    print(f"Running {n} AI-only games...")
    for i in range(n):
        r = run_one(seed=100 + i, level=2 + (i % 5))
        print(
            f"  seed={r['seed']:3d} turns={r['turns']:3d} "
            f"finished={r['finished']} order={r['finish_order']} levels={r['levels']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
