#!/usr/bin/env python3
"""Fetch the source commits locked for CrossLLM artifact collection.

This tool retrieves public upstream code into a caller-chosen *private* cache.
It does not alter the public dataset and does not fetch deployments, RPC data,
or exploit material.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def run(*args: str, cwd: Path | None = None) -> str:
    completed = subprocess.run(args, cwd=cwd, text=True, check=True, capture_output=True)
    return completed.stdout.strip()


def main(destination: Path, requested_lineages: set[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    lock = json.loads((root / "sources" / "source_lock.json").read_text(encoding="utf-8"))
    destination.mkdir(parents=True, exist_ok=True)
    receipts = []
    selected = [
        item for item in lock["lineages"]
        if requested_lineages is None or item["lineage_id"] in requested_lineages
    ]
    unknown = (requested_lineages or set()) - {item["lineage_id"] for item in lock["lineages"]}
    if unknown:
        raise SystemExit(f"Unknown lineage identifiers: {', '.join(sorted(unknown))}")
    for item in selected:
        target = destination / item["lineage_id"]
        if target.exists() and any(target.iterdir()):
            raise SystemExit(f"Refusing to overwrite non-empty {target}")
        target.mkdir(exist_ok=True)
        run("git", "init", "-q", cwd=target)
        run("git", "remote", "add", "origin", item["repository"], cwd=target)
        run("git", "fetch", "--depth", "1", "origin", item["commit"], cwd=target)
        run("git", "checkout", "-q", "--detach", "FETCH_HEAD", cwd=target)
        actual = run("git", "rev-parse", "HEAD", cwd=target)
        if actual != item["commit"]:
            raise SystemExit(f"Commit mismatch for {item['lineage_id']}: {actual}")
        receipts.append({"lineage_id": item["lineage_id"], "repository": item["repository"], "commit": actual})
    (destination / "retrieval_receipt.json").write_text(
        json.dumps({"lock_status": lock["lock_status"], "lineages": receipts}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"OK: fetched {len(receipts)} locked source trees into {destination}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: fetch_pinned_sources.py PRIVATE_SOURCE_CACHE [LINEAGE_ID ...]")
    selected = set(sys.argv[2:]) or None
    raise SystemExit(main(Path(sys.argv[1]).resolve(), selected))
