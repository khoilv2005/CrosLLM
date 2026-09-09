#!/usr/bin/env python3
"""
Generate a timestamped development snapshot receipt for the CrossLLM benchmark
proposal. Hashes are useful for detecting local changes, but this script never
turns synthetic manifests, generated mutations or template adjudication rows
into evaluation admission evidence.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = ROOT / "dataset" / "benchmark"
OUT_FILE = BENCHMARK_DIR / "commitment_receipt.json"

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def main():
    files_to_seal = {
        "benchmark_public_manifest": ROOT / "benchmark.public.jsonl",
        "benchmark_private_manifest": BENCHMARK_DIR / "benchmark.private.jsonl",
        "mutation_operators": BENCHMARK_DIR / "mutation_operators.json",
        "trigger_validation_evidence": BENCHMARK_DIR / "trigger_validation_evidence.jsonl",
        "adjudication_records": BENCHMARK_DIR / "adjudication_records.jsonl"
    }

    sealed_hashes = {}
    collective_hasher = hashlib.sha256()

    for name, path in files_to_seal.items():
        if not path.exists():
            raise FileNotFoundError(f"Required benchmark artifact missing: {path}")
        digest = sha256_file(path)
        sealed_hashes[name] = {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": digest
        }
        collective_hasher.update(digest.encode("utf-8"))

    commitment_root = collective_hasher.hexdigest()

    receipt = {
        "commitment_version": "1.0.0",
        "protocol_gate": "Development proposal snapshot (not benchmark-ready)",
        "status": "DEVELOPMENT_TEMPLATE_ONLY",
        "seal_timestamp": "2026-09-08T00:00:00Z",
        "total_instances_structurally_proposed": 240,
        "total_instances_admitted": 0,
        "evaluation_lineages_count": 12,
        "sealed_artifacts": sealed_hashes,
        "collective_commitment_merkle_root": commitment_root,
        "adjudication_verdict": "PENDING_INDEPENDENT_REVIEW",
        "notes": "Hashes provide a development snapshot only; they do not prove source ancestry, semantic mutations, triggers, controls, independent labels or evaluation admission."
    }

    with OUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2)

    print("=" * 70)
    print("CrossLLM Benchmark Development Snapshot Hashed")
    print(f"Commitment Root SHA-256: {commitment_root}")
    print(f"Receipt written to: {OUT_FILE.relative_to(ROOT)}")
    print("=" * 70)

if __name__ == "__main__":
    main()
