"""Source-backed subprocess executors for the shared verification pipeline.

The symbolic search and native witness checker are intentionally protocol
adapters rather than an invented EVM implementation.  A pinned external tool
receives the candidate runtime request and returns a strict JSON result.  The
adapter preserves transport/tool failures and validates every identity needed
to connect a returned witness to the candidate.  Independent replay is then
performed by :class:`IndependentEVMReplay` with a separate pinned spec.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Callable, Mapping

from ..contracts.canonical import sha256_hex
from ..contracts.records import ReplayStatus, SearchStatus
from ..replay.evm import EVMReplaySpec, IndependentEVMReplay
from ..replay.process import run_process
from .adapter import RuntimeCandidatePlan
from .pipeline import VerificationExecutors
from .records import StageResult, StageStatus


_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_DIGEST_REF = re.compile(r"@sha256:[0-9a-fA-F]{64}$")
_SELECTOR = re.compile(r"^0x[0-9a-fA-F]{8}$")
_CALLDATA = re.compile(r"^0x(?:[0-9a-fA-F]{2})*$")


@dataclass(frozen=True, slots=True)
class SourceCommandSpec:
    """Identity and invocation contract for one JSON source-backed tool."""

    adapter_id: str
    executable: str
    arguments: tuple[str, ...]
    workdir: Path
    tool_revision: str
    container_ref: str
    timeout_seconds: float = 180.0

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value for value in (
            self.adapter_id, self.executable, self.tool_revision, self.container_ref,
        )):
            raise ValueError("source command identity is incomplete")
        if not _DIGEST_REF.search(self.container_ref):
            raise ValueError("source command container must use an immutable sha256 digest")
        if not isinstance(self.arguments, tuple) or any(not isinstance(value, str) for value in self.arguments):
            raise ValueError("source command arguments must be a tuple of strings")
        if not self.workdir.is_dir():
            raise ValueError("source command workdir must be an existing directory")
        if self.timeout_seconds <= 0:
            raise ValueError("source command timeout must be positive")

    @property
    def spec_hash(self) -> str:
        return sha256_hex({
            "schema_version": 1,
            "adapter_id": self.adapter_id,
            "executable": self.executable,
            "arguments": list(self.arguments),
            "workdir": str(self.workdir.resolve()),
            "tool_revision": self.tool_revision,
            "container_ref": self.container_ref,
            "timeout_seconds": self.timeout_seconds,
        })

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "adapter_id": self.adapter_id,
            "executable": self.executable,
            "arguments": list(self.arguments),
            "workdir": str(self.workdir.resolve()),
            "tool_revision": self.tool_revision,
            "container_ref": self.container_ref,
            "timeout_seconds": self.timeout_seconds,
            "spec_hash": self.spec_hash,
        }


@dataclass(frozen=True, slots=True)
class _JsonCommandResult:
    payload: dict[str, Any] | None
    status: StageStatus | None
    reason: str | None
    evidence: dict[str, object]
    witness_path: Path | None = None


class SourceBackedVerificationExecutors:
    """Connect pinned source tools to the common candidate pipeline.

    The external tools must implement this small protocol:

    * search output: ``status`` from ``SearchStatus``, ``complete`` and a
      candidate-bound ``witness`` for complete SAT;
    * witness-check output: ``status`` from ``ReplayStatus``, matching
      ``trace_hash``, ``candidate_violation`` and ``property_holds``;
    * independent replay output: the normal ``EVMReplaySpec`` response plus
      explicit ``property_holds`` and ``security_relevance`` booleans.

    No output is treated as success merely because the process exits zero.
    """

    def __init__(
        self,
        *,
        search: SourceCommandSpec,
        witness: SourceCommandSpec,
        replay: EVMReplaySpec,
        replay_workdir: Path,
        cancelled: Callable[[], bool] | None = None,
    ) -> None:
        if "{request}" not in search.arguments:
            raise ValueError("source search command must include a {request} argument")
        if "{request}" not in witness.arguments or "{witness}" not in witness.arguments:
            raise ValueError("source witness command must include {request} and {witness} arguments")
        if "{witness}" not in replay.arguments:
            raise ValueError("independent replay spec must include a {witness} argument")
        if not replay_workdir.is_dir():
            raise ValueError("independent replay workdir must be an existing directory")
        self.search_spec = search
        self.witness_spec = witness
        self.replay_spec = replay
        self.replay_workdir = replay_workdir.resolve()
        self.cancelled = cancelled
        self._tempdir = tempfile.TemporaryDirectory(prefix="crossllm-source-verification-")
        self._witnesses: dict[str, dict[str, Any]] = {}
        self._witness_paths: dict[str, Path] = {}
        self._witness_properties: dict[str, bool] = {}

    def executors(self) -> VerificationExecutors:
        return VerificationExecutors(
            symbolic_search=self.symbolic_search,
            witness_check=self.witness_check,
            independent_replay=self.independent_replay,
            spec_hash=self.spec_hash,
        )

    @property
    def spec_hash(self) -> str:
        """Fingerprint every executable boundary used by this pipeline."""

        return sha256_hex({
            "schema_version": 1,
            "search": self.search_spec.as_dict(),
            "witness": self.witness_spec.as_dict(),
            "replay": self.replay_spec.spec_hash,
            "replay_workdir": str(self.replay_workdir),
        })

    def close(self) -> None:
        self._tempdir.cleanup()

    def __enter__(self) -> "SourceBackedVerificationExecutors":
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()

    def symbolic_search(self, plan: RuntimeCandidatePlan) -> StageResult:
        if not plan.executable or plan.search_request is None:
            return StageResult("symbolic_search", StageStatus.UNSUPPORTED, "runtime_plan_not_executable")
        result = self._invoke(self.search_spec, dict(plan.search_request), f"search-{self._key(plan)}")
        if result.status is not None:
            return StageResult("symbolic_search", result.status, result.reason, evidence=result.evidence)
        payload = result.payload or {}
        status = _enum_status(payload.get("status"), SearchStatus)
        complete = payload.get("complete")
        evidence = {**result.evidence, "search_status": status.value if status else None, "complete": complete}
        if status is None or not isinstance(complete, bool):
            return StageResult("symbolic_search", StageStatus.UNKNOWN, "search_output_invalid_status_or_complete", evidence=evidence)
        if status is SearchStatus.SAT:
            if not complete:
                return StageResult("symbolic_search", StageStatus.UNKNOWN, "sat_result_not_complete", evidence=evidence)
            witness = payload.get("witness")
            reason = _validate_source_witness(witness, plan)
            if reason is not None:
                return StageResult("symbolic_search", StageStatus.UNKNOWN, reason, evidence=evidence)
            if payload.get("candidate_violation") is not True:
                return StageResult("symbolic_search", StageStatus.UNKNOWN, "sat_output_missing_candidate_violation", evidence=evidence)
            self._witnesses[self._key(plan)] = dict(witness)
            evidence["candidate_violation"] = True
            evidence["witness_id"] = witness["witness_id"]
            return StageResult("symbolic_search", StageStatus.PASSED, evidence=evidence)
        if status is SearchStatus.BOUNDED_UNSAT:
            if not complete:
                return StageResult("symbolic_search", StageStatus.UNKNOWN, "bounded_unsat_result_not_complete", evidence=evidence)
            evidence["candidate_violation"] = False
            return StageResult("symbolic_search", StageStatus.PASSED, evidence=evidence)
        return StageResult("symbolic_search", _search_stage_status(status), _status_reason(status), evidence=evidence)

    def witness_check(self, plan: RuntimeCandidatePlan) -> StageResult:
        key = self._key(plan)
        witness = self._witnesses.get(key)
        if witness is None:
            return StageResult("witness_check", StageStatus.NOT_APPLICABLE, "no_complete_sat_witness")
        result = self._invoke(
            self.witness_spec,
            {"runtime_request": dict(plan.search_request or {}), "witness": witness},
            f"witness-{key}",
            witness=witness,
        )
        if result.status is not None:
            return StageResult("witness_check", result.status, result.reason, evidence=result.evidence)
        payload = result.payload or {}
        status = _enum_status(payload.get("status"), ReplayStatus)
        evidence = {**result.evidence, "replay_status": status.value if status else None}
        if status is None:
            return StageResult("witness_check", StageStatus.UNKNOWN, "witness_output_invalid_status", evidence=evidence)
        if status is not ReplayStatus.PASS:
            return StageResult("witness_check", _replay_stage_status(status), payload.get("reason") if isinstance(payload.get("reason"), str) else _status_reason(status), evidence=evidence)
        trace_hash = payload.get("trace_hash")
        if not _HEX64.fullmatch(trace_hash or ""):
            return StageResult("witness_check", StageStatus.UNKNOWN, "witness_output_invalid_trace_hash", evidence=evidence)
        evidence["trace_hash"] = trace_hash
        if trace_hash != witness["trace_hash"]:
            return StageResult("witness_check", StageStatus.FAILED, "witness_trace_hash_mismatch", evidence=evidence)
        candidate_violation = payload.get("candidate_violation")
        property_holds = payload.get("property_holds")
        if not isinstance(candidate_violation, bool) or not isinstance(property_holds, bool):
            return StageResult("witness_check", StageStatus.UNKNOWN, "witness_output_missing_property_observations", evidence=evidence)
        evidence.update({"candidate_violation": candidate_violation, "property_holds": property_holds})
        if not candidate_violation or property_holds:
            return StageResult("witness_check", StageStatus.FAILED, "witness_does_not_demonstrate_violation", evidence=evidence)
        self._witness_paths[key] = result.witness_path or self._write_witness(key, witness)
        self._witness_properties[key] = property_holds
        return StageResult("witness_check", StageStatus.PASSED, evidence=evidence)

    def independent_replay(self, plan: RuntimeCandidatePlan) -> StageResult:
        key = self._key(plan)
        witness_path = self._witness_paths.get(key)
        witness = self._witnesses.get(key)
        if witness_path is None or witness is None:
            return StageResult("independent_replay", StageStatus.NOT_APPLICABLE, "witness_check_not_passed")
        result = IndependentEVMReplay().run(
            self.replay_spec,
            self.replay_workdir,
            witness_path=witness_path,
            cancelled=self.cancelled,
        )
        evidence = {"replay": result.as_dict(), "trace_hash": result.trace_hash}
        if result.status is not ReplayStatus.PASS:
            return StageResult("independent_replay", _replay_stage_status(result.status), result.reason, result.elapsed_seconds, evidence)
        if result.trace_hash != witness["trace_hash"]:
            return StageResult("independent_replay", StageStatus.FAILED, "replay_trace_hash_mismatch", result.elapsed_seconds, evidence)
        expected_property = self._witness_properties.get(key)
        if result.property_holds is None or expected_property is None:
            return StageResult("independent_replay", StageStatus.UNKNOWN, "replay_output_missing_property_observation", result.elapsed_seconds, evidence)
        if result.property_holds != expected_property:
            return StageResult("independent_replay", StageStatus.FAILED, "replay_property_observation_mismatch", result.elapsed_seconds, evidence)
        if result.security_relevance is None:
            return StageResult("independent_replay", StageStatus.UNKNOWN, "replay_output_missing_security_relevance", result.elapsed_seconds, evidence)
        evidence["property_holds"] = result.property_holds
        evidence["security_relevance"] = result.security_relevance
        return StageResult("independent_replay", StageStatus.PASSED, elapsed_seconds=result.elapsed_seconds, evidence=evidence)

    def _invoke(
        self,
        spec: SourceCommandSpec,
        payload: Mapping[str, object],
        stem: str,
        *,
        witness: Mapping[str, object] | None = None,
    ) -> _JsonCommandResult:
        request_path = Path(self._tempdir.name) / f"{stem}.request.json"
        request_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        witness_path: Path | None = None
        if witness is not None:
            witness_path = Path(self._tempdir.name) / f"{stem}.witness.json"
            witness_path.write_text(json.dumps(witness, sort_keys=True) + "\n", encoding="utf-8")
        executable = shutil.which(spec.executable)
        base_evidence: dict[str, object] = {
            "command_spec_hash": spec.spec_hash,
            "request_hash": hashlib.sha256(request_path.read_bytes()).hexdigest(),
        }
        if witness_path is not None:
            base_evidence["witness_input_hash"] = hashlib.sha256(witness_path.read_bytes()).hexdigest()
        if executable is None:
            return _JsonCommandResult(None, StageStatus.UNSUPPORTED, "executable_missing", base_evidence, witness_path)
        arguments = tuple(
            argument.replace("{request}", str(request_path)).replace("{witness}", str(witness_path) if witness_path else "{witness}")
            for argument in spec.arguments
        )
        try:
            outcome = run_process(
                (executable, *arguments),
                cwd=spec.workdir,
                timeout_seconds=spec.timeout_seconds,
                cancelled=self.cancelled,
            )
        except OSError as error:
            return _JsonCommandResult(None, StageStatus.UNKNOWN, f"command_start_failure:{error}", base_evidence, witness_path)
        evidence = {
            **base_evidence,
            "exit_code": outcome.returncode,
            "stdout_hash": hashlib.sha256(outcome.stdout).hexdigest(),
            "stderr_hash": hashlib.sha256(outcome.stderr).hexdigest(),
        }
        if outcome.reason == "timeout":
            return _JsonCommandResult(None, StageStatus.TIMEOUT, "command_timeout", evidence, witness_path)
        if outcome.reason is not None:
            return _JsonCommandResult(None, StageStatus.UNKNOWN, outcome.reason, evidence, witness_path)
        if outcome.returncode != 0:
            return _JsonCommandResult(None, StageStatus.CRASH, "command_nonzero_exit", evidence, witness_path)
        try:
            output = json.loads(outcome.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            return _JsonCommandResult(None, StageStatus.UNKNOWN, f"command_output_parse_failure:{error}", evidence, witness_path)
        if not isinstance(output, dict):
            return _JsonCommandResult(None, StageStatus.UNKNOWN, "command_output_not_object", evidence, witness_path)
        return _JsonCommandResult(output, None, None, evidence, witness_path)

    def _write_witness(self, key: str, witness: Mapping[str, object]) -> Path:
        path = Path(self._tempdir.name) / f"{key}.witness.checked.json"
        path.write_text(json.dumps(witness, sort_keys=True) + "\n", encoding="utf-8")
        return path

    @staticmethod
    def _key(plan: RuntimeCandidatePlan) -> str:
        return plan.cache_key or plan.canonical_ast_hash or plan.candidate.slot_id


def _validate_source_witness(value: object, plan: RuntimeCandidatePlan) -> str | None:
    if not isinstance(value, Mapping):
        return "search_output_missing_witness"
    required = ("witness_id", "query_id", "runtime_hash", "artifact_hash", "deployment_hash", "canonical_ast_hash", "initial_state_hash", "trace_hash", "actions", "domains", "observations")
    if any(not isinstance(value.get(name), (str, list)) for name in required):
        return "source_witness_missing_required_fields"
    for name in ("runtime_hash", "artifact_hash", "deployment_hash", "canonical_ast_hash", "initial_state_hash", "trace_hash"):
        if not isinstance(value.get(name), str) or _HEX64.fullmatch(value[name]) is None:
            return f"source_witness_invalid_{name}"
    request = plan.search_request or {}
    for name in ("runtime_hash", "artifact_hash", "deployment_hash", "canonical_ast_hash", "initial_state_hash"):
        if value[name] != request.get(name):
            return f"source_witness_{name}_mismatch"
    if not isinstance(value["witness_id"], str) or not value["witness_id"] or not isinstance(value["query_id"], str) or not value["query_id"]:
        return "source_witness_invalid_identity"
    if not isinstance(value["actions"], list) or any(not isinstance(action, Mapping) for action in value["actions"]):
        return "source_witness_invalid_actions"
    action_fields = ("action_id", "caller", "caller_role", "calldata", "domain", "contract", "selector")
    raw_bindings = request.get("actions", [])
    allowed_bindings = {
        tuple(str(action.get(field)) for field in ("action_id", "caller_role", "domain", "contract", "selector"))
        for action in raw_bindings
        if isinstance(action, Mapping)
    }
    for action in value["actions"]:
        if any(not isinstance(action.get(field), str) or not action[field] for field in action_fields):
            return "source_witness_action_missing_runtime_fields"
        if not _CALLDATA.fullmatch(action["calldata"]):
            return "source_witness_invalid_calldata"
        if not _SELECTOR.fullmatch(action["selector"]):
            return "source_witness_invalid_selector"
        binding = tuple(action[field] for field in ("action_id", "caller_role", "domain", "contract", "selector"))
        if binding not in allowed_bindings:
            return "source_witness_action_binding_mismatch"
    if not isinstance(value["observations"], (list, Mapping)):
        return "source_witness_invalid_observations"
    if not isinstance(value["domains"], list) or any(not isinstance(domain, str) or not domain for domain in value["domains"]):
        return "source_witness_invalid_domains"
    if len(value["domains"]) != len(set(value["domains"])):
        return "source_witness_duplicate_domains"
    return None


def _enum_status(value: object, enum_type: type[Any]) -> Any | None:
    if not isinstance(value, str):
        return None
    try:
        return enum_type(value)
    except ValueError:
        return None


def _search_stage_status(status: SearchStatus) -> StageStatus:
    return {
        SearchStatus.UNKNOWN: StageStatus.UNKNOWN,
        SearchStatus.TIMEOUT: StageStatus.TIMEOUT,
        SearchStatus.UNSUPPORTED: StageStatus.UNSUPPORTED,
        SearchStatus.CRASH: StageStatus.CRASH,
    }.get(status, StageStatus.UNKNOWN)


def _replay_stage_status(status: ReplayStatus) -> StageStatus:
    return {
        ReplayStatus.FAIL: StageStatus.FAILED,
        ReplayStatus.UNKNOWN: StageStatus.UNKNOWN,
        ReplayStatus.UNSUPPORTED: StageStatus.UNSUPPORTED,
        ReplayStatus.PASS: StageStatus.PASSED,
    }[status]


def _status_reason(status: Any) -> str:
    return f"backend_status:{status.value}"


__all__ = ["SourceBackedVerificationExecutors", "SourceCommandSpec"]
