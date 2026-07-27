"""Cross-process locks for the small set of user-owned storage resources."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Lock

from filelock import FileLock, Timeout

LOCK_TIMEOUT_SECONDS = 5.0


class StorageBusyError(OSError):
    """Raised when another Guandan process holds a storage lock too long."""


_registry_guard = Lock()
_locks: dict[str, FileLock] = {}


def _lock_for(resource: Path) -> FileLock:
    lock_path = resource.with_name(f".{resource.name}.lock")
    key = str(lock_path.resolve())
    with _registry_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = FileLock(lock_path, timeout=LOCK_TIMEOUT_SECONDS)
            _locks[key] = lock
    return lock


@contextmanager
def storage_lock(resource: Path) -> Iterator[None]:
    """Exclusively lock one logical storage resource across threads and processes."""
    resource.parent.mkdir(parents=True, exist_ok=True)
    lock = _lock_for(resource)
    try:
        with lock:
            yield
    except Timeout as exc:
        raise StorageBusyError(f"存储正在被另一个掼蛋进程使用：{resource.name}") from exc


__all__ = ["LOCK_TIMEOUT_SECONDS", "StorageBusyError", "storage_lock"]
