"""Enforce coverage floors for persistence and state recovery boundaries."""
import argparse
import json
from pathlib import Path

FLOORS = {
    "src/guandan/storage/": 80.0,
    "src/guandan/ui/session.py": 78.0,
    "src/guandan/engine/replay.py": 72.0,
}


def check(report: dict) -> list[str]:
    failures = []
    for prefix, minimum in FLOORS.items():
        rows = [value["summary"] for name, value in report["files"].items()
                if name.replace("\\", "/").startswith(prefix)]
        total = sum(row["num_statements"] + row["num_branches"] for row in rows)
        covered = sum(row["covered_lines"] + row["covered_branches"] for row in rows)
        percentage = 100 * covered / total if total else 0
        print(f"{prefix}: {percentage:.2f}% (minimum {minimum:.0f}%)")
        if percentage < minimum:
            failures.append(prefix)
    return failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    raise SystemExit(bool(check(json.loads(args.report.read_text()))))
