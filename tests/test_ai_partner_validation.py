"""Acceptance recipes must not promote an overall gain hiding weak partners."""

from __future__ import annotations

import pytest

from scripts.ai_partner_validation import DEV, FULL, HOLDOUT, clock_tier_passed, paired_gate
from scripts.ai_team_trial import candidate


def test_predeclared_seed_blocks_are_disjoint():
    blocks = [
        range(start, start + count)
        for starts, count in ((DEV.values(), 32), (HOLDOUT.values(), 240))
        for group in starts
        for start in group
    ]
    blocks.extend(range(start, start + 24) for start in FULL.values())
    flattened = [seed for block in blocks for seed in block]
    assert len(flattened) == len(set(flattened))


@pytest.mark.parametrize(
    "team_pass,mixed_pass,weak_gain,allowed",
    [
        (True, True, 0.01, True),
        (False, True, 0.01, False),
        (True, False, 0.01, False),
        (True, True, -0.01, False),
    ],
)
def test_both_intervals_and_each_companion_must_pass(team_pass, mixed_pass, weak_gain, allowed):
    team = {"pairs": 240, "gain_confidence_95": [0.01 if team_pass else -0.01, 0.1]}
    mixed = {
        "pairs": 240,
        "gain_confidence_95": [0.01 if mixed_pass else -0.01, 0.1],
        "by_companion": {
            str(s): {"mean_paired_gain": weak_gain if s == 0 else 0.1} for s in range(3)
        },
    }
    assert paired_gate(team, mixed) == allowed
    mixed["by_companion"].pop("0")
    assert not paired_gate(team, mixed)


def test_incomplete_holdout_cannot_pass_and_clock_gates_are_per_tier():
    team = {"pairs": 239, "gain_confidence_95": [0.01, 0.1]}
    mixed = {
        "pairs": 240,
        "gain_confidence_95": [0.01, 0.1],
        "by_companion": {str(s): {"mean_paired_gain": 0.1} for s in range(3)},
    }
    assert not paired_gate(team, mixed)
    clock = {
        "records": [{"tier": tier, "passed": tier == 4} for tier in (3, 4)],
        "consecutive_actions": [
            {"tier": tier, "passed": True} for tier in (3, 4) for _ in range(3)
        ],
    }
    assert not clock_tier_passed(clock, 3) and clock_tier_passed(clock, 4)


@pytest.mark.parametrize("tier", [3, 4])
@pytest.mark.parametrize(
    "variant,adaptation,chain",
    [
        ("adaptive", True, False),
        ("chain", False, True),
        ("partner_combined", True, True),
    ],
)
def test_variants_are_isolated_and_use_the_requested_work(tier, variant, adaptation, chain):
    policy = candidate(tier, variant, "fixed", 256 if tier == 3 else 768)
    assert policy.partner_adaptation == adaptation and policy.response_chain == chain
    assert policy.iterations == (256 if tier == 3 else 768)
    assert policy.time_budget_ms == 0
    assert not policy.team_tactics and not policy.lead_chain
    assert not policy.heterogeneous_rollouts and not policy.partner_bomb_guard


def test_production_budget_is_not_replaced_by_development_work():
    assert candidate(3, "adaptive", "clock", 128).time_budget_ms == 1000
    policy = candidate(4, "partner_combined", "clock", 128)
    assert (
        policy.iterations == 768
        and policy.time_budget_ms == 2000
        and policy.critical_time_budget_ms == 5000
    )
