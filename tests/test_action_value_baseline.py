"""Smoke tests for reproducible action-value diagnostics."""
from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "action_value_baseline.py"


def test_ladder_samples_only_positions_with_undecided_winner():
    from scripts.action_value_baseline import sample_diverse_positions

    rows = sample_diverse_positions(18, seed_start=47000, stratify_phases=True)
    assert {row["phase"] for row in rows} == {"opening", "middle", "endgame"}
    assert all(not row["state"].finish_order for row in rows)
    # The old sampler accepted seat 0's already-decided A-level endgame here.
    assert rows[17]["seed"] != 47017


def test_action_label_completes_ranking_after_head_place(monkeypatch):
    from guandan.ai.play import play_or_pass
    from guandan.ai.strategy import make_strategy
    from guandan.engine.state import make_initial_state
    from scripts import action_value_baseline as audit

    state = make_initial_state(seed=17)
    strategy = make_strategy(0)
    rng = random.Random(17)
    while not state.finish_order:
        play_or_pass(state, state.current_player(), strategy, rng)
    player = state.current_player()
    action = strategy.select_pattern(state, player)
    audit._init_worker({17: state}, {17: [action]}, {17: player})

    continuations = []
    def record(sim, *args, **kwargs):
        continuations.append(sim)
        return play_or_pass(sim, *args, **kwargs)

    monkeypatch.setattr(audit, "play_or_pass", record)
    label = audit._playout((17, 0, 0))
    assert continuations and continuations[-1].finished
    assert label[:2] == (17, 0)
    assert 0.0 < label[2] < 1.0


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
        assert row["regret"][method] == pytest.approx(best - values[json.dumps(key)], abs=0.00005)


def test_placed_and_match_state_sampler_covers_counters_and_all_seats():
    from scripts.action_value_baseline import sample_diverse_positions

    rows = sample_diverse_positions(36, seed_start=126000, stratify_phases=True, include_placed=True)
    placed = [r for r in rows if r["phase"] == "placed"]
    assert {r["seat"] for r in placed} == set(range(4))
    assert all(r["state"].finish_order for r in placed)
    assert any(r["team_levels"][0] != r["team_levels"][1] for r in rows)
    assert {c for r in rows for c in r["a_failure_counts"]} == {0, 1, 2}


def test_legacy_head_labels_are_rejected_for_new_objective():
    from scripts.action_value_baseline import evaluate

    with pytest.raises(ValueError, match="legacy head-place"):
        evaluate({"meta": {}, "positions": []}, [], pairwise=True)
