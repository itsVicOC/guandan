"""Bounded JSON-lines RPC with persistent fault evidence for isolated policies."""
from __future__ import annotations

import hashlib
import json
import os
import queue
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any


class RPCFailure(RuntimeError):
    def __init__(self, record: dict[str, Any], path: Path):
        self.record, self.path = record, path
        super().__init__(f"policy worker {record['stage']} failed: {record['reason']}; evidence: {path}")


def request_timeout(request: dict[str, Any]) -> float:
    if request.get("mode") != "clock":
        return 60.0
    budget = float(request.get("budget_ms", 5000 if request.get("difficulty") == 4 else 2000))
    return max(2.0, budget / 1000 * 1.15 + 2.0)


class PolicyClient:
    """One outstanding request; timeouts terminate rather than resample games."""

    def __init__(self, command: list[str], *, root: Path, startup_timeout: float = 10,
                 failure_dir: Path | None = None):
        self.root = Path(root)
        self.command = command
        directory = failure_dir or Path(os.environ.get("GUANDAN_EVAL_FAILURE_DIR", tempfile.gettempdir())) / "guandan-rpc"
        directory.mkdir(parents=True, exist_ok=True)
        self.log_path = directory / f"worker-{uuid.uuid4().hex}.stderr"
        self._stderr = self.log_path.open("wb")
        self._responses: queue.Queue[str | Exception | None] = queue.Queue()
        self._request_lock = threading.Lock()
        self._next_id = 0
        self._closed = False
        self._failed = False
        try:
            self.process = subprocess.Popen(
                command, cwd=self.root,
                env={**os.environ, "PYTHONPATH": str(self.root / "src"), "PYTHONDONTWRITEBYTECODE": "1"},
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._stderr, text=True,
            )
        except OSError as exc:
            self._stderr.close()
            record = {"stage": "startup", "reason": str(exc), "command": command,
                      "root": str(self.root), "returncode": None, "stderr_tail": ""}
            path = self.log_path.with_suffix(".failure.json")
            path.write_text(json.dumps(record, indent=2) + "\n")
            raise RPCFailure(record, path) from exc
        self._reader = threading.Thread(target=self._read, daemon=True, name="policy-rpc-reader")
        self._reader.start()
        self.ready = self._receive(startup_timeout, "startup", None)
        if not self.ready.get("ready"):
            self._fail("startup", "invalid readiness response", None)

    def _read(self) -> None:
        assert self.process.stdout is not None
        try:
            for line in self.process.stdout:
                self._responses.put(line)
            self._responses.put(None)
        except (OSError, ValueError) as error:
            self._responses.put(error)

    def _receive(self, timeout: float, stage: str, request: dict | None) -> dict:
        try:
            line = self._responses.get(timeout=max(0.001, timeout))
        except queue.Empty:
            self._fail(stage, "timeout", request)
        if not isinstance(line, str):
            self._fail(stage, "worker exited or pipe failed", request)
        try:
            result = json.loads(line)
        except (TypeError, ValueError):
            self._fail(stage, "invalid JSON response", request)
        if not isinstance(result, dict):
            self._fail(stage, "response must be an object", request)
        return result

    def query(self, request: dict, *, timeout: float | None = None) -> dict:
        with self._request_lock:
            if self._closed:
                raise RuntimeError("policy client is closed")
            self._next_id += 1
            outgoing = {**request, "request_id": self._next_id}
            payload = json.dumps(outgoing) + "\n"
            # Writing also belongs to the timeout: a stuck child can stop reading.
            def send() -> None:
                try:
                    assert self.process.stdin is not None
                    self.process.stdin.write(payload)
                    self.process.stdin.flush()
                except (OSError, ValueError) as error:
                    self._responses.put(error)

            started = time.perf_counter()
            threading.Thread(target=send, daemon=True, name="policy-rpc-writer").start()
            result = self._receive(timeout if timeout is not None else request_timeout(request), "request", outgoing)
            # Historical workers have no ID field; the client remains serial.
            if "request_id" in result and result["request_id"] != self._next_id:
                self._fail("request", "response ID differs", outgoing)
            self.last_transport_seconds = time.perf_counter() - started
            return result

    def _fail(self, stage: str, reason: str, request: dict | None) -> Any:
        self._failed = True
        self.close()
        with self.log_path.open("rb") as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - 8192))
            tail = stream.read().decode("utf-8", errors="replace")
        record = {"stage": stage, "reason": reason, "root": str(self.root),
                  "command": self.command, "request": request,
                  "request_id": request.get("request_id") if request else None,
                  "request_sha256": hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest(),
                  "returncode": self.process.returncode, "stderr_tail": tail}
        path = self.log_path.with_suffix(".failure.json")
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        raise RPCFailure(record, path)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        # Do not close a pipe while its writer owns the TextIO lock.
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1)
        self._reader.join(timeout=0.5)
        if self.process.stdin is not None:
            self.process.stdin.close()
        if self.process.stdout is not None:
            self.process.stdout.close()
        self._stderr.close()
        if not self._failed:
            self.log_path.unlink(missing_ok=True)
