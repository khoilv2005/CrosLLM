#!/usr/bin/env python3
"""Validate the public source/test overlay contract for evaluation cases.

This is a fast preflight.  It verifies every case's source/test receipts and
the locked harness target paths without copying or compiling the harness.  It
does not read mutation patches, property assessments, trigger evidence or
replay traces, and it does not claim a candidate was verified.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_MANIFESTS = (
    ROOT / "benchmark.public.jsonl",
    ROOT / "dataset" / "benchmark" / "benchmark.public.jsonl",
)


def _manifest_path(value: Path | None, root: Path) -> Path:
    if value is not None:
        path = value if value.is_absolute() else root / value
        return path.resolve()
    for path in DEFAULT_MANIFESTS:
        if path.is_file():
            return path.resolve()
    raise FileNotFoundError("public benchmark manifest is missing")


def _read_manifest(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: expected a JSON object")
        rows.append(value)
    return rows


def _report_hash(value: dict[str, Any]) -> str:
    body = dict(value)
    body.pop("report_sha256", None)
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.",
        suffix=".tmp", delete=False,
    ) as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        temporary = Path(stream.name)
    temporary.replace(path)


def validate_source_workspaces(
    root: Path = ROOT,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Return a source-case receipt report without materializing workspaces."""

    root = root.resolve()
    manifest = _manifest_path(manifest_path, root)
    if not manifest.is_file():
        raise FileNotFoundError(f"manifest is missing: {manifest}")
    from crossllm.verification.source_workspace import load_source_case_identity

    rows = _read_manifest(manifest)
    cases: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        lineage_id = row.get("lineage_id")
        case_id = row.get("instance_id")
        result: dict[str, Any] = {
            "lineage_id": lineage_id,
            "case_id": case_id,
            "status": "failed",
        }
        if not isinstance(lineage_id, str) or not lineage_id or not isinstance(case_id, str) or not case_id:
            result["reason"] = "manifest_missing_case_identity"
        elif (lineage_id, case_id) in seen:
            result["reason"] = "duplicate_manifest_case"
        else:
            seen.add((lineage_id, case_id))
            try:
                identity = load_source_case_identity(root, lineage_id, case_id)
            except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as error:
                result["reason"] = str(error)
            else:
                result["status"] = "pass"
                result["source_case_identity"] = identity.as_dict()
        cases.append(result)

    passed = sum(case["status"] == "pass" for case in cases)
    report: dict[str, Any] = {
        "schema_version": 1,
        "record_type": "source_case_workspace_validation",
        "scope": "public_source_test_receipts_only",
        "gold_fields_read": False,
        "manifest_path": str(manifest.relative_to(root)).replace("\\", "/"),
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "case_count": len(cases),
        "passed_cases": passed,
        "failed_cases": len(cases) - passed,
        "status": "pass" if cases and passed == len(cases) else "blocked",
        "cases": cases,
    }
    report["report_sha256"] = _report_hash(report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        report = validate_source_workspaces(args.root, args.manifest)
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"FAILED: {error}")
        return 2
    if args.out is not None:
        output = args.out if args.out.is_absolute() else args.root.resolve() / args.out
        _atomic_write(output.resolve(), report)
        print(json.dumps({
            "status": report["status"],
            "case_count": report["case_count"],
            "passed_cases": report["passed_cases"],
            "failed_cases": report["failed_cases"],
            "report_sha256": report["report_sha256"],
            "out": str(output.resolve()),
        }, sort_keys=True))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
