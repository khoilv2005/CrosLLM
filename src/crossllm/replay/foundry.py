"""Digest-pinned Docker/Foundry replay boundary.

The adapter is deliberately separate from the in-memory paired fixture. It
executes ``forge test --json`` in a read-only project mount and preserves
compiler/tool/container failures as non-success statuses.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
import time
from typing import Any, Callable, Mapping

from ..contracts.canonical import sha256_hex
from ..contracts.records import ReplayStatus
from .process import run_process


_DIGEST_REF = re.compile(r"@sha256:[0-9a-fA-F]{64}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SOLC = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_DOCKER_VOLUME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")


@dataclass(frozen=True, slots=True)
class FoundryReplaySpec:
    image_ref: str
    project_path: Path
    tool_revision: str
    artifact_hash: str
    initialization_hash: str
    profile_hash: str
    semantic_engine: str
    compiler_version: str | None = None
    test_filter: str | None = None
    network_mode: str = "none"
    timeout_seconds: float = 180.0
    support_matrix_hash: str | None = None
    compiler_volume: str | None = None
    compiler_image_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.image_ref or not _DIGEST_REF.search(self.image_ref):
            raise ValueError("Foundry image must use an immutable @sha256 digest")
        if not self.project_path.is_dir():
            raise ValueError("Foundry project path must be an existing directory")
        if not self.tool_revision or not self.semantic_engine:
            raise ValueError("Foundry replay identity is incomplete")
        for name in ("artifact_hash", "initialization_hash", "profile_hash"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _HEX64.fullmatch(value):
                raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")
        if self.compiler_version is not None and not _SOLC.fullmatch(self.compiler_version):
            raise ValueError("compiler_version must be a semantic Solidity version")
        if self.compiler_volume is not None and not _DOCKER_VOLUME.fullmatch(self.compiler_volume):
            raise ValueError("compiler_volume must be a valid Docker volume name")
        if self.compiler_volume is None and self.compiler_image_ref is not None:
            raise ValueError("compiler_image_ref requires compiler_volume")
        if self.compiler_volume is not None:
            if self.compiler_version is None:
                raise ValueError("compiler_volume requires compiler_version")
            if self.compiler_image_ref is None or not _DIGEST_REF.search(self.compiler_image_ref):
                raise ValueError("compiler_image_ref must be an immutable @sha256 digest")
        if self.network_mode not in {"none", "bridge"}:
            raise ValueError("network_mode must be none or bridge")
        if self.timeout_seconds <= 0:
            raise ValueError("Foundry replay timeout must be positive")
        if self.support_matrix_hash is not None and not _HEX64.fullmatch(self.support_matrix_hash):
            raise ValueError("support_matrix_hash must be a lowercase SHA-256 hex digest")

    @property
    def spec_hash(self) -> str:
        return sha256_hex(self.as_dict(include_hash=False))

    def as_dict(self, *, include_hash: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": 1,
            "image_ref": self.image_ref,
            "project_path": str(self.project_path.resolve()),
            "tool_revision": self.tool_revision,
            "artifact_hash": self.artifact_hash,
            "initialization_hash": self.initialization_hash,
            "profile_hash": self.profile_hash,
            "semantic_engine": self.semantic_engine,
            "compiler_version": self.compiler_version,
            "test_filter": self.test_filter,
            "network_mode": self.network_mode,
            "timeout_seconds": self.timeout_seconds,
            "support_matrix_hash": self.support_matrix_hash,
            "compiler_volume": self.compiler_volume,
            "compiler_image_ref": self.compiler_image_ref,
        }
        if include_hash:
            payload["spec_hash"] = sha256_hex(payload)
        return payload

    def command(self, *, docker_executable: str = "docker") -> tuple[str, ...]:
        command = [
            docker_executable,
            "run", "--rm",
            f"--network={self.network_mode}",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--pids-limit", "512",
            "--cpus", "4",
            "--memory", str(16 * 1024**3) + "b",
            "--tmpfs", (
                "/tmp:rw,nosuid,size=1g"
                if self.network_mode == "bridge"
                else "/tmp:rw,noexec,nosuid,size=1g"
            ),
            "--env", "HOME=/tmp/crossllm-home",
            "--env", "FOUNDRY_HOME=/tmp/crossllm-foundry-home",
            "--env", "SVM_HOME=/tmp/crossllm-svm-home",
            "--mount", f"type=bind,src={self.project_path.resolve()},dst=/work,readonly",
            "--workdir", "/work",
            "--entrypoint", "/usr/local/bin/forge",
            self.image_ref,
            "test", "--root", "/work", "--json",
            "--out", "/tmp/crossllm-foundry-out",
            "--cache-path", "/tmp/crossllm-foundry-cache",
        ]
        if self.compiler_volume is not None:
            # Insert the compiler volume immediately before the project mount.
            mount_index = command.index("--mount")
            command[mount_index:mount_index] = [
                "--mount", f"type=volume,src={self.compiler_volume},dst=/compiler,readonly",
            ]
            command.extend(("--use", "/compiler/solc"))
        elif self.compiler_version is not None:
            command.extend(("--use", self.compiler_version))
        if self.test_filter is not None:
            command.extend(("--match-test", self.test_filter))
        return tuple(command)


@dataclass(frozen=True, slots=True)
class FoundryReplayResult:
    spec_hash: str
    status: ReplayStatus
    exit_code: int | None
    stdout_hash: str | None
    stderr_hash: str | None
    elapsed_seconds: float
    test_count: int
    passed_tests: int
    failed_tests: int
    reason: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "spec_hash": self.spec_hash,
            "status": self.status.value,
            "exit_code": self.exit_code,
            "stdout_hash": self.stdout_hash,
            "stderr_hash": self.stderr_hash,
            "elapsed_seconds": self.elapsed_seconds,
            "test_count": self.test_count,
            "passed_tests": self.passed_tests,
            "failed_tests": self.failed_tests,
            "reason": self.reason,
        }


class FoundryDockerReplay:
    """Execute a Foundry test project without shell interpretation."""

    def run(
        self,
        spec: FoundryReplaySpec,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> FoundryReplayResult:
        started = time.monotonic()
        docker = shutil.which("docker")
        if docker is None:
            return self._result(spec, ReplayStatus.UNSUPPORTED, None, None, None, started, 0, 0, 0, "docker_missing")
        try:
            outcome = run_process(
                spec.command(docker_executable=docker),
                cwd=spec.project_path,
                timeout_seconds=spec.timeout_seconds,
                cancelled=cancelled,
            )
        except OSError as error:
            return self._result(spec, ReplayStatus.UNKNOWN, None, None, None, started, 0, 0, 0, f"foundry_start_failure:{error}")
        stdout, stderr = outcome.stdout, outcome.stderr
        if outcome.reason == "timeout":
            return self._result(spec, ReplayStatus.UNKNOWN, outcome.returncode, stdout, stderr, started, 0, 0, 0, "foundry_timeout")
        if outcome.reason is not None:
            return self._result(spec, ReplayStatus.UNKNOWN, outcome.returncode, stdout, stderr, started, 0, 0, 0, outcome.reason)
        if outcome.returncode != 0:
            error_text = stderr.decode("utf-8", errors="replace")
            status, reason = classify_foundry_failure(error_text)
            return self._result(spec, status, outcome.returncode, stdout, stderr, started, 0, 0, 0, reason)
        try:
            payload = json.loads(stdout.decode("utf-8"))
            test_count, passed, failed = summarize_foundry_json(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            return self._result(spec, ReplayStatus.UNKNOWN, outcome.returncode, stdout, stderr, started, 0, 0, 0, f"foundry_output_parse_failure:{error}")
        status = ReplayStatus.PASS if failed == 0 else ReplayStatus.FAIL
        return self._result(spec, status, outcome.returncode, stdout, stderr, started, test_count, passed, failed, None)

    @staticmethod
    def _result(
        spec: FoundryReplaySpec,
        status: ReplayStatus,
        exit_code: int | None,
        stdout: bytes | None,
        stderr: bytes | None,
        started: float,
        test_count: int,
        passed: int,
        failed: int,
        reason: str | None,
    ) -> FoundryReplayResult:
        return FoundryReplayResult(
            spec.spec_hash,
            status,
            exit_code,
            _hash(stdout),
            _hash(stderr),
            max(0.0, time.monotonic() - started),
            test_count,
            passed,
            failed,
            reason,
        )


def summarize_foundry_json(payload: Mapping[str, Any]) -> tuple[int, int, int]:
    """Return total/success/failure counts from Foundry's JSON test output."""
    statuses: list[str] = []

    def visit(value: object) -> None:
        if isinstance(value, Mapping):
            test_results = value.get("test_results")
            if isinstance(test_results, Mapping):
                for result in test_results.values():
                    if isinstance(result, Mapping) and isinstance(result.get("status"), str):
                        statuses.append(result["status"].lower())
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    if not statuses:
        raise ValueError("Foundry output has no test_results")
    passed = sum(status in {"success", "passed", "pass"} for status in statuses)
    return len(statuses), passed, len(statuses) - passed


def classify_foundry_failure(error_text: str) -> tuple[ReplayStatus, str]:
    """Classify a failed Foundry invocation without hiding environment faults."""
    lowered = error_text.lower()
    if "missing solc" in lowered and "offline" in lowered:
        return ReplayStatus.UNSUPPORTED, "compiler_missing"
    if "permission denied" in lowered and (".svm" in lowered or "solc" in lowered):
        return ReplayStatus.UNKNOWN, "compiler_execution_denied"
    if "binaries.soliditylang.org" in lowered or "failed to lookup address" in lowered:
        return ReplayStatus.UNKNOWN, "compiler_install_unavailable"
    return ReplayStatus.FAIL, "foundry_nonzero_exit"


def _hash(value: bytes | None) -> str | None:
    return hashlib.sha256(value).hexdigest() if value is not None else None


__all__ = ["FoundryDockerReplay", "FoundryReplayResult", "FoundryReplaySpec", "classify_foundry_failure", "summarize_foundry_json"]
