#!/usr/bin/env python3
"""Export gold-free Qwen3.8 local-model proposal inputs for Colab.

This creates a separate exploratory model arm. It never reads private benchmark
labels and it deliberately derives new campaign IDs, avoiding collisions with
the existing cloud-Qwen archives.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from uuid import NAMESPACE_URL, uuid5
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from crossllm.contracts.canonical import canonical_json, sha256_hex  # noqa: E402
from run_evaluation_proposal_stage import PROMPT_PATHS, _public_pack  # noqa: E402

MODEL_TAG = "Qwen/Qwen3.8-27B-local-4bit"
BACKBONE = "Qwen3.8-27B-local"


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--zip-out", type=Path, required=True)
    parser.add_argument("--plan", type=Path, default=ROOT / "protocol" / "locks" / "campaigns.plan.json")
    parser.add_argument("--max-campaigns", type=int, default=None)
    args = parser.parse_args()

    plan = _load(args.plan)
    plan_rows = plan.get("campaigns")
    if not isinstance(plan_rows, list):
        raise ValueError("campaign plan has no campaigns list")
    selected = [
        row for row in plan_rows
        if isinstance(row, dict) and row.get("backbone") == "Qwen"
        and row.get("method") in PROMPT_PATHS
    ]
    selected.sort(key=lambda row: str(row["campaign_id"]))
    if args.max_campaigns is not None:
        selected = selected[:args.max_campaigns]
    if not selected:
        raise ValueError("no Qwen campaigns selected")

    packs: dict[str, dict[str, object]] = {}
    rows: list[dict[str, object]] = []
    for source in selected:
        source_id = str(source["campaign_id"])
        method = str(source["method"])
        lineage = str(source["lineage_id"])
        pack = packs.setdefault(lineage, _public_pack(lineage))
        campaign = dict(source)
        campaign_id = str(uuid5(NAMESPACE_URL, f"qwen38-local:{source_id}"))
        campaign.update({
            "campaign_id": campaign_id,
            "backbone": BACKBONE,
            "model_tag": MODEL_TAG,
            "source_campaign_id": source_id,
            "status": "planned_local_exploratory",
        })
        prompt_template = PROMPT_PATHS[method].read_text(encoding="utf-8")
        rows.append({
            "campaign_id": campaign_id,
            "source_campaign_id": source_id,
            "arm": "crossllm" if method == "crossllm_e2e" else "direct",
            "method": method,
            "campaign": campaign,
            "public_artifact_pack": pack,
            "public_artifact_pack_hash": sha256_hex(pack),
            "prompt": prompt_template.replace("{artifact_pack}", canonical_json(pack).decode("ascii")),
        })

    args.out_dir.mkdir(parents=True, exist_ok=True)
    campaigns_path = args.out_dir / "campaigns.jsonl"
    campaigns_path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    manifest = {
        "record_type": "qwen38_local_colab_input_manifest",
        "model_tag": MODEL_TAG,
        "campaign_count": len(rows),
        "source_plan": str(args.plan),
        "campaigns_sha256": _sha256(campaigns_path),
        "privacy": "gold-free public artifact packs only",
        "scope": "exploratory local-model arm; requires a protocol amendment before primary-result pooling",
    }
    _write_json(args.out_dir / "manifest.json", manifest)
    args.zip_out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.zip_out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.write(campaigns_path, "campaigns.jsonl")
        archive.write(args.out_dir / "manifest.json", "manifest.json")
    print(json.dumps({"campaigns": len(rows), "zip": str(args.zip_out), "sha256": _sha256(args.zip_out)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
