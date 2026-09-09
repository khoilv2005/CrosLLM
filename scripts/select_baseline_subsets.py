"""Freeze outcome-blind baseline/ablation or sensitivity subset IDs.

The input contains only pre-outcome instance metadata. This command refuses to
overwrite an existing selection record, so a frozen seed/ID set cannot be
silently changed by a later invocation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from crossllm.baselines import select_balanced_subset


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="JSON array or JSONL instance metadata")
    parser.add_argument("--output", required=True, type=Path, help="new JSON selection record")
    parser.add_argument("--target-size", required=True, type=int)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--min-lineages", required=True, type=int)
    parser.add_argument("--min-families", required=True, type=int)
    parser.add_argument("--record-id-field", default="instance_id")
    parser.add_argument("--lineage-field", default="lineage_id")
    parser.add_argument("--family-field", default="family")
    parser.add_argument("--truth-field", default="ground_truth")
    parser.add_argument("--positive-label", default="positive")
    parser.add_argument("--negative-label", default="negative")
    parser.add_argument("--support-field", default=None)
    parser.add_argument(
        "--required-method",
        action="append",
        default=[],
        help="static eligible method name; may be repeated to report common-supported coverage",
    )
    parser.add_argument(
        "--balance-field",
        action="append",
        default=[],
        help="pre-outcome categorical field to balance during fill; may be repeated",
    )
    return parser


def load_records(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ValueError(f"input does not exist: {path}")
    text = path.read_text(encoding="utf-8-sig")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = [json.loads(line) for line in text.splitlines() if line.strip()]
    if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
        raise ValueError("input must be a JSON array or JSONL objects")
    return payload


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.output.exists():
        raise ValueError(f"refusing to overwrite frozen selection: {args.output}")
    records = load_records(args.input)
    selection = select_balanced_subset(
        records,
        target_size=args.target_size,
        seed=args.seed,
        min_lineages=args.min_lineages,
        min_families=args.min_families,
        record_id_field=args.record_id_field,
        lineage_field=args.lineage_field,
        family_field=args.family_field,
        truth_field=args.truth_field,
        positive_label=args.positive_label,
        negative_label=args.negative_label,
        support_field=args.support_field,
        required_methods=args.required_method,
        balance_fields=args.balance_field,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(selection.as_dict(), ensure_ascii=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(selection.as_dict(), ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as error:
        print(f"selection error: {error}", file=sys.stderr)
        raise SystemExit(2)
