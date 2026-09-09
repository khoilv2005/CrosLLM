#!/usr/bin/env python3
"""Run the Docker worker isolation canary for M08.06.

Only a public sentinel is mounted into the real container.  The remaining
cases exercise fail-closed policy decisions in the command builder.  The
receipt records hashes and status, never sentinel contents, environment files
or provider credentials.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crossllm.contracts.canonical import sha256_hex
from crossllm.runtime import DockerWorkerCommandBuilder, MountSpec, WorkerIsolationPolicy
from dataset.tools import extract_all_artifacts


DEFAULT_OUTPUT = ROOT / "dataset" / "reports" / "isolation_canary.json"
IMAGE_REF = extract_all_artifacts.DOCKER_FOUNDRY
SENTINEL = "CROSSLLM_PUBLIC_SENTINEL_V1"
CASE_IDS = (
    "public_sentinel_execution",
    "private_gold_mount",
    "model_weight_mount",
    "provider_egress_allowlist",
    "provider_egress_block",
    "broadcast_block",
)


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _record(
    case_id: str,
    expected: str,
    observed: str,
    passed: bool,
    *,
    reason: str,
    command_hash: str | None = None,
    stdout_hash: str | None = None,
    stderr_hash: str | None = None,
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "expected": expected,
        "observed": observed,
        "passed": passed,
        "reason": reason,
        "command_hash": command_hash,
        "stdout_sha256": stdout_hash,
        "stderr_sha256": stderr_hash,
    }


def _stable_command_hash(argv: tuple[str, ...], source: Path) -> str:
    normalized = ["<public-sentinel>" if item == str(source) else item for item in argv]
    return sha256_hex(normalized)


def run_canary(root: Path = ROOT) -> dict[str, object]:
    policy = WorkerIsolationPolicy()
    builder = DockerWorkerCommandBuilder(policy=policy)
    rows: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="crossllm-public-sentinel-") as directory:
        public_root = Path(directory)
        sentinel_path = public_root / "sentinel.txt"
        sentinel_path.write_text(SENTINEL + "\n", encoding="utf-8")
        command = builder.build(
            image_ref=IMAGE_REF,
            command=(
                "-c",
                "cat /work/public/sentinel.txt | grep -F CROSSLLM_PUBLIC_SENTINEL_V1 && "
                "test ! -e /work/private/sentinel.txt && test ! -e /root/.ollama/models",
            ),
            mounts=[MountSpec(str(public_root), "/work/public", "public_artifact")],
            entrypoint="/bin/sh",
        )
        try:
            outcome = subprocess.run(
                list(command.argv),
                cwd=root,
                capture_output=True,
                timeout=120,
                check=False,
            )
            rows.append(_record(
                "public_sentinel_execution",
                "pass",
                "pass" if outcome.returncode == 0 else "fail",
                outcome.returncode == 0,
                reason="public sentinel readable; private/model paths absent in read-only network-none container"
                if outcome.returncode == 0 else "docker sentinel command returned non-zero",
                command_hash=_stable_command_hash(tuple(command.argv), public_root),
                stdout_hash=_hash_bytes(outcome.stdout),
                stderr_hash=_hash_bytes(outcome.stderr),
            ))
        except (OSError, subprocess.TimeoutExpired) as error:
            rows.append(_record(
                "public_sentinel_execution", "pass", "unknown", False,
                reason=f"docker canary execution failed: {type(error).__name__}",
                command_hash=_stable_command_hash(tuple(command.argv), public_root),
            ))

    try:
        builder.build(
            image_ref=IMAGE_REF, command=("worker",),
            mounts=[MountSpec("private-gold", "/work/gold", "private_gold")],
        )
        rows.append(_record("private_gold_mount", "blocked", "accepted", False, reason="private gold mount was accepted"))
    except PermissionError as error:
        rows.append(_record("private_gold_mount", "blocked", "blocked", True, reason=str(error)))

    try:
        builder.build(
            image_ref=IMAGE_REF, command=("worker",),
            mounts=[MountSpec("local-cache", "/root/.ollama/models", "public_artifact")],
        )
        rows.append(_record("model_weight_mount", "blocked", "accepted", False, reason="model cache mount was accepted"))
    except PermissionError as error:
        rows.append(_record("model_weight_mount", "blocked", "blocked", True, reason=str(error)))

    provider = builder.build(
        image_ref=IMAGE_REF, command=("worker",), endpoint="https://ollama.com/api/chat"
    )
    provider_ok = (
        provider.network_mode == "bridge"
        and provider.as_dict()["egress_enforcement"] == "external_firewall_required"
        and provider.as_dict()["allowed_network_hosts"] == ["ollama.com"]
    )
    rows.append(_record(
        "provider_egress_allowlist", "allowlisted_external_firewall", "allowlisted_external_firewall" if provider_ok else "invalid",
        provider_ok, reason="provider worker is bridge-only and allowlisted to ollama.com; firewall remains an external deployment control",
        command_hash=sha256_hex(list(provider.argv)),
    ))

    try:
        builder.build(image_ref=IMAGE_REF, command=("worker",), endpoint="https://untrusted.example/api")
        rows.append(_record("provider_egress_block", "blocked", "accepted", False, reason="non-allowlisted endpoint was accepted"))
    except PermissionError as error:
        rows.append(_record("provider_egress_block", "blocked", "blocked", True, reason=str(error)))

    try:
        builder.build(image_ref=IMAGE_REF, command=("worker",), broadcast=True)
        rows.append(_record("broadcast_block", "blocked", "accepted", False, reason="broadcast was accepted"))
    except PermissionError as error:
        rows.append(_record("broadcast_block", "blocked", "blocked", True, reason=str(error)))

    payload: dict[str, object] = {
        "schema_version": 1,
        "record_type": "docker_worker_isolation_canary",
        "scope": "development_runtime_isolation_only",
        "image_ref": IMAGE_REF,
        "case_ids": list(CASE_IDS),
        "cases": rows,
        "case_count": len(rows),
        "passed_count": sum(bool(row["passed"]) for row in rows),
        "all_passed": all(bool(row["passed"]) for row in rows),
        "sentinel_sha256": _hash_bytes((SENTINEL + "\n").encode("utf-8")),
        "network_none_for_execution": True,
        "private_gold_mounted": False,
        "model_weights_mounted": False,
        "broadcast_allowed": False,
        "provider_allowlist": ["ollama.com"],
        "external_firewall_required_for_provider": True,
        "source": "scripts/run_isolation_canary.py",
        "admission_eligible": False,
        "evidence_scope": "development_runtime_isolation_only",
    }
    payload["report_hash"] = sha256_hex(payload)
    return payload


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def validate_report(root: Path = ROOT, report_path: Path | None = None) -> list[str]:
    root = root.resolve()
    path = report_path or root / DEFAULT_OUTPUT.relative_to(ROOT)
    errors: list[str] = []
    try:
        report = _load(path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [f"isolation canary report unreadable: {error}"]
    body = dict(report)
    stored_hash = body.pop("report_hash", None)
    if stored_hash != sha256_hex(body):
        errors.append("isolation canary report hash mismatch")
    if report.get("schema_version") != 1 or report.get("record_type") != "docker_worker_isolation_canary":
        errors.append("isolation canary identity mismatch")
    if report.get("image_ref") != IMAGE_REF or "@sha256:" not in str(report.get("image_ref")):
        errors.append("isolation canary image is not the locked digest")
    if report.get("case_ids") != list(CASE_IDS):
        errors.append("isolation canary case coverage mismatch")
    cases = report.get("cases")
    if not isinstance(cases, list) or len(cases) != len(CASE_IDS):
        return errors + ["isolation canary cases are incomplete"]
    if [row.get("case_id") for row in cases if isinstance(row, dict)] != list(CASE_IDS):
        errors.append("isolation canary case order mismatch")
    if report.get("case_count") != len(CASE_IDS) or report.get("passed_count") != len(CASE_IDS) or report.get("all_passed") is not True:
        errors.append("isolation canary did not pass all cases")
    if report.get("private_gold_mounted") is not False or report.get("model_weights_mounted") is not False:
        errors.append("isolation canary reports a forbidden mount")
    if report.get("broadcast_allowed") is not False:
        errors.append("isolation canary broadcast policy is not disabled")
    if report.get("provider_allowlist") != ["ollama.com"]:
        errors.append("isolation canary provider allowlist mismatch")
    for row in cases:
        if not isinstance(row, dict) or row.get("passed") is not True:
            errors.append(f"isolation canary case failed: {row.get('case_id') if isinstance(row, dict) else '<invalid>'}")
    return errors


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    output = args.out.resolve() if args.out else root / DEFAULT_OUTPUT.relative_to(ROOT)
    try:
        if args.check:
            errors = validate_report(root, output)
            if errors:
                print("FAILED")
                print("\n".join(errors))
                return 1
            print("OK: Docker isolation canary is valid and development-only")
            return 0
        report = run_canary(root)
        _atomic_json(output, report)
        print(f"Docker isolation canary: {report['passed_count']}/{report['case_count']} pass")
        print(f"evidence written to: {output}")
        return 0 if report["all_passed"] else 1
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"[FAIL] {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
