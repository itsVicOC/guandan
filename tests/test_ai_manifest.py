from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from scripts.ai_manifest import evaluation_manifest, manifest_fingerprint, verify_manifest
from scripts.fit_action_ranker import snapshot_fingerprint


@pytest.mark.parametrize("relative", ["src/guandan/engine/state.py", "src/guandan/storage/serialization.py",
                                     "src/guandan/ai/profiles/policy.json", "scripts/worker.py",
                                     "tests/fixtures/corpus.json", "pyproject.toml", "uv.lock"])
def test_manifest_tracks_rules_serializer_tools_corpus_and_environment(tmp_path, relative):
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("before")
    original = evaluation_manifest(tmp_path, {"namespace": "test", "seeds": [1, 2]})
    verify_manifest(tmp_path, original)
    path.write_text("after")
    assert manifest_fingerprint(evaluation_manifest(tmp_path, original["recipe"])) != manifest_fingerprint(original)
    with pytest.raises(ValueError, match="dependency changed"):
        verify_manifest(tmp_path, original)


def test_recipe_changes_are_fingerprinted(tmp_path):
    assert manifest_fingerprint(evaluation_manifest(tmp_path, {"seed": 1})) != manifest_fingerprint(
        evaluation_manifest(tmp_path, {"seed": 2}))


def test_portable_frozen_fixture_has_original_source(tmp_path):
    fixture = Path(__file__).parent / "fixtures/frozen-v11.zip"
    with zipfile.ZipFile(fixture) as archive:
        archive.extractall(tmp_path)
    manifest = json.loads((tmp_path / "snapshot-manifest.json").read_text())
    assert snapshot_fingerprint(tmp_path) == manifest["source_sha256"]
