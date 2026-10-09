"""Actual frontend rounds must survive tribute, save/load and strict replay."""
from __future__ import annotations

import json
import random
from dataclasses import replace

import pytest

from guandan.ai import make_strategy, play_or_pass
from guandan.engine.events import TributeResisted
from guandan.engine.replay import replay_events
from guandan.engine.rounds import deal_next_round, set_dealt_round_starter
from guandan.engine.rules.tributes import apply_tribute_flow
from guandan.engine.state import make_initial_state
from guandan.storage import load_game, restore_game_state
from guandan.ui.session import GameSession


def finish(state):
    policy, rng = make_strategy(0), random.Random(1)
    for _ in range(2000):
        if state.finished:
            assert replay_events(state.history, ruleset_version=state.ruleset_version) == state
            return state
        play_or_pass(state, state.current_player(), policy, rng)
    raise AssertionError("round did not finish")


def predecessor(levels, counts, ruleset=3):
    for seed in range(1, 100):
        state = finish(make_initial_state(level=14, seed=seed, team_levels=levels,
                                          a_failure_counts=counts, ruleset_version=ruleset))
        if not state.match_finished:
            return state
    raise AssertionError("no non-final A round")


@pytest.mark.parametrize("levels,counts", [([14, 5], [0, 0]), ([14, 5], [1, 0]),
                                          ([5, 14], [0, 1]), ([14, 14], [0, 1])])
@pytest.mark.parametrize("resist", [False, True])
def test_a_counts_survive_pending_tribute_resume_and_played_round(levels, counts, resist, monkeypatch):
    previous = predecessor(levels, counts)
    session = GameSession(difficulty=0, existing_state=previous)
    for seed in range(1, 1000):
        next_state = deal_next_round(previous, seed=seed, first_player=0)
        tribute = apply_tribute_flow(previous.finish_order, next_state.hands,
                                     level=next_state.level, wild_card=next_state.wild_card)
        if any(isinstance(event, TributeResisted) for event in tribute.events) == resist:
            break
    else:
        raise AssertionError("no required tribute fixture")
    monkeypatch.setattr("guandan.ui.session.random.randint", lambda a, b: seed)
    assert session.prepare_next_game().ok
    assert session.begin_next_game_tribute().ok
    session.save_current()
    resumed = GameSession.from_savegame(load_game())
    assert resumed.match_id == session.match_id
    assert resumed.finalize_next_game().ok
    assert resumed.state.a_failure_counts == previous.a_failure_counts
    assert resumed.state.history[0].a_failure_counts == tuple(previous.a_failure_counts)
    resumed.save_current()
    assert restore_game_state(load_game()) == resumed.state
    finish(resumed.state)
    assert resumed.save_finished_if_needed()


@pytest.mark.parametrize("finished", [False, True])
def test_existing_dropped_counter_save_is_backed_up_and_repaired(tmp_path, monkeypatch, finished):
    monkeypatch.setenv("GUANDAN_DATA_DIR", str(tmp_path))
    session = GameSession(difficulty=0, existing_state=predecessor([14, 5], [1, 0]))
    assert session.start_next_game().ok
    if finished:
        finish(session.state)
    session.state.history[0] = replace(session.state.history[0], a_failure_counts=(0, 0))
    # Write the affected build's checkpoint, including a finished checkpoint.
    from guandan.storage import save_game

    save_game(session.state, session.game_id, 0, [None, 0, 0, 0], session.seed,
              match_id=session.match_id, round_index=2)
    path = tmp_path / "savegame.json"
    original = path.read_bytes()
    restored = load_game()
    assert restored is not None and restored["revision"] == 2
    assert restore_game_state(restored) == replay_events(restored["events"])
    assert next(tmp_path.glob("savegame.json.a-counter-backup-*")).read_bytes() == original
    assert load_game()["revision"] == 2  # Repair is applied once.


def test_counter_repair_does_not_accept_unrelated_snapshot_damage(tmp_path, monkeypatch):
    monkeypatch.setenv("GUANDAN_DATA_DIR", str(tmp_path))
    session = GameSession(difficulty=0, existing_state=predecessor([14, 5], [1, 0]))
    assert session.start_next_game().ok
    session.save_current()
    path = tmp_path / "savegame.json"
    payload = json.loads(path.read_text())
    payload["events"][0]["a_failure_counts"] = [0, 0]
    payload["state"]["hands"][0][0]["rank"] = 99
    path.write_text(json.dumps(payload))
    original = path.read_bytes()
    assert load_game() is None
    assert path.read_bytes() == original
    assert not list(tmp_path.glob("savegame.json.a-counter-backup-*"))


def test_shared_session_carries_three_a_failures_through_saves_and_reset(monkeypatch):
    state = finish(make_initial_state(level=14, seed=1, team_levels=[14, 5]))
    assert state.a_failure_counts == [1, 0]
    session = GameSession(difficulty=0, existing_state=state)
    match_id = session.match_id
    for expected_count, expected_level in ((2, 14), (0, 2)):
        previous = session.state
        for seed in range(1, 100):
            candidate = deal_next_round(previous, seed=seed, first_player=0)
            tribute = apply_tribute_flow(previous.finish_order, candidate.hands,
                                         level=candidate.level, wild_card=candidate.wild_card)
            candidate.history.extend(tribute.events)
            set_dealt_round_starter(candidate, tribute.first_player)
            finish(candidate)
            if not candidate.match_finished and candidate.a_failure_counts[0] == expected_count:
                break
        else:
            raise AssertionError("no next failed A fixture")
        monkeypatch.setattr("guandan.ui.session.random.randint", lambda a, b, chosen=seed: chosen)
        assert session.prepare_next_game().ok
        assert session.begin_next_game_tribute().ok
        session.save_current()
        session = GameSession.from_savegame(load_game())
        assert session.finalize_next_game().ok
        session.save_current()
        assert restore_game_state(load_game()) == session.state
        finish(session.state)
        assert session.state.a_failure_counts == [expected_count, 0]
        assert session.state.team_levels_final[0] == expected_level
        assert session.match_id == match_id
        assert session.save_finished_if_needed()


@pytest.mark.parametrize("version", [1, 2])
def test_legacy_rule_rounds_resume_with_original_a_settlement(version):
    state = finish(make_initial_state(level=14, seed=1, team_levels=[14, 5], ruleset_version=version))
    assert state.team_levels_final[0] == 2 and state.a_failure_counts == [0, 0]
    session = GameSession(difficulty=0, existing_state=state)
    assert session.start_next_game().ok
    session.save_current()
    restored = restore_game_state(load_game())
    assert restored == session.state and restored.ruleset_version == version
    assert restored.team_levels[0] == 2
