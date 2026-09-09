"""Independent EVM replay subprocess boundary for M05.03.

The adapter does not interpret Solidity or reuse the native paired fixture. It
executes a separately identified command and accepts only an explicit replay
status from that command. Missing binaries, malformed output and nonzero exits
are preserved as non-success states.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
import time
from typing import Callable

from ..contracts.canonical import sha256_hex
from ..contracts.records import ReplayStatus
from .process import run_process


_HEX64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class EVMReplaySpec:
    adapter_id: str
    executable: str
    arguments: tuple[str, ...]
    tool_revision: str
    container_ref: str
    artifact_hash: str
    initialization_hash: str
    profile_hash: str
    semantic_engine: str
    timeout_seconds: float = 180.0
    support_matrix_hash: str | None = None

    def __post_init__(self) -> None:
        required = (
            self.adapter_id, self.executable, self.tool_revision, self.container_ref,
            self.artifact_hash, self.initialization_hash, self.profile_hash,
            self.semantic_engine,
        )
        if any(not value for value in required):
            raise ValueError("independent EVM replay spec requires complete identity")
        if self.adapter_id.lower() in {"native", "fixture", "paired_fixture"}:
            raise ValueError("independent replay adapter cannot be the native fixture")
        if re.search(r"@sha256:[0-9a-fA-F]{64}$", self.container_ref) is None:
            raise ValueError("replay container must use an immutable sha256 digest")
        for name in ("artifact_hash", "initialization_hash", "profile_hash"):
            value = getattr(self, name)
            if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
                raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")
        if self.timeout_seconds <= 0:
            raise ValueError("replay timeout must be positive")
        if self.support_matrix_hash is not None and (
            len(self.support_matrix_hash) != 64
            or self.support_matrix_hash != self.support_matrix_hash.lower()
            or any(char not in "0123456789abcdef" for char in self.support_matrix_hash)
        ):
            raise ValueError("support matrix hash must be a lowercase SHA-256 hex digest")

    @property
    def spec_hash(self) -> str:
        return sha256_hex({
            "adapter_id": self.adapter_id,
            "executable": self.executable,
            "arguments": list(self.arguments),
            "tool_revision": self.tool_revision,
            "container_ref": self.container_ref,
            "artifact_hash": self.artifact_hash,
            "initialization_hash": self.initialization_hash,
            "profile_hash": self.profile_hash,
            "semantic_engine": self.semantic_engine,
            "timeout_seconds": self.timeout_seconds,
            "support_matrix_hash": self.support_matrix_hash,
        })


@dataclass(frozen=True, slots=True)
class EVMReplayResult:
    spec_hash: str
    status: ReplayStatus
    exit_code: int | None
    stdout_hash: str | None
    stderr_hash: str | None
    trace_hash: str | None
    elapsed_seconds: float
    reason: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "spec_hash": self.spec_hash,
            "status": self.status.value,
            "exit_code": self.exit_code,
            "stdout_hash": self.stdout_hash,
            "stderr_hash": self.stderr_hash,
            "trace_hash": self.trace_hash,
            "elapsed_seconds": self.elapsed_seconds,
            "reason": self.reason,
        }


class IndependentEVMReplay:
    """Run a separately pinned EVM adapter command without shell evaluation."""

    def run(
        self,
        spec: EVMReplaySpec,
        workdir: Path,
        *,
        witness_path: Path | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> EVMReplayResult:
        started = time.monotonic()
        executable = shutil.which(spec.executable)
        if executable is None:
            return self._result(spec, ReplayStatus.UNSUPPORTED, None, None, None, None, started, "executable_missing")
        if not workdir.is_dir():
            return self._result(spec, ReplayStatus.UNSUPPORTED, None, None, None, None, started, "workdir_missing")
        try:
            if any(argument == "{witness}" for argument in spec.arguments):
                if witness_path is None:
                    return self._result(spec, ReplayStatus.UNKNOWN, None, None, None, None, started, "witness_path_missing")
                if not witness_path.is_file():
                    return self._result(spec, ReplayStatus.UNKNOWN, None, None, None, None, started, "witness_file_missing")
            arguments = tuple(
                str(witness_path) if argument == "{witness}" and witness_path is not None else argument
                for argument in spec.arguments
            )
            outcome = run_process(
                (executable, *arguments),
                cwd=workdir,
                timeout_seconds=spec.timeout_seconds,
                cancelled=cancelled,
            )
        except OSError as error:
            return self._result(spec, ReplayStatus.UNKNOWN, None, None, None, None, started, f"replay_start_failure:{error}")
        stdout_hash = _hash(outcome.stdout)
        stderr_hash = _hash(outcome.stderr)
        if outcome.reason == "timeout":
            return self._result(spec, ReplayStatus.UNKNOWN, outcome.returncode, stdout_hash, stderr_hash, None, started, "replay_timeout")
        if outcome.reason is not None:
            return self._result(spec, ReplayStatus.UNKNOWN, outcome.returncode, stdout_hash, stderr_hash, None, started, outcome.reason)
        if outcome.returncode != 0:
            return self._result(spec, ReplayStatus.FAIL, outcome.returncode, stdout_hash, stderr_hash, None, started, "replay_nonzero_exit")
        try:
            payload = json.loads(outcome.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            return self._result(spec, ReplayStatus.UNKNOWN, outcome.returncode, stdout_hash, stderr_hash, None, started, f"replay_output_parse_failure:{error}")
        if not isinstance(payload, dict) or not isinstance(payload.get("status"), str):
            return self._result(spec, ReplayStatus.UNKNOWN, outcome.returncode, stdout_hash, stderr_hash, None, started, "replay_output_missing_status")
        try:
            status = ReplayStatus(payload["status"])
        except ValueError:
            return self._result(spec, ReplayStatus.UNKNOWN, outcome.returncode, stdout_hash, stderr_hash, None, started, "replay_output_invalid_status")
        trace_hash = payload.get("trace_hash")
        if trace_hash is not None and (not isinstance(trace_hash, str) or _HEX64.fullmatch(trace_hash) is None):
            return self._result(spec, ReplayStatus.UNKNOWN, outcome.returncode, stdout_hash, stderr_hash, None, started, "replay_output_invalid_trace_hash")
        if status is ReplayStatus.PASS and trace_hash is None:
            return self._result(spec, ReplayStatus.UNKNOWN, outcome.returncode, stdout_hash, stderr_hash, None, started, "replay_output_missing_trace_hash")
        reason = payload.get("reason") if isinstance(payload.get("reason"), str) else None
        return self._result(spec, status, outcome.returncode, stdout_hash, stderr_hash, trace_hash, started, reason)

    @staticmethod
    def _result(
        spec: EVMReplaySpec,
        status: ReplayStatus,
        exit_code: int | None,
        stdout_hash: str | None,
        stderr_hash: str | None,
        trace_hash: str | None,
        started: float,
        reason: str | None,
    ) -> EVMReplayResult:
        return EVMReplayResult(spec.spec_hash, status, exit_code, stdout_hash, stderr_hash, trace_hash, max(0.0, time.monotonic() - started), reason)


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


__all__ = ["EVMReplayResult", "EVMReplaySpec", "IndependentEVMReplay"]
