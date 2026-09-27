"""Qt workers with results delivered back to the owner on the event thread."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, Signal

from ..ui.background import run_turn
from ..ui.session import GameSession


class WorkerSignals(QObject):
    completed = Signal(object)


class AIWorker(QRunnable):
    def __init__(self, session: GameSession, *, save_only: bool = False) -> None:
        super().__init__()
        self.session = session
        self.save_only = save_only
        self.signals = WorkerSignals()

    def run(self) -> None:
        self.signals.completed.emit(run_turn(self.session, save_only=self.save_only))


class StorageWorker(QRunnable):
    def __init__(self, operation: Callable[[], object]) -> None:
        super().__init__()
        self.operation = operation
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            self.signals.completed.emit((self.operation(), None))
        except Exception as exc:
            self.signals.completed.emit((None, exc))
