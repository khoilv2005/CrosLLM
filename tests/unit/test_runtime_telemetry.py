from __future__ import annotations

import unittest

from crossllm.runtime import EffortPhase, ResourceUsage, TelemetryLedger, TelemetryRecord


class RuntimeTelemetryTests(unittest.TestCase):
    def test_method_horizon_and_adjudication_effort_are_separate(self) -> None:
        ledger = TelemetryLedger()
        ledger.append(TelemetryRecord(
            EffortPhase.METHOD_HORIZON,
            ResourceUsage(cpu_core_seconds=2.0, solver_seconds=1.0, wall_seconds=3.0, input_tokens=10, generated_tokens=4, cost_usd=0.2),
            campaign_id="c1", attempt_id="a1", queue_seconds=1.0, throttled_seconds=0.5, throttle_count=1,
        ))
        ledger.append(TelemetryRecord(
            EffortPhase.ADJUDICATION,
            ResourceUsage(cpu_core_seconds=5.0, solver_seconds=0.0, wall_seconds=6.0, input_tokens=20, generated_tokens=8, cost_usd=0.3),
            campaign_id="c1", attempt_id="a1",
        ))
        method = ledger.aggregate(EffortPhase.METHOD_HORIZON)
        adjudication = ledger.aggregate(EffortPhase.ADJUDICATION)
        self.assertEqual(method["cpu_core_seconds"], 2.0)
        self.assertEqual(method["queue_seconds"], 1.0)
        self.assertEqual(method["throttle_count"], 1)
        self.assertEqual(method["generated_tokens"], 4)
        self.assertEqual(adjudication["cpu_core_seconds"], 5.0)
        self.assertEqual(adjudication["cost_usd"], 0.3)

    def test_unknown_token_usage_stays_unknown_in_aggregate(self) -> None:
        ledger = TelemetryLedger()
        ledger.append(TelemetryRecord(
            EffortPhase.METHOD_HORIZON,
            ResourceUsage(input_tokens=10, generated_tokens=None, missing_field_reasons={"generated_tokens": "provider_omitted_usage"}),
        ))
        ledger.append(TelemetryRecord(
            EffortPhase.METHOD_HORIZON,
            ResourceUsage(input_tokens=20, generated_tokens=5),
        ))
        aggregate = ledger.aggregate(EffortPhase.METHOD_HORIZON)
        self.assertEqual(aggregate["input_tokens"], 30)
        self.assertIsNone(aggregate["generated_tokens"])
        self.assertEqual(aggregate["missing_field_reasons"]["generated_tokens"], "provider_omitted_usage")

    def test_resource_record_contains_explicit_phase_and_identity(self) -> None:
        record = TelemetryRecord(
            EffortPhase.PREPROCESSING,
            ResourceUsage(memory_high_water_bytes=100),
            campaign_id="c1", attempt_id="a1", worker_id="worker-1",
        )
        payload = record.as_dict()
        self.assertEqual(payload["phase"], "preprocessing")
        self.assertEqual(payload["campaign_id"], "c1")
        self.assertEqual(payload["memory_high_water_bytes"], 100)

    def test_resource_vector_preserves_measured_cost(self) -> None:
        self.assertEqual(ResourceUsage(cost_usd=0.42).as_resource_vector()["cost_usd"], 0.42)


if __name__ == "__main__":
    unittest.main()
