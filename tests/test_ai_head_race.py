"""The win-only extension must reproduce the full runner's head-place result."""
from __future__ import annotations

import pytest

from guandan.ai.benchmark import run_match
from guandan.ai.strategies.professional import ProfessionalStrategy
from guandan.ai.strategy import make_strategy
from scripts.ai_head_race import run_head_race, summarize


@pytest.mark.parametrize("level", [2, 9, 14])
def test_head_race_matches_full_round_with_identical_rng_and_policies(level: int) -> None:
    def factory(difficulty, player):
        if difficulty == 3:
            return ProfessionalStrategy(iterations=12, time_budget_ms=0)
        return make_strategy(difficulty)

    difficulties = (3, 1, 3, 1)
    full = run_match(1320 + level, level=level, difficulties=difficulties, strategy_factory=factory)
    head = run_head_race(
        1320 + level, level=level, difficulties=difficulties, strategy_factory=factory
    )
    assert full.finished
    assert head["head_determined"]
    assert head["head_player"] == full.finish_order[0]
    assert head["winner_team"] == full.winner_team
    assert head["turns_until_head"] < full.turns


def test_head_summary_rejects_incomplete_or_duplicate_seed_pairs() -> None:
    row = {"seed": 1, "candidate_team": 0, "candidate_won": True, "head_determined": True}
    with pytest.raises(ValueError, match="exactly one leg"):
        summarize([row, row])
    with pytest.raises(ValueError, match="undetermined"):
        summarize([row, {**row, "candidate_team": 1, "head_determined": False}])


def test_head_cli_rejects_prior_from_another_policy(tmp_path, monkeypatch) -> None:
    import json

    from scripts.ai_head_race import main

    prior = tmp_path / "prior.json"
    prior.write_text(json.dumps({
        "candidate_difficulty": 4, "baseline_difficulty": 3,
        "deterministic_search": True, "full_match": False, "policy_version": "previous",
    }))
    monkeypatch.setattr("sys.argv", ["ai_head_race", "--prior", str(prior), "--out", str(tmp_path / "out.json")])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2


def test_head_cli_does_not_mix_clock_and_fixed_work(tmp_path, monkeypatch) -> None:
    from scripts.ai_head_race import main

    monkeypatch.setattr("sys.argv", [
        "ai_head_race", "--clock", "--prior", "unused.json", "--out", str(tmp_path / "out.json"),
    ])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
