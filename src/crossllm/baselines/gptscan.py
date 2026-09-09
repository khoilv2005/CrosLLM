"""GPTScan transport/adaptation audit boundary (M07.02)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Iterable

from ..contracts.canonical import sha256_hex
from .external import BaselineResult, ExternalToolAdapter, ToolSpec


class FidelityStatus(StrEnum):
    PENDING_AUDIT = "pending_audit"
    FAITHFUL = "faithful"
    TRANSPARENT_ADAPTATION = "transparent_adaptation"
    NOT_REPRODUCIBLE = "not_reproducible"


@dataclass(frozen=True, slots=True)
class GPTScanAudit:
    """What was retained or changed when the original method uses Ollama."""

    original_method_revision: str
    learned_components: tuple[str, ...]
    retained_components: tuple[str, ...]
    omitted_components: tuple[str, ...] = ()
    fidelity: FidelityStatus = FidelityStatus.PENDING_AUDIT
    parity_fixture_hash: str | None = None
    diff_report_hash: str | None = None

    def __post_init__(self) -> None:
        if not self.original_method_revision:
            raise ValueError("GPTScan original revision is required")
        if not self.learned_components:
            raise ValueError("GPTScan audit requires learned component inventory")
        if not self.retained_components:
            raise ValueError("GPTScan audit requires retained component inventory")
        if self.fidelity is FidelityStatus.FAITHFUL and self.omitted_components:
            raise ValueError("faithful GPTScan audit cannot omit components")
        if self.fidelity is FidelityStatus.TRANSPARENT_ADAPTATION and not self.omitted_components:
            raise ValueError("transparent adaptation must name omitted components")
        for name, value in (("parity_fixture_hash", self.parity_fixture_hash), ("diff_report_hash", self.diff_report_hash)):
            if value is not None and (len(value) != 64 or value != value.lower() or any(char not in "0123456789abcdef" for char in value)):
                raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")

    def as_dict(self) -> dict[str, object]:
        return {
            "original_method_revision": self.original_method_revision,
            "learned_components": list(self.learned_components),
            "retained_components": list(self.retained_components),
            "omitted_components": list(self.omitted_components),
            "fidelity": self.fidelity.value,
            "parity_fixture_hash": self.parity_fixture_hash,
            "diff_report_hash": self.diff_report_hash,
            "claim_label": "faithful_reproduction" if self.fidelity is FidelityStatus.FAITHFUL else "transparent_adaptation",
        }


@dataclass(frozen=True, slots=True)
class GPTScanSpec:
    variant: str
    backbone: str
    transport: str
    tool: ToolSpec
    audit: GPTScanAudit

    def __post_init__(self) -> None:
        if not self.variant or not self.backbone:
            raise ValueError("GPTScan variant and backbone are required")
        if self.transport != "ollama":
            raise ValueError("GPTScan adapter currently supports only Ollama transport")
        if self.tool.network_policy != "provider_only":
            raise ValueError("GPTScan Ollama runs require provider_only network policy")

    @property
    def identity_hash(self) -> str:
        return sha256_hex(self.as_dict(include_hash=False))

    def as_dict(self, *, include_hash: bool = True) -> dict[str, object]:
        payload = {
            "schema_version": 1,
            "variant": self.variant,
            "backbone": self.backbone,
            "transport": self.transport,
            "tool": self.tool.as_dict(),
            "audit": self.audit.as_dict(),
        }
        if include_hash:
            payload["identity_hash"] = self.identity_hash
        return payload


@dataclass(frozen=True, slots=True)
class GPTScanParityReport:
    fixture_hash: str
    reference_finding_ids: tuple[str, ...]
    adapted_finding_ids: tuple[str, ...]
    equal: bool
    differences: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "fixture_hash": self.fixture_hash,
            "reference_finding_ids": list(self.reference_finding_ids),
            "adapted_finding_ids": list(self.adapted_finding_ids),
            "equal": self.equal,
            "differences": list(self.differences),
        }


class GPTScanAdapter:
    """Run a declared GPTScan variant without changing its audit label."""

    def __init__(self, external: ExternalToolAdapter | None = None) -> None:
        self.external = external or ExternalToolAdapter()

    def run(self, spec: GPTScanSpec, workdir: Path) -> BaselineResult:
        return self.external.run(spec.tool, workdir)


def compare_parity(
    reference: BaselineResult,
    adapted: BaselineResult,
    *,
    fixture_hash: str,
) -> GPTScanParityReport:
    """Compare normalized IDs/categories while preserving native results."""
    if len(fixture_hash) != 64 or fixture_hash != fixture_hash.lower() or any(char not in "0123456789abcdef" for char in fixture_hash):
        raise ValueError("fixture_hash must be a lowercase SHA-256 hex digest")
    reference_ids = tuple(f"{finding.finding_id}:{finding.category}" for finding in reference.findings)
    adapted_ids = tuple(f"{finding.finding_id}:{finding.category}" for finding in adapted.findings)
    differences: list[str] = []
    if reference.status != adapted.status:
        differences.append(f"status:{reference.status.value}!={adapted.status.value}")
    if reference_ids != adapted_ids:
        differences.append("finding_ids_or_categories_differ")
    return GPTScanParityReport(fixture_hash, reference_ids, adapted_ids, not differences, tuple(differences))


__all__ = [
    "FidelityStatus", "GPTScanAdapter", "GPTScanAudit", "GPTScanParityReport",
    "GPTScanSpec", "compare_parity",
]
