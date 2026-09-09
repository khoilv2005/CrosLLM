from __future__ import annotations

import unittest

from crossllm.runtime import ReadinessChecker, ReadinessStatus
from crossllm.contracts.canonical import sha256_hex
from crossllm.replay import EVMExecutionSupportMatrix, SupportEntry, SupportStatus


def complete_evidence() -> dict[str, object]:
    fields = (
        "backend_support_matrix", "independent_evm_differential", "witness_checker",
        "development_lineages_reviewed", "evaluation_lineages_reviewed", "split_leakage_checked",
        "corpus_admitted", "source_build_harness_hashes", "independent_positive_validation",
        "independent_control_validation", "selection_locked", "bounds_locked", "precision_study_complete",
        "budget_locked", "method_smoke_coverage", "ablation_smoke_coverage", "sensitivity_smoke_coverage",
        "analysis_rehearsal", "adjudication_rehearsal", "missingness_policy_tested", "isolation_rehearsal",
        "fault_rehearsal", "provider_outage_rehearsal", "commitment_timestamp_before_first_request",
        "dependency_hashes_consistent", "acceptance_owner_assigned", "adjudication_schedule_assigned",
        "compute_quota_storage_plan", "deviation_owners_assigned",
    )
    evidence: dict[str, object] = {field: True for field in fields}
    evidence["backend_support_matrix"] = EVMExecutionSupportMatrix(
        matrix_id="synthetic-v1",
        engine="synthetic-evm",
        engine_revision="1",
        entries=(SupportEntry("opcode", "CALL", SupportStatus.SUPPORTED, evidence_hash="a" * 64),),
        acceptance_status="owner_accepted",
        acceptance_owner="project-owner",
        accepted_at="2026-09-08T00:00:00Z",
        acceptance_agent="codex",
    ).as_dict()
    evidence.update({"admitted_positive_count": 120, "admitted_control_count": 120, "benchmark_manifest_hash": "b"})
    return evidence


class ReadinessTests(unittest.TestCase):
    def test_current_planning_inputs_are_not_evaluation_ready(self) -> None:
        import json
        from pathlib import Path

        root = Path(__file__).parents[2]
        protocol = json.loads((root / "protocol/protocol.json").read_text(encoding="utf-8"))
        models = json.loads((root / "protocol/models.json").read_text(encoding="utf-8"))
        toolchain = json.loads((root / "containers/toolchain.lock.json").read_text(encoding="utf-8"))
        report = ReadinessChecker().check(
            mode="evaluation", protocol=protocol, models=models, toolchain=toolchain,
            campaign_plan=None, evidence=None,
        )
        self.assertFalse(report.ready)
        self.assertEqual(report.gates[0].status, ReadinessStatus.PENDING)
        self.assertIn("G3.03", {gate.gate_id for gate in report.gates})
        self.assertEqual(len(report.report_hash), 64)

    def test_complete_synthetic_lock_set_passes_all_gates(self) -> None:
        protocol = {
            "schema_version": 2, "status": "EVALUATION_LOCKED", "budgets": {},
            "proposal_slots": 8, "evaluation_replicates": 10, "missing_execution_fields": [],
        }
        protocol["lock_hash"] = sha256_hex(protocol)
        models = {"models": [
            {
                "family": family, "requested_tag": f"{family}:tag", "license": "synthetic",
                "license_source": "synthetic://license", "public_weight_and_license_evidence": "synthetic",
                "sources": ["synthetic://model"], "identity_limitations": "synthetic served identity",
                "run_date": "2026-09-08", "effective_api_settings": {"temperature": 0.5}, "preflight_status": "passed",
            }
            for family in ("GLM", "DeepSeek", "Qwen", "gpt-oss")
        ]}
        models["provider"] = {
            "name": "ollama_cloud",
            "base_url": "https://ollama.com",
            "chat_endpoint": "https://ollama.com/api/chat",
            "auth_env": "OLLAMA_API_KEY",
            "execution_mode": "remote_cloud_api",
            "local_weights": False,
        }
        models["lock_hash"] = sha256_hex(models)
        toolchain = {
            "status": "evaluation_locked",
            "images": {"worker": {"ref": "registry.example/worker@sha256:" + "a" * 64}},
            "python_dependencies": {"packages": [{"name": "z3-solver", "version": "5.1.0.0"}]},
        }
        toolchain["lock_hash"] = sha256_hex(toolchain)
        plan = {
            "mode": "evaluation", "campaigns": [{"campaign_id": "c1"}],
            "protocol_lock_hash": protocol["lock_hash"], "model_lock_hash": models["lock_hash"], "benchmark_manifest_hash": "b",
        }
        plan["plan_hash"] = sha256_hex(plan)
        report = ReadinessChecker().check(
            mode="evaluation", protocol=protocol, models=models, toolchain=toolchain,
            campaign_plan=plan, evidence=complete_evidence(),
        )
        self.assertTrue(report.ready, report.as_dict())
        self.assertTrue(all(gate.status is ReadinessStatus.PASS for gate in report.gates))

    def test_explicit_failed_evidence_is_fail_not_pending(self) -> None:
        evidence = complete_evidence()
        evidence["fault_rehearsal"] = False
        report = ReadinessChecker().check(
            mode="development", protocol={"schema_version": 1, "budgets": {}, "proposal_slots": 8},
            models={"models": []}, toolchain={"images": {}}, campaign_plan={"campaigns": [{"campaign_id": "c"}]},
            evidence=evidence,
        )
        gate = next(gate for gate in report.gates if gate.gate_id == "G3.08")
        self.assertEqual(gate.status, ReadinessStatus.FAIL)
        self.assertIn("fault_rehearsal", gate.reasons[0])

    def test_boolean_support_flag_cannot_satisfy_backend_gate(self) -> None:
        evidence = complete_evidence()
        evidence["backend_support_matrix"] = True
        report = ReadinessChecker().check(
            mode="development", protocol={"schema_version": 1, "budgets": {}, "proposal_slots": 8},
            models={"models": []}, toolchain={"images": {}}, campaign_plan={"campaigns": [{"campaign_id": "c"}]},
            evidence=evidence,
        )
        gate = next(gate for gate in report.gates if gate.gate_id == "G3.01")
        self.assertEqual(gate.status, ReadinessStatus.PENDING)

    def test_second_reviewer_field_is_not_required(self) -> None:
        evidence = complete_evidence()
        evidence.pop("acceptance_owner_assigned")
        evidence["adjudication_schedule_assigned"] = True
        report = ReadinessChecker().check(
            mode="development", protocol={"schema_version": 1, "budgets": {}, "proposal_slots": 8},
            models={"models": []}, toolchain={"images": {}}, campaign_plan={"campaigns": [{"campaign_id": "c"}]},
            evidence=evidence,
        )
        gate = next(gate for gate in report.gates if gate.gate_id == "G3.10")
        self.assertEqual(gate.status, ReadinessStatus.PENDING)
        self.assertIn("acceptance_owner_assigned", gate.reasons[0])

    def test_evaluation_model_gate_rejects_local_serving_provider(self) -> None:
        models = {
            "models": [{"family": family} for family in ("GLM", "DeepSeek", "Qwen", "gpt-oss")],
            "provider": {
                "name": "ollama_local",
                "base_url": "http://localhost:11434",
                "chat_endpoint": "http://localhost:11434/api/chat",
                "auth_env": "NONE",
                "execution_mode": "local_weights",
                "local_weights": True,
            },
        }
        report = ReadinessChecker().check(
            mode="evaluation", protocol=None, models=models, toolchain=None,
            campaign_plan=None, evidence=None,
        )
        gate = next(gate for gate in report.gates if gate.gate_id == "G3.04")
        self.assertEqual(gate.status, ReadinessStatus.FAIL)
        self.assertIn("ollama_cloud", " ".join(gate.reasons))


if __name__ == "__main__":
    unittest.main()
