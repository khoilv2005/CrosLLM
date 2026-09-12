#!/usr/bin/env python3
"""Create one providerless T0 campaign archive from a public artifact pack."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from crossllm.contracts.canonical import sha256_hex
from crossllm.methods import T0DeterministicProposer, T0ProposalRun, T0TemplateLibrary


def build_t0_archive(
    pack: Mapping[str, Any],
    run: T0ProposalRun,
    *,
    campaign_id: str,
    lineage_id: str,
    instance_id: str,
    replicate: int,
) -> dict[str, object]:
    """Wrap a deterministic T0 run in the standard archive envelope."""

    if not all(isinstance(value, str) and value for value in (campaign_id, lineage_id, instance_id)):
        raise ValueError("campaign, lineage and instance IDs are required")
    if not isinstance(replicate, int) or isinstance(replicate, bool) or replicate <= 0:
        raise ValueError("replicate must be a positive integer")
    method_run = run.method_run.as_dict()
    return {
        "schema_version": 1,
        "record_type": "proposal_campaign_archive",
        "campaign": {
            "campaign_id": campaign_id,
            "attempt_id": run.method_run.attempt_id,
            "lineage_id": lineage_id,
            "instance_id": instance_id,
            "replicate": replicate,
            "method": "t0",
            "backbone": "deterministic",
            "model_tag": "deterministic-t0",
            "config_hash": run.template_library_hash,
            "request_settings_hash": sha256_hex(run.method_run.settings),
        },
        "public_artifact_pack_hash": run.method_run.artifact_pack_hash,
        "public_artifact_pack": dict(pack),
        "method_run": method_run,
    }


def write_t0_campaign(path: Path, archive: Mapping[str, object]) -> None:
    """Write one immutable-style JSONL archive atomically."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(archive, ensure_ascii=True, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_t0_campaign")
    parser.add_argument("--pack", type=Path, required=True, help="gold-free public artifact pack JSON")
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--lineage-id", required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--replicate", type=int, required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--template-library", type=Path, default=ROOT / "configs" / "t0_templates.json")
    parser.add_argument("--proposal-slots", type=int, default=8)
    parser.add_argument("--out", type=Path, required=True, help="T0 archive root directory")
    args = parser.parse_args(argv)
    pack = json.loads(args.pack.read_text(encoding="utf-8-sig"))
    if not isinstance(pack, dict):
        raise SystemExit("public pack must be a JSON object")
    proposer = T0DeterministicProposer(T0TemplateLibrary.from_file(args.template_library))
    run = proposer.propose(pack, attempt_id=args.attempt_id, proposal_slots=args.proposal_slots)
    archive = build_t0_archive(
        pack,
        run,
        campaign_id=args.campaign_id,
        lineage_id=args.lineage_id,
        instance_id=args.instance_id,
        replicate=args.replicate,
    )
    path = args.out / args.campaign_id / "campaigns.jsonl"
    write_t0_campaign(path, archive)
    print(json.dumps({
        "archive": str(path),
        "campaign_id": args.campaign_id,
        "slot_count": len(run.method_run.slots),
        "candidate_count": len(run.candidate_hashes),
        "provider_call_count": 0,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
