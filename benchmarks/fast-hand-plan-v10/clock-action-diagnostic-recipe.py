"""Label every changed paired-clock action; a proxy diagnostic, not strength."""
import hashlib
import json
import random
from pathlib import Path

from guandan.ai import diagnostics
from guandan.ai.mcts.determinize import determinize
from guandan.ai.mcts.information_set import _apply_action
from guandan.ai.strategy import make_strategy
from guandan.engine.state import clone_state_for_search
from guandan.storage.serialization import _dict_to_pattern
from scripts.fit_action_ranker import frozen_playout, snapshot_fingerprint

root = Path.cwd()
folder = root / "benchmarks/fast-hand-plan-v10"
old = json.loads((folder / "counter-clock.json").read_text())["records"]
new = json.loads((folder / "packed-clock.json").read_text())["records"]
positions = dict(diagnostics.positions())
rows = []
for before, after in zip(old, new):
    if before["action"] == after["action"]:
        continue
    assert before["cache"] == "warm" and before["case"] == after["case"]
    state = positions[before["case"]]
    actor = state.current_player()
    actions = [_dict_to_pattern(r["action"]) if r["action"] else None for r in (before, after)]
    policies = [make_strategy(tier) for tier in range(3)]
    memo, value_memo = {}, {}
    values = [[[], []] for _ in range(3)]
    for world in range(32):
        seed = int.from_bytes(hashlib.sha256(f"packed-clock-label-v10/{world}".encode()).digest()[:8], "big")
        sampled = determinize(state, actor, random.Random(seed))
        for style in range(3):
            for branch, action in enumerate(actions):
                simulated = clone_state_for_search(sampled)
                assert _apply_action(simulated, actor, action)
                values[style][branch].append(frozen_playout(simulated, actor, style, policies, memo, value_memo))
        if (world + 1) % 8 == 0:
            print(f"clock-action diagnostic: {world + 1}/32 worlds", flush=True)
    rows.append({"case": before["case"], "tier": before["tier"], "before": before["action"],
                 "after": after["action"], "evaluations_before": before["simulations"],
                 "evaluations_after": after["simulations"], "values": values,
                 "mean_gain_by_companion": [sum(b-a for a,b in zip(v[0],v[1]))/32 for v in values]})
report = {"purpose": "all observed changed paired-clock actions; complete tier-2 proxy continuations, not game strength",
          "source_sha256": snapshot_fingerprint(root), "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          "changed_decisions": len(rows), "completed_branches": len(rows)*3*32*2, "records": rows}
(folder / "clock-action-diagnostic.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({k:v for k,v in report.items() if k != "records"}))
