from __future__ import annotations

import random
from dataclasses import replace

import pytest

from guandan.ai.candidates import pattern_key
from guandan.ai.config import DecisionBudget, ResearchConfig, SearchConfig, production_configuration
from guandan.ai.strategies.professional import ProfessionalStrategy
from guandan.engine.state import make_initial_state


def test_disabled_research_fields_do_not_change_production_semantics():
    old = {"search": {"iterations": 256}, "policy": {"time_budget_ms": 1000}}
    new = {"search": {"iterations": 256, "action_ranker": False},
           "policy": {"time_budget_ms": 1000, "urgent_blocking": False, "urgent_blocking_weight": 123,
                      "reference_rollout_turns": 0}}
    assert production_configuration(old) == production_configuration(new)
    new["policy"]["urgent_blocking"] = True
    assert production_configuration(old) != production_configuration(new)


def test_typed_and_legacy_configuration_preserve_action_reason_and_rng():
    state = make_initial_state(seed=67000)
    typed = ProfessionalStrategy(search_config=SearchConfig(iterations=24, time_budget_ms=0,
                                                          critical_time_budget_ms=0),
                                 research_config=ResearchConfig(), rng=random.Random(4))
    old = ProfessionalStrategy(iterations=24, time_budget_ms=0, rng=random.Random(4))
    a, b = typed.select_pattern(state, state.turn_index), old.select_pattern(state, state.turn_index)
    assert (pattern_key(a) if a else None) == (pattern_key(b) if b else None)
    assert typed.last_decision_reason == old.last_decision_reason
    assert typed.rng.getstate() == old.rng.getstate()
    typed.iterations = 12
    assert typed.search_config.iterations == 12


def test_mapping_accepts_canonical_and_profile_aliases():
    assert SearchConfig.from_mapping({"top_actions": 3}).max_actions == 3
    assert SearchConfig.from_mapping({"max_actions": 4, "top_actions": 3}).max_actions == 4
    assert SearchConfig(time_budget_ms=0).critical_time_budget_ms == 0
    assert SearchConfig.from_mapping({"time_budget_ms": 0}).critical_time_budget_ms == 0
    with pytest.raises(ValueError, match="require root search"):
        ProfessionalStrategy(search_config=SearchConfig(search_mode="tree"),
                             research_config=ResearchConfig(action_ranker=True))
    with pytest.raises(ValueError, match="style adaptation"):
        ResearchConfig(reference_rollout_turns=8, partner_adaptation=True).validate(SearchConfig())


def test_budget_slices_cannot_extend_parent_or_expired_deadline(monkeypatch):
    monkeypatch.setattr("guandan.ai.config.time.perf_counter", lambda: 10.0)
    budget = DecisionBudget.start(2000)
    assert budget.deadline == 12.0
    assert budget.slice(0.5).deadline == 11.0
    monkeypatch.setattr("guandan.ai.config.time.perf_counter", lambda: 11.9)
    assert budget.slice(1).deadline == 12.0
    assert budget.slice(0.5).deadline <= 12.0
    expired = replace(budget, deadline=9.0)
    assert expired.slice(0.5).deadline == 9.0 and expired.remaining_ms() == 0
    assert DecisionBudget.start(0).slice(0.5).deadline is None


def test_endgame_solver_and_fallback_share_full_parent_budget(monkeypatch):
    from guandan.ai.mcts.endgame_solver import UNSOLVED
    from guandan.ai.strategies.dachangsheng import DaiChangshengStrategy

    monkeypatch.setattr("guandan.ai.config.time.perf_counter", lambda: 10.0)
    deadlines = {}

    def solve(*args, **kwargs):
        deadlines["solver"] = kwargs["deadline"]
        return UNSOLVED

    def fallback(self, *args):
        deadlines["parent"] = self._inherited_budget.deadline
        return None

    monkeypatch.setattr("guandan.ai.strategies.dachangsheng.solve_endgame", solve)
    monkeypatch.setattr(ProfessionalStrategy, "select_pattern", fallback)
    state = make_initial_state(seed=7)
    state.hands = [hand[:2] for hand in state.hands]
    strategy = DaiChangshengStrategy()
    strategy.select_pattern(state, state.turn_index)
    assert deadlines == {"solver": 13.5, "parent": 15.0}
    assert strategy._inherited_budget is None
