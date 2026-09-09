"""Versioned prompt and ordered proposal-slot policy for M06.04–M06.05."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
import re

from ..contracts.canonical import sha256_hex
from ..providers.ollama import ProviderResponse


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class PromptPolicy:
    allow_memory: bool = False
    allow_tools: bool = False
    allow_retrieval: bool = False
    proposal_slots: int = 8

    def __post_init__(self) -> None:
        if self.proposal_slots <= 0:
            raise ValueError("proposal_slots must be positive")
        if self.allow_memory or self.allow_tools or self.allow_retrieval:
            raise ValueError("CrossLLM proposal policy forbids memory, tools and retrieval")

    def as_dict(self) -> dict[str, object]:
        return {
            "allow_memory": self.allow_memory,
            "allow_tools": self.allow_tools,
            "allow_retrieval": self.allow_retrieval,
            "proposal_slots": self.proposal_slots,
        }


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    template_id: str
    version: str
    text: str
    policy: PromptPolicy = PromptPolicy()

    def __post_init__(self) -> None:
        if not self.template_id or not self.version or not isinstance(self.text, str) or not self.text:
            raise ValueError("prompt template identity and text are required")
        if self.text.count("{artifact_pack}") != 1:
            raise ValueError("prompt template must contain exactly one artifact_pack placeholder")

    @property
    def template_hash(self) -> str:
        return sha256_hex({
            "template_id": self.template_id,
            "version": self.version,
            "text": self.text,
            "policy": self.policy.as_dict(),
        })

    def render(self, artifact_pack_text: str) -> str:
        if not isinstance(artifact_pack_text, str):
            raise ValueError("artifact pack text must be a string")
        return self.text.replace("{artifact_pack}", artifact_pack_text)


class ProposalSlotStatus(StrEnum):
    PENDING = "pending"
    CANDIDATE = "candidate"
    DUPLICATE = "duplicate"
    ABSTAIN = "abstain"
    INVALID = "invalid"
    TRUNCATED = "truncated"
    REFUSAL = "refusal"
    PROVIDER_FAILURE = "provider_failure"


@dataclass(frozen=True, slots=True)
class ProposalSlot:
    slot_id: str
    index: int
    status: ProposalSlotStatus
    raw_response_hash: str | None = None
    candidate: object | None = None
    reason: str | None = None
    canonical_ast_hash: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "slot_id": self.slot_id,
            "index": self.index,
            "status": self.status,
            "raw_response_hash": self.raw_response_hash,
            "candidate": self.candidate.as_dict() if hasattr(self.candidate, "as_dict") else self.candidate,
            "reason": self.reason,
            "canonical_ast_hash": self.canonical_ast_hash,
        }


class OrderedProposalSlots:
    """An attempt with fixed ordered slots and one terminal record per slot."""

    def __init__(self, attempt_id: str, *, policy: PromptPolicy | None = None) -> None:
        if not attempt_id:
            raise ValueError("attempt_id is required")
        self.attempt_id = attempt_id
        self.policy = policy or PromptPolicy()
        self._slots = [ProposalSlot(f"{attempt_id}:slot:{index}", index, ProposalSlotStatus.PENDING) for index in range(self.policy.proposal_slots)]

    @property
    def slots(self) -> tuple[ProposalSlot, ...]:
        return tuple(self._slots)

    def record(
        self,
        index: int,
        status: ProposalSlotStatus,
        *,
        raw_response_hash: str | None = None,
        candidate: object | None = None,
        reason: str | None = None,
        canonical_ast_hash: str | None = None,
    ) -> ProposalSlot:
        if index < 0 or index >= len(self._slots):
            raise IndexError("proposal slot index out of bounds")
        if status is ProposalSlotStatus.PENDING:
            raise ValueError("recorded slot status must be terminal")
        current = self._slots[index]
        if current.status is not ProposalSlotStatus.PENDING:
            raise ValueError("proposal slot already has a terminal record")
        if status is ProposalSlotStatus.CANDIDATE and candidate is None:
            raise ValueError("candidate slot requires candidate payload")
        if status is not ProposalSlotStatus.CANDIDATE and candidate is not None:
            raise ValueError("non-candidate slot cannot carry a candidate payload")
        if canonical_ast_hash is not None and not _SHA256_RE.fullmatch(canonical_ast_hash):
            raise ValueError("canonical_ast_hash must be a lowercase SHA-256 digest")
        if canonical_ast_hash is not None and status not in {
            ProposalSlotStatus.CANDIDATE, ProposalSlotStatus.DUPLICATE,
        }:
            raise ValueError("canonical_ast_hash requires a candidate or duplicate slot")
        updated = ProposalSlot(current.slot_id, index, status, raw_response_hash, candidate, reason, canonical_ast_hash)
        self._slots[index] = updated
        return updated

    def complete(self) -> bool:
        return all(slot.status is not ProposalSlotStatus.PENDING for slot in self._slots)


def classify_response(response: ProviderResponse, candidate: object | None = None) -> tuple[ProposalSlotStatus, object | None, str | None]:
    """Classify transport output while preserving the consumed slot."""
    if response.error is not None:
        return ProposalSlotStatus.PROVIDER_FAILURE, None, response.error
    if response.partial:
        return ProposalSlotStatus.TRUNCATED, None, "provider_response_partial"
    if not response.response_text or not response.response_text.strip():
        return ProposalSlotStatus.REFUSAL, None, "empty_response"
    try:
        parsed = json.loads(response.response_text)
    except json.JSONDecodeError:
        return ProposalSlotStatus.INVALID, None, "response_not_json"
    if isinstance(parsed, dict) and parsed.get("abstain") is True:
        return ProposalSlotStatus.ABSTAIN, None, parsed.get("reason") if isinstance(parsed.get("reason"), str) else "explicit_abstain"
    if candidate is not None:
        return ProposalSlotStatus.CANDIDATE, candidate, None
    return ProposalSlotStatus.INVALID, None, "candidate_not_compiled"


def candidate_identity(candidate: object) -> tuple[str, str | None]:
    """Return the dedup hash and optional semantic canonical AST hash.

    A compiled XLIR invariant exposes ``canonical_hash`` over its canonical
    body.  Serialized invariants are accepted only after that digest is
    recomputed from their serialized canonical body; trusting a caller-supplied
    hash would let an untrusted response influence semantic deduplication.
    Raw parsed payloads retain deterministic duplicate detection through their
    canonical JSON hash, but are not labelled as semantic AST identities.
    """
    semantic_hash: object = getattr(candidate, "canonical_hash", None)
    body: object = getattr(candidate, "body", None)
    if body is not None and hasattr(body, "as_dict"):
        try:
            body = body.as_dict()
        except (TypeError, ValueError):
            body = None
    if isinstance(candidate, dict):
        semantic_hash = candidate.get("canonical_hash")
        body = candidate.get("body")
    if (
        isinstance(semantic_hash, str)
        and _SHA256_RE.fullmatch(semantic_hash)
        and isinstance(body, dict)
    ):
        try:
            if sha256_hex(body) == semantic_hash:
                return semantic_hash, semantic_hash
        except (TypeError, ValueError):
            pass
    try:
        return sha256_hex(candidate), None
    except (TypeError, ValueError) as error:
        raise ValueError("candidate cannot be assigned a deterministic identity") from error
