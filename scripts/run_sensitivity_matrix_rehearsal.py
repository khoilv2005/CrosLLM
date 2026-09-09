#!/usr/bin/env python3
"""Build and validate the development M07.07 sensitivity matrix contract."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crossllm.baselines import build_sensitivity_matrix
from crossllm.contracts.canonical import sha256_hex


DEFAULT_OUTPUT = ROOT / "dataset" / "reports" / "m07_sensitivity_matrix_rehearsal.json"


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _matrix():
    return build_sensitivity_matrix(
        matrix_id="m07-sensitivity-v1",
        methods=("X", "P"),
        tracks=("automatic",),
        attestation_profiles=("honest", "conditional"),
        program_size_strata=("small",),
    )


def build_report(root: Path = ROOT, *, observed_at: str | None = None) -> dict[str, Any]:
    del root
    matrix = _matrix()
    status_counts = Counter(cell.eligibility.status.value for cell in matrix.cells)
    coverage = [
        {"method": method, "track": track, "cell_count": sum(
            1 for cell in matrix.cells if cell.method == method and cell.track == track
        )}
        for method, track in (("X", "automatic"), ("P", "automatic"))
    ]
    body: dict[str, Any] = {
        "schema_version": 1,
        "record_type": "development_sensitivity_matrix_rehearsal",
        "scope": "m07_07_planning_contract_only",
        "status": "pass" if len(matrix.cells) == 13824 else "fail",
        "matrix_id": matrix.matrix_id,
        "matrix_hash": matrix.matrix_hash,
        "cell_count": len(matrix.cells),
        "dimensions": {
            "methods": ["X", "P"],
            "tracks": ["automatic"],
            "proposal_prefixes": [1, 2, 4, 8],
            "transaction_bounds": [2, 4, 6, 8],
            "channel_bounds": [[6, 1], [12, 2], [24, 4]],
            "solver_timeouts_seconds": [10, 30, 120],
            "horizons_minutes": [15, 60],
            "channel_modes": ["fifo", "reordering"],
            "reorg_modes": ["none", "bounded_pre_finality"],
            "challenge_timings": ["before", "at", "after"],
            "attestation_profiles": ["honest", "conditional"],
            "program_size_strata": ["small"],
        },
        "eligibility_counts": {
            "pending": status_counts.get("pending", 0),
            "eligible": status_counts.get("eligible", 0),
            "unsupported": status_counts.get("unsupported", 0),
        },
        "coverage": coverage,
        "admission_eligible": False,
        "evidence_scope": "development_planning_non_admission",
        "command": "python scripts/run_sensitivity_matrix_rehearsal.py --check",
        "observed_at": observed_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    body["report_hash"] = sha256_hex(body)
    return body


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected an object")
    return value


def validate_report(root: Path = ROOT, report_path: Path | None = None) -> list[str]:
    root = root.resolve()
    path = report_path or root / DEFAULT_OUTPUT.relative_to(ROOT)
    try:
        report = _load(path)
        expected = build_report(root, observed_at=report.get("observed_at"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [f"sensitivity matrix rehearsal unreadable: {error}"]
    errors: list[str] = []
    body = dict(report)
    stored_hash = body.pop("report_hash", None)
    if stored_hash != sha256_hex(body):
        errors.append("sensitivity matrix rehearsal report hash mismatch")
    expected_body = dict(expected)
    expected_body.pop("report_hash", None)
    if body != expected_body:
        errors.append("sensitivity matrix rehearsal content mismatch")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    output = args.out.resolve() if args.out else root / DEFAULT_OUTPUT.relative_to(ROOT)
    try:
        if args.check:
            errors = validate_report(root, output)
            if errors:
                print("FAILED")
                print("\n".join(errors))
                return 1
            print("OK: M07.07 sensitivity matrix rehearsal is valid and non-admission")
            return 0
        report = build_report(root)
        _atomic_json(output, report)
        print(f"sensitivity matrix rehearsal: {report['cell_count']} pending cells")
        print(f"evidence written to: {output}")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"[FAIL] {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
