"""Branch only public replay prefixes; finish branches with legal style proxies."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from dataclasses import replace
from pathlib import Path

from guandan.ai.candidates import pattern_key
from guandan.ai.mcts.determinize import determinize
from guandan.ai.mcts.information_set import _apply_action
from guandan.ai.play import play_or_pass
from guandan.ai.strategy import make_strategy
from guandan.engine.events import ShuffleDeal
from guandan.engine.replay import replay_events
from guandan.engine.state import clone_state_for_search
from guandan.storage.serialization import deserialize_events

try:
    from scripts.ai_team_trial import (
        BASELINE_SHA,
        FrozenClient,
        FrozenStrategy,
        candidate,
        canonical_utility,
        source_fingerprint,
    )
except ModuleNotFoundError:
    from ai_team_trial import (
        BASELINE_SHA,
        FrozenClient,
        FrozenStrategy,
        candidate,
        canonical_utility,
        source_fingerprint,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--variant", choices=("corrected", "value", "team", "takeover", "lead", "endgame", "policy", "mixed", "combined", "guard", "guard_lead", "adaptive", "chain", "partner_combined", "action_ranker"), default="combined")
    parser.add_argument("--difficulty", type=int, choices=(3, 4), default=4)
    parser.add_argument("--fixed-iterations", type=int, default=128)
    parser.add_argument("--worlds", type=int, default=32)
    parser.add_argument("--ruleset", type=int, choices=(2, 3), help="explicit what-if projection; preserve the original fixture")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.worlds < 1 or args.fixed_iterations < 1:
        parser.error("positive worlds and fixed iterations required")
    ranked = args.variant == "action_ranker"
    if ranked:
        from scripts.fit_action_ranker import derived_seed, label_recipe

        label_recipe(args.baseline_root)
    fixture = Path(__file__).resolve().parents[1] / "tests/fixtures/ai-human-partner-replay.json"
    data = json.loads(fixture.read_text())
    rows = []
    for index in data["decision_events"]:
        events = deserialize_events(data["events"][:index])
        if args.ruleset is not None:
            if not isinstance(events[0], ShuffleDeal):
                raise RuntimeError("replay prefix has no initial deal")
            events[0] = replace(events[0], a_failure_counts=(0, 0))
        state = replay_events(events, allow_incomplete_tail=True,
                              ruleset_version=args.ruleset or data.get("ruleset_version", 2))
        player = state.current_player()
        client = FrozenClient(args.baseline_root)
        try:
            old = FrozenStrategy(client, args.difficulty, "fixed", args.fixed_iterations)
            action_seed = derived_seed(f"human-replay-action-{args.difficulty}", index) if ranked else 1000 + index
            old.rng = random.Random(action_seed)
            new = candidate(args.difficulty, args.variant, "fixed", args.fixed_iterations)
            new.rng = random.Random(action_seed)
            actions = [old.select_pattern(state, player), new.select_pattern(state, player)]
        finally:
            client.close()
        style_rows = []
        for style in (0, 1, 2):
            values = [[], []]
            for sample in range(args.worlds):
                world_seed = derived_seed("human-replay-world", index, sample) if ranked else 100000 + index * 100 + sample
                world = determinize(state, player, random.Random(world_seed))
                for branch, action in enumerate(actions):
                    sim = clone_state_for_search(world)
                    if not _apply_action(sim, player, action):
                        raise RuntimeError("illegal replay branch")
                    policies = [make_strategy(style if seat == (player + 2) % 4 else 2)
                                for seat in range(4)] if ranked else [make_strategy(style) for _ in range(4)]
                    rng = random.Random(world_seed if ranked else 200000 + index * 100 + sample)
                    for _ in range(600):
                        if sim.finished:
                            values[branch].append(canonical_utility(sim, player % 2))
                            break
                        seat = sim.current_player()
                        play_or_pass(sim, seat, policies[seat], rng)
                    else:
                        raise RuntimeError("replay proxy did not finish")
            style_rows.append({"style": style, "common_worlds": args.worlds,
                               "old_mean_utility": sum(values[0]) / args.worlds,
                               "new_mean_utility": sum(values[1]) / args.worlds,
                               "paired_differences": [b - a for a, b in zip(*values)]})
        rows.append({"event_prefix": index, "player": player,
                     "old_action": pattern_key(actions[0]) if actions[0] else ["pass"],
                     "new_action": pattern_key(actions[1]) if actions[1] else ["pass"],
                     "new_reason": new.last_decision_reason,
                     "partner_probabilities": new.last_search.partner_probabilities if new.last_search else (),
                     "response_chain": new.last_search.response_chain if new.last_search else None,
                     "action_ranker": new.last_search.action_ranker if new.last_search else None,
                     "styles": style_rows})
        print(f"replay prefix {index}: legal continuations complete", flush=True)
    manifest = args.baseline_root / "policy-snapshot.json"
    baseline = json.loads(manifest.read_text())["source_sha256"] if manifest.exists() else BASELINE_SHA
    args.out.write_text(json.dumps({"baseline_sha": baseline, "source_sha256": source_fingerprint(),
                                    "replay_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                                    "difficulty": args.difficulty, "fixed_iterations": args.fixed_iterations,
                                    "variant": args.variant, "worlds": args.worlds, "ruleset_override": args.ruleset,
                                    "fixture_ruleset": data.get("ruleset_version", 2),
                                    "continuation": "legal independent style proxies, not recorded human suffixes",
                                    "positions": rows}, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
