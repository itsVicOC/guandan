"""Independent full-deal calibration audit after head place is determined."""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
from pathlib import Path

from guandan.ai.match_value import OUTCOMES, outcome_value
from guandan.ai.mcts.search import _evaluate_result
from scripts import fit_match_value as fitting


def collect(job):
    rows = []
    apply = fitting._apply_action

    def observe(state, player, pattern):
        result = apply(state, player, pattern)
        if state.finish_order and not state.finished and (state.finish_order[0] + 2) % 4 not in state.finish_order:
            head = state.finish_order[0] % 2
            rows.append({"prediction": _evaluate_result(state, 0),
                         "payoffs": [outcome_value(state, 0, head, p) for p in (2, 3, 4)],
                         "phase": "head_only" if len(state.finish_order) == 1 else "second_fixed"})
        return result

    # Instrument the legal proxy collector inside this private worker; the
    # evaluator does not alter cards, RNG or subsequent proxy choices.
    fitting._apply_action = observe
    try:
        deal = fitting.collect(job)
    finally:
        fitting._apply_action = apply
    place = OUTCOMES[deal["relative_outcome"]][1]
    for row in rows:
        row["actual_utility"] = row.pop("payoffs")[place - 2]
    return {"seed": job[1], "levels": deal["levels"], "a_failures": deal["a_failures"], "positions": rows}


def summarize(rows):
    return {"positions": len(rows),
            "mean_error": sum(r["prediction"] - r["actual_utility"] for r in rows) / len(rows),
            "mean_squared_error": sum((r["prediction"] - r["actual_utility"]) ** 2 for r in rows) / len(rows),
            "mean_absolute_error": sum(abs(r["prediction"] - r["actual_utility"]) for r in rows) / len(rows)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    with mp.get_context("spawn").Pool(args.workers) as pool:
        deals = list(pool.imap(collect, enumerate(range(127000, 127192))))
    rows = [row for deal in deals for row in deal["positions"]]
    report = {"seed_start": 127000, "deals": 192, "training": False,
              "objective": "completed ranking mapped to the common empirical continuation table",
              "note": "Correlated positions within whole deals; diagnostic calibration, not a strength gate.",
              "summary": summarize(rows),
              "by_phase": {phase: summarize([r for r in rows if r["phase"] == phase])
                           for phase in ("head_only", "second_fixed")},
              "bins": [{"range": [i / 10, (i + 1) / 10], "positions": len(part),
                        "mean_prediction": sum(r["prediction"] for r in part) / len(part),
                        "mean_actual": sum(r["actual_utility"] for r in part) / len(part)}
                       for i in range(10) if (part := [r for r in rows if i <= r["prediction"] * 10 < i + 1
                                                       or (i == 9 and r["prediction"] == 1.0)])],
              "observations": deals}
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["summary"]))


if __name__ == "__main__":
    main()
