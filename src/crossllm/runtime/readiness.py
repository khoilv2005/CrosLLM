"""Conservative G3 readiness checks for development and evaluation runs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Any, Mapping, Sequence

from ..contracts.canonical import sha256_hex
from ..replay.support import EVMExecutionSupportMatrix


class ReadinessStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    PENDING = "PENDING"


@dataclass(frozen=True, slots=True)
class ReadinessGate:
    gate_id: str
    status: ReadinessStatus
    reasons: tuple[str, ...]
    evidence: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "gate_id": self.gate_id,
            "status": self.status.value,
            "reasons": list(self.reasons),
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    mode: str
    ready: bool
    gates: tuple[ReadinessGate, ...]
    report_hash: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "mode": self.mode,
            "ready": self.ready,
            "gates": [gate.as_dict() for gate in self.gates],
            "report_hash": self.report_hash,
        }


class EvaluationLaunchBlocked(RuntimeError):
    """Raised when an evaluation launch is attempted before G3 is complete."""

    def __init__(self, decision: "EvaluationLaunchDecision") -> None:
        self.decision = decision
        super().__init__("evaluation launch blocked: " + "; ".join(decision.reasons))


@dataclass(frozen=True, slots=True)
class EvaluationLaunchDecision:
    """Side-effect-free decision at the boundary immediately before execution."""

    allowed: bool
    mode: str
    readiness_report_hash: str
    reasons: tuple[str, ...]
    provider_calls_started: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "allowed": self.allowed,
            "mode": self.mode,
            "readiness_report_hash": self.readiness_report_hash,
            "reasons": list(self.reasons),
            "provider_calls_started": self.provider_calls_started,
        }


class EvaluationLaunchGuard:
    """Fail closed before the first evaluation provider request.

    This guard is intentionally separate from readiness construction. A caller
    must supply a previously generated, hash-consistent evaluation report; a
    development report, a tampered report, an incomplete gate set, or a plan
    explicitly marked non-admissible can never reach an evaluation runner.
    The guard itself performs no I/O and starts no provider calls.
    """

    _REQUIRED_GATE_IDS = frozenset({
        "protocol", "G3.01", "G3.02", "G3.03", "G3.04", "toolchain",
        "campaign_plan", "G3.05", "G3.06", "G3.07", "G3.08", "G3.09", "G3.10",
    })

    def check(
        self,
        report: ReadinessReport,
        *,
        campaign_plan: Mapping[str, Any] | None = None,
        campaign_ids: Sequence[str] | None = None,
    ) -> EvaluationLaunchDecision:
        reasons: list[str] = []
        if not isinstance(report, ReadinessReport):
            return EvaluationLaunchDecision(
                False, "unknown", "", ("readiness report must be a ReadinessReport",), False,
            )
        if report.mode != "evaluation":
            reasons.append("readiness report mode is not evaluation")
        expected_payload = {
            "mode": report.mode,
            "ready": report.ready,
            "gates": [gate.as_dict() for gate in report.gates],
        }
        if report.report_hash != sha256_hex(expected_payload):
            reasons.append("readiness report hash mismatch")
        gate_ids = [gate.gate_id for gate in report.gates]
        missing = sorted(self._REQUIRED_GATE_IDS - set(gate_ids))
        if missing:
            reasons.append("readiness report is missing gates: " + ", ".join(missing))
        duplicates = sorted(gate_id for gate_id in set(gate_ids) if gate_ids.count(gate_id) > 1)
        if duplicates:
            reasons.append("readiness report has duplicate gates: " + ", ".join(duplicates))
        failed = [
            gate.gate_id for gate in report.gates
            if gate.status is not ReadinessStatus.PASS
        ]
        if failed:
            reasons.append("readiness gates are not all PASS: " + ", ".join(failed))
        if report.ready is not True:
            reasons.append("readiness report is not ready")
        if campaign_plan is None:
            reasons.append("campaign plan is required for evaluation launch")
        elif not isinstance(campaign_plan, Mapping):
            reasons.append("campaign plan must be a JSON object")
        else:
            if campaign_plan.get("mode") != "evaluation":
                reasons.append("campaign plan mode is not evaluation")
            if campaign_plan.get("admission_eligible") is False:
                reasons.append("campaign plan is explicitly non-admissible")
            if campaign_plan.get("evaluation_lock") is False:
                reasons.append("campaign plan is explicitly not evaluation-locked")
            planned_ids = _campaign_ids(campaign_plan)
            if not planned_ids:
                reasons.append("campaign plan has no valid campaign IDs")
            if campaign_ids is not None:
                unplanned = sorted(set(campaign_ids) - planned_ids)
                if unplanned:
                    reasons.append("task campaign IDs are not in plan: " + ", ".join(unplanned))
        return EvaluationLaunchDecision(
            not reasons,
            report.mode,
            report.report_hash,
            tuple(reasons) if reasons else ("all evaluation launch gates passed",),
            False,
        )

    def assert_ready(
        self,
        report: ReadinessReport,
        *,
        campaign_plan: Mapping[str, Any] | None = None,
        campaign_ids: Sequence[str] | None = None,
    ) -> EvaluationLaunchDecision:
        decision = self.check(report, campaign_plan=campaign_plan, campaign_ids=campaign_ids)
        if not decision.allowed:
            raise EvaluationLaunchBlocked(decision)
        return decision


class ReadinessChecker:
    """Evaluate explicit G3 evidence without inferring missing evidence.

    The checker deliberately treats absent values as ``PENDING`` and explicit
    negative assertions as ``FAIL``. No command-line flag can override a gate.
    Served-weight digests are not required here because the protocol permits a
    documented unknown digest limitation; effective settings and preflight are
    still required for evaluation.
    """

    def check(
        self,
        *,
        mode: str,
        protocol: Mapping[str, Any] | None,
        models: Mapping[str, Any] | None,
        toolchain: Mapping[str, Any] | None,
        campaign_plan: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
        evidence: Mapping[str, Any] | None,
    ) -> ReadinessReport:
        if mode not in {"development", "evaluation"}:
            raise ValueError("mode must be development or evaluation")
        gates = (
            self._protocol_gate(mode, protocol),
            self._model_gate(mode, models),
            self._toolchain_gate(mode, toolchain),
            self._campaign_gate(mode, campaign_plan, protocol, models, evidence),
            self._backend_gate(evidence),
            self._evidence_gate("G3.02", evidence, (
                "development_lineages_reviewed",
                "evaluation_lineages_reviewed",
                "split_leakage_checked",
            )),
            self._corpus_gate(evidence),
            self._evidence_gate("G3.05", evidence, (
                "selection_locked",
                "bounds_locked",
                "precision_study_complete",
                "budget_locked",
            )),
            self._evidence_gate("G3.06", evidence, (
                "method_smoke_coverage",
                "ablation_smoke_coverage",
                "sensitivity_smoke_coverage",
            )),
            self._evidence_gate("G3.07", evidence, (
                "analysis_rehearsal",
                "adjudication_rehearsal",
                "missingness_policy_tested",
            )),
            self._evidence_gate("G3.08", evidence, (
                "isolation_rehearsal",
                "fault_rehearsal",
                "provider_outage_rehearsal",
            )),
            self._evidence_gate("G3.09", evidence, (
                "commitment_timestamp_before_first_request",
                "dependency_hashes_consistent",
            )),
            self._evidence_gate("G3.10", evidence, (
                "acceptance_owner_assigned",
                "adjudication_schedule_assigned",
                "compute_quota_storage_plan",
                "deviation_owners_assigned",
            )),
        )
        # Model preflight is a dedicated gate, but G3.04 remains visible in the
        # report so the output maps one-to-one to the implementation plan.
        model_gate = gates[1]
        gates = gates[:1] + (
            ReadinessGate("G3.04", model_gate.status, model_gate.reasons, model_gate.evidence),
        ) + gates[2:]
        ready = all(gate.status is ReadinessStatus.PASS for gate in gates)
        payload = {"mode": mode, "ready": ready, "gates": [gate.as_dict() for gate in gates]}
        return ReadinessReport(mode, ready, gates, sha256_hex(payload))

    @staticmethod
    def _backend_gate(evidence: Mapping[str, Any] | None) -> ReadinessGate:
        if evidence is None:
            return ReadinessGate("G3.01", ReadinessStatus.PENDING, ("evidence index is missing",))
        raw_matrix = evidence.get("backend_support_matrix")
        if raw_matrix is True:
            return ReadinessGate("G3.01", ReadinessStatus.PENDING, ("owner-accepted backend support matrix record is required",))
        if raw_matrix is False:
            return ReadinessGate("G3.01", ReadinessStatus.FAIL, ("backend support matrix explicitly failed",))
        if not isinstance(raw_matrix, Mapping):
            return ReadinessGate("G3.01", ReadinessStatus.PENDING, ("backend support matrix record is missing",))
        try:
            matrix = EVMExecutionSupportMatrix.from_dict(raw_matrix)
        except ValueError as error:
            return ReadinessGate("G3.01", ReadinessStatus.FAIL, (f"invalid backend support matrix: {error}",))
        if matrix.acceptance_status != "owner_accepted":
            return ReadinessGate("G3.01", ReadinessStatus.PENDING, ("backend support matrix is not owner-accepted",))
        other = ReadinessChecker._evidence_gate("G3.01", evidence, (
            "independent_evm_differential", "witness_checker",
        ))
        if other.status is not ReadinessStatus.PASS:
            return other
        return ReadinessGate(
            "G3.01", ReadinessStatus.PASS,
            ("owner-accepted backend support matrix and replay evidence are present",),
            ("backend_support_matrix", "independent_evm_differential", "witness_checker"),
        )

    @staticmethod
    def _protocol_gate(mode: str, protocol: Mapping[str, Any] | None) -> ReadinessGate:
        if protocol is None:
            return ReadinessGate("protocol", ReadinessStatus.PENDING, ("protocol lock is missing",))
        required = ("schema_version", "budgets", "proposal_slots")
        missing = tuple(field for field in required if field not in protocol)
        if missing:
            return ReadinessGate("protocol", ReadinessStatus.FAIL, (f"missing fields: {', '.join(missing)}",))
        if mode == "development":
            return ReadinessGate("protocol", ReadinessStatus.PASS, ("development protocol accepted",))
        status = str(protocol.get("status", ""))
        if "PROSPECTIVE" in status or status not in {"LOCKED", "EVALUATION_LOCKED"}:
            return ReadinessGate("protocol", ReadinessStatus.PENDING, ("protocol is not an evaluation lock",))
        replicates = protocol.get("evaluation_replicates")
        if not isinstance(replicates, int) or isinstance(replicates, bool) or replicates <= 0:
            return ReadinessGate("protocol", ReadinessStatus.PENDING, ("evaluation_replicates is not a positive locked integer",))
        missing_execution = protocol.get("missing_execution_fields", ())
        if missing_execution:
            return ReadinessGate("protocol", ReadinessStatus.PENDING, ("missing execution fields remain",))
        lock_error = _lock_hash_error(protocol, "lock_hash")
        if lock_error is not None:
            return ReadinessGate("protocol", ReadinessStatus.FAIL if "mismatch" in lock_error else ReadinessStatus.PENDING, (lock_error,))
        return ReadinessGate("protocol", ReadinessStatus.PASS, ("evaluation protocol lock is complete",))

    @staticmethod
    def _model_gate(mode: str, models: Mapping[str, Any] | None) -> ReadinessGate:
        if models is None:
            return ReadinessGate("models", ReadinessStatus.PENDING, ("model lock/metadata is missing",))
        rows = models.get("models")
        if not isinstance(rows, list):
            return ReadinessGate("models", ReadinessStatus.FAIL, ("models must be a list",))
        expected = {"GLM", "DeepSeek", "Qwen", "gpt-oss"}
        observed = {row.get("family") for row in rows if isinstance(row, dict)}
        missing = sorted(expected - observed)
        if missing:
            return ReadinessGate("models", ReadinessStatus.PENDING, (f"model families missing: {', '.join(missing)}",))
        duplicates = sorted(family for family in expected if sum(row.get("family") == family for row in rows if isinstance(row, dict)) > 1)
        if duplicates:
            return ReadinessGate("models", ReadinessStatus.FAIL, (f"duplicate model families: {', '.join(duplicates)}",))
        if mode == "development":
            return ReadinessGate("models", ReadinessStatus.PASS, ("development metadata covers four model families",))
        provider = models.get("provider")
        if not isinstance(provider, dict):
            return ReadinessGate("models", ReadinessStatus.PENDING, ("evaluation model metadata has no provider execution block",))
        provider_errors = []
        if provider.get("name") != "ollama_cloud":
            provider_errors.append("provider.name must be ollama_cloud")
        if provider.get("base_url") != "https://ollama.com":
            provider_errors.append("provider.base_url must be https://ollama.com")
        if provider.get("chat_endpoint") != "https://ollama.com/api/chat":
            provider_errors.append("provider.chat_endpoint must be https://ollama.com/api/chat")
        if provider.get("execution_mode") != "remote_cloud_api":
            provider_errors.append("provider.execution_mode must be remote_cloud_api")
        if provider.get("auth_env") != "OLLAMA_API_KEY":
            provider_errors.append("provider.auth_env must be OLLAMA_API_KEY")
        if provider.get("local_weights") is not False:
            provider_errors.append("provider.local_weights must be false")
        if provider_errors:
            return ReadinessGate("models", ReadinessStatus.FAIL, tuple(provider_errors))
        incomplete: list[str] = []
        failed: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                incomplete.append("non-object model row")
                continue
            family = str(row.get("family", "unknown"))
            for field in ("requested_tag", "license", "license_source", "public_weight_and_license_evidence"):
                if not isinstance(row.get(field), str) or not row[field].strip():
                    incomplete.append(f"{family}.{field}")
            sources = row.get("sources")
            if not isinstance(sources, list) or not sources or any(not isinstance(source, str) or not source for source in sources):
                incomplete.append(f"{family}.sources")
            if not isinstance(row.get("run_date"), str) or not row["run_date"]:
                incomplete.append(f"{family}.run_date")
            if not isinstance(row.get("effective_api_settings"), dict) or not row["effective_api_settings"]:
                incomplete.append(f"{family}.effective_api_settings")
            if row.get("preflight_status") != "passed":
                if "preflight_status" not in row or row.get("preflight_status") in (None, ""):
                    incomplete.append(f"{family}.preflight_status")
                else:
                    failed.append(f"{family}.preflight_status")
            identity_is_missing = not isinstance(row.get("served_weight_digest"), str) or not row.get("served_weight_digest") or row.get("immutable_served_weights_guaranteed") is not True
            if identity_is_missing and (not isinstance(row.get("identity_limitations"), str) or not row["identity_limitations"].strip()):
                incomplete.append(f"{family}.identity_limitations")
        if incomplete:
            return ReadinessGate("models", ReadinessStatus.PENDING, ("live preflight incomplete: " + ", ".join(incomplete),))
        if failed:
            return ReadinessGate("models", ReadinessStatus.FAIL, ("live preflight failed: " + ", ".join(failed),))
        lock_error = _lock_hash_error(models, "lock_hash")
        if lock_error is not None:
            return ReadinessGate("models", ReadinessStatus.FAIL if "mismatch" in lock_error else ReadinessStatus.PENDING, (lock_error,))
        return ReadinessGate("models", ReadinessStatus.PASS, ("four model families have runtime preflight evidence",))

    @staticmethod
    def _toolchain_gate(mode: str, toolchain: Mapping[str, Any] | None) -> ReadinessGate:
        if toolchain is None:
            return ReadinessGate("toolchain", ReadinessStatus.PENDING, ("toolchain lock is missing",))
        images = toolchain.get("images")
        if not isinstance(images, dict):
            return ReadinessGate("toolchain", ReadinessStatus.FAIL, ("toolchain images are missing",))
        if not images:
            return ReadinessGate("toolchain", ReadinessStatus.PENDING, ("toolchain image lock is empty",))
        unpinned = tuple(name for name, row in images.items() if not isinstance(row, dict) or not _is_digest_ref(str(row.get("ref", ""))))
        if unpinned:
            return ReadinessGate("toolchain", ReadinessStatus.PENDING, (f"unpinned image references: {', '.join(unpinned)}",))
        if mode == "development":
            return ReadinessGate("toolchain", ReadinessStatus.PASS, ("development toolchain probe is available",))
        if toolchain.get("status") != "evaluation_locked":
            return ReadinessGate("toolchain", ReadinessStatus.PENDING, ("toolchain is not evaluation_locked",))
        packages = toolchain.get("python_dependencies", {}).get("packages", [])
        if not packages:
            return ReadinessGate("toolchain", ReadinessStatus.PENDING, ("Python dependency lock is empty",))
        lock_error = _lock_hash_error(toolchain, "lock_hash")
        if lock_error is not None:
            return ReadinessGate("toolchain", ReadinessStatus.FAIL if "mismatch" in lock_error else ReadinessStatus.PENDING, (lock_error,))
        return ReadinessGate("toolchain", ReadinessStatus.PASS, ("evaluation toolchain and Python dependencies are locked",))

    @staticmethod
    def _campaign_gate(
        mode: str,
        campaign_plan: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
        protocol: Mapping[str, Any] | None,
        models: Mapping[str, Any] | None,
        evidence: Mapping[str, Any] | None,
    ) -> ReadinessGate:
        if campaign_plan is None:
            return ReadinessGate("campaign_plan", ReadinessStatus.PENDING, ("campaign plan is missing",))
        if isinstance(campaign_plan, Mapping):
            rows = campaign_plan.get("campaigns")
            metadata = campaign_plan
        else:
            rows = campaign_plan
            metadata = {}
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)) or not rows:
            return ReadinessGate("campaign_plan", ReadinessStatus.FAIL, ("campaign plan has no campaigns",))
        if mode == "development":
            return ReadinessGate("campaign_plan", ReadinessStatus.PASS, (f"development plan has {len(rows)} campaigns",))
        missing = tuple(field for field in ("protocol_lock_hash", "model_lock_hash", "benchmark_manifest_hash") if not metadata.get(field))
        if missing:
            return ReadinessGate("campaign_plan", ReadinessStatus.PENDING, (f"evaluation plan missing lock hashes: {', '.join(missing)}",))
        if metadata.get("mode") != "evaluation":
            return ReadinessGate("campaign_plan", ReadinessStatus.PENDING, ("campaign plan mode is not evaluation",))
        lock_error = _lock_hash_error(metadata, "plan_hash")
        if lock_error is not None:
            return ReadinessGate("campaign_plan", ReadinessStatus.FAIL if "mismatch" in lock_error else ReadinessStatus.PENDING, (lock_error,))
        if protocol is None or metadata.get("protocol_lock_hash") != protocol.get("lock_hash"):
            return ReadinessGate("campaign_plan", ReadinessStatus.PENDING, ("campaign protocol lock hash does not match protocol artifact",))
        if models is None or metadata.get("model_lock_hash") != models.get("lock_hash"):
            return ReadinessGate("campaign_plan", ReadinessStatus.PENDING, ("campaign model lock hash does not match model artifact",))
        if evidence is None or metadata.get("benchmark_manifest_hash") != evidence.get("benchmark_manifest_hash"):
            return ReadinessGate("campaign_plan", ReadinessStatus.PENDING, ("campaign benchmark hash is not linked to evidence",))
        return ReadinessGate("campaign_plan", ReadinessStatus.PASS, (f"evaluation plan has {len(rows)} campaigns",))

    @classmethod
    def _corpus_gate(cls, evidence: Mapping[str, Any] | None) -> ReadinessGate:
        if evidence is None:
            return ReadinessGate("G3.03", ReadinessStatus.PENDING, ("corpus evidence index is missing",))
        required = ("corpus_admitted", "source_build_harness_hashes", "independent_positive_validation", "independent_control_validation")
        gate = cls._evidence_gate("G3.03", evidence, required)
        if gate.status is not ReadinessStatus.PASS:
            return gate
        counts = (evidence.get("admitted_positive_count"), evidence.get("admitted_control_count"))
        if any(not isinstance(count, int) or count < 120 for count in counts):
            return ReadinessGate("G3.03", ReadinessStatus.PENDING, ("admitted corpus counts do not meet 120/120 target",))
        return ReadinessGate("G3.03", ReadinessStatus.PASS, ("admitted positives and controls meet target",))

    @staticmethod
    def _evidence_gate(
        gate_id: str,
        evidence: Mapping[str, Any] | None,
        fields: Sequence[str],
    ) -> ReadinessGate:
        if evidence is None:
            return ReadinessGate(gate_id, ReadinessStatus.PENDING, ("evidence index is missing",))
        missing = tuple(field for field in fields if field not in evidence)
        if missing:
            return ReadinessGate(gate_id, ReadinessStatus.PENDING, (f"evidence missing: {', '.join(missing)}",))
        failed = tuple(field for field in fields if evidence.get(field) is not True)
        if failed:
            return ReadinessGate(gate_id, ReadinessStatus.FAIL, (f"evidence explicitly failed: {', '.join(failed)}",))
        return ReadinessGate(gate_id, ReadinessStatus.PASS, ("required evidence is present",), tuple(fields))


def _is_digest_ref(value: str) -> bool:
    return bool(re.search(r"@sha256:[0-9a-fA-F]{64}$", value))


def _lock_hash_error(payload: Mapping[str, Any], field: str) -> str | None:
    supplied = payload.get(field)
    if not isinstance(supplied, str) or not supplied:
        return f"{field} is missing"
    unsigned = {key: value for key, value in payload.items() if key != field}
    if supplied != sha256_hex(unsigned):
        return f"{field} mismatch"
    return None


def _campaign_ids(campaign_plan: Mapping[str, Any]) -> set[str]:
    rows = campaign_plan.get("campaigns")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return set()
    identifiers: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            return set()
        campaign_id = row.get("campaign_id")
        if not isinstance(campaign_id, str) or not campaign_id:
            return set()
        identifiers.append(campaign_id)
    if len(identifiers) != len(set(identifiers)):
        return set()
    return set(identifiers)
