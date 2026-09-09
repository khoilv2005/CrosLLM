"""No-shell subprocess execution with timeout and cooperative cancellation."""

from __future__ import annotations

from dataclasses import dataclass
import subprocess
import time
from pathlib import Path
from typing import Callable


@dataclass(frozen=True, slots=True)
class ProcessOutcome:
    """Captured process result; ``reason`` is set for controlled interruption."""

    returncode: int | None
    stdout: bytes
    stderr: bytes
    reason: str | None = None


def run_process(
    command: tuple[str, ...] | list[str],
    *,
    cwd: Path,
    timeout_seconds: float,
    cancelled: Callable[[], bool] | None = None,
) -> ProcessOutcome:
    """Run a process without a shell and terminate it on timeout/cancellation."""

    if timeout_seconds <= 0:
        raise ValueError("process timeout must be positive")
    process = subprocess.Popen(
        list(command),
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    )
    deadline = time.monotonic() + timeout_seconds

    while True:
        if cancelled is not None:
            try:
                if cancelled():
                    stdout, stderr = _terminate(process)
                    return ProcessOutcome(process.returncode, stdout, stderr, "cancelled")
            except Exception as error:
                stdout, stderr = _terminate(process)
                return ProcessOutcome(process.returncode, stdout, stderr, f"cancellation_error:{error}")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            stdout, stderr = _terminate(process)
            return ProcessOutcome(process.returncode, stdout, stderr, "timeout")
        try:
            stdout, stderr = process.communicate(
                timeout=min(remaining, 0.05) if cancelled is not None else remaining
            )
            return ProcessOutcome(process.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            continue


def _terminate(process: subprocess.Popen[bytes]) -> tuple[bytes, bytes]:
    """Best-effort graceful termination followed by a hard kill."""

    if process.poll() is None:
        process.terminate()
    try:
        stdout, stderr = process.communicate(timeout=1.0)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
    return stdout or b"", stderr or b""


__all__ = ["ProcessOutcome", "run_process"]
