"""Faithful external-tool boundary for native baselines.

This adapter executes only an explicitly pinned command supplied by a baseline
specification. It does not translate findings into CrossLLM concepts and does
not treat missing binaries, unsupported scope or parse failures as clean runs.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time
from math import isfinite

from ..contracts.canonical import sha256_hex
from ..contracts.records import SearchStatus


@dataclass(frozen=True, slots=True)
class ResourceEnvelope:
    """Declared limits for one native-tool invocation.

    The adapter can enforce a wall-clock timeout portably. CPU, memory and PID
    limits are deliberately recorded as declarations because enforcement is
    supervisor/container specific on the supported hosts. A run must not be
    interpreted as resource-controlled evidence unless the outer runner records
    enforcement separately.
    """

    cpu_cores: int = 1
    memory_mib: int = 4096
    pids: int = 512
    wall_seconds: float = 3600.0

    def __post_init__(self) -> None:
        if self.cpu_cores <= 0 or self.memory_mib <= 0 or self.pids <= 0:
            raise ValueError("resource limits must be positive")
        if not isfinite(self.wall_seconds) or self.wall_seconds <= 0:
            raise ValueError("resource wall_seconds must be finite and positive")

    def as_dict(self) -> dict[str, int | float]:
        return {
            "cpu_cores": self.cpu_cores,
            "memory_mib": self.memory_mib,
            "pids": self.pids,
            "wall_seconds": self.wall_seconds,
        }


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    executable: str
    arguments: tuple[str, ...]
    upstream_revision: str
    config_hash: str
    supported_scope: str
    timeout_seconds: float = 3600.0
    resource_envelope: ResourceEnvelope = ResourceEnvelope()
    network_policy: str = "offline"
    output_schema: str = "json_array"

    def __post_init__(self) -> None:
        if not self.name or not self.executable or not self.upstream_revision or not self.config_hash or not self.supported_scope:
            raise ValueError("tool spec identity/config fields are required")
        if any(not isinstance(argument, str) or not argument for argument in self.arguments):
            raise ValueError("tool arguments must be non-empty strings")
        if self.timeout_seconds <= 0:
            raise ValueError("tool timeout must be positive")
        if self.timeout_seconds > self.resource_envelope.wall_seconds:
            raise ValueError("tool timeout cannot exceed declared wall-clock envelope")
        if self.network_policy not in {"offline", "provider_only", "unrestricted"}:
            raise ValueError("network_policy must be offline, provider_only or unrestricted")
        if self.output_schema not in {"json_array", "slither_json", "ityfuzz_json"}:
            raise ValueError("output_schema must be json_array, slither_json or ityfuzz_json")

    @property
    def argv_hash(self) -> str:
        return sha256_hex({"executable": self.executable, "arguments": self.arguments})

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "executable": self.executable,
            "arguments": list(self.arguments),
            "argv_hash": self.argv_hash,
            "upstream_revision": self.upstream_revision,
            "config_hash": self.config_hash,
            "supported_scope": self.supported_scope,
            "timeout_seconds": self.timeout_seconds,
            "resource_envelope": self.resource_envelope.as_dict(),
            "network_policy": self.network_policy,
            "output_schema": self.output_schema,
        }


@dataclass(frozen=True, slots=True)
class BaselineFinding:
    tool: str
    finding_id: str
    category: str
    location: str | None
    message: str
    raw: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "tool": self.tool,
            "finding_id": self.finding_id,
            "category": self.category,
            "location": self.location,
            "message": self.message,
            "raw": self.raw,
        }


@dataclass(frozen=True, slots=True)
class BaselineResult:
    tool: ToolSpec
    status: SearchStatus
    exit_code: int | None
    stdout_hash: str | None
    stderr_hash: str | None
    findings: tuple[BaselineFinding, ...]
    elapsed_seconds: float
    reason: str | None = None

    @property
    def clean(self) -> bool:
        return self.status is SearchStatus.BOUNDED_UNSAT and self.reason == "completed_without_findings"

    def as_dict(self) -> dict[str, object]:
        return {
            "tool": self.tool.as_dict(),
            "status": self.status,
            "exit_code": self.exit_code,
            "stdout_hash": self.stdout_hash,
            "stderr_hash": self.stderr_hash,
            "findings": [finding.as_dict() for finding in self.findings],
            "elapsed_seconds": self.elapsed_seconds,
            "reason": self.reason,
            "clean": self.clean,
            "resource_enforcement": "declared_only",
        }


class ExternalToolAdapter:
    """Run native tool output without granting it CrossLLM semantics."""

    def run(self, spec: ToolSpec, workdir: Path) -> BaselineResult:
        started = time.monotonic()
        executable = shutil.which(spec.executable)
        if executable is None:
            return BaselineResult(spec, SearchStatus.UNSUPPORTED, None, None, None, (), _elapsed(started), "executable_missing")
        if not workdir.is_dir():
            return BaselineResult(spec, SearchStatus.UNSUPPORTED, None, None, None, (), _elapsed(started), "workdir_missing")
        try:
            completed = subprocess.run(
                [executable, *spec.arguments],
                cwd=workdir,
                capture_output=True,
                text=False,
                timeout=spec.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            stdout = _bytes(error.stdout)
            stderr = _bytes(error.stderr)
            return BaselineResult(spec, SearchStatus.TIMEOUT, None, _hash(stdout), _hash(stderr), (), _elapsed(started), "tool_timeout")
        except OSError as error:
            return BaselineResult(spec, SearchStatus.CRASH, None, None, None, (), _elapsed(started), f"tool_start_failure:{error}")
        stdout_hash = _hash(completed.stdout)
        stderr_hash = _hash(completed.stderr)
        if completed.returncode != 0:
            return BaselineResult(spec, SearchStatus.CRASH, completed.returncode, stdout_hash, stderr_hash, (), _elapsed(started), "nonzero_exit")
        try:
            findings = normalize_findings(
                spec.name,
                json.loads(completed.stdout.decode("utf-8")),
                output_schema=spec.output_schema,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            return BaselineResult(spec, SearchStatus.CRASH, completed.returncode, stdout_hash, stderr_hash, (), _elapsed(started), f"output_parse_failure:{error}")
        if findings:
            return BaselineResult(spec, SearchStatus.SAT, completed.returncode, stdout_hash, stderr_hash, findings, _elapsed(started), "findings_returned")
        return BaselineResult(spec, SearchStatus.BOUNDED_UNSAT, completed.returncode, stdout_hash, stderr_hash, (), _elapsed(started), "completed_without_findings")


def normalize_findings(
    tool: str,
    payload: object,
    *,
    output_schema: str = "json_array",
) -> tuple[BaselineFinding, ...]:
    """Normalize only common metadata; preserve raw tool output unchanged."""
    if output_schema == "slither_json":
        return _normalize_slither_findings(tool, payload)
    if output_schema == "ityfuzz_json":
        return _normalize_ityfuzz_findings(tool, payload)
    if output_schema != "json_array":
        raise ValueError("unsupported native output schema")
    if not isinstance(payload, list):
        raise ValueError("native tool output must be a JSON array")
    return _normalize_rows(tool, payload)


def _normalize_rows(tool: str, payload: list[object]) -> tuple[BaselineFinding, ...]:
    findings: list[BaselineFinding] = []
    for index, row in enumerate(payload):
        if not isinstance(row, dict):
            raise ValueError(f"finding {index} must be an object")
        category = row.get("category") or row.get("check") or row.get("type")
        message = row.get("message") or row.get("description")
        if not isinstance(category, str) or not category or not isinstance(message, str) or not message:
            raise ValueError(f"finding {index} lacks category/message")
        location = row.get("location")
        if location is not None and not isinstance(location, str):
            raise ValueError(f"finding {index} location must be a string")
        finding_id = row.get("id")
        if not isinstance(finding_id, str) or not finding_id:
            finding_id = f"{tool}:{index}"
        findings.append(BaselineFinding(tool, finding_id, category, location, message, dict(row)))
    return tuple(findings)


def _normalize_slither_findings(tool: str, payload: object) -> tuple[BaselineFinding, ...]:
    if not isinstance(payload, dict):
        raise ValueError("Slither JSON output must be an object")
    results = payload.get("results")
    if not isinstance(results, dict):
        raise ValueError("Slither JSON output lacks results object")
    detectors = results.get("detectors")
    if not isinstance(detectors, list):
        raise ValueError("Slither JSON output lacks detector list")
    normalized: list[dict[str, object]] = []
    for index, detector in enumerate(detectors):
        if not isinstance(detector, dict):
            raise ValueError(f"Slither detector {index} must be an object")
        row = dict(detector)
        row.setdefault("id", detector.get("check") or f"detector-{index}")
        row.setdefault("category", detector.get("check"))
        row.setdefault("message", detector.get("description"))
        elements = detector.get("elements")
        if isinstance(elements, list) and elements and isinstance(elements[0], dict):
            first = elements[0]
            location = first.get("source_mapping") or first.get("type_specific_fields")
            if isinstance(location, (dict, str)):
                row["location"] = location if isinstance(location, str) else json.dumps(location, sort_keys=True)
        normalized.append(row)
    return _normalize_rows(tool, normalized)


def _normalize_ityfuzz_findings(tool: str, payload: object) -> tuple[BaselineFinding, ...]:
    if isinstance(payload, list):
        return _normalize_rows(tool, payload)
    if not isinstance(payload, dict):
        raise ValueError("ItyFuzz JSON output must be an object or array")
    rows = payload.get("findings", payload.get("issues"))
    if not isinstance(rows, list):
        raise ValueError("ItyFuzz JSON output lacks findings/issues list")
    return _normalize_rows(tool, rows)


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _bytes(value: bytes | str | None) -> bytes:
    if value is None:
        return b""
    return value if isinstance(value, bytes) else value.encode()


def _elapsed(started: float) -> float:
    return max(0.0, time.monotonic() - started)
