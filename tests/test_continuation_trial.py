"""Independent experiment lineage and promotion gates."""
from __future__ import annotations

from scripts.ai_continuation_diagnostic import seed_for
from scripts.ai_continuation_trial import COUNTS, development_gate, tier_clock_passed
from scripts.fit_action_ranker import derived_seed


def test_v9_seed_namespaces_do_not_reuse_v8_or_other_stages():
    seeds = [seed_for(f"{stage}-{tier}", index) for stage, count in COUNTS.items()
             for tier in (3, 4) for index in range(count)]
    assert len(seeds) == len(set(seeds))
    old = {derived_seed(f"{stage}-{tier}", index) for stage, count in COUNTS.items()
           for tier in (3, 4) for index in range(count)}
    assert not old.intersection(seeds)
    full = [seed_for("full-deal", seed_for(f"full-{tier}", index), offset)
            for tier in (3, 4) for index in range(48) for offset in range(64)]
    assert len(full) == len(set(full))
    assert not set(full).intersection(seeds)


def test_development_needs_both_payoffs_and_all_serial_clocks():
    clock = {"records": [{"tier": tier, "passed": True} for tier in (3, 4) for _ in range(21)]}
    positive = {"pairs": 32, "mean_paired_gain": 0.01}
    assert development_gate(positive, positive, clock, 3)
    assert not development_gate(positive, {**positive, "mean_paired_gain": 0}, clock, 3)
    clock["records"][0]["passed"] = False
    assert not development_gate(positive, positive, clock, 3)
    assert tier_clock_passed(clock, 4)
    assert not tier_clock_passed({"records": []}, 4)


def test_v11_does_not_reuse_cancelled_v9_or_v8_seeds():
    from scripts.ai_budget_refinement_trial import seed_for as capped_seed

    inputs = [(f"{stage}-{tier}", index) for stage, count in COUNTS.items()
              for tier in (3, 4) for index in range(count)]
    current = {capped_seed(stage, index) for stage, index in inputs}
    previous = {seed_for(stage, index) for stage, index in inputs}
    previous.update(derived_seed(stage, index) for stage, index in inputs)
    assert len(current) == len(inputs) and not current.intersection(previous)
    full = [capped_seed("full-deal", capped_seed(f"full-{tier}", index), offset)
            for tier in (3, 4) for index in range(48) for offset in range(64)]
    assert len(full) == len(set(full)) and not current.intersection(full)
