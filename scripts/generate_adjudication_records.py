#!/usr/bin/env python3
"""Generate an explicitly synthetic adjudication template.

This helper is for rehearsing the adjudication import/export boundary only.
It must never manufacture labels, consensus, admission, or reviewer evidence
from a public benchmark manifest. Real labels are entered by independent
raters and reconciled through ``crossllm adjudication-import``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = ROOT / "dataset" / "benchmark"
PUBLIC_MANIFEST = ROOT / "benchmark.public.jsonl"
OUT_FILE = BENCHMARK_DIR / "adjudication_records.jsonl"


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_manifest(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: manifest row must be an object")
            rows.append(value)
    if not rows:
        raise ValueError(f"{path}: manifest is empty")
    return rows


def _template_record(instance: dict[str, Any]) -> dict[str, Any]:
    public_fields = {
        key: instance.get(key)
        for key in ("instance_id", "lineage_id", "property_family", "cohort")
    }
    return {
        "schema_version": 1,
        "record_status": "template_pending_independent_review",
        "provenance_status": "synthetic_template_not_evidence",
        **public_fields,
        "source_manifest_row_hash": _canonical_hash(instance),
        "labels": [],
        "reconciliation": None,
        "reviewer_roles": ["independent_rater_1", "independent_rater_2", "third_adjudicator"],
        "note": "Synthetic workflow template; populate only from independent review records.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=OUT_FILE)
    parser.add_argument(
        "--allow-synthetic-template",
        action="store_true",
        help="explicitly create a development-only pending template; never an admission record",
    )
    args = parser.parse_args(argv)

    if not args.allow_synthetic_template:
        print(
            "REFUSING to generate adjudication records: independent labels and consensus "
            "must not be fabricated from a public manifest. Re-run with "
            "--allow-synthetic-template only for a pending development template.",
            file=sys.stderr,
        )
        return 2

    manifest_path = args.manifest or (
        PUBLIC_MANIFEST if PUBLIC_MANIFEST.exists() else BENCHMARK_DIR / "benchmark.public.jsonl"
    )
    try:
        instances = _load_manifest(manifest_path)
        records = [_template_record(instance) for instance in instances]
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8", newline="\n") as stream:
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    print(f"Generated {len(records)} pending synthetic adjudication templates in {args.out}")
    print("This output is not evidence and cannot satisfy evaluation admission.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
