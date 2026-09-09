"""Explicit worker isolation policy for M08.06.

These checks are the policy boundary. Container/cgroup and OS permissions must
enforce the same decision at deployment time; a CLI flag alone is insufficient.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from urllib.parse import urlparse


class IsolationStatus(StrEnum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class MountSpec:
    source: str
    target: str
    sensitivity: str
    read_only: bool = True

    def __post_init__(self) -> None:
        if not self.source or not self.target:
            raise ValueError("mount source and target are required")
        if self.sensitivity not in {"public_artifact", "controlled_raw", "private_gold"}:
            raise ValueError("unsupported mount sensitivity")


@dataclass(frozen=True, slots=True)
class IsolationDecision:
    status: IsolationStatus
    operation: str
    reason: str


@dataclass(frozen=True, slots=True)
class WorkerIsolationPolicy:
    """Default worker policy: no gold, no broadcast and explicit egress allowlist."""

    gold_access: str = "disabled"
    allow_broadcast: bool = False
    allowed_network_hosts: tuple[str, ...] = ("ollama.com",)

    def __post_init__(self) -> None:
        if self.gold_access != "disabled":
            raise ValueError("automatic workers must have gold_access=disabled")
        if any(not host or "/" in host or ":" in host for host in self.allowed_network_hosts):
            raise ValueError("allowed_network_hosts must contain hostnames only")

    def check_mounts(self, mounts: tuple[MountSpec, ...] | list[MountSpec]) -> IsolationDecision:
        private = [mount for mount in mounts if mount.sensitivity == "private_gold"]
        if private:
            return IsolationDecision(IsolationStatus.BLOCKED, "mount", "private gold mount is forbidden")
        writable = [mount for mount in mounts if not mount.read_only]
        if writable:
            return IsolationDecision(IsolationStatus.BLOCKED, "mount", "writable bind mount is forbidden")
        model_cache = [mount for mount in mounts if _looks_like_model_cache(mount)]
        if model_cache:
            return IsolationDecision(IsolationStatus.BLOCKED, "mount", "model-weight/cache mount is forbidden")
        return IsolationDecision(IsolationStatus.ALLOWED, "mount", "only non-gold mounts present")

    def check_broadcast(self, *, broadcast: bool) -> IsolationDecision:
        if broadcast and not self.allow_broadcast:
            return IsolationDecision(IsolationStatus.BLOCKED, "evm_broadcast", "execution must not broadcast")
        return IsolationDecision(IsolationStatus.ALLOWED, "evm_broadcast", "broadcast policy satisfied")

    def check_network(self, endpoint: str) -> IsolationDecision:
        parsed = urlparse(endpoint)
        host = parsed.hostname
        if parsed.scheme not in {"http", "https"} or not host:
            return IsolationDecision(IsolationStatus.BLOCKED, "network", "endpoint must be an HTTP(S) URL")
        if host not in self.allowed_network_hosts:
            return IsolationDecision(IsolationStatus.BLOCKED, "network", "endpoint is outside provider allowlist")
        return IsolationDecision(IsolationStatus.ALLOWED, "network", "endpoint is allowlisted")

    def validate(self, mounts: tuple[MountSpec, ...] | list[MountSpec], *, endpoint: str | None = None, broadcast: bool = False) -> tuple[IsolationDecision, ...]:
        decisions = [self.check_mounts(mounts), self.check_broadcast(broadcast=broadcast)]
        if endpoint is not None:
            decisions.append(self.check_network(endpoint))
        return tuple(decisions)

    def assert_compliant(self, mounts: tuple[MountSpec, ...] | list[MountSpec], *, endpoint: str | None = None, broadcast: bool = False) -> None:
        blocked = [decision for decision in self.validate(mounts, endpoint=endpoint, broadcast=broadcast) if decision.status == IsolationStatus.BLOCKED]
        if blocked:
            raise PermissionError("; ".join(decision.reason for decision in blocked))


def _looks_like_model_cache(mount: MountSpec) -> bool:
    """Reject common local model/cache paths even when mislabeled public."""
    value = re.sub(r"[\\]+", "/", f"{mount.source}/{mount.target}").lower()
    markers = (
        "/.ollama", "/models", "/model-weights", "/weights", "/huggingface",
        "/hf-cache", "/transformers-cache", "/vllm-cache",
    )
    return any(marker in value for marker in markers)
