"""Four fixed-work equivalence pairs; never count as strength samples."""
import argparse
import json
from pathlib import Path

from scripts.ai_continuation_diagnostic import seed_for
from scripts.ai_continuation_trial import fingerprint, trial_pair
from scripts.fit_action_ranker import snapshot_fingerprint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = args.baseline_root.resolve()
    records = []
    for tier in (3, 4):
        for suite in ("dev", "mixed"):
            config = {"baseline_root": str(root), "baseline_sha": snapshot_fingerprint(root),
                      "suite": suite, "variant": "baseline", "mode": "fixed", "difficulty": tier,
                      "fixed_iterations": 128, "match_states": True, "source_sha256": fingerprint()}
            rows = trial_pair((17, seed_for("packed-off-control", tier + (10 if suite == "mixed" else 0)), config))
            assert rows[0]["result"]["finish_order"] == rows[1]["result"]["finish_order"]
            assert abs(sum(row["gain"] for row in rows) / 2) < 1e-12
            records.append({"config": config, "observations": rows})
            print(tier, suite, "same final ranking; paired gain zero", flush=True)
    args.out.write_text(json.dumps({"purpose": "equivalence, not strength", "pairs": 4, "games": 8,
                                    "passed": True, "records": records}, indent=2) + "\n")


if __name__ == "__main__":
    main()
