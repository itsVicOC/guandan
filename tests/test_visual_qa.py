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
    assert len(artifacts) == 30
    assert {artifact["format"] for artifact in artifacts} == {"png", "svg"}
    assert all(Path(artifact["path"]).is_file() for artifact in artifacts)
    names = {Path(artifact["path"]).name for artifact in artifacts}
    for seat in range(4):
        for size in ("1080x760", "1280x860"):
            assert f"game-fourway-seat-{seat}-{size}.png" in names
    assert "game-flush-first-1080x760.png" in names
