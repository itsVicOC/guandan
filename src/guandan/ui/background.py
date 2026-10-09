"""Frontend-neutral background results and retry semantics."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from .session import GameSession

logger = logging.getLogger(__name__)
FailureStage = Literal["decision", "storage"]


@dataclass(frozen=True)
class TurnResult:
    messages: tuple[str, ...] = ()
    error: Exception | None = None
    stage: FailureStage | None = None


@dataclass
class TurnController:
    """One frontend turn at a time; leaving waits for committed work to finish."""

    phase: Literal["idle", "thinking", "saving", "failed", "leaving"] = "idle"
    failure: TurnResult | None = None
    leave_requested: bool = False

    def _rest(self) -> None:
        self.phase = "leaving" if self.leave_requested else "failed" if self.failure else "idle"

    def set_running(self, active: bool) -> None:
        if active:
            if self.phase == "saving" or self.leave_requested:
                raise RuntimeError("cannot start a turn while saving or leaving")
            self.phase = "thinking"
        elif self.phase == "thinking":
            self._rest()

    def set_saving(self, active: bool) -> None:
        if active:
            if self.phase == "thinking":
                raise RuntimeError("cannot save while a turn is running")
            self.phase = "saving"
        elif self.phase == "saving":
            self._rest()

    def set_failure(self, result: TurnResult | None) -> None:
        self.failure = result
        if self.phase not in ("thinking", "saving"):
            self._rest()

    def request_leave(self, active: bool) -> None:
        self.leave_requested = active
        if self.phase not in ("thinking", "saving"):
            self._rest()

    @property
    def can_schedule(self) -> bool:
        return self.phase == "idle" and not self.leave_requested


class TurnStateOwner:
    """Compatibility properties shared by Qt and Textual event handlers."""

    _turn: TurnController

    @property
    def _ai_running(self) -> bool:
        return self._turn.phase == "thinking"

    @_ai_running.setter
    def _ai_running(self, active: bool) -> None:
        self._turn.set_running(active)

    @property
    def _saving(self) -> bool:
        return self._turn.phase == "saving"

    @_saving.setter
    def _saving(self, active: bool) -> None:
        self._turn.set_saving(active)

    @property
    def _failed_turn(self) -> TurnResult | None:
        return self._turn.failure

    @_failed_turn.setter
    def _failed_turn(self, result: TurnResult | None) -> None:
        self._turn.set_failure(result)

    @property
    def _leave_requested(self) -> bool:
        return self._turn.leave_requested

    @_leave_requested.setter
    def _leave_requested(self, active: bool) -> None:
        self._turn.request_leave(active)


@dataclass
class OperationGate:
    """Discard a completion from an older request or a detached page."""

    generation: int = 0

    def begin(self) -> int:
        self.generation += 1
        return self.generation

    def accepts(self, token: int) -> bool:
        return token == self.generation

    def invalidate(self) -> None:
        self.generation += 1


def run_turn(session: GameSession, *, save_only: bool = False) -> TurnResult:
    """Retry storage without repeating an action already committed to the engine."""
    stage: FailureStage = "storage" if save_only else "decision"
    messages: tuple[str, ...] = ()
    try:
        if not save_only:
            action = session.step_ai()
            messages = (action.message,)
            if not action.ok:
                return TurnResult(messages, RuntimeError(action.message), "decision")
        stage = "storage"
        if not session.autosave_after_ai():
            raise OSError(session.last_action)
        return TurnResult(messages)
    except Exception as exc:
        logger.exception("Background %s failed: game=%s events=%s", stage,
                         session.game_id, len(session.require_state().history))
        return TurnResult(messages, exc, stage)
