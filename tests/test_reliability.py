"""Real persistence and frontend boundary regressions from the September review."""
from __future__ import annotations

import copy
import json
import os
import random
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from guandan.ai import make_strategy, play_or_pass
from guandan.engine.state import make_initial_state
from guandan.storage import load_game, load_profile, record_round_statistics
from guandan.storage.profile import DEFAULT_PROFILE
from guandan.ui.background import TurnResult
from guandan.ui.session import GameSession


@pytest.fixture
def isolated_storage(tmp_path):
    with patch("guandan.storage.paths.get_storage_dir", return_value=tmp_path):
        yield tmp_path


def finished_round():
    state = make_initial_state(level=2, first_player=0, seed=5)
    strategy = make_strategy(0)
    rng = random.Random(5)
    for _ in range(1000):
        if state.finished:
            return state
        play_or_pass(state, state.current_player(), strategy, rng)
    raise AssertionError("round did not finish")


@pytest.mark.parametrize("started", [False, True])
@pytest.mark.parametrize("human_role", ["head", "tail"])
def test_pending_round_survives_disk_restore(isolated_storage, started, human_role):
    state = finished_round()
    human = state.finish_order[0] if human_role == "head" else next(
        p for p in range(4) if p not in state.finish_order
    )
    session = GameSession(difficulty=0, existing_state=state, human=human, game_id="previous")
    with patch("guandan.ui.session.random.randint", return_value=9):
        assert session.prepare_next_game().ok
    if started:
        assert session.begin_next_game_tribute().ok
    session.save_unfinished()
    payload = load_game()
    assert payload is not None
    restored = GameSession.from_savegame(payload)
    assert restored.is_next_game_pending()
    assert restored.display_state() == session.display_state()
    assert restored.pending_next_game_choice() == session.pending_next_game_choice()
    assert restored.resumable_round()[1:] == session.resumable_round()[1:]
    for target in (session, restored):
        target.begin_next_game_tribute()
        choice = target.pending_next_game_choice()
        assert target.finalize_next_game(choice.cards[0] if choice else None).ok
    assert restored.state == session.state
    restored.save_unfinished()
    continued = GameSession.from_savegame(load_game())
    assert not continued.is_next_game_pending()
    assert continued.state == restored.state


def test_gui_save_uses_pending_round(isolated_storage):
    pytest.importorskip("PySide6")
    from guandan.gui.window import GuandanMainWindow

    session = GameSession(difficulty=0, existing_state=finished_round())
    assert session.prepare_next_game().ok
    window = SimpleNamespace(game_page=SimpleNamespace(session=session, is_ai_running=lambda: False))
    assert GuandanMainWindow.save_current_game(window)
    assert load_game() is not None


def test_stale_session_cannot_overwrite_newer_progress(isolated_storage):
    from guandan.storage.savegame import SaveConflictError

    original = GameSession(difficulty=0, seed=9)
    original.save_unfinished()
    other = GameSession.from_savegame(load_game())
    original.save_unfinished()
    current = (isolated_storage / "savegame.json").read_bytes()
    with pytest.raises(SaveConflictError) as error:
        other.save_unfinished()
    assert (isolated_storage / "savegame.json").read_bytes() == current
    assert error.value.recovery_path.exists()
    assert json.loads(error.value.recovery_path.read_text())["game_id"] == other.game_id


def test_two_new_sessions_keep_both_games_on_conflict(isolated_storage):
    from guandan.storage.savegame import SaveConflictError

    first = GameSession(difficulty=0, seed=9)
    second = GameSession(difficulty=0, seed=10)
    first.save_unfinished()
    with pytest.raises(SaveConflictError):
        second.save_unfinished()
    assert load_game()["game_id"] == first.game_id
    assert len(list((isolated_storage / "recovery").glob("*.json"))) == 1


def test_stale_delete_keeps_newer_revision(isolated_storage):
    from guandan.storage import delete_savegame

    session = GameSession(difficulty=0, seed=9)
    session.save_unfinished()
    stale = load_game()
    session.save_unfinished()
    assert not delete_savegame(expected_game_id=stale["game_id"], expected_revision=stale["revision"])
    assert load_game()["revision"] == stale["revision"] + 1


def test_finished_conflict_keeps_error_type_and_does_not_settle(isolated_storage):
    from guandan.storage.savegame import SaveConflictError

    owner = GameSession(difficulty=0, seed=9)
    owner.save_unfinished()
    stale = GameSession(difficulty=0, existing_state=finished_round())
    with pytest.raises(SaveConflictError):
        stale.save_current()
    assert not list((isolated_storage / "history").glob("*.json"))
    assert load_game()["game_id"] == owner.game_id


@pytest.mark.parametrize("bucket", [None, {}, {"rounds": "4", "heads": "2"}])
def test_nested_profile_damage_keeps_valid_data_and_backup(isolated_storage, bucket):
    profile = copy.deepcopy(DEFAULT_PROFILE)
    profile["statistics"]["total_rounds"] = 123
    profile["statistics"]["by_difficulty_rounds"] = {"2": bucket}
    path = isolated_storage / "profile.json"
    original = json.dumps(profile)
    path.write_text(original)
    restored = load_profile()
    record_round_statistics(restored, got_head=True, difficulty=2)
    assert restored["statistics"]["total_rounds"] == 124
    assert restored["statistics"]["by_difficulty_rounds"]["2"]["heads"] >= 1
    assert any(p.read_text() == original for p in isolated_storage.glob("profile.json.corrupt-*"))


def test_gui_worker_exception_stops_automatic_retries():
    pytest.importorskip("PySide6")
    from guandan.gui.window import GamePage

    page = SimpleNamespace(
        session=SimpleNamespace(last_action=""), _ai_running=True,
        _ai_worker=object(), refresh=Mock(), schedule_ai=Mock(),
    )
    page._main_window = SimpleNamespace(stack=SimpleNamespace(currentWidget=lambda: page), _leave_requested=None)
    GamePage._ai_finished(page, TurnResult(error=RuntimeError("failed search"), stage="decision"))
    page.schedule_ai.assert_not_called()


def test_storage_retry_does_not_repeat_committed_action():
    from guandan.ui.background import run_turn
    from guandan.ui.session import SessionAction

    session = GameSession(difficulty=0)
    with patch.object(session, "step_ai", return_value=SessionAction(True, "出牌")) as step, patch.object(
        session, "autosave_after_ai", side_effect=[False, True]
    ):
        failed = run_turn(session)
        assert failed.stage == "storage"
        assert run_turn(session, save_only=True).error is None
        assert step.call_count == 1


def test_conflict_recovery_preserves_the_replaced_save(isolated_storage):
    from guandan.storage.savegame import SaveConflictError, activate_recovery, list_recovery_games

    first = GameSession(difficulty=0, seed=9)
    second = GameSession(difficulty=0, seed=10)
    first.save_unfinished()
    with pytest.raises(SaveConflictError):
        second.save_unfinished()
    activate_recovery(list_recovery_games()[0]["name"])
    assert load_game()["game_id"] == second.game_id
    assert first.game_id in {entry["game_id"] for entry in list_recovery_games()}
    restored = GameSession.from_savegame(load_game())
    restored.save_unfinished()


def test_two_processes_cannot_commit_the_same_revision(isolated_storage):
    GameSession(difficulty=0, seed=9).save_unfinished()
    script = '''
import sys
from guandan.ui.session import GameSession
from guandan.storage import load_game
from guandan.storage.savegame import SaveConflictError
session = GameSession.from_savegame(load_game())
print("ready", flush=True)
sys.stdin.readline()
try:
    session.save_unfinished()
    print("saved")
except SaveConflictError:
    print("conflict")
'''
    processes = [subprocess.Popen(
        [sys.executable, "-c", script], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
        env={**os.environ, "GUANDAN_DATA_DIR": str(isolated_storage)},
    ) for _ in range(2)]
    try:
        for process in processes:
            assert process.stdout.readline().strip() == "ready"
        for process in processes:
            process.stdin.write("go\n")
            process.stdin.flush()
        results = [process.communicate(timeout=15) for process in processes]
        assert all(process.returncode == 0 for process in processes), results
        assert sorted(out.strip() for out, _ in results) == ["conflict", "saved"]
        assert load_game()["revision"] == 2
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()


def test_statistics_rebuild_previews_and_preserves_profile(isolated_storage):
    from guandan.storage import update_profile
    from guandan.storage.maintenance import rebuild_statistics

    session = GameSession(difficulty=0, existing_state=finished_round())
    assert session.save_finished_if_needed()
    update_profile(lambda profile: profile["statistics"].update(total_rounds=999))
    assert rebuild_statistics()["statistics"]["total_rounds"] == 1
    assert load_profile()["statistics"]["total_rounds"] == 999
    result = rebuild_statistics(apply=True)
    assert result["backup"]
    assert load_profile()["statistics"]["total_rounds"] == 1
    (isolated_storage / "history" / "broken.json").write_text("{broken")
    with pytest.raises(ValueError, match="损坏"):
        rebuild_statistics(apply=True)
    assert load_profile()["statistics"]["total_rounds"] == 1
