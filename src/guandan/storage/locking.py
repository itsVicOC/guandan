"""Cross-process locks for the small set of user-owned storage resources."""
from __future__ import annotations

import threading
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


def _holder_hint(resource: Path, blocked_thread: int) -> str:
    """Explain who is likely holding the lock.

    The previous message always blamed "另一个掼蛋进程", even when the caller was
    blocked by another thread of the same process (the GUI saves from a
    QThreadPool worker), which sent users hunting for a process that does not
    exist.
    """
    others = [
        thread
        for thread in threading.enumerate()
        if thread.ident != blocked_thread and thread.is_alive()
    ]
    if others:
        names = ", ".join(sorted({thread.name for thread in others})[:3])
        return f"本程序内其他线程正在写入 {resource.name}（{names}）"
    return f"存储正在被另一个掼蛋进程使用：{resource.name}"


@contextmanager
def storage_lock(resource: Path) -> Iterator[None]:
    """Exclusively lock one logical storage resource across threads and processes."""
    resource.parent.mkdir(parents=True, exist_ok=True)
    lock = _lock_for(resource)
    blocked_thread = threading.get_ident()
    try:
        with lock:
            yield
    except Timeout as exc:
        raise StorageBusyError(
            f"{_holder_hint(resource, blocked_thread)}"
            f"（等待 {LOCK_TIMEOUT_SECONDS:.0f} 秒后超时）"
        ) from exc


__all__ = ["LOCK_TIMEOUT_SECONDS", "StorageBusyError", "storage_lock"]
