#!/usr/bin/env python3
"""Generate one offline T0 proposal run from a public artifact pack."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from crossllm.methods.t0 import T0DeterministicProposer, T0TemplateLibrary  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_t0_proposer")
    parser.add_argument("--pack", type=Path, required=True, help="gold-free public evaluation artifact pack JSON")
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--template-library", type=Path, default=ROOT / "configs" / "t0_templates.json")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--proposal-slots", type=int, default=8)
    args = parser.parse_args(argv)
    pack = json.loads(args.pack.read_text(encoding="utf-8-sig"))
    if not isinstance(pack, dict):
        raise SystemExit("public pack must be a JSON object")
    library = T0TemplateLibrary.from_file(args.template_library)
    run = T0DeterministicProposer(library).propose(
        pack,
        attempt_id=args.attempt_id,
        artifact_pack_hash=pack.get("pack_id") if isinstance(pack.get("pack_id"), str) else None,
        proposal_slots=args.proposal_slots,
    )
    output = args.out if args.out.is_absolute() else ROOT / args.out
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(json.dumps(run.as_dict(), ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(output)
    print(json.dumps({"out": str(output), "template_library_hash": run.template_library_hash, "candidate_count": len(run.candidate_hashes)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
