#!/usr/bin/env python3
"""
Generate CrossLLM benchmark manifests:
- dataset/benchmark/benchmark.public.jsonl (blinded, evaluation-compliant)
- dataset/benchmark/benchmark.private.jsonl (contains ground-truth secret properties & triggers)
- root benchmark.public.jsonl (convenience link/copy for protocol_tool validation)

Conforms to schemas/benchmark_manifest.schema.json and tools/protocol_tool.py.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = ROOT / "dataset"
BENCHMARK_DIR = DATASET_DIR / "benchmark"
OPERATORS_PATH = BENCHMARK_DIR / "mutation_operators.json"
SOURCE_LOCK_PATH = DATASET_DIR / "sources" / "source_lock.json"
SEALED_HOSTS_PATH = DATASET_DIR / "cases" / "sealed_hosts.jsonl"

SEAL_TIMESTAMP = "2026-09-08T00:00:00Z"

def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def load_sources_and_hosts():
    with SOURCE_LOCK_PATH.open(encoding="utf-8") as f:
        source_lock = json.load(f)
    lineage_locks = {l["lineage_id"]: l for l in source_lock["lineages"]}

    sealed_hosts = {}
    with SEALED_HOSTS_PATH.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                h = json.loads(line)
                sealed_hosts[h["lineage_id"]] = h

    return lineage_locks, sealed_hosts

def load_operators():
    with OPERATORS_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    return data["operators"]

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate an explicitly synthetic CrossLLM benchmark proposal."
    )
    parser.add_argument(
        "--allow-synthetic-proposal",
        action="store_true",
        help=(
            "opt in to deterministic fixture generation; the output is not "
            "evaluation evidence and is never admitted by this flag"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.allow_synthetic_proposal:
        print(
            "REFUSING to generate benchmark manifests: this script creates "
            "synthetic proposal data, not independently validated evidence.",
            file=sys.stderr,
        )
        print(
            "Re-run with --allow-synthetic-proposal only for development fixtures.",
            file=sys.stderr,
        )
        return 2

    print(
        "WARNING: generating synthetic proposal fixtures; output is not "
        "evaluation-admissible evidence.",
        file=sys.stderr,
    )
    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    lineage_locks, sealed_hosts = load_sources_and_hosts()
    operators = load_operators()

    eval_lineages = [
        "hyperlane", "axelar_gmp", "synapse", "wormhole_evm_sdk",
        "across", "stargate", "arbitrum_token_bridge", "optimism",
        "zksync_era", "polygon_zkevm", "scroll", "linea"
    ]

    public_rows: list[dict[str, Any]] = []
    private_rows: list[dict[str, Any]] = []

    # Map operators into 10 target evaluation pairs per lineage
    # Operators order:
    # 0: OP_REPLAY_NONCE_REMOVAL (replay)
    # 1: OP_REPLAY_DOMAIN_STRIP (replay)
    # 2: OP_SPOOF_SOURCE_SENDER (input_validation)
    # 3: OP_SPOOF_CHAIN_ID (input_validation)
    # 4: OP_INVARIANT_FEE_UNDERFLOW (logic)
    # 5: OP_INVARIANT_ACCOUNTING_DESYNC (logic)
    # 6: OP_UNVERIFIED_CALLER_BYPASS (message_handling)
    # 7: OP_CALLBACK_REENTRANCY (message_handling)
    # 8: OP_QUORUM_THRESHOLD_DECREMENT (quorum)
    # 9: OP_FINALITY_WINDOW_TRUNCATION (finality)

    for lineage_id in eval_lineages:
        lock = lineage_locks[lineage_id]
        host = sealed_hosts[lineage_id]

        art_dir = DATASET_DIR / "artifacts" / lineage_id
        receipt_path = art_dir / "source_receipt.json"
        build_path = art_dir / "build_info.json"
        channel_path = art_dir / "channel_profile.json"

        with receipt_path.open(encoding="utf-8") as f:
            receipt = json.load(f)
        with build_path.open(encoding="utf-8") as f:
            build_info = json.load(f)
        with channel_path.open(encoding="utf-8") as f:
            channel_info = json.load(f)

        source_commit = lock["commit"]
        source_repo = lock["repository"]
        source_sha256 = receipt.get("source_archive_sha256") or sha256_text(f"SRC:{lineage_id}:{source_commit}")
        compiler_hash = sha256_text(json.dumps(build_info, sort_keys=True))

        source_chains = channel_info.get("source_domains", ["ethereum"])
        target_chains = channel_info.get("target_domains", ["arbitrum"])
        c_src = source_chains[0].lower() if source_chains else "ethereum"
        c_dst = target_chains[1].lower() if len(target_chains) > 1 else "arbitrum"
        chain_pair = [c_src, c_dst]

        architecture = host.get("architecture", "canonical_L1_L2_bridge")
        threat_profile_id = f"threat_{lineage_id}_cross_domain_v1"
        attestation_profile_id = f"attest_{channel_info.get('message_passing', 'relayer_attestation')}"
        protocol_name = host.get("protocol", lineage_id.replace("_", " ").title())
        version_id = f"v_{source_commit[:8]}"

        for idx, op in enumerate(operators, 1):
            op_id = op["operator_id"]
            family = op["property_family"]
            pair_num = f"{idx:02d}"

            mutant_id = f"eval_{lineage_id}_mut_{pair_num}"
            control_id = f"eval_{lineage_id}_ctrl_{pair_num}"
            # Opaque gold_property_id to prevent leaking property semantics in public manifest
            gold_prop_id = f"prop_opq_{sha256_text(f'{family}:{lineage_id}:{pair_num}')[:16]}"

            # Distinct artifact pack sha256 for each instance
            mutant_pack_sha = sha256_text(f"CROSSLLM:ARTIFACT_PACK:{mutant_id}:{op_id}:{source_commit}")
            control_pack_sha = sha256_text(f"CROSSLLM:ARTIFACT_PACK:{control_id}:{op_id}:{source_commit}")

            evidence_mutant = sha256_text(f"EVIDENCE:MUTANT:{mutant_id}:{gold_prop_id}:{op_id}")
            evidence_control = sha256_text(f"EVIDENCE:CONTROL:{control_id}:{gold_prop_id}:{op_id}")

            # Vulnerable Mutant Instance (Cohort: sealed) - Public blinded row
            vulnerable_row = {
                "instance_id": mutant_id,
                "lineage_id": lineage_id,
                "protocol_name": protocol_name,
                "version_id": version_id,
                "parent_instance_id": None,
                "paired_instance_id": control_id,
                "split": "evaluation",
                "cohort": "sealed",
                "status": "vulnerable",
                "source_repository": source_repo,
                "source_commit": source_commit,
                "source_sha256": source_sha256,
                "artifact_pack_sha256": mutant_pack_sha,
                "compiler_settings_hash": compiler_hash,
                "chain_pair": chain_pair,
                "architecture": architecture,
                "threat_profile_id": threat_profile_id,
                "attestation_profile_id": attestation_profile_id,
                "property_family": family,
                "gold_property_id": gold_prop_id,
                "ground_truth_evidence_hash": evidence_mutant,
                "trigger_validation_status": "pass",
                "provenance_status": "synthetic_proposal",
                "native_evm_scope": True,
                "mutation_operator_id": None,
                "seal_timestamp": SEAL_TIMESTAMP,
                "infrastructure_contract_count": 2
            }

            # Patched/Negative Control Instance (Cohort: negative) - Public blinded row
            control_row = {
                "instance_id": control_id,
                "lineage_id": lineage_id,
                "protocol_name": protocol_name,
                "version_id": version_id,
                "parent_instance_id": None,
                "paired_instance_id": mutant_id,
                "split": "evaluation",
                "cohort": "negative",
                "status": "patched",
                "source_repository": source_repo,
                "source_commit": source_commit,
                "source_sha256": source_sha256,
                "artifact_pack_sha256": control_pack_sha,
                "compiler_settings_hash": compiler_hash,
                "chain_pair": chain_pair,
                "architecture": architecture,
                "threat_profile_id": threat_profile_id,
                "attestation_profile_id": attestation_profile_id,
                "property_family": family,
                "gold_property_id": gold_prop_id,
                "ground_truth_evidence_hash": evidence_control,
                "trigger_validation_status": "pass",
                "provenance_status": "synthetic_proposal",
                "native_evm_scope": True,
                "mutation_operator_id": None,
                "seal_timestamp": SEAL_TIMESTAMP,
                "negative_validation_scope": {
                    "scope_type": "contract_level_invariant",
                    "conservation_invariants_verified": True,
                    "exploit_blocked": True,
                    "legitimate_workflow_preserved": True
                },
                "infrastructure_contract_count": 2
            }

            # Secret ground truth payloads (strictly stored in benchmark.private.jsonl)
            trigger_payload = "0x" + sha256_text(f"TRIGGER_CALLDATA_{mutant_id}")[:8] + "000000000000000000000000" + sha256_text(f"ARG_{op_id}")[:40]
            mutation_diff_sim = f"--- a/contracts/{lineage_id}/Bridge.sol\n+++ b/contracts/{lineage_id}/Bridge.sol\n@@ -42,7 +42,6 @@\n- {op['transformation']}\n+ // MUTATION APPLIED: {op_id}"

            vulnerable_private = copy.deepcopy(vulnerable_row)
            vulnerable_private["mutation_operator_id"] = op_id
            vulnerable_private["gold_property"] = op["intended_security_property"]
            vulnerable_private["trigger_calldata"] = trigger_payload
            vulnerable_private["exploit_payload"] = {
                "attack_vector": op["semantic_consequence"],
                "calldata": trigger_payload,
                "expected_revert_on_patch": True
            }
            vulnerable_private["mutation_diff"] = mutation_diff_sim

            control_private = copy.deepcopy(control_row)
            control_private["mutation_operator_id"] = op_id
            control_private["gold_property"] = op["intended_security_property"]
            control_private["trigger_calldata"] = trigger_payload
            control_private["exploit_payload"] = {
                "attack_vector": op["negative_control_policy"],
                "calldata": trigger_payload,
                "expected_revert_on_patch": True
            }
            control_private["mutation_diff"] = "// Clean patched variant; operator not applied"

            public_rows.append(vulnerable_row)
            public_rows.append(control_row)
            private_rows.append(vulnerable_private)
            private_rows.append(control_private)

    # Write public manifest
    public_path = BENCHMARK_DIR / "benchmark.public.jsonl"
    with public_path.open("w", encoding="utf-8") as f:
        for row in public_rows:
            f.write(json.dumps(row) + "\n")

    # Write private manifest
    private_path = BENCHMARK_DIR / "benchmark.private.jsonl"
    with private_path.open("w", encoding="utf-8") as f:
        for row in private_rows:
            f.write(json.dumps(row) + "\n")

    # Create convenient copy at root
    root_public_path = ROOT / "benchmark.public.jsonl"
    shutil.copyfile(public_path, root_public_path)

    print(f"Generated {len(public_rows)} instances across {len(eval_lineages)} evaluation lineages.")
    print(f"Public manifest:  {public_path} ({root_public_path})")
    print(f"Private manifest: {private_path}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
