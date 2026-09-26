"""Smoke tests for reproducible action-value diagnostics."""
from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "action_value_baseline.py"


def test_ladder_samples_only_positions_with_undecided_winner():
    from scripts.action_value_baseline import sample_diverse_positions

    rows = sample_diverse_positions(18, seed_start=47000, stratify_phases=True)
    assert {row["phase"] for row in rows} == {"opening", "middle", "endgame"}
    assert all(not row["state"].finish_order for row in rows)
    # The old sampler accepted seat 0's already-decided A-level endgame here.
    assert rows[17]["seed"] != 47017


def test_action_label_stops_after_head_place(monkeypatch):
    from guandan.ai.play import play_or_pass
    from guandan.ai.strategy import make_strategy
    from guandan.engine.state import make_initial_state, team_of
    from scripts import action_value_baseline as audit

    state = make_initial_state(seed=17)
    strategy = make_strategy(0)
    rng = random.Random(17)
    while not state.finish_order:
        play_or_pass(state, state.current_player(), strategy, rng)
    player = state.current_player()
    action = strategy.select_pattern(state, player)
    audit._init_worker({17: state}, {17: [action]}, {17: player})

    def unexpected(*args, **kwargs):
        raise AssertionError("head place already determines the round-win label")

    monkeypatch.setattr(audit, "play_or_pass", unexpected)
    assert audit._playout((17, 0, 0)) == (
        17, 0, int(team_of(state.finish_order[0]) == team_of(player))
    )


def test_diverse_evaluation_covers_multiple_seats_and_source_policies(tmp_path):
    output = tmp_path / "diverse.json"
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "evaluate-diverse",
            "--positions", "4",
            "--playouts", "2",
            "--workers", "1",
            "--out", str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    rows = payload["positions"]

    assert len(rows) == 4
    assert {row["seat"] for row in rows} == {0, 1}
    assert {row["source_difficulty"] for row in rows} == {0, 2}
    assert all(set(row["regret"]) == {"greedy", "root32", "root96"} for row in rows)


def test_ladder_preserves_reusable_action_labels_and_variant_picks(tmp_path):
    output = tmp_path / "ladder.json"
    subprocess.run([
        sys.executable, str(SCRIPT), "evaluate-ladder",
        "--positions", "1", "--playouts", "2", "--workers", "1",
        "--include-confidence-guard", "--out", str(output),
    ], check=True, capture_output=True, text=True)
    payload = json.loads(output.read_text())
    row = payload["positions"][0]
    assert payload["meta"]["head_undetermined_at_sampling"]
    assert "4_confidence" in row["selected_action_keys"]
    values = {
        json.dumps(action["key"]): action["wins"] / action["samples"]
        for action in row["action_values"]
    }
    best = max(values.values())
    for method, key in row["selected_action_keys"].items():
        assert row["regret"][method] == best - values[json.dumps(key)]
