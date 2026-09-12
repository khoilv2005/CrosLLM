#!/usr/bin/env python3
"""Compile source-backed evaluation workspaces in a pinned Foundry container.

This is a preflight only.  It never reads mutation patches, trigger results,
property assessments, or replay traces and it does not run an evaluation test.
The command catches a different class of failure from
``validate_source_case_workspaces.py``: missing imports, stale harness files,
compiler/remapping problems, and case overlays that do not compile together.

The report deliberately calls a successful compilation ``compile_pass`` rather
than ``verified``.  Candidate-specific search, witness checking and independent
replay still have to consume the resulting workspace.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crossllm.verification.source_workspace import (  # noqa: E402
    load_source_case_identity,
    materialize_source_case_workspace,
)


DEFAULT_IMAGE = "ghcr.io/foundry-rs/foundry@sha256:0c00cb0bda1ab1b91c9a6bf60f4c76c09c1a8870824b6d4718afbabacf6f9a17"
DEFAULT_MANIFEST = ROOT / "benchmark.public.jsonl"
DEFAULT_OUTPUT = ROOT / "dataset" / "reports" / "source_case_compilation.json"


@dataclass(frozen=True, slots=True)
class CompilationResult:
    lineage_id: str
    case_id: str
    status: str
    exit_code: int | None
    stdout_sha256: str | None
    stderr_sha256: str | None
    reason: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "lineage_id": self.lineage_id,
            "case_id": self.case_id,
            "status": self.status,
            "exit_code": self.exit_code,
            "stdout_sha256": self.stdout_sha256,
            "stderr_sha256": self.stderr_sha256,
            "reason": self.reason,
        }


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_manifest(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: manifest row must be an object")
        lineage_id = value.get("lineage_id")
        case_id = value.get("instance_id")
        if not isinstance(lineage_id, str) or not lineage_id:
            raise ValueError(f"{path}:{line_number}: lineage_id is missing")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError(f"{path}:{line_number}: instance_id is missing")
        rows.append({"lineage_id": lineage_id, "case_id": case_id})
    return rows


def _docker_command(workspace: Path, image: str) -> list[str]:
    # The workspace is disposable and mounted read-only.  Foundry's output and
    # cache are tmpfs-backed so the source checkout cannot be modified.
    return [
        "docker", "run", "--rm",
        "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--pids-limit", "128", "--memory", "2g",
        "--tmpfs", "/tmp:rw,exec,nosuid,size=512m",
        "--tmpfs", "/home/foundry:rw,exec,nosuid,size=512m,uid=1000,gid=1000,mode=700",
        "-e", "FOUNDRY_CACHE_PATH=/tmp/crossllm-cache",
        "-e", "FOUNDRY_OUT=/tmp/crossllm-out",
        "--mount", f"type=bind,source={workspace.resolve()},target=/work,readonly",
        "--workdir", "/work",
        "--entrypoint", "/usr/local/bin/forge",
        image, "build", "--root", "/work", "--out", "/tmp/crossllm-out",
        "--cache-path", "/tmp/crossllm-cache",
    ]


def compile_workspace(workspace: Path, *, image: str, timeout_seconds: float) -> tuple[str, int | None, bytes, bytes, str | None]:
    if "@sha256:" not in image:
        raise ValueError("Foundry image must be digest-pinned")
    command = _docker_command(workspace, image)
    try:
        completed = subprocess.run(
            command,
            cwd=workspace,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout if isinstance(error.stdout, bytes) else str(error.stdout or "").encode()
        stderr = error.stderr if isinstance(error.stderr, bytes) else str(error.stderr or "").encode()
        return "timeout", None, stdout, stderr, "foundry_build_timeout"
    except OSError as error:
        return "tool_error", None, b"", str(error).encode(), f"docker_start_failure:{error}"
    status = "compile_pass" if completed.returncode == 0 else "compile_fail"
    return status, completed.returncode, completed.stdout, completed.stderr, None


def _result_for_case(
    repo_root: Path,
    lineage_id: str,
    case_id: str,
    *,
    image: str,
    timeout_seconds: float,
) -> CompilationResult:
    try:
        # Validate receipts before materialization.  This also ensures the
        # compile report cannot silently switch to a different case bundle.
        load_source_case_identity(repo_root, lineage_id, case_id)
        with materialize_source_case_workspace(repo_root, lineage_id, case_id) as (workspace, _identity):
            status, exit_code, stdout, stderr, reason = compile_workspace(
                workspace, image=image, timeout_seconds=timeout_seconds,
            )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return CompilationResult(lineage_id, case_id, "input_error", None, None, None, str(error))
    return CompilationResult(
        lineage_id,
        case_id,
        status,
        exit_code,
        _sha256(stdout),
        _sha256(stderr),
        reason,
    )


def _report(results: Iterable[CompilationResult], *, manifest: Path, image: str, timeout_seconds: float) -> dict[str, Any]:
    rows = [result.as_dict() for result in results]
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row["status"])
        counts[status] = counts.get(status, 0) + 1
    per_lineage: dict[str, dict[str, int]] = {}
    for row in rows:
        lineage = str(row["lineage_id"])
        lineage_counts = per_lineage.setdefault(lineage, {})
        status = str(row["status"])
        lineage_counts[status] = lineage_counts.get(status, 0) + 1
    body: dict[str, Any] = {
        "schema_version": 1,
        "record_type": "source_case_compilation",
        "scope": "source_case_compile_preflight_only",
        "gold_fields_read": False,
        "candidate_search_run": False,
        "witness_check_run": False,
        "independent_replay_run": False,
        "manifest_path": (
            str(manifest.resolve().relative_to(ROOT)).replace("\\", "/")
            if manifest.resolve().is_relative_to(ROOT)
            else str(manifest.resolve()).replace("\\", "/")
        ),
        "manifest_sha256": _sha256(manifest.read_bytes()),
        "foundry_image": image,
        "timeout_seconds": timeout_seconds,
        "case_count": len(rows),
        "counts": dict(sorted(counts.items())),
        "per_lineage": {key: dict(sorted(value.items())) for key, value in sorted(per_lineage.items())},
        "status": "pass" if rows and all(row["status"] == "compile_pass" for row in rows) else "blocked",
        "cases": rows,
    }
    unsigned = dict(body)
    body["report_sha256"] = _sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode())
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--lineage", action="append", default=None)
    parser.add_argument("--case", dest="case_ids", action="append", default=None)
    parser.add_argument("--max-cases", type=int, default=None)
    parser.add_argument("--image", default=os.environ.get("CROSSLLM_FOUNDRY_IMAGE", DEFAULT_IMAGE))
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    if args.max_cases is not None and args.max_cases <= 0:
        parser.error("--max-cases must be positive")
    repo_root = args.repo_root.resolve()
    manifest = args.manifest.resolve()
    rows = _read_manifest(manifest)
    selected_lineages = set(args.lineage or ())
    selected_cases = set(args.case_ids or ())
    if selected_lineages:
        rows = [row for row in rows if row["lineage_id"] in selected_lineages]
    if selected_cases:
        rows = [row for row in rows if row["case_id"] in selected_cases]
    if args.max_cases is not None:
        rows = rows[:args.max_cases]
    results = [
        _result_for_case(
            repo_root,
            row["lineage_id"],
            row["case_id"],
            image=args.image,
            timeout_seconds=args.timeout_seconds,
        )
        for row in rows
    ]
    report = _report(results, manifest=manifest, image=args.image, timeout_seconds=args.timeout_seconds)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_name(f".{args.out.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(args.out)
    print(json.dumps({
        "status": report["status"],
        "case_count": report["case_count"],
        "counts": report["counts"],
        "report_sha256": report["report_sha256"],
        "out": str(args.out.resolve()),
    }, sort_keys=True))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
