"""Repository-owned visual smoke capture."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_visual_qa_capture_is_nonblank_and_complete(tmp_path: Path) -> None:
    output = tmp_path / "visual"
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["GUANDAN_TUI_NO_RESIZE"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/capture_visual_qa.py",
            "--output",
            str(output),
        ],
        cwd=Path(__file__).parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    artifacts = manifest["artifacts"]
    assert len(artifacts) == 15
    assert {artifact["format"] for artifact in artifacts} == {"png", "svg"}
    assert all(Path(artifact["path"]).is_file() for artifact in artifacts)
