from __future__ import annotations

import unittest

from crossllm.runtime import (
    AdmissionStatus,
    Quota,
    ResourceEnvelope,
    ResourceObservation,
    ResourceRequest,
    ResourceUsage,
    WorkerResourceScheduler,
)


class RuntimeResourceTests(unittest.TestCase):
    def test_default_worker_envelope_is_four_cores_and_sixteen_gib(self) -> None:
        envelope = ResourceEnvelope()
        self.assertEqual(envelope.cpu_cores, 4)
        self.assertEqual(envelope.memory_bytes, 16 * 1024**3)
        self.assertEqual(envelope.max_solver_processes_per_profile, 1)

    def test_admission_enforces_capacity_and_allows_concurrent_campaigns(self) -> None:
        scheduler = WorkerResourceScheduler(
            ResourceEnvelope(cpu_cores=4, memory_bytes=16, max_concurrent_campaigns=4)
        )
        first = scheduler.submit(ResourceRequest("c1", 2, 8, solver_profile="profile-a"))
        second = scheduler.submit(ResourceRequest("c2", 2, 8, solver_profile="profile-b"))
        third = scheduler.submit(ResourceRequest("c3", 1, 1, solver_profile="profile-c"))
        self.assertEqual(first.status, AdmissionStatus.ADMITTED)
        self.assertEqual(second.status, AdmissionStatus.ADMITTED)
        self.assertEqual(third.status, AdmissionStatus.QUEUED)
        self.assertEqual(third.reason, "CPU capacity unavailable")
        self.assertEqual(scheduler.snapshot().active_campaigns, 2)

        admitted = scheduler.release(first.lease_id, ResourceUsage(cpu_core_seconds=2.5, wall_seconds=3.0))
        self.assertEqual(len(admitted), 1)
        self.assertEqual(admitted[0].status, AdmissionStatus.ADMITTED)
        self.assertEqual(admitted[0].campaign_id, "c3")
        self.assertEqual(scheduler.snapshot().used_core_seconds, 2.5)

    def test_one_solver_process_per_profile_is_serialized(self) -> None:
        scheduler = WorkerResourceScheduler(
            ResourceEnvelope(cpu_cores=4, memory_bytes=16, max_concurrent_campaigns=4)
        )
        first = scheduler.submit(ResourceRequest("c1", 1, 4, solver_profile="z3-profile"))
        second = scheduler.submit(ResourceRequest("c2", 1, 4, solver_profile="z3-profile"))
        self.assertEqual(first.status, AdmissionStatus.ADMITTED)
        self.assertEqual(second.status, AdmissionStatus.QUEUED)
        self.assertEqual(second.reason, "solver profile is already active")
        admitted = scheduler.release(first.lease_id, ResourceUsage())
        self.assertEqual(admitted[0].campaign_id, "c2")
        self.assertEqual(scheduler.snapshot().active_solver_profiles, ("z3-profile",))

    def test_quota_exhaustion_queues_then_rejects_impossible_request(self) -> None:
        scheduler = WorkerResourceScheduler(
            ResourceEnvelope(cpu_cores=4, memory_bytes=16, max_concurrent_campaigns=4),
            Quota(max_core_seconds=5.0, max_generated_tokens=100),
        )
        first = scheduler.submit(ResourceRequest("c1", 1, 1, estimated_core_seconds=4.0, estimated_generated_tokens=80))
        second = scheduler.submit(ResourceRequest("c2", 1, 1, estimated_core_seconds=2.0, estimated_generated_tokens=20))
        impossible = scheduler.submit(ResourceRequest("c3", 1, 1, estimated_core_seconds=6.0))
        self.assertEqual(first.status, AdmissionStatus.ADMITTED)
        self.assertEqual(second.status, AdmissionStatus.QUEUED)
        self.assertEqual(second.reason, "quota temporarily unavailable")
        self.assertEqual(impossible.status, AdmissionStatus.REJECTED)
        self.assertIn("exceed quota", impossible.reason)

        admitted = scheduler.release(first.lease_id, ResourceUsage(cpu_core_seconds=3.0, generated_tokens=60))
        self.assertEqual(admitted[0].status, AdmissionStatus.ADMITTED)
        self.assertEqual(admitted[0].campaign_id, "c2")
        self.assertEqual(scheduler.snapshot().queued_campaigns, 0)

    def test_observation_reports_worker_and_campaign_limit_violations(self) -> None:
        scheduler = WorkerResourceScheduler(ResourceEnvelope(cpu_cores=4, memory_bytes=16))
        request = ResourceRequest("c1", 2, 8)
        violations = scheduler.observe(request, ResourceObservation(active_cpu_cores=5, memory_high_water_bytes=20))
        self.assertEqual(
            violations,
            (
                "worker CPU envelope exceeded",
                "campaign CPU allocation exceeded",
                "worker memory envelope exceeded",
                "campaign memory allocation exceeded",
            ),
        )

    def test_resource_usage_preserves_missing_token_measurements_as_null(self) -> None:
        usage = ResourceUsage(missing_field_reasons={"generated_tokens": "provider_omitted_usage"})
        self.assertIsNone(usage.as_resource_vector()["generated_tokens"])
        self.assertEqual(usage.as_resource_vector()["missing_field_reasons"]["generated_tokens"], "provider_omitted_usage")


if __name__ == "__main__":
    unittest.main()
