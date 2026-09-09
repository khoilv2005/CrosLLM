#!/usr/bin/env python3
"""Audit a private source cache against the immutable lineage lock.

The command is read-only with respect to the cache and public dataset.  It
checks HEAD, worktree cleanliness and a byte-level ``git archive`` digest.  It
also checks the configured origin and inventories tracked license files. It
never promotes a lineage or rewrites a receipt; discrepancies are evidence
that must be reviewed before artifact admission.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess



def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(args, cwd=cwd, capture_output=True, timeout=120, check=False)


def _normalize_remote(value: str) -> str:
    """Compare GitHub remotes without treating a trailing .git as material."""
    return value.strip().rstrip("/").removesuffix(".git").lower()


def _tracked_license_paths(repo: Path) -> list[str]:
    result = _run("git", "ls-tree", "-r", "--name-only", "HEAD", cwd=repo)
    if result.returncode != 0:
        return []
    names = result.stdout.decode("utf-8", errors="replace").splitlines()
    license_names = {"license", "license.md", "license.txt", "copying", "copying.md"}
    return sorted(
        name for name in names
        if Path(name).name.lower() in license_names
    )


def audit(root: Path, cache: Path, *, docker_archive_image: str | None = None) -> dict[str, object]:
    lock = json.loads((root / "dataset" / "sources" / "source_lock.json").read_text(encoding="utf-8"))
    registry_path = root / "dataset" / "sources" / "source_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.is_file() else {}
    registry_by_id = {
        row.get("source_id"): row
        for row in registry.get("sources", [])
        if isinstance(row, dict) and row.get("source_id")
    }
    receipt_path = root / "dataset" / "artifacts" / "source_receipts.jsonl"
    expected_archives: dict[str, str] = {}
    if receipt_path.is_file():
        for line_number, line in enumerate(receipt_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            lineage = row.get("lineage_id")
            archive = row.get("source_archive_sha256")
            if isinstance(lineage, str) and isinstance(archive, str):
                if lineage in expected_archives:
                    raise ValueError(f"duplicate source receipt for {lineage} at line {line_number}")
                expected_archives[lineage] = archive

    rows: list[dict[str, object]] = []
    for item in lock["lineages"]:
        lineage = item["lineage_id"]
        repo = cache / lineage
        row: dict[str, object] = {"lineage_id": lineage, "path": str(repo)}
        if not (repo / ".git").exists():
            row.update({"status": "MISSING", "reason": "git_repository_missing"})
            rows.append(row)
            continue
        head_result = _run("git", "rev-parse", "HEAD", cwd=repo)
        head = head_result.stdout.decode("utf-8", errors="replace").strip()
        remote_result = _run("git", "remote", "get-url", "origin", cwd=repo)
        remote = remote_result.stdout.decode("utf-8", errors="replace").strip()
        status_result = _run("git", "status", "--porcelain=v1", "--untracked-files=all", cwd=repo)
        dirty = bool(status_result.stdout.strip())
        archive_result = _run("git", "archive", "--format=tar", "HEAD", cwd=repo)
        archive_backend = "host"
        host_archive_stderr = archive_result.stderr.decode("utf-8", errors="replace").strip() or None
        if archive_result.returncode != 0 and docker_archive_image:
            docker_result = _run(
                "docker", "run", "--rm", "--network=none", "--read-only",
                "-v", f"{cache.resolve()}:/sources:ro",
                docker_archive_image, "git", "-C", f"/sources/{lineage}",
                "archive", "--format=tar", "HEAD", cwd=root,
            )
            if docker_result.returncode == 0:
                archive_result = docker_result
                archive_backend = "docker"
            else:
                docker_stderr = docker_result.stderr.decode("utf-8", errors="replace").strip() or None
                host_archive_stderr = "; ".join(
                    detail for detail in (
                        host_archive_stderr,
                        f"docker fallback: {docker_stderr}" if docker_stderr else None,
                    ) if detail
                ) or None
        archive_hash = hashlib.sha256(archive_result.stdout).hexdigest() if archive_result.returncode == 0 else None
        license_paths = _tracked_license_paths(repo)
        registry_row = registry_by_id.get(item.get("source_id"), {})
        expected_archive = expected_archives.get(lineage)
        commit_match = head == item["commit"]
        remote_match = bool(remote) and _normalize_remote(remote) == _normalize_remote(item["repository"])
        archive_match = expected_archive is not None and archive_hash == expected_archive
        if archive_result.returncode != 0:
            status = "ARCHIVE_FAILED"
        elif not remote_match:
            status = "REMOTE_MISMATCH"
        elif not commit_match:
            status = "COMMIT_MISMATCH"
        elif dirty:
            status = "DIRTY_WORKTREE"
        elif expected_archive is not None and not archive_match:
            status = "ARCHIVE_MISMATCH"
        else:
            status = "PASS"
        row.update({
            "status": status,
            "head": head,
            "expected_commit": item["commit"],
            "commit_match": commit_match,
            "remote": remote or None,
            "expected_remote": item["repository"],
            "remote_match": remote_match,
            "dirty_worktree": dirty,
            "archive_sha256": archive_hash,
            "expected_archive_sha256": expected_archive,
            "archive_match": archive_match if expected_archive is not None else None,
            "archive_backend": archive_backend,
            "archive_stderr": host_archive_stderr if archive_result.returncode != 0 else None,
            "declared_license": registry_row.get("license"),
            "tracked_license_paths": license_paths,
            "license_evidence_status": (
                "tracked_license_file_found" if license_paths else "no_tracked_license_file_found"
            ),
            "license_review_status": "pending_component_review",
        })
        rows.append(row)
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row["status"])
        counts[status] = counts.get(status, 0) + 1
    return {
        "schema_version": 1,
        "cache": str(cache.resolve()),
        "lock": str((root / "dataset" / "sources" / "source_lock.json").resolve()),
        "lineages": rows,
        "summary": {"total": len(rows), "by_status": dict(sorted(counts.items()))},
        "admission_note": "This report is diagnostic; it never promotes source or case admission.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cache", type=Path, help="private source-cache directory")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    parser.add_argument(
        "--docker-archive-image", default=None, metavar="IMAGE@SHA256",
        help="optional pinned Linux image for host git-archive failures",
    )
    args = parser.parse_args()
    try:
        report = audit(
            args.root.resolve(), args.cache.resolve(),
            docker_archive_image=args.docker_archive_image,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if all(row["status"] == "PASS" for row in report["lineages"]) else 3


if __name__ == "__main__":
    raise SystemExit(main())
