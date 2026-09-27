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
