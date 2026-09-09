#!/usr/bin/env python3
"""Run a deterministic synthetic rehearsal of the M08.07 version block.

The rehearsal checks that a matching identity can pass, a failed canary and
identity drift block execution, and an explicit deviation is recorded as a
different status.  It uses no provider, model or evaluation data.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crossllm.contracts.canonical import sha256_hex
from crossllm.runtime import CanaryStatus, VersionBlock, VersionIdentity


DEFAULT_OUTPUT = ROOT / "dataset" / "reports" / "m08_canary_version_rehearsal.json"
CASE_IDS = (
    "matching_identity_passes",
    "failed_panel_blocks",
    "identity_drift_blocks",
    "explicit_deviation_is_distinct",
)


def _identity(*, digest: str | None = None, model: str = "qwen3.5:397b-cloud") -> VersionIdentity:
    return VersionIdentity(
        model,
        digest,
        "p" * 64,
        "q" * 64,
        "toolchain-development-v1",
    )


def _case(case_id: str, assertions: dict[str, bool], evidence: object) -> dict[str, object]:
    return {
        "case_id": case_id,
        "passed": all(assertions.values()),
        "assertions": assertions,
        "evidence_sha256": sha256_hex(evidence),
    }


def _build_cases() -> list[dict[str, object]]:
    base = _identity(digest="sha256:development-weight-unknown")

    passing = VersionBlock("m08-canary", base).observe(
        base, canary_passed=True, evidence_hash="a" * 64
    )
    failed = VersionBlock("m08-canary", base).observe(
        base, canary_passed=False, evidence_hash="b" * 64
    )
    drift = VersionBlock("m08-canary", base).observe(
        _identity(digest="sha256:drifted-weight"), canary_passed=True, evidence_hash="c" * 64
    )
    block = VersionBlock("m08-canary", base)
    deviation = block.register_deviation(
        _identity(model="qwen3.5:397b-cloud-retired"),
        "synthetic approved provider version migration",
        "d" * 64,
    )
    return [
        _case("matching_identity_passes", {
            "status_passed": passing.status is CanaryStatus.PASSED,
            "identity_matches": passing.identity_hash == base.identity_hash,
            "reason_absent": passing.reason is None,
        }, passing.as_dict()),
        _case("failed_panel_blocks", {
            "status_blocked": failed.status is CanaryStatus.BLOCKED,
            "reason_explicit": failed.reason == "canary panel failed",
            "identity_preserved": failed.identity_hash == base.identity_hash,
        }, failed.as_dict()),
        _case("identity_drift_blocks", {
            "status_blocked": drift.status is CanaryStatus.BLOCKED,
            "reason_requires_deviation": drift.reason == "version identity drift; explicit deviation required",
            "identity_changed": drift.identity_hash != base.identity_hash,
        }, drift.as_dict()),
        _case("explicit_deviation_is_distinct", {
            "status_deviation": deviation.status is CanaryStatus.DEVIATION,
            "reason_recorded": deviation.reason == "synthetic approved provider version migration",
            "evidence_recorded": deviation.evidence_hash == "d" * 64,
        }, deviation.as_dict()),
    ]


def build_report(root: Path = ROOT) -> dict[str, Any]:
    del root  # The rehearsal intentionally has no external inputs.
    cases = _build_cases()
    body: dict[str, Any] = {
        "schema_version": 1,
        "record_type": "synthetic_m08_canary_version_rehearsal",
        "scope": "development_version_block_rehearsal_only",
        "admission_eligible": False,
        "provider_calls": 0,
        "case_ids": list(CASE_IDS),
        "cases": cases,
        "case_count": len(cases),
        "passed_count": sum(bool(case["passed"]) for case in cases),
        "all_passed": all(bool(case["passed"]) for case in cases),
        "limitations": [
            "no provider calls or model identity attestations were executed",
            "identities and canary outcomes are synthetic fixtures",
            "the rehearsal does not establish evaluation readiness or permit a deviation without governance approval",
        ],
    }
    body["report_hash"] = sha256_hex(body)
    return body


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def validate_report(root: Path = ROOT, report_path: Path | None = None) -> list[str]:
    path = report_path or root.resolve() / DEFAULT_OUTPUT.relative_to(ROOT)
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"canary version rehearsal unreadable: {error}"]
    if not isinstance(report, dict):
        return ["canary version rehearsal must be an object"]
    errors: list[str] = []
    body = dict(report)
    stored_hash = body.pop("report_hash", None)
    if stored_hash != sha256_hex(body):
        errors.append("canary version rehearsal report hash mismatch")
    expected = build_report(root)
    for key in (
        "schema_version", "record_type", "scope", "admission_eligible", "provider_calls",
        "case_ids", "cases", "case_count", "passed_count", "all_passed", "limitations",
    ):
        if report.get(key) != expected.get(key):
            errors.append(f"{key} mismatch")
    if report.get("admission_eligible") is not False or report.get("provider_calls") != 0:
        errors.append("canary version rehearsal must be non-admission with zero provider calls")
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
        print("OK: synthetic M08 canary version rehearsal is valid and non-admission")
        return 0
    report = build_report(root)
    _atomic_json(output, report)
    print(f"synthetic M08 canary version rehearsal: {report['passed_count']}/{report['case_count']} pass")
    print("provider calls: 0")
    print(f"evidence written to: {output}")
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
