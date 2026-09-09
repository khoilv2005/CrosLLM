#!/usr/bin/env python3
"""Validate the canonical mapping from guide-era paths to this repository.

The map is deliberately a navigation/provenance artifact.  It never promotes
planning metadata, synthetic fixtures, or a source lock to evaluation evidence.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from crossllm.contracts.canonical import sha256_hex


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "dataset" / "reports" / "reconciliation_map.json"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _entry(
    guide_reference: str,
    canonical_paths: tuple[str, ...],
    *,
    use: str,
    admission_boundary: str,
    optional_paths: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "guide_reference": guide_reference,
        "canonical_paths": list(canonical_paths),
        **({"optional_paths": list(optional_paths)} if optional_paths else {}),
        "use": use,
        "admission_boundary": admission_boundary,
    }


def _entries() -> tuple[dict[str, object], ...]:
    return (
        _entry(
            "models_registry.json",
            ("protocol/models.json",),
            use="Declared model families, provider settings, and planned identifiers.",
            admission_boundary="Planning metadata only; runtime identity/effective settings require live attestation.",
        ),
        _entry(
            "primary_sources.md",
            (
                "dataset/sources/source_lock.json",
                "dataset/sources/source_registry.json",
                "dataset/artifacts/lineage_reviews.jsonl",
            ),
            use="Locked repositories, host/lineage/split metadata, and lineage review ledger.",
            admission_boundary="Locks do not replace retrieval, clean-tree, license, ancestry, build, or independent review evidence.",
        ),
        _entry(
            "../manuscript/tables.tex",
            ("paper/paper.tex",),
            optional_paths=("analysis/outputs",),
            use="Canonical manuscript and hash-linked generated analysis table outputs when available.",
            admission_boundary="Generated tables require frozen raw outcomes and a provenance manifest; missing values remain explicit.",
        ),
        _entry(
            "manuscript/",
            ("paper/",),
            use="Canonical paper source directory.",
            admission_boundary="paper/paper.tex is the sole canonical manuscript source; references.bib is its bibliography.",
        ),
        _entry(
            "benchmark manifest",
            ("benchmark.public.jsonl", "dataset/benchmark/benchmark.public.jsonl"),
            use="Public structural manifest used by development validation and pipeline rehearsal.",
            admission_boundary="Structural validation is not benchmark admission; use the admission validator with independent evidence.",
        ),
        _entry(
            "private benchmark truth",
            ("dataset/benchmark/benchmark.private.jsonl",),
            use="Restricted proposal/ground-truth payloads.",
            admission_boundary="Existing generated rows are not independent mutation/trigger evidence and must not be published.",
        ),
    )


def _source_of_truth() -> tuple[str, ...]:
    return (
        "dataset/sources/source_lock.json",
        "containers/toolchain.lock.json",
        "protocol/models.json",
        "protocol/protocol.json",
        "benchmark.public.jsonl",
    )


def build_report(root: Path = ROOT, *, generated_on: str | None = None) -> dict[str, object]:
    root = root.resolve()
    date = generated_on or datetime.now(timezone.utc).date().isoformat()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError("generated_on must be an ISO date")
    entries = [dict(item) for item in _entries()]
    for item in entries:
        hashes: dict[str, str] = {}
        for relative in item["canonical_paths"]:  # type: ignore[index]
            path = root / str(relative)
            if path.is_file():
                hashes[str(relative)] = _sha256_file(path)
        if hashes:
            item["file_sha256"] = hashes
    body: dict[str, object] = {
        "schema_version": 1,
        "record_type": "repository_reconciliation_map",
        "status": "development_mapping_complete",
        "generated_on": date,
        "entries": entries,
        "source_of_truth": list(_source_of_truth()),
    }
    body["mapping_hash"] = sha256_hex({"entries": entries, "source_of_truth": list(_source_of_truth())})
    body["report_hash"] = sha256_hex(body)
    return body


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("reconciliation report must be a JSON object")
    return value


def _safe_relative(value: object) -> str | None:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        return None
    normalized = value.replace("\\", "/")
    if normalized.startswith("../") or "/../" in normalized or normalized == "..":
        return None
    return normalized


def validate_report(root: Path = ROOT, report_path: Path = DEFAULT_OUTPUT) -> list[str]:
    root = root.resolve()
    try:
        report = _load(report_path.resolve())
    except (OSError, json.JSONDecodeError, ValueError) as error:
        return [f"reconciliation report unreadable: {error}"]
    errors: list[str] = []
    for key, expected in {
        "schema_version": 1,
        "record_type": "repository_reconciliation_map",
        "status": "development_mapping_complete",
    }.items():
        if report.get(key) != expected:
            errors.append(f"{key} mismatch")
    generated_on = report.get("generated_on")
    if not isinstance(generated_on, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", generated_on):
        errors.append("generated_on must be an ISO date")
    entries = report.get("entries")
    expected_entries = {item["guide_reference"] for item in _entries()}
    if not isinstance(entries, list):
        return errors + ["entries must be a list"]
    actual_entries = {
        item.get("guide_reference") for item in entries
        if isinstance(item, dict)
    }
    if actual_entries != expected_entries or len(entries) != len(expected_entries):
        errors.append("guide reference coverage mismatch")
    for index, item in enumerate(entries, 1):
        if not isinstance(item, dict):
            errors.append(f"entry {index} must be an object")
            continue
        reference = item.get("guide_reference", f"entry-{index}")
        canonical = item.get("canonical_paths")
        if not isinstance(canonical, list) or not canonical:
            errors.append(f"{reference}: canonical_paths must be a non-empty list")
            continue
        for raw_path in canonical:
            relative = _safe_relative(raw_path)
            if relative is None:
                errors.append(f"{reference}: unsafe canonical path")
                continue
            target = root / relative
            if not target.exists():
                errors.append(f"{reference}: canonical path missing: {relative}")
            if target.is_file():
                supplied = item.get("file_sha256", {})
                if not isinstance(supplied, dict) or supplied.get(relative) != _sha256_file(target):
                    errors.append(f"{reference}: file hash mismatch: {relative}")
        optional = item.get("optional_paths", [])
        if not isinstance(optional, list):
            errors.append(f"{reference}: optional_paths must be a list")
        elif any(_safe_relative(raw_path) is None for raw_path in optional):
            errors.append(f"{reference}: unsafe optional path")
        expected = next((candidate for candidate in _entries() if candidate["guide_reference"] == reference), None)
        if expected is not None:
            if item.get("use") != expected["use"] or item.get("admission_boundary") != expected["admission_boundary"]:
                errors.append(f"{reference}: semantic mapping text mismatch")
            if item.get("canonical_paths") != expected["canonical_paths"]:
                errors.append(f"{reference}: canonical path mapping mismatch")
    source_paths = report.get("source_of_truth")
    if source_paths != list(_source_of_truth()):
        errors.append("source_of_truth mismatch")
    mapping_body = {"entries": entries, "source_of_truth": source_paths}
    if report.get("mapping_hash") != sha256_hex(mapping_body):
        errors.append("mapping_hash mismatch")
    unsigned = dict(report)
    supplied_report_hash = unsigned.pop("report_hash", None)
    if supplied_report_hash != sha256_hex(unsigned):
        errors.append("report_hash mismatch")
    if not isinstance(report.get("mapping_hash"), str) or not SHA256_RE.fullmatch(report["mapping_hash"]):  # type: ignore[arg-type]
        errors.append("mapping_hash must be a lowercase SHA-256 digest")
    if not isinstance(report.get("report_hash"), str) or not SHA256_RE.fullmatch(report["report_hash"]):  # type: ignore[arg-type]
        errors.append("report_hash must be a lowercase SHA-256 digest")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    output = args.out.resolve() if args.out else root / DEFAULT_OUTPUT.relative_to(ROOT)
    if args.check:
        errors = validate_report(root, output)
        if errors:
            print("FAILED")
            print("\n".join(errors))
            return 1
        print("OK: reconciliation map is complete and hash-valid")
        return 0
    report = build_report(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"reconciliation report written to: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
