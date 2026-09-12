#!/usr/bin/env python3
"""Run one locked source-case harness in an isolated Foundry container.

This command is a source/harness execution probe.  It validates that a case
overlay can compile and execute its paired Solidity test from a clean state,
but it does not consume XLIR candidates, read gold properties, or emit a
verified finding.  Candidate-specific search, witness checking and replay
remain separate stages of the shared verification pipeline.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from crossllm.verification.source_workspace import (  # noqa: E402
    load_source_case_identity,
    materialize_source_case_workspace,
)


DEFAULT_IMAGE = (
    "ghcr.io/foundry-rs/foundry@sha256:"
    "0c00cb0bda1ab1b91c9a6bf60f4c76c09c1a8870824b6d4718afbabacf6f9a17"
)


@dataclass(frozen=True, slots=True)
class HarnessResult:
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


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _docker_command(
    workspace: Path,
    image: str,
    *,
    test_path: str,
    match_test: str | None = None,
    container_name: str = "crossllm-source-case",
) -> list[str]:
    if "@sha256:" not in image:
        raise ValueError("Foundry image must be digest-pinned")
    if not test_path or test_path.startswith("/") or ".." in Path(test_path).parts:
        raise ValueError("test_path must be a safe workspace-relative path")
    if match_test is not None and re.fullmatch(r"[A-Za-z0-9_.*?\-]+", match_test) is None:
        raise ValueError("match_test contains unsupported characters")
    command = [
        "docker", "run", "--rm", "--name", container_name,
        "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--pids-limit", "128", "--memory", "2g",
        "--tmpfs", "/tmp:rw,exec,nosuid,size=512m",
        "--tmpfs", "/home/foundry:rw,exec,nosuid,size=512m,uid=1000,gid=1000,mode=700",
        "-e", "FOUNDRY_CACHE_PATH=/tmp/crossllm-cache",
        "-e", "FOUNDRY_OUT=/tmp/crossllm-out",
        "--mount", f"type=bind,source={workspace.resolve()},target=/work,readonly",
        "--workdir", "/work",
        "--entrypoint", "/usr/local/bin/forge",
        image, "test", "--root", "/work", "--out", "/tmp/crossllm-out",
        "--cache-path", "/tmp/crossllm-cache", "--match-path", test_path,
        "--json",
    ]
    if match_test is not None:
        command.extend(("--match-test", match_test))
    return command


def run_harness(
    workspace: Path,
    *,
    image: str,
    test_path: str,
    match_test: str | None,
    timeout_seconds: float,
) -> tuple[str, int | None, bytes, bytes, str | None]:
    container_name = f"crossllm-source-case-{os.getpid()}"
    command = _docker_command(
        workspace, image, test_path=test_path, match_test=match_test,
        container_name=container_name,
    )
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
        # ``subprocess.run(timeout=...)`` does not terminate a child Docker
        # container.  Remove only the exact container created by this probe so
        # a dropped worker cannot accumulate orphaned Foundry processes.
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True,
            timeout=10,
            check=False,
        )
        return "timeout", None, stdout, stderr, "foundry_test_timeout"
    except OSError as error:
        return "tool_error", None, b"", str(error).encode(), f"docker_start_failure:{error}"
    status = "pass" if completed.returncode == 0 else "fail"
    return status, completed.returncode, completed.stdout, completed.stderr, None


def run_case(
    repo_root: Path,
    lineage_id: str,
    case_id: str,
    *,
    image: str,
    match_test: str | None,
    timeout_seconds: float,
) -> HarnessResult:
    try:
        identity = load_source_case_identity(repo_root, lineage_id, case_id)
        with materialize_source_case_workspace(repo_root, lineage_id, case_id) as (workspace, _):
            # The case receipt keeps the archive path (runtime/test/...),
            # while the materializer deliberately overlays the file into the
            # Foundry project's test/ directory.
            test_path = f"test/{Path(identity.test_path).name}"
            status, exit_code, stdout, stderr, reason = run_harness(
                workspace,
                image=image,
                test_path=test_path,
                match_test=match_test,
                timeout_seconds=timeout_seconds,
            )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return HarnessResult(lineage_id, case_id, "input_error", None, None, None, str(error))
    return HarnessResult(
        lineage_id,
        case_id,
        status,
        exit_code,
        _sha256(stdout),
        _sha256(stderr),
        reason,
    )


def _report(
    result: HarnessResult,
    *,
    image: str,
    match_test: str | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": 1,
        "record_type": "source_case_harness_probe",
        "scope": "source_backed_case_harness_execution_probe",
        "gold_fields_read": False,
        "candidate_specific": False,
        "xlir_search_run": False,
        "witness_check_run": False,
        "independent_replay_run": False,
        "foundry_image": image,
        "match_test": match_test,
        "timeout_seconds": timeout_seconds,
        "result": result.as_dict(),
        "status": "pass" if result.status == "pass" else "blocked",
    }
    body["report_sha256"] = _sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    )
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--lineage", required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--match-test", default=None)
    parser.add_argument("--image", default=os.environ.get("CROSSLLM_FOUNDRY_IMAGE", DEFAULT_IMAGE))
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    if args.match_test is not None and re.fullmatch(r"[A-Za-z0-9_.*?\-]+", args.match_test) is None:
        parser.error("--match-test contains unsupported characters")
    result = run_case(
        args.repo_root.resolve(), args.lineage, args.case,
        image=args.image, match_test=args.match_test,
        timeout_seconds=args.timeout_seconds,
    )
    report = _report(
        result,
        image=args.image,
        match_test=args.match_test,
        timeout_seconds=args.timeout_seconds,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_name(f".{args.out.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(args.out)
    print(json.dumps({
        "status": report["status"],
        "case_id": args.case,
        "match_test": args.match_test,
        "result": result.status,
        "report_sha256": report["report_sha256"],
        "out": str(args.out.resolve()),
    }, sort_keys=True))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
