"""Smoke tests for reproducible action-value diagnostics."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "action_value_baseline.py"


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
