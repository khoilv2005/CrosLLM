#!/usr/bin/env python3
"""Fetch the source commits locked for CrossLLM artifact collection.

This tool retrieves public upstream code into a caller-chosen *private* cache.
It does not alter the public dataset and does not fetch deployments, RPC data,
or exploit material.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


def run(*args: str, cwd: Path | None = None) -> str:
    completed = subprocess.run(args, cwd=cwd, text=True, check=True, capture_output=True)
    return completed.stdout.strip()


def normalize_remote(value: str) -> str:
    return value.strip().rstrip("/").removesuffix(".git").lower()


def archive_sha256(repo: Path) -> str:
    completed = subprocess.run(
        ("git", "archive", "--format=tar", "HEAD"),
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise SystemExit(f"Unable to archive {repo}: {detail}")
    return hashlib.sha256(completed.stdout).hexdigest()


def main(destination: Path, requested_lineages: set[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    lock = json.loads((root / "sources" / "source_lock.json").read_text(encoding="utf-8"))
    destination.mkdir(parents=True, exist_ok=True)
    receipt_path = destination / "retrieval_receipt.json"
    receipts_by_lineage = {}
    if receipt_path.exists():
        existing = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipts_by_lineage = {
            item["lineage_id"]: item for item in existing.get("lineages", [])
        }
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
            actual = run("git", "rev-parse", "HEAD", cwd=target)
            if actual != item["commit"]:
                raise SystemExit(f"Refusing to overwrite non-empty {target}")
            remote = run("git", "remote", "get-url", "origin", cwd=target)
            if normalize_remote(remote) != normalize_remote(item["repository"]):
                raise SystemExit(
                    f"Remote mismatch for {item['lineage_id']}: "
                    f"{remote} != {item['repository']}"
                )
        else:
            target.mkdir(exist_ok=True)
            run("git", "init", "-q", cwd=target)
            run("git", "remote", "add", "origin", item["repository"], cwd=target)
            run("git", "fetch", "--depth", "1", "origin", item["commit"], cwd=target)
            run("git", "checkout", "-q", "--detach", "FETCH_HEAD", cwd=target)
        actual = run("git", "rev-parse", "HEAD", cwd=target)
        if actual != item["commit"]:
            raise SystemExit(f"Commit mismatch for {item['lineage_id']}: {actual}")
        remote = run("git", "remote", "get-url", "origin", cwd=target)
        if normalize_remote(remote) != normalize_remote(item["repository"]):
            raise SystemExit(
                f"Remote mismatch for {item['lineage_id']}: "
                f"{remote} != {item['repository']}"
            )
        dirty = bool(run(
            "git", "status", "--porcelain=v1", "--untracked-files=all", cwd=target
        ))
        receipts_by_lineage[item["lineage_id"]] = {
            "lineage_id": item["lineage_id"],
            "repository": item["repository"],
            "commit": actual,
            "remote": remote,
            "dirty_worktree": dirty,
            "source_archive_sha256": archive_sha256(target),
        }
    receipts = [receipts_by_lineage[key] for key in sorted(receipts_by_lineage)]
    receipt_path.write_text(
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
