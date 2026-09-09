"""Canary/version block records for M08.07."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ..contracts.canonical import sha256_hex


class CanaryStatus(StrEnum):
    PENDING = "pending"
    PASSED = "passed"
    BLOCKED = "blocked"
    DEVIATION = "deviation"


@dataclass(frozen=True, slots=True)
class VersionIdentity:
    model_tag: str
    served_weight_digest: str | None
    protocol_lock_hash: str
    prompt_hash: str
    toolchain_digest: str

    def __post_init__(self) -> None:
        if not all((self.model_tag, self.protocol_lock_hash, self.prompt_hash, self.toolchain_digest)):
            raise ValueError("version identity requires model, protocol, prompt and toolchain identity")

    def as_dict(self) -> dict[str, str | None]:
        return {
            "model_tag": self.model_tag,
            "served_weight_digest": self.served_weight_digest,
            "protocol_lock_hash": self.protocol_lock_hash,
            "prompt_hash": self.prompt_hash,
            "toolchain_digest": self.toolchain_digest,
        }

    @property
    def identity_hash(self) -> str:
        return sha256_hex(self.as_dict())


@dataclass(frozen=True, slots=True)
class CanaryObservation:
    block_id: str
    identity_hash: str
    status: CanaryStatus
    evidence_hash: str | None = None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "identity_hash": self.identity_hash,
            "status": self.status.value,
            "evidence_hash": self.evidence_hash,
            "reason": self.reason,
        }


class VersionBlock:
    """Freeze one identity and block all mismatches until explicit deviation."""

    def __init__(self, block_id: str, identity: VersionIdentity) -> None:
        if not block_id:
            raise ValueError("block_id is required")
        self.block_id = block_id
        self.identity = identity
        self._observations: list[CanaryObservation] = []

    @property
    def observations(self) -> tuple[CanaryObservation, ...]:
        return tuple(self._observations)

    def observe(self, identity: VersionIdentity, *, canary_passed: bool, evidence_hash: str | None = None) -> CanaryObservation:
        if identity.identity_hash != self.identity.identity_hash:
            observation = CanaryObservation(
                self.block_id,
                identity.identity_hash,
                CanaryStatus.BLOCKED,
                evidence_hash,
                "version identity drift; explicit deviation required",
            )
        elif not canary_passed:
            observation = CanaryObservation(
                self.block_id,
                identity.identity_hash,
                CanaryStatus.BLOCKED,
                evidence_hash,
                "canary panel failed",
            )
        else:
            observation = CanaryObservation(
                self.block_id,
                identity.identity_hash,
                CanaryStatus.PASSED,
                evidence_hash,
                None,
            )
        self._observations.append(observation)
        return observation

    def register_deviation(self, identity: VersionIdentity, reason: str, evidence_hash: str) -> CanaryObservation:
        if not reason or not evidence_hash:
            raise ValueError("deviation requires reason and evidence_hash")
        observation = CanaryObservation(
            self.block_id,
            identity.identity_hash,
            CanaryStatus.DEVIATION,
            evidence_hash,
            reason,
        )
        self._observations.append(observation)
        return observation

