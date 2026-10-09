"""Serial production clocks for an explicitly selected planner checkout."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import guandan
from scripts import ai_continuation_trial as trial
from scripts.fit_action_ranker import snapshot_fingerprint


def packed_seed(stage, index, round_index=0):
    return int.from_bytes(hashlib.sha256(
        f"packed-planner-v10/{stage}/{index}/{round_index}".encode()).digest()[:8], "big")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--method", choices=("baseline", "refined"), default="baseline")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if not Path(guandan.__file__).resolve().is_relative_to((args.root / "src").resolve()):
        raise RuntimeError("clock imported a different checkout")
    trial.seed_for = packed_seed
    report = trial.clock_check(args.method)
    report.update(source_sha256=snapshot_fingerprint(args.root),
                  harness_sha256=trial.fingerprint(),
                  clock_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  namespace="packed-planner-v10", runtime_root=str(args.root.resolve()))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"method": args.method, "passed": report["passed"], "records": len(report["records"])}))


if __name__ == "__main__":
    main()
