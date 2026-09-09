from __future__ import annotations

import unittest

from crossllm.contracts import CampaignStatus
from crossllm.contracts.canonical import sha256_hex
from crossllm.runtime import (
    EvaluationLaunchBlocked,
    EvaluationLaunchGuard,
    EvaluationRunner,
    ReadinessGate,
    ReadinessReport,
    ReadinessStatus,
    ResourceRequest,
    WorkerTask,
)


def ready_report() -> ReadinessReport:
    gate_ids = (
        "protocol", "G3.01", "G3.02", "G3.03", "G3.04", "toolchain",
        "campaign_plan", "G3.05", "G3.06", "G3.07", "G3.08", "G3.09", "G3.10",
    )
    gates = tuple(ReadinessGate(gate_id, ReadinessStatus.PASS, ("ok",)) for gate_id in gate_ids)
    payload = {
        "mode": "evaluation",
        "ready": True,
        "gates": [gate.as_dict() for gate in gates],
    }
    return ReadinessReport("evaluation", True, gates, sha256_hex(payload))


class EvaluationLaunchGuardTests(unittest.TestCase):
    def test_complete_report_allows_launch_without_provider_side_effect(self) -> None:
        decision = EvaluationLaunchGuard().check(
            ready_report(),
            campaign_plan={
                "mode": "evaluation", "admission_eligible": True,
                "campaigns": [{"campaign_id": "evaluation-campaign"}],
            },
        )
        self.assertTrue(decision.allowed)
        self.assertFalse(decision.provider_calls_started)

    def test_development_report_and_non_admissible_plan_are_blocked(self) -> None:
        report = ready_report()
        development = ReadinessReport(
            "development", report.ready, report.gates,
            sha256_hex({
                "mode": "development",
                "ready": report.ready,
                "gates": [gate.as_dict() for gate in report.gates],
            }),
        )
        decision = EvaluationLaunchGuard().check(
            development,
            campaign_plan={"mode": "development", "admission_eligible": False, "evaluation_lock": False},
        )
        self.assertFalse(decision.allowed)
        self.assertIn("mode is not evaluation", " ".join(decision.reasons))
        self.assertIn("non-admissible", " ".join(decision.reasons))
        self.assertIn("not evaluation-locked", " ".join(decision.reasons))

    def test_tampered_report_and_missing_gate_are_blocked(self) -> None:
        report = ready_report()
        tampered = ReadinessReport(
            report.mode,
            report.ready,
            report.gates[:-1],
            report.report_hash,
        )
        decision = EvaluationLaunchGuard().check(tampered)
        self.assertFalse(decision.allowed)
        self.assertIn("hash mismatch", " ".join(decision.reasons))
        self.assertIn("missing gates", " ".join(decision.reasons))

    def test_assert_ready_raises_before_execution(self) -> None:
        report = ready_report()
        blocked = ReadinessReport(
            report.mode,
            False,
            report.gates,
            sha256_hex({
                "mode": report.mode,
                "ready": False,
                "gates": [gate.as_dict() for gate in report.gates],
            }),
        )
        with self.assertRaises(EvaluationLaunchBlocked) as context:
            EvaluationLaunchGuard().assert_ready(blocked)
        self.assertFalse(context.exception.decision.provider_calls_started)

    def test_evaluation_runner_checks_guard_before_task_callback(self) -> None:
        calls = 0

        def execute() -> str:
            nonlocal calls
            calls += 1
            return "ok"

        task = WorkerTask(
            "evaluation-campaign",
            "evaluation-attempt",
            ResourceRequest("evaluation-campaign", 1, 1),
            execute,
        )
        base = ready_report()
        blocked_report = ReadinessReport(
            "evaluation", False, base.gates,
            sha256_hex({
                "mode": "evaluation",
                "ready": False,
                "gates": [gate.as_dict() for gate in base.gates],
            }),
        )
        with self.assertRaises(EvaluationLaunchBlocked):
            EvaluationRunner().run([task], readiness_report=blocked_report)
        self.assertEqual(calls, 0)

        result = EvaluationRunner().run(
            [task],
            readiness_report=base,
            campaign_plan={
                "mode": "evaluation", "admission_eligible": True,
                "campaigns": [{"campaign_id": "evaluation-campaign"}],
            },
        )
        self.assertEqual(calls, 1)
        self.assertEqual(result.runs[0].status, CampaignStatus.COMPLETED)

    def test_evaluation_runner_rejects_unplanned_campaign_before_callback(self) -> None:
        calls = 0

        def execute() -> str:
            nonlocal calls
            calls += 1
            return "must not run"

        task = WorkerTask(
            "not-planned",
            "not-planned-attempt",
            ResourceRequest("not-planned", 1, 1),
            execute,
        )
        with self.assertRaises(EvaluationLaunchBlocked) as context:
            EvaluationRunner().run(
                [task],
                readiness_report=ready_report(),
                campaign_plan={
                    "mode": "evaluation",
                    "campaigns": [{"campaign_id": "planned"}],
                },
            )
        self.assertEqual(calls, 0)
        self.assertIn("not in plan", " ".join(context.exception.decision.reasons))


if __name__ == "__main__":
    unittest.main()
