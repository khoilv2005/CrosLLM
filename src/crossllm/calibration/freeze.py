"""Development-only freeze artifact for M10.07."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Mapping

from ..contracts.canonical import sha256_hex
from .planning import SelectionDecision


@dataclass(frozen=True, slots=True)
class DevelopmentFreeze:
    selection: SelectionDecision
    protocol_hash: str
    prompt_hash: str
    primitives_hash: str
    mutation_policy_hash: str
    harness_policy_hash: str
    runtime_policy_hash: str
    analysis_code_hash: str
    freeze_hash: str

    def as_dict(self) -> dict[str, object]:
        payload = {
            "schema_version": 1,
            "split": "development",
            "selection": self.selection.as_dict(),
            "protocol_hash": self.protocol_hash,
            "prompt_hash": self.prompt_hash,
            "primitives_hash": self.primitives_hash,
            "mutation_policy_hash": self.mutation_policy_hash,
            "harness_policy_hash": self.harness_policy_hash,
            "runtime_policy_hash": self.runtime_policy_hash,
            "analysis_code_hash": self.analysis_code_hash,
        }
        return {**payload, "freeze_hash": self.freeze_hash}

    def write_json(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.as_dict(), sort_keys=True, indent=2) + "\n", encoding="utf-8")


def freeze_development_selection(
    selection: SelectionDecision,
    *,
    hashes: Mapping[str, str],
    evaluation_observation_ids: tuple[str, ...] = (),
) -> DevelopmentFreeze:
    """Freeze only development-derived decisions and all required code inputs."""
    if not selection.rule.development_only:
        raise ValueError("only development-only selection rules can be frozen")
    if evaluation_observation_ids:
        raise ValueError("evaluation observations cannot enter development freeze")
    required = (
        "protocol_hash", "prompt_hash", "primitives_hash", "mutation_policy_hash",
        "harness_policy_hash", "runtime_policy_hash", "analysis_code_hash",
    )
    missing = tuple(name for name in required if not isinstance(hashes.get(name), str) or not hashes[name])
    if missing:
        raise ValueError(f"freeze is missing hashes: {', '.join(missing)}")
    payload = {
        "schema_version": 1,
        "split": "development",
        "selection": selection.as_dict(),
        **{name: hashes[name] for name in required},
    }
    return DevelopmentFreeze(
        selection,
        *(hashes[name] for name in required),
        sha256_hex(payload),
    )
