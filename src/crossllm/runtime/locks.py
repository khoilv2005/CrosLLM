"""Fail-closed builders for hash-addressed evaluation dependency locks."""

from __future__ import annotations

from collections.abc import Mapping
import copy
import re

from ..contracts.canonical import sha256_hex


_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def build_protocol_lock(
    protocol: Mapping[str, object],
    *,
    model_lock_hash: str,
    benchmark_manifest_hash: str,
    captured_at: str,
    dependency_hashes: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Materialize an evaluation protocol lock only from complete inputs.

    The prospective planning file is intentionally not mutated. Missing
    execution decisions and invalid dependency hashes stop this function before
    any lock is returned, preventing a planning configuration from being
    mistaken for an evaluation lock.
    """
    if not isinstance(protocol, Mapping):
        raise ValueError("protocol must be an object")
    forbidden = _forbidden_secret_paths(protocol)
    if forbidden:
        raise ValueError("protocol contains credential-like fields: " + ", ".join(forbidden))
    if not isinstance(captured_at, str) or not captured_at.strip():
        raise ValueError("captured_at must be a non-empty string")
    _validate_hash(model_lock_hash, "model_lock_hash")
    _validate_hash(benchmark_manifest_hash, "benchmark_manifest_hash")
    dependency_hashes = dict(dependency_hashes or {})
    if any(not isinstance(key, str) or not key.strip() for key in dependency_hashes):
        raise ValueError("dependency hash names must be non-empty strings")
    for key, value in dependency_hashes.items():
        _validate_hash(value, f"dependency_hashes.{key}")

    missing = protocol.get("missing_execution_fields")
    if not isinstance(missing, list):
        raise ValueError("protocol.missing_execution_fields must be a list")
    if missing:
        raise ValueError(
            "protocol lock blocked; missing execution fields: "
            + ", ".join(str(field) for field in missing)
        )
    replicates = protocol.get("evaluation_replicates")
    if not isinstance(replicates, int) or isinstance(replicates, bool) or replicates <= 0:
        raise ValueError("protocol lock requires a positive evaluation_replicates")
    for field in ("schema_version", "model_families", "budgets", "proposal_slots"):
        if field not in protocol:
            raise ValueError(f"protocol lock requires {field}")

    payload = copy.deepcopy(dict(protocol))
    payload.pop("lock_hash", None)
    payload.update(
        {
            "status": "EVALUATION_LOCKED",
            "missing_execution_fields": [],
            "locked_at": captured_at,
            "model_lock_hash": model_lock_hash,
            "benchmark_manifest_hash": benchmark_manifest_hash,
            "dependency_hashes": {key: dependency_hashes[key] for key in sorted(dependency_hashes)},
        }
    )
    payload["lock_hash"] = sha256_hex(payload)
    return payload


def _validate_hash(value: object, name: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{name} must be a 64-character SHA-256 hex digest")


def _forbidden_secret_paths(value: object, path: str = "") -> list[str]:
    forbidden_names = {"api_key", "authorization", "credential", "password", "secret"}
    if isinstance(value, Mapping):
        paths: list[str] = []
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if str(key).lower() in forbidden_names:
                paths.append(child_path)
            paths.extend(_forbidden_secret_paths(child, child_path))
        return paths
    if isinstance(value, list):
        paths: list[str] = []
        for index, child in enumerate(value):
            paths.extend(_forbidden_secret_paths(child, f"{path}[{index}]"))
        return paths
    return []
