"""Canonical evaluation lineage covering rules, serialization, tools and data."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def evaluation_manifest(root: Path, recipe: dict[str, Any] | None = None) -> dict[str, Any]:
    paths = set(root.joinpath("src").rglob("*.py")) | set(root.joinpath("src").rglob("*.json"))
    paths.update(root.joinpath("scripts").glob("*.py"))
    paths.update(path for path in root.joinpath("tests/fixtures").rglob("*") if path.is_file())
    paths.update(path for name in ("pyproject.toml", "uv.lock") if (path := root / name).exists())
    return {"schema": 1, "recipe": recipe or {}, "files": {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }}


def manifest_fingerprint(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def verify_manifest(root: Path, manifest: dict[str, Any]) -> None:
    for relative, expected in manifest["files"].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"evaluation dependency changed: {relative}")
