#!/usr/bin/env python3
"""Materialize the offline verification queue for completed gpt-oss proposals.

The command re-parses every archived provider response against the stored public
artifact pack.  It is intentionally fail-closed: grounded XLIR is *not* a
verified finding.  The shared candidate-to-runtime adapter and verification
metrics contracts are available, but source-backed symbolic search, witness
construction, and independent replay remain pending until a concrete runtime
executor is supplied. No provider, Docker, or replay command is invoked by
this preparatory step.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from crossllm.methods import parse_json_response
from run_evaluation_proposal_stage import _compiler
DEFAULT_RUN_ROOT = ROOT / "build" / "evaluation_runs" / "r3_primary"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    temporary.replace(path)


def _manifest(path: Path) -> dict[str, dict[str, object]]:
    records: dict[str, dict[str, object]] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict) or not isinstance(value.get("instance_id"), str):
            raise ValueError(f"{path}:{number}: invalid manifest row")
        records[value["instance_id"]] = value
    return records


def _archive(path: Path) -> dict[str, Any]:
    rows = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != 1:
        raise ValueError(f"{path}: expected exactly one JSONL row")
    value = json.loads(rows[0])
    if not isinstance(value, dict):
        raise ValueError(f"{path}: invalid archive row")
    return value


def _queue_for_arm(root: Path, arm: str, manifest: dict[str, dict[str, object]]) -> tuple[list[dict[str, object]], list[str]]:
    queued: list[dict[str, object]] = []
    errors: list[str] = []
    for path in sorted(root.glob("*/campaigns.jsonl")):
        try:
            archive = _archive(path)
            campaign = archive["campaign"]
            method_run = archive["method_run"]
            pack = archive["public_artifact_pack"]
            instance_id = campaign["instance_id"]
            responses = method_run["provider_responses"]
            slots = method_run["slots"]
            if not all(isinstance(value, list) and len(value) == 8 for value in (responses, slots)):
                raise ValueError("expected exactly eight responses and slots")
            if not isinstance(pack, dict) or not isinstance(instance_id, str) or instance_id not in manifest:
                raise ValueError("missing public pack or benchmark instance")
            compiler = _compiler(pack)
            for index, (response, slot) in enumerate(zip(responses, slots)):
                if not isinstance(response, dict) or not isinstance(slot, dict):
                    raise ValueError(f"slot {index}: invalid receipt")
                candidate = None
                reason: str | None = None
                if response.get("http_status") != 200:
                    reason = "provider_response_not_successful"
                elif not isinstance(response.get("response_text"), str):
                    reason = "response_text_missing"
                else:
                    try:
                        payload = parse_json_response(response["response_text"])
                        if isinstance(payload, dict) and payload.get("abstain") is True:
                            reason = "model_abstained"
                        else:
                            compiled = compiler.compile(payload)
                            if compiled.ok:
                                candidate = compiled.invariant
                            else:
                                reason = "xlir_compile_rejected"
                    except (ValueError, TypeError, json.JSONDecodeError):
                        reason = "response_not_parseable_as_xlir"
                queued.append({
                    "schema_version": 1,
                    "record_type": "gptoss_verification_queue_item",
                    "campaign_id": campaign["campaign_id"],
                    "arm": arm,
                    "instance_id": instance_id,
                    "lineage_id": campaign["lineage_id"],
                    "replicate": campaign["replicate"],
                    "slot": index,
                    "proposal_status": slot.get("status"),
                    "grounding": "passed" if candidate is not None else "rejected",
                    "xlir": "passed" if candidate is not None else "rejected",
                    "candidate_hash": getattr(candidate, "canonical_hash", None),
                    "symbolic_search": "pending_source_backed_executor" if candidate is not None else "not_applicable",
                    "witness_check": "pending_source_backed_executor" if candidate is not None else "not_applicable",
                    "native_replay": "pending_source_backed_executor" if candidate is not None else "not_applicable",
                    "verification_status": "pending_source_backed_executor" if candidate is not None else "not_a_grounded_candidate",
                    "reason": "source_backed_verification_executor_missing" if candidate is not None else reason,
                    "ground_truth": manifest[instance_id]["status"],
                    "property_family": manifest[instance_id]["property_family"],
                    "paired_instance_id": manifest[instance_id].get("paired_instance_id"),
                    "archive": str(path),
                })
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{path}: {exc}")
    return queued, errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--manifest", type=Path, default=ROOT / "dataset" / "benchmark" / "benchmark.public.jsonl")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    manifest = _manifest(args.manifest)
    output = args.out or args.run_root / "gptoss_verification"
    items: list[dict[str, object]] = []
    errors: list[str] = []
    for arm, directory in (("crossllm", args.run_root / "gpt-oss_cross"), ("direct", args.run_root / "gpt-oss_direct")):
        arm_items, arm_errors = _queue_for_arm(directory, arm, manifest)
        items.extend(arm_items)
        errors.extend(arm_errors)
    candidate_items = [item for item in items if item["verification_status"] == "pending_source_backed_executor"]
    report = {
        "schema_version": 1,
        "record_type": "gptoss_verification_preflight",
        "offline_only": True,
        "archive_campaigns": len({(item["arm"], item["campaign_id"]) for item in items}),
        "queue_items": len(items),
        "grounded_candidates": len(candidate_items),
        "candidate_to_runtime_adapter": "shared_runtime_adapter_available",
        "verified_findings": 0,
        "verified_recall": "unavailable; no candidate-specific symbolic/witness/replay outcomes exist",
        "t0": "offline deterministic proposer available; corpus run pending",
        "negative_false_alert_rate": "unavailable; candidate-specific backend outcomes do not exist",
        "statistical_pipeline": "shared verification metrics and analysis exporters available; raw verification outcomes pending",
        "errors": errors,
    }
    _write_jsonl(output / "queue.jsonl", items)
    _write_json(output / "preflight.json", report)
    print(json.dumps({"archives": report["archive_campaigns"], "queue_items": len(items), "grounded_candidates": len(candidate_items), "errors": len(errors)}, sort_keys=True))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
