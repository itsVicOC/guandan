"""Run storage work off the event loop and discard stale screen completions."""
from __future__ import annotations

from collections.abc import Callable

from textual import work
from textual.screen import Screen

from ...ui.background import OperationGate


class StorageScreen(Screen):
    def __init__(self) -> None:
        super().__init__()
        self._operation_gate = OperationGate()
        self._storage_busy = False

    def _start_storage(self, operation: Callable[[], object], completion: Callable[[object], None]) -> None:
        if self._storage_busy:
            return
        self._storage_busy = True
        self._run_storage(self._operation_gate.begin(), operation, completion)

    @work(thread=True, group="storage")
    def _run_storage(self, token: int, operation: Callable[[], object], completion: Callable[[object], None]) -> None:
        payload: tuple[object, Exception | None]
        try:
            payload = operation(), None
        except Exception as exc:
            payload = None, exc
        self.app.call_from_thread(self._storage_completed, token, completion, payload)

    def _storage_completed(self, token: int, completion: Callable[[object], None], payload: object) -> None:
        if not self._operation_gate.accepts(token):
            return
        self._storage_busy = False
        if self.is_mounted and self.app.screen is self:
            completion(payload)

    def on_unmount(self) -> None:
        self._operation_gate.invalidate()

    def on_screen_suspend(self) -> None:
        self._operation_gate.invalidate()
        self._storage_busy = False
