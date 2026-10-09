"""Index, verify and export research evidence without deleting original data."""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from collections import Counter
from pathlib import Path


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def research_index(root: Path) -> dict:
    records = []
    for path in sorted((root / "benchmarks").rglob("*")):
        relative = path.relative_to(root).as_posix()
        if not path.is_file() or relative == "benchmarks/research-index.json" or any(
            part in {"archives", "production", "__pycache__"} for part in path.relative_to(root / "benchmarks").parts
        ):
            continue
        kind = "snapshot" if path.suffix == ".zip" else "raw" if path.suffix in {"gz", ".gz", ".jsonl"} else "report"
        records.append({"path": relative, "kind": kind, "bytes": path.stat().st_size, "sha256": file_hash(path)})
    return {"schema": 1, "scope": "historical research; production baselines excluded",
            "files": records, "total_bytes": sum(record["bytes"] for record in records),
            "counts": dict(Counter(record["kind"] for record in records))}


def verified_path(root: Path, record: dict) -> Path:
    path = (root / record["path"]).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file() or file_hash(path) != record["sha256"]:
        raise ValueError(f"research evidence changed or missing: {record['path']}")
    return path


def verify_index(root: Path, index: dict) -> None:
    for record in index["files"]:
        verified_path(root, record)


def export_bundle(root: Path, index: dict, output: Path) -> None:
    verify_index(root, index)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Never replace an existing research attachment accidentally.
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for record in index["files"]:
            archive.write(verified_path(root, record), record["path"])
        archive.writestr("research-index.json", json.dumps(index, indent=2) + "\n")
    with zipfile.ZipFile(output) as archive:
        for record in index["files"]:
            if hashlib.sha256(archive.read(record["path"])).hexdigest() != record["sha256"]:
                raise ValueError(f"archive verification failed: {record['path']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("index", "verify", "export"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--index", type=Path, default=Path("benchmarks/research-index.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    index_path = args.index if args.index.is_absolute() else args.root / args.index
    if args.action == "index":
        index = research_index(args.root)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n")
    else:
        index = json.loads(index_path.read_text())
        if args.action == "verify":
            verify_index(args.root, index)
        else:
            if args.output is None:
                parser.error("export requires --output")
            export_bundle(args.root, index, args.output)
    print(f"{args.action}: {len(index['files'])} files, {index['total_bytes']} bytes")


if __name__ == "__main__":
    main()
