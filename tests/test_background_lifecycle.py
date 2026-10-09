from __future__ import annotations

import pytest

from guandan.ui.background import OperationGate, TurnController, TurnResult


def test_leave_waits_for_turn_then_save_without_allowing_new_turn():
    control = TurnController()
    assert control.can_schedule
    control.set_running(True)
    control.request_leave(True)
    assert control.phase == "thinking" and not control.can_schedule
    with pytest.raises(RuntimeError, match="turn is running"):
        control.set_saving(True)
    control.set_running(False)
    assert control.phase == "leaving"
    with pytest.raises(RuntimeError, match="saving or leaving"):
        control.set_running(True)
    control.set_saving(True)
    assert control.phase == "saving"
    control.set_saving(False)
    control.request_leave(False)
    assert control.can_schedule


def test_failure_blocks_scheduling_until_retry_and_survives_leave_save_failure():
    control = TurnController()
    control.set_running(True)
    control.set_running(False)
    failure = TurnResult(error=OSError("disk full"), stage="storage")
    control.set_failure(failure)
    assert control.phase == "failed" and not control.can_schedule
    control.request_leave(True)
    control.set_saving(True)
    control.set_saving(False)
    control.request_leave(False)
    assert control.phase == "failed" and control.failure.stage == "storage"
    control.set_failure(None)
    control.set_running(True)
    assert control.phase == "thinking"


def test_old_request_and_detached_page_completions_are_discarded():
    gate = OperationGate()
    first = gate.begin()
    second = gate.begin()
    assert not gate.accepts(first) and gate.accepts(second)
    gate.invalidate()
    assert not gate.accepts(second)
