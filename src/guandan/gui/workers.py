"""Qt workers with results delivered back to the owner on the event thread."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, Signal

from ..ui.background import run_turn
from ..ui.session import GameSession


class WorkerSignals(QObject):
    completed = Signal(object)


def _emit_completed(signals: WorkerSignals, payload: object) -> None:
    try:
        signals.completed.emit(payload)
    except RuntimeError as exc:
        # Application shutdown can destroy the Qt signal source after the disk
        # operation finishes. Its owner can no longer receive a completion.
        if "deleted" not in str(exc):
            raise


class AIWorker(QRunnable):
    def __init__(self, session: GameSession, *, save_only: bool = False) -> None:
        super().__init__()
        self.session = session
        self.save_only = save_only
        self.signals = WorkerSignals()

    def run(self) -> None:
        _emit_completed(self.signals, run_turn(self.session, save_only=self.save_only))


class StorageWorker(QRunnable):
    def __init__(self, operation: Callable[[], object]) -> None:
        super().__init__()
        self.operation = operation
        self.signals = WorkerSignals()

    def run(self) -> None:
        payload: tuple[object, Exception | None]
        try:
            payload = self.operation(), None
        except Exception as exc:
            payload = None, exc
        _emit_completed(self.signals, payload)
