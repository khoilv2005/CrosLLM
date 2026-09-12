#!/usr/bin/env python3
"""Build the public, gold-free runtime binding coverage report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from crossllm.verification.runtime import build_runtime_binding_matrix  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build_runtime_binding_matrix")
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=ROOT / "dataset" / "reports" / "runtime_binding_matrix.json")
    parser.add_argument("--lineage", action="append", default=[], help="limit to one or more lineage IDs")
    args = parser.parse_args(argv)
    lineages = tuple(args.lineage) if args.lineage else None
    matrix = build_runtime_binding_matrix(args.repo_root, lineages)
    output = args.out if args.out.is_absolute() else args.repo_root / args.out
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(
        json.dumps(matrix.as_dict(), ensure_ascii=True, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(output)
    print(json.dumps({"out": str(output), "case_count": len(matrix.cases), "counts": matrix.counts}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
