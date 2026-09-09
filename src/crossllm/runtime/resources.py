"""Resource envelopes, quota-aware admission and runtime observations for M08.02."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from threading import RLock
from typing import Any


DEFAULT_WORKER_CPU_CORES = 4
DEFAULT_WORKER_MEMORY_BYTES = 16 * 1024**3


class AdmissionStatus(StrEnum):
    ADMITTED = "admitted"
    QUEUED = "queued"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ResourceEnvelope:
    """Hard resources available to one worker.

    The envelope is intentionally explicit instead of relying on host capacity.
    A production worker/container must enforce the same values outside Python.
    """

    cpu_cores: int = DEFAULT_WORKER_CPU_CORES
    memory_bytes: int = DEFAULT_WORKER_MEMORY_BYTES
    max_concurrent_campaigns: int = DEFAULT_WORKER_CPU_CORES
    max_solver_processes_per_profile: int = 1

    def __post_init__(self) -> None:
        if self.cpu_cores <= 0:
            raise ValueError("cpu_cores must be positive")
        if self.memory_bytes <= 0:
            raise ValueError("memory_bytes must be positive")
        if self.max_concurrent_campaigns <= 0:
            raise ValueError("max_concurrent_campaigns must be positive")
        if self.max_solver_processes_per_profile != 1:
            raise ValueError("exactly one solver process per profile is required")

    def as_dict(self) -> dict[str, int]:
        return {
            "cpu_cores": self.cpu_cores,
            "memory_bytes": self.memory_bytes,
            "max_concurrent_campaigns": self.max_concurrent_campaigns,
            "max_solver_processes_per_profile": self.max_solver_processes_per_profile,
        }


@dataclass(frozen=True, slots=True)
class Quota:
    """Optional cumulative quota for a worker queue.

    ``None`` means that the dimension is not configured. A request that can never
    fit a configured quota is rejected; temporary contention is queued.
    """

    max_core_seconds: float | None = None
    max_input_tokens: int | None = None
    max_generated_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.max_core_seconds is not None and self.max_core_seconds < 0:
            raise ValueError("max_core_seconds must be non-negative")
        if self.max_input_tokens is not None and self.max_input_tokens < 0:
            raise ValueError("max_input_tokens must be non-negative")
        if self.max_generated_tokens is not None and self.max_generated_tokens < 0:
            raise ValueError("max_generated_tokens must be non-negative")


@dataclass(frozen=True, slots=True)
class ResourceRequest:
    campaign_id: str
    cpu_cores: int
    memory_bytes: int
    solver_profile: str | None = None
    estimated_core_seconds: float = 0.0
    estimated_input_tokens: int | None = None
    estimated_generated_tokens: int | None = None

    def __post_init__(self) -> None:
        if not self.campaign_id:
            raise ValueError("campaign_id is required")
        if self.cpu_cores <= 0 or self.memory_bytes <= 0:
            raise ValueError("requested CPU and memory must be positive")
        if self.estimated_core_seconds < 0:
            raise ValueError("estimated_core_seconds must be non-negative")
        if self.estimated_input_tokens is not None and self.estimated_input_tokens < 0:
            raise ValueError("estimated_input_tokens must be non-negative")
        if self.estimated_generated_tokens is not None and self.estimated_generated_tokens < 0:
            raise ValueError("estimated_generated_tokens must be non-negative")


@dataclass(frozen=True, slots=True)
class ResourceUsage:
    """Measured usage for a completed or interrupted campaign attempt."""

    cpu_core_seconds: float = 0.0
    solver_seconds: float = 0.0
    memory_high_water_bytes: int | None = None
    wall_seconds: float = 0.0
    input_tokens: int | None = None
    generated_tokens: int | None = None
    cost_usd: float | None = None
    missing_field_reasons: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("cpu_core_seconds", "solver_seconds", "wall_seconds"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.memory_high_water_bytes is not None and self.memory_high_water_bytes < 0:
            raise ValueError("memory_high_water_bytes must be non-negative")
        for name in ("input_tokens", "generated_tokens"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.cost_usd is not None and self.cost_usd < 0:
            raise ValueError("cost_usd must be non-negative")

    def as_resource_vector(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "cpu_core_seconds": self.cpu_core_seconds,
            "solver_seconds": self.solver_seconds,
            "memory_high_water_bytes": self.memory_high_water_bytes,
            "wall_seconds": self.wall_seconds,
            "input_tokens": self.input_tokens,
            "generated_tokens": self.generated_tokens,
            "cost_usd": self.cost_usd,
            "missing_field_reasons": dict(self.missing_field_reasons),
        }


@dataclass(frozen=True, slots=True)
class ResourceObservation:
    """Instantaneous/aggregate host observation used for enforcement checks."""

    active_cpu_cores: int | None = None
    memory_high_water_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    status: AdmissionStatus
    campaign_id: str
    reason: str
    lease_id: str | None = None
    queue_position: int | None = None


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    active_campaigns: int
    queued_campaigns: int
    active_cpu_cores: int
    active_memory_bytes: int
    used_core_seconds: float
    used_input_tokens: int
    used_generated_tokens: int
    active_solver_profiles: tuple[str, ...]
    throttled_count: int


@dataclass(frozen=True, slots=True)
class _Lease:
    lease_id: str
    request: ResourceRequest


class WorkerResourceScheduler:
    """FIFO, quota-aware scheduler for campaigns on one bounded worker.

    Admission reserves declared CPU/RAM. Runtime measurements are supplied to
    ``release`` and are retained in the snapshot; this class does not pretend to
    replace cgroups/job objects that enforce limits at the process boundary.
    """

    def __init__(
        self,
        envelope: ResourceEnvelope | None = None,
        quota: Quota | None = None,
    ) -> None:
        self._lock = RLock()
        self.envelope = envelope or ResourceEnvelope()
        self.quota = quota or Quota()
        self._active: dict[str, _Lease] = {}
        self._queue: list[ResourceRequest] = []
        self._used_core_seconds = 0.0
        self._used_input_tokens = 0
        self._used_generated_tokens = 0
        self._reserved_core_seconds = 0.0
        self._reserved_input_tokens = 0
        self._reserved_generated_tokens = 0
        self._throttled_count = 0
        self._next_lease = 1

    def submit(self, request: ResourceRequest) -> AdmissionDecision:
        with self._lock:
            rejection = self._permanent_rejection(request)
            if rejection is not None:
                return AdmissionDecision(AdmissionStatus.REJECTED, request.campaign_id, rejection)
            if self._can_admit(request):
                return self._admit(request)
            self._queue.append(request)
            self._throttled_count += 1
            return AdmissionDecision(
                AdmissionStatus.QUEUED,
                request.campaign_id,
                self._queue_reason(request),
                queue_position=len(self._queue),
            )

    def release(self, lease_id: str, usage: ResourceUsage) -> tuple[AdmissionDecision, ...]:
        with self._lock:
            lease = self._active.pop(lease_id, None)
            if lease is None:
                raise ValueError("unknown or already released lease")
            self._unreserve(lease.request)
            self._used_core_seconds += usage.cpu_core_seconds
            self._used_input_tokens += usage.input_tokens or 0
            self._used_generated_tokens += usage.generated_tokens or 0
            admitted: list[AdmissionDecision] = []
            while self._queue:
                request = self._queue[0]
                rejection = self._permanent_rejection(request)
                if rejection is not None:
                    self._queue.pop(0)
                    admitted.append(AdmissionDecision(AdmissionStatus.REJECTED, request.campaign_id, rejection))
                    continue
                if not self._can_admit(request):
                    break
                self._queue.pop(0)
                admitted.append(self._admit(request))
            return tuple(admitted)

    def cancel_queued(self, campaign_id: str) -> bool:
        """Remove one queued campaign when the runner gives up explicitly.

        Queue admission is otherwise FIFO and only ``release`` drains it.  A
        runner that reaches a terminal quota/deadline decision must be able to
        remove the request without submitting a duplicate request or leaving a
        ghost entry in the scheduler snapshot.
        """
        with self._lock:
            for index, request in enumerate(self._queue):
                if request.campaign_id == campaign_id:
                    self._queue.pop(index)
                    return True
        return False

    def observe(self, request: ResourceRequest, observation: ResourceObservation) -> tuple[str, ...]:
        """Return hard-limit violations for a running request."""
        with self._lock:
            errors: list[str] = []
            if observation.active_cpu_cores is not None:
                if observation.active_cpu_cores > self.envelope.cpu_cores:
                    errors.append("worker CPU envelope exceeded")
                if observation.active_cpu_cores > request.cpu_cores:
                    errors.append("campaign CPU allocation exceeded")
            if observation.memory_high_water_bytes is not None:
                if observation.memory_high_water_bytes > self.envelope.memory_bytes:
                    errors.append("worker memory envelope exceeded")
                if observation.memory_high_water_bytes > request.memory_bytes:
                    errors.append("campaign memory allocation exceeded")
            return tuple(errors)

    def snapshot(self) -> ResourceSnapshot:
        with self._lock:
            return ResourceSnapshot(
                active_campaigns=len(self._active),
                queued_campaigns=len(self._queue),
                active_cpu_cores=sum(lease.request.cpu_cores for lease in self._active.values()),
                active_memory_bytes=sum(lease.request.memory_bytes for lease in self._active.values()),
                used_core_seconds=self._used_core_seconds,
                used_input_tokens=self._used_input_tokens,
                used_generated_tokens=self._used_generated_tokens,
                active_solver_profiles=tuple(sorted(
                    request.solver_profile
                    for request in (lease.request for lease in self._active.values())
                    if request.solver_profile is not None
                )),
                throttled_count=self._throttled_count,
            )

    def _admit(self, request: ResourceRequest) -> AdmissionDecision:
        lease_id = f"lease-{self._next_lease}"
        self._next_lease += 1
        self._active[lease_id] = _Lease(lease_id, request)
        self._reserve(request)
        return AdmissionDecision(AdmissionStatus.ADMITTED, request.campaign_id, "resources_available", lease_id)

    def _can_admit(self, request: ResourceRequest) -> bool:
        snapshot = self.snapshot()
        if snapshot.active_campaigns >= self.envelope.max_concurrent_campaigns:
            return False
        if snapshot.active_cpu_cores + request.cpu_cores > self.envelope.cpu_cores:
            return False
        if snapshot.active_memory_bytes + request.memory_bytes > self.envelope.memory_bytes:
            return False
        if request.solver_profile is not None and request.solver_profile in snapshot.active_solver_profiles:
            return False
        return self._quota_allows_estimate(request)

    def _permanent_rejection(self, request: ResourceRequest) -> str | None:
        if request.cpu_cores > self.envelope.cpu_cores:
            return "requested CPU exceeds worker envelope"
        if request.memory_bytes > self.envelope.memory_bytes:
            return "requested memory exceeds worker envelope"
        if request.solver_profile is not None and self.envelope.max_solver_processes_per_profile != 1:
            return "unsupported solver process policy"
        if self.quota.max_core_seconds is not None and request.estimated_core_seconds > self.quota.max_core_seconds:
            return "estimated core-seconds exceed quota"
        if (
            self.quota.max_input_tokens is not None
            and request.estimated_input_tokens is not None
            and request.estimated_input_tokens > self.quota.max_input_tokens
        ):
            return "estimated input tokens exceed quota"
        if (
            self.quota.max_generated_tokens is not None
            and request.estimated_generated_tokens is not None
            and request.estimated_generated_tokens > self.quota.max_generated_tokens
        ):
            return "estimated generated tokens exceed quota"
        return None

    def _quota_allows_estimate(self, request: ResourceRequest) -> bool:
        if self.quota.max_core_seconds is not None and (
            self._used_core_seconds + self._reserved_core_seconds + request.estimated_core_seconds
            > self.quota.max_core_seconds
        ):
            return False
        if self.quota.max_input_tokens is not None and request.estimated_input_tokens is not None and (
            self._used_input_tokens + self._reserved_input_tokens + request.estimated_input_tokens
            > self.quota.max_input_tokens
        ):
            return False
        if self.quota.max_generated_tokens is not None and request.estimated_generated_tokens is not None and (
            self._used_generated_tokens + self._reserved_generated_tokens + request.estimated_generated_tokens
            > self.quota.max_generated_tokens
        ):
            return False
        return True

    def _reserve(self, request: ResourceRequest) -> None:
        self._reserved_core_seconds += request.estimated_core_seconds
        self._reserved_input_tokens += request.estimated_input_tokens or 0
        self._reserved_generated_tokens += request.estimated_generated_tokens or 0

    def _unreserve(self, request: ResourceRequest) -> None:
        self._reserved_core_seconds -= request.estimated_core_seconds
        self._reserved_input_tokens -= request.estimated_input_tokens or 0
        self._reserved_generated_tokens -= request.estimated_generated_tokens or 0

    def _queue_reason(self, request: ResourceRequest) -> str:
        snapshot = self.snapshot()
        if snapshot.active_campaigns >= self.envelope.max_concurrent_campaigns:
            return "campaign concurrency limit"
        if snapshot.active_cpu_cores + request.cpu_cores > self.envelope.cpu_cores:
            return "CPU capacity unavailable"
        if snapshot.active_memory_bytes + request.memory_bytes > self.envelope.memory_bytes:
            return "memory capacity unavailable"
        if request.solver_profile is not None and request.solver_profile in snapshot.active_solver_profiles:
            return "solver profile is already active"
        return "quota temporarily unavailable"
