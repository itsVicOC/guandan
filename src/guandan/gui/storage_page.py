"""Bounded UI lifetime for disk operations that may wait on a storage lock."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QWidget

from ..ui.background import OperationGate
from .workers import StorageWorker


class StoragePage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._operation_gate = OperationGate()
        self._storage_worker: StorageWorker | None = None
        self._storage_completion: Callable[[object], None] | None = None
        self._storage_busy = False

    def _start_storage(self, operation: Callable[[], object], completion: Callable[[object], None]) -> bool:
        if self._storage_busy:
            return False
        self._storage_busy = True
        token = self._operation_gate.begin()
        self._storage_completion = completion

        def perform() -> object:
            try:
                return token, operation(), None
            except Exception as exc:
                return token, None, exc

        worker = StorageWorker(perform)
        self._storage_worker = worker
        worker.signals.completed.connect(self._storage_completed)
        QThreadPool.globalInstance().start(worker)
        return True

    def _storage_completed(self, payload: object) -> None:
        if not isinstance(payload, tuple) or not isinstance(payload[0], tuple):
            return
        token, data, error = payload[0]
        if not self._operation_gate.accepts(token):
            return
        completion = self._storage_completion
        self._storage_worker = None
        self._storage_completion = None
        self._storage_busy = False
        if completion is not None:
            completion((data, error))

    def deactivate(self) -> None:
        # Mutations finish safely, but a detached page may not navigate or warn.
        self._operation_gate.invalidate()
        self._storage_completion = None
        self._storage_busy = False
