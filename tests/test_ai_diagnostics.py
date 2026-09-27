"""Ensure gates reject incompatible experiments and deliberate regressions."""
import copy

from guandan.ai.diagnostics import gate_failures


def report(mode="fixed"):
    return {"compatibility": {"mode": mode, "policy": "v1"}, "records": [{
        "case": "opening", "difficulty": 4, "player": 0, "action": ["pass"],
        "reason": "search", "budget_ms": 2000, "elapsed_seconds": 2.01,
    }]}


def test_changed_action_fails_fixed_gate():
    baseline = report()
    changed = copy.deepcopy(baseline)
    changed["records"][0]["action"] = ["different"]
    assert gate_failures(changed, baseline)
    assert not gate_failures(baseline, baseline)


def test_changed_policy_and_clock_data_cannot_reuse_fixed_baseline():
    baseline = report()
    changed = copy.deepcopy(baseline)
    changed["compatibility"]["policy"] = "v2"
    assert gate_failures(changed, baseline)
    assert gate_failures(report("clock"), baseline)


def test_clock_gate_uses_the_budget_of_each_decision():
    production = report("clock")
    assert not gate_failures(production)
    production["records"][0]["elapsed_seconds"] = 3.0
    assert gate_failures(production)
