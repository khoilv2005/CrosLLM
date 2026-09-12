"""Clean source-backed case workspaces for candidate executors.

The verification protocol must execute the source and test bundle belonging to
the requested case, not the checked-in harness build products and not a stale
workspace left by another candidate.  This module resolves the public case
identity, verifies the source/test receipts, and materializes an isolated
Foundry workspace whose initial state is created by the harness ``setUp``.

Only public runtime inputs are read here: ``metadata.json``,
``build_manifest.json``, ``paired_harness.json`` and ``source_identity.json``.
Mutation patches, property assessments, trigger evidence and replay traces are
deliberately outside this boundary.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from typing import Any, Iterator, Mapping


_BUILD_PRODUCT_NAMES = frozenset({"out", "cache", "broadcast", ".git"})


@dataclass(frozen=True, slots=True)
class SourceCaseIdentity:
    """Public identity and overlay paths for one source-backed case."""

    lineage_id: str
    case_id: str
    split: str
    source_path: str
    source_sha256: str
    test_path: str
    test_sha256: str
    upstream_source_path: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "record_type": "source_case_identity",
            "lineage_id": self.lineage_id,
            "case_id": self.case_id,
            "split": self.split,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "test_path": self.test_path,
            "test_sha256": self.test_sha256,
            "upstream_source_path": self.upstream_source_path,
        }


@contextmanager
def materialize_source_case_workspace(
    repo_root: Path,
    lineage_id: str,
    case_id: str,
    *,
    case_root: Path | None = None,
) -> Iterator[tuple[Path, SourceCaseIdentity]]:
    """Yield ``(workspace, identity)`` for a clean source-backed case.

    The base harness is copied without build products.  The case's recorded
    source file replaces the exact locked upstream source path and its paired
    test is placed under the base harness ``test/`` directory.  No caller can
    escape the repository/case roots through an absolute or ``..`` path.
    """

    root = Path(repo_root).resolve()
    harness_root = _under_root(root / "dataset" / "harness" / lineage_id, root)
    resolved_case_root = _under_root(
        Path(case_root).resolve() if case_root is not None else root / "dataset" / "artifacts" / lineage_id / "cases" / case_id,
        root,
    )
    identity = _read_identity(resolved_case_root, lineage_id, case_id)
    source = _case_file(resolved_case_root, identity.source_path, "source")
    test = _case_file(resolved_case_root, identity.test_path, "test")
    _check_sha256(source, identity.source_sha256, "case source")
    _check_sha256(test, identity.test_sha256, "paired harness test")

    target_source = _under_root(harness_root / _safe_relative(identity.upstream_source_path), harness_root)
    target_test = _test_target(harness_root, identity.test_path)
    if not harness_root.is_dir():
        raise FileNotFoundError(f"source harness directory is missing: {harness_root}")
    if not target_source.parent.is_dir():
        raise FileNotFoundError(f"locked source target directory is missing: {target_source.parent}")
    if not target_test.parent.is_dir():
        raise FileNotFoundError(f"harness test target directory is missing: {target_test.parent}")

    with tempfile.TemporaryDirectory(prefix=f"crossllm-source-{lineage_id}-") as temporary:
        workspace = Path(temporary) / "harness"
        shutil.copytree(harness_root, workspace, ignore=_ignore_build_products)
        copied_source = _under_root(workspace / _safe_relative(identity.upstream_source_path), workspace)
        copied_test = _test_target(workspace, identity.test_path)
        copied_source.parent.mkdir(parents=True, exist_ok=True)
        copied_test.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, copied_source)
        shutil.copyfile(test, copied_test)
        yield workspace, identity


def _read_identity(case_root: Path, lineage_id: str, case_id: str) -> SourceCaseIdentity:
    metadata = _read_object(case_root / "metadata.json")
    build = _read_object(case_root / "build_manifest.json")
    paired = _read_object(case_root / "paired_harness.json")
    source_identity = _read_object(case_root / "source_identity.json")

    _require_text(metadata, "lineage_id", lineage_id, "metadata")
    _require_text(metadata, "instance_id", case_id, "metadata")
    split = metadata.get("split")
    if not isinstance(split, str) or not split:
        raise ValueError("metadata.split must be a non-empty string")

    source = build.get("source")
    if not isinstance(source, Mapping):
        raise ValueError("build_manifest.source must be an object")
    source_path = _relative_text(source, "path", "build_manifest.source")
    source_sha256 = _digest_text(source, "sha256", "build_manifest.source")
    built_source_sha256 = metadata.get("built_source_sha256")
    if built_source_sha256 is not None and built_source_sha256 != source_sha256:
        raise ValueError("metadata.built_source_sha256 does not match build_manifest.source.sha256")

    test = paired.get("test")
    if not isinstance(test, Mapping):
        raise ValueError("paired_harness.test must be an object")
    test_path = _relative_text(test, "path", "paired_harness.test")
    test_sha256 = _digest_text(test, "sha256", "paired_harness.test")
    upstream_source_path = _relative_text(source_identity, "upstream_source_path", "source_identity")
    return SourceCaseIdentity(
        lineage_id=lineage_id,
        case_id=case_id,
        split=split,
        source_path=source_path,
        source_sha256=source_sha256,
        test_path=test_path,
        test_sha256=test_sha256,
        upstream_source_path=upstream_source_path,
    )


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as error:
        raise FileNotFoundError(f"required source-case receipt is missing: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _case_file(case_root: Path, relative: str, label: str) -> Path:
    path = _under_root(case_root / _safe_relative(relative), case_root)
    if not path.is_file():
        raise FileNotFoundError(f"{label} file is missing: {path}")
    return path


def _test_target(harness_root: Path, test_path: str) -> Path:
    relative = _safe_relative(test_path)
    parts = relative.parts
    if len(parts) < 2 or parts[-2] != "test":
        raise ValueError("paired harness test path must end under a test directory")
    return _under_root(harness_root / "test" / relative.name, harness_root)


def _safe_relative(value: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("relative path must be a non-empty string")
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"path escapes its declared root: {value!r}")
    return candidate


def _under_root(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"path escapes root {root}: {path}") from error
    return resolved


def _require_text(value: Mapping[str, Any], field: str, expected: str, label: str) -> None:
    actual = value.get(field)
    if actual != expected:
        raise ValueError(f"{label}.{field} does not match requested identity")


def _relative_text(value: Mapping[str, Any], field: str, label: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{label}.{field} must be a non-empty path")
    _safe_relative(item)
    return item.replace("\\", "/")


def _digest_text(value: Mapping[str, Any], field: str, label: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or len(item) != 64 or item.lower() != item or any(char not in "0123456789abcdef" for char in item):
        raise ValueError(f"{label}.{field} must be a lowercase SHA-256 digest")
    return item


def _check_sha256(path: Path, expected: str, label: str) -> None:
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(f"{label} hash mismatch: expected {expected}, got {actual}")


def _ignore_build_products(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in _BUILD_PRODUCT_NAMES}


__all__ = ["SourceCaseIdentity", "materialize_source_case_workspace"]
