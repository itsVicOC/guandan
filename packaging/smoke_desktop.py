"""Verify that a packaged desktop executable starts and stays alive."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


def packaged_executable() -> Path:
    dist_root = Path(os.environ.get("GUANDAN_DIST_ROOT", "dist"))
    if sys.platform == "darwin":
        return dist_root / "Guandan.app/Contents/MacOS/Guandan"
    if sys.platform == "win32":
        return dist_root / "Guandan/Guandan.exe"
    return dist_root / "Guandan/Guandan"


def main() -> int:
    executable = packaged_executable()
    if not executable.is_file():
        print(f"packaged executable not found: {executable}", file=sys.stderr)
        return 1

    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    verification_env = dict(env)
    verification_env["GUANDAN_PACKAGE_SMOKE"] = "1"
    verification = subprocess.run(
        [str(executable.resolve())],
        capture_output=True,
        text=True,
        env=verification_env,
        timeout=30,
        check=False,
    )
    if verification.returncode != 0:
        print(verification.stdout, file=sys.stderr)
        print(verification.stderr, file=sys.stderr)
        print(
            f"packaged AI verification failed: {verification.returncode}",
            file=sys.stderr,
        )
        return 1

    process = subprocess.Popen(
        [str(executable.resolve())],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            return_code = process.poll()
            if return_code is not None:
                stdout, stderr = process.communicate()
                print(stdout, file=sys.stderr)
                print(stderr, file=sys.stderr)
                print(f"packaged application exited early: {return_code}", file=sys.stderr)
                return 1
            time.sleep(0.1)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    print(f"packaged application started successfully: {executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
