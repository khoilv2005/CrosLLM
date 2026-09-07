#!/usr/bin/env python3
"""Validate the public CrossLLM dataset starter without third-party packages."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ALLOWED_CASE_KINDS = {
    "historical_positive", "sealed_positive", "patched_negative",
    "benign_negative", "traffic_auxiliary",
}
ALLOWED_STATUSES = {"candidate", "admitted", "rejected", "sealed_pending", "sealed_ready"}
ALLOWED_SPLITS = {"development", "evaluation", "unassigned"}


def read_jsonl(path: Path):
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                yield line_number, json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {error.msg}") from error


def validate_case(path: Path, line_number: int, case: dict, source_ids: set[str], case_ids: set[str]) -> list[str]:
    errors: list[str] = []
    prefix = f"{path.name}:{line_number}"
    for field in ("case_id", "case_kind", "admission_status", "lineage_id", "split"):
        if not case.get(field):
            errors.append(f"{prefix}: missing {field}")
    if case.get("case_id") in case_ids:
        errors.append(f"{prefix}: duplicate case_id {case['case_id']}")
    else:
        case_ids.add(case.get("case_id"))
    if case.get("case_kind") not in ALLOWED_CASE_KINDS:
        errors.append(f"{prefix}: invalid case_kind")
    if case.get("admission_status") not in ALLOWED_STATUSES:
        errors.append(f"{prefix}: invalid admission_status")
    if case.get("split") not in ALLOWED_SPLITS:
        errors.append(f"{prefix}: invalid split")
    for source_id in case.get("source_ids", []):
        if source_id not in source_ids:
            errors.append(f"{prefix}: unknown source_id {source_id}")
    if case.get("admission_status") == "admitted":
        for field in ("ground_truth_evidence", "trigger_validation", "control_pair_id"):
            if not case.get(field):
                errors.append(f"{prefix}: admitted case missing {field}")
    if case.get("case_kind") == "sealed_positive":
        for field in ("ground_truth_evidence", "trigger_validation", "control_pair_id"):
            if not case.get(field):
                errors.append(f"{prefix}: sealed positive missing {field}")
        forbidden = {"exploit_payload", "private_key", "rpc_url", "broadcast_command"}
        present = forbidden.intersection(case)
        if present:
            errors.append(f"{prefix}: public sealed record exposes forbidden fields {sorted(present)}")
    return errors


def main(root: Path) -> int:
    registry_path = root / "sources" / "source_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    source_ids = {item["source_id"] for item in registry["sources"]}
    expected_roles = {"historical_inventory", "historical_replay_reference", "independent_replay_reference", "cross_chain_transaction_metadata", "traffic_auxiliary", "sealed_host_lineage"}
    errors = []
    for source in registry["sources"]:
        if source.get("role") not in expected_roles:
            errors.append(f"source registry: invalid role for {source.get('source_id')}")
        if not str(source.get("url", "")).startswith("https://"):
            errors.append(f"source registry: non-HTTPS URL for {source.get('source_id')}")

    case_ids: set[str] = set()
    for filename in ("historical_candidates.jsonl",):
        path = root / "cases" / filename
        for line_number, case in read_jsonl(path):
            errors.extend(validate_case(path, line_number, case, source_ids, case_ids))

    host_path = root / "cases" / "sealed_hosts.jsonl"
    host_ids: set[str] = set()
    hosts_by_id: dict[str, dict] = {}
    for line_number, host in read_jsonl(host_path):
        prefix = f"{host_path.name}:{line_number}"
        for field in ("host_id", "protocol", "lineage_id", "source_id", "split", "admission_status"):
            if not host.get(field):
                errors.append(f"{prefix}: missing {field}")
        if host.get("host_id") in host_ids:
            errors.append(f"{prefix}: duplicate host_id {host['host_id']}")
        host_ids.add(host.get("host_id"))
        if host.get("source_id") not in source_ids:
            errors.append(f"{prefix}: unknown source_id {host.get('source_id')}")
        if host.get("admission_status") not in {"sealed_pending", "sealed_ready", "rejected"}:
            errors.append(f"{prefix}: invalid host admission_status")
        hosts_by_id[host.get("host_id")] = host

    lock_path = root / "sources" / "source_lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    locked_host_ids: set[str] = set()
    locked_lineages: set[str] = set()
    lock_splits = {"development": 0, "evaluation": 0}
    for item in lock["lineages"]:
        prefix = f"{lock_path.name}:{item.get('lineage_id', '<unknown>')}"
        for field in ("host_id", "lineage_id", "source_id", "repository", "commit", "split", "artifact_status"):
            if not item.get(field):
                errors.append(f"{prefix}: missing {field}")
        if item.get("host_id") in locked_host_ids:
            errors.append(f"{prefix}: duplicate host_id")
        if item.get("lineage_id") in locked_lineages:
            errors.append(f"{prefix}: duplicate lineage_id")
        locked_host_ids.add(item.get("host_id"))
        locked_lineages.add(item.get("lineage_id"))
        if item.get("source_id") not in source_ids:
            errors.append(f"{prefix}: unknown source_id {item.get('source_id')}")
        if item.get("split") not in lock_splits:
            errors.append(f"{prefix}: invalid split")
        else:
            lock_splits[item["split"]] += 1
        commit = item.get("commit", "")
        if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit):
            errors.append(f"{prefix}: commit is not a lowercase full SHA-1")
        host = hosts_by_id.get(item.get("host_id"))
        if host is not None:
            for field in ("lineage_id", "split", "source_id"):
                if item.get(field) != host.get(field):
                    errors.append(
                        f"{prefix}: {field} does not match sealed host registry"
                    )

    if locked_host_ids != host_ids:
        errors.append("source lock and sealed host registry have different host identifiers")
    if lock_splits != {"development": 4, "evaluation": 12}:
        errors.append(f"source lock split must remain 4 development / 12 evaluation, got {lock_splits}")

    lock_by_lineage = {item["lineage_id"]: item for item in lock["lineages"]}
    receipt_path = root / "artifacts" / "source_receipts.jsonl"
    receipt_lineages: set[str] = set()
    for line_number, receipt in read_jsonl(receipt_path):
        prefix = f"{receipt_path.name}:{line_number}"
        lineage = receipt.get("lineage_id")
        if lineage not in lock_by_lineage:
            errors.append(f"{prefix}: unknown lineage_id {lineage}")
            continue
        if lineage in receipt_lineages:
            errors.append(f"{prefix}: duplicate lineage receipt")
        receipt_lineages.add(lineage)
        if receipt.get("source_commit") != lock_by_lineage[lineage]["commit"]:
            errors.append(f"{prefix}: source_commit does not match source lock")
        archive_hash = receipt.get("source_archive_sha256", "")
        if len(archive_hash) != 64 or any(char not in "0123456789abcdef" for char in archive_hash):
            errors.append(f"{prefix}: source_archive_sha256 is not a lowercase SHA-256")
        if receipt.get("artifact_admission_status") != "source_pinned_only":
            errors.append(f"{prefix}: unexpected artifact_admission_status")
    pinned_in_lock = {item["lineage_id"] for item in lock["lineages"] if item["artifact_status"] == "source_pinned"}
    if receipt_lineages != pinned_in_lock:
        errors.append("source receipts and source_pinned lock entries differ")

    if errors:
        print("FAILED")
        print("\n".join(errors))
        return 1
    print(
        f"OK: {len(case_ids)} historical candidates, {len(host_ids)} sealed host lineages "
        f"({lock_splits['development']} development / {lock_splits['evaluation']} evaluation), "
        f"{len(receipt_lineages)} source-pinned, {len(source_ids)} registered sources"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1] if len(sys.argv) == 2 else ".").resolve()))
