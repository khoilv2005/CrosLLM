#!/usr/bin/env python3
"""CrossLLM Master Checksum Generator.

Computes canonical SHA-256 hashes for all dataset files (excluding git and caches)
and writes the authoritative root dataset/checksums.sha256 manifest.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = ROOT / "dataset"
EXCLUDED_DATASET_FILES = {
    # Private gold, exact triggers and adjudication labels must not enter the
    # public master checksum manifest.
    "benchmark.private.jsonl",
    "adjudication_records.jsonl",
}

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()

def main() -> int:
    print("=" * 60)
    print("Generating CrossLLM Master Artifact Checksums")
    print("=" * 60)
    
    checksum_lines = []
    file_count = 0
    
    # Target directories to hash
    target_subdirs = [
        "artifacts", "benchmark", "cases", "harness", "sources", "reports", "schemas"
    ]
    
    all_files: list[Path] = []
    for sub in target_subdirs:
        subpath = DATASET_DIR / sub
        if not subpath.exists():
            continue
        for p in subpath.rglob("*"):
            if p.is_file():
                # Skip existing root checksum file or temp files
                if p.name == "checksums.sha256" and p.parent == DATASET_DIR:
                    continue
                if any(part.startswith(".") for part in p.parts):
                    continue
                if "__pycache__" in p.parts:
                    continue
                if p.name in EXCLUDED_DATASET_FILES:
                    continue
                all_files.append(p)
                
    # Sort deterministically by relative path posix
    all_files.sort(key=lambda x: x.relative_to(DATASET_DIR).as_posix())
    
    for f in all_files:
        sha = sha256_file(f)
        rel = f.relative_to(DATASET_DIR).as_posix()
        checksum_lines.append(f"{sha}  {rel}")
        file_count += 1
        
    out_file = DATASET_DIR / "checksums.sha256"
    out_file.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    
    print(f"[OK] Master checksums generated: {file_count} files hashed.")
    print(f"Written to: {out_file.relative_to(ROOT)}")
    print("=" * 60)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
