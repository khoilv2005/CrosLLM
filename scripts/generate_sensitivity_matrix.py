"""Generate a pending M07.07 sensitivity matrix from explicit dimension names."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from crossllm.baselines import build_sensitivity_matrix


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--matrix-id", default="m07-sensitivity-v1")
    parser.add_argument("--method", action="append", required=True)
    parser.add_argument("--track", action="append", required=True)
    parser.add_argument("--attestation-profile", action="append", required=True)
    parser.add_argument("--program-size-stratum", action="append", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.output.exists():
        raise ValueError(f"refusing to overwrite sensitivity matrix: {args.output}")
    matrix = build_sensitivity_matrix(
        matrix_id=args.matrix_id,
        methods=args.method,
        tracks=args.track,
        attestation_profiles=args.attestation_profile,
        program_size_strata=args.program_size_stratum,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(matrix.as_dict(), ensure_ascii=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"matrix_id": matrix.matrix_id, "matrix_hash": matrix.matrix_hash, "cell_count": len(matrix.cells)}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as error:
        print(f"sensitivity matrix error: {error}", file=sys.stderr)
        raise SystemExit(2)
