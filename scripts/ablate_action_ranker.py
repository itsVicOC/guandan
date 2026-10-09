"""Diagnostic-only refits on the frozen splits; never select a deployment model."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from guandan.ai.action_ranker import FEATURE_NAMES, MODEL_PATH, load_model
from scripts.ai_team_trial import source_fingerprint
from scripts.fit_action_ranker import fit_weights, pair_examples, ranking_metrics, read_labels


def ablate(folder: Path) -> dict:
    import numpy as np

    recipe, deals = read_labels(folder)
    payload = json.loads(MODEL_PATH.read_text())
    model = load_model()
    coefficient = payload["meta"]["regularization"]
    train = [row for row in deals if row["split"] == "train"]
    diagnostic = [row for row in deals if row["split"] == "diagnostic"]
    x, targets = pair_examples(train)
    structure = {"singletons", "pairs", "triples", "bomb_groups", "broken_pairs",
                 "broken_triples", "broken_bombs", "low_singletons", "control_remaining",
                 "wild_remaining", "suited_links", "lost_suited_links"}
    masks = {
        "without_public_interactions": ["*" not in name for name in FEATURE_NAMES],
        "without_played_suit_counts": [not name.startswith("used_suit_") for name in FEATURE_NAMES],
        "without_residual_structure": [name.split("*")[0] not in structure for name in FEATURE_NAMES],
    }
    results = {"full_model": ranking_metrics(diagnostic, model.weights)}
    for name, mask in masks.items():
        included = np.asarray(mask)
        weights = np.zeros(len(FEATURE_NAMES))
        weights[included] = fit_weights(x[:, included], targets, coefficient)
        results[name] = {"retained_features": int(sum(mask)), **ranking_metrics(diagnostic, weights)}
        print(f"{name}: diagnostic regret {results[name]['model_regret']:.6f}", flush=True)
    report = {"recipe": recipe, "source_sha256": source_fingerprint(), "model_sha256": model.sha256,
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "regularization": coefficient, "results": results,
              "interpretation": "Refits reuse only training deals and the primary tuning-selected L2. Diagnostic results are descriptive; they never select weights or alter acceptance seeds."}
    (folder / "ablation.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, default=Path("benchmarks/action-ranker-v1"))
    args = parser.parse_args()
    ablate(args.folder)


if __name__ == "__main__":
    main()
