"""Atomic JSON persistence helpers."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _fsync_directory(directory: Path) -> None:
    """Flush a directory entry so a rename survives a power loss.

    `os.replace` is atomic but not durable: without this the rename can still
    be lost on a crash, so a file the user was told was "saved" silently
    reverts to the previous version.
    """
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        # Some filesystems (and Windows) refuse to fsync a directory handle.
        pass
    finally:
        os.close(fd)


def resolve_write_target(path: Path) -> Path:
    """Return the real file a write should land on.

    If the destination is a symlink (e.g. the user redirected ``~/.guandan``
    into a synced folder), replacing the link itself would silently detach the
    synced copy and stop updating it.
    """
    if path.is_symlink():
        try:
            return path.resolve(strict=False)
        except OSError:
            return path
    return path


def write_json_atomic(path: Path, data: Any) -> None:
    """Write JSON beside its destination and atomically replace the old file."""
    target = resolve_write_target(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temp_path = Path(stream.name)
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, target)
        _fsync_directory(target.parent)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


__all__ = ["resolve_write_target", "write_json_atomic"]
