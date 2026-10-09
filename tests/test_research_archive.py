import json
import zipfile

import pytest

from scripts.ai_research_archive import export_bundle, research_index, verify_index


def test_export_preserves_failed_raw_evidence_and_checks_every_file(tmp_path):
    raw = tmp_path / "benchmarks/failed-v1/raw.jsonl"
    raw.parent.mkdir(parents=True)
    raw.write_text('{"gain": -1}\n')
    production = tmp_path / "benchmarks/production/baseline.json"
    production.parent.mkdir()
    production.write_text("{}")
    index = research_index(tmp_path)
    assert len(index["files"]) == 1 and index["counts"] == {"raw": 1}
    bundle = tmp_path / "benchmarks/archives/study.zip"
    export_bundle(tmp_path, index, bundle)
    assert research_index(tmp_path) == index  # Exports never recursively enter the index.
    assert raw.read_text() == '{"gain": -1}\n'
    with zipfile.ZipFile(bundle) as archive:
        assert archive.read("benchmarks/failed-v1/raw.jsonl") == raw.read_bytes()
        assert json.loads(archive.read("research-index.json")) == index
    raw.write_text("changed")
    with pytest.raises(ValueError, match="evidence changed"):
        verify_index(tmp_path, index)


def test_export_refuses_overwrite_and_paths_outside_bundle_root(tmp_path):
    index = {"files": []}
    bundle = tmp_path / "study.zip"
    export_bundle(tmp_path, index, bundle)
    with pytest.raises(FileExistsError):
        export_bundle(tmp_path, index, bundle)
    with pytest.raises(ValueError, match="evidence changed"):
        verify_index(tmp_path, {"files": [{"path": "../outside", "sha256": "bad"}]})
