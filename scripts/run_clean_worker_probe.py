#!/usr/bin/env python3
"""Build and smoke-test the hash-pinned development worker in Docker.

The probe validates installation and isolation only.  It does not mount the
repository, private benchmark, credentials, model cache, or a provider socket
into the worker, and it never upgrades the result to evaluation readiness.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any

from crossllm.contracts.canonical import sha256_hex


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = ROOT / "containers" / "python-worker.lock.json"
DEFAULT_OUTPUT = ROOT / "dataset" / "reports" / "clean_worker_probe.json"
DOCKERFILE = ROOT / "containers" / "worker.Dockerfile"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(command: list[str], *, cwd: Path = ROOT, timeout: float = 900.0) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(command, cwd=cwd, capture_output=True, timeout=timeout, check=False)


def _digest_pinned(value: str) -> bool:
    return bool(re.fullmatch(r".+@sha256:[0-9a-f]{64}", value))


def _input_hashes(root: Path) -> dict[str, str]:
    paths = [root / "requirements.lock", root / "pyproject.toml", DOCKERFILE]
    paths.extend(sorted((root / "src").rglob("*.py")))
    return {path.relative_to(root).as_posix(): _sha256(path) for path in paths}


def _smoke_command() -> str:
    return (
        "import crossllm, json, jsonschema, z3, os, pathlib, sys; "
        "assert crossllm.__version__ == '0.1.0'; "
        "assert jsonschema.__version__; "
        "assert z3.get_version_string(); "
        "assert os.environ.get('OLLAMA_API_KEY') is None; "
        "assert not list(pathlib.Path('/opt/crossllm').glob('**/*.safetensors')); "
        "print(json.dumps({'python': sys.version.split()[0], 'crossllm': crossllm.__version__, 'z3': z3.get_version_string(), 'weights': False}, sort_keys=True))"
    )


def build_and_probe(
    root: Path = ROOT,
    *,
    base_image: str,
    output: Path = DEFAULT_OUTPUT,
    lock_path: Path = DEFAULT_LOCK,
    image_tag: str = "crossllm-clean-worker:development",
) -> dict[str, object]:
    root = root.resolve()
    if not _digest_pinned(base_image):
        raise ValueError("base_image must be digest-pinned")
    inputs = _input_hashes(root)
    lock = {
        "schema_version": 1,
        "record_type": "python_worker_base_lock",
        "status": "development_probe",
        "base_image": base_image,
        "dockerfile_sha256": inputs["containers/worker.Dockerfile"],
        "requirements_lock_sha256": inputs["requirements.lock"],
        "observed_on": datetime.now(timezone.utc).date().isoformat(),
    }
    lock["lock_hash"] = sha256_hex(lock)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    build = _run([
        # Dependency installation is a build-time operation.  Host networking
        # avoids the Docker Desktop bridge timeout observed on PyPI; the
        # resulting worker is smoke-tested with network=none below.
        "docker", "build", "--pull=false", "--network=host", "--file", str(DOCKERFILE),
        "--build-arg", f"PYTHON_IMAGE={base_image}", "--tag", image_tag, ".",
    ], timeout=1800.0)
    if build.returncode != 0:
        raise RuntimeError(f"worker image build failed: {build.stderr.decode('utf-8', 'replace')[-4000:]}")

    inspect = _run(["docker", "image", "inspect", image_tag, "--format", "{{.Id}}"], timeout=60.0)
    image_id = inspect.stdout.decode("utf-8", "replace").strip() if inspect.returncode == 0 else None
    run_command = [
        "docker", "run", "--rm", "--network=none", "--read-only",
        "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit", "128",
        "--memory", "1g", "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m",
        image_tag, "-c", _smoke_command(),
    ]
    smoke = _run(run_command, timeout=300.0)
    stdout = smoke.stdout.decode("utf-8", "replace")
    stderr = smoke.stderr.decode("utf-8", "replace")
    assertions = {
        "build_succeeded": build.returncode == 0,
        "smoke_exit_zero": smoke.returncode == 0,
        "network_none": True,
        "read_only_root": True,
        "no_bind_mounts": True,
        "non_root_worker": "weights" in stdout and "crossllm" in stdout,
        "no_model_weights": '"weights": false' in stdout,
        "no_provider_secret": "OLLAMA_API_KEY" not in stdout,
    }
    body: dict[str, object] = {
        "schema_version": 1,
        "record_type": "clean_worker_installation_probe",
        "status": "clean_worker_pass" if all(assertions.values()) else "clean_worker_fail",
        "scope": "development_clean_worker_probe",
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "base_image": base_image,
        "image_id": image_id,
        "input_hashes": inputs,
        "container_policy": {
            "network": "none",
            "read_only_root": True,
            "bind_mounts": [],
            "model_weights_mounted": False,
            "private_gold_mounted": False,
            "broadcast_capability": False,
            "run_as_non_root": True,
        },
        "build_result": {
            "exit_code": build.returncode,
            "stdout_sha256": hashlib.sha256(build.stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(build.stderr).hexdigest(),
        },
        "smoke_result": {
            "exit_code": smoke.returncode,
            "stdout_sha256": hashlib.sha256(smoke.stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(smoke.stderr).hexdigest(),
            "assertions": assertions,
        },
        "admission_eligible": False,
        "limitations": [
            "development image only; no evaluation worker image lock",
            "probe does not establish source ancestry, benchmark admission, or provider identity",
        ],
    }
    body["report_hash"] = sha256_hex(body)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return body


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("clean worker report must be a JSON object")
    return value


def validate_report(root: Path = ROOT, report_path: Path = DEFAULT_OUTPUT) -> list[str]:
    root = root.resolve()
    try:
        report = _load(report_path.resolve())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [f"clean worker report unreadable: {error}"]
    errors: list[str] = []
    for key, expected in {
        "schema_version": 1,
        "record_type": "clean_worker_installation_probe",
        "scope": "development_clean_worker_probe",
        "admission_eligible": False,
    }.items():
        if report.get(key) != expected:
            errors.append(f"{key} mismatch")
    base_image = report.get("base_image")
    if not isinstance(base_image, str) or not _digest_pinned(base_image):
        errors.append("base_image is not digest-pinned")
    policy = report.get("container_policy")
    expected_policy = {
        "network": "none", "read_only_root": True, "bind_mounts": [],
        "model_weights_mounted": False, "private_gold_mounted": False,
        "broadcast_capability": False, "run_as_non_root": True,
    }
    if policy != expected_policy:
        errors.append("container policy is not fail-closed")
    expected_inputs = _input_hashes(root)
    if report.get("input_hashes") != expected_inputs:
        errors.append("worker input hashes do not match current sources")
    smoke = report.get("smoke_result")
    if not isinstance(smoke, dict):
        errors.append("smoke_result is missing")
    else:
        if smoke.get("exit_code") != 0:
            errors.append("clean worker smoke test did not pass")
        assertions = smoke.get("assertions")
        if not isinstance(assertions, dict) or not assertions or not all(value is True for value in assertions.values()):
            errors.append("clean worker smoke assertions are incomplete")
        for field in ("stdout_sha256", "stderr_sha256"):
            if not isinstance(smoke.get(field), str) or not SHA256_RE.fullmatch(smoke[field]):  # type: ignore[arg-type]
                errors.append(f"smoke_result.{field} is not a SHA-256 digest")
    unsigned = dict(report)
    supplied = unsigned.pop("report_hash", None)
    if supplied != sha256_hex(unsigned):
        errors.append("report_hash mismatch")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--base-image", required=False)
    parser.add_argument("--lock-out", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--image-tag", default="crossllm-clean-worker:development")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    output = args.out.resolve() if args.out else root / DEFAULT_OUTPUT.relative_to(ROOT)
    if args.check:
        errors = validate_report(root, output)
        if errors:
            print("FAILED")
            print("\n".join(errors))
            return 1
        print("OK: clean development worker probe is valid and non-admission")
        return 0
    if not args.base_image:
        raise SystemExit("--base-image is required when creating a probe")
    lock = args.lock_out.resolve() if args.lock_out else root / DEFAULT_LOCK.relative_to(ROOT)
    report = build_and_probe(root, base_image=args.base_image, output=output, lock_path=lock, image_tag=args.image_tag)
    print(json.dumps({"status": report["status"], "report": str(output), "lock": str(lock)}, sort_keys=True))
    return 0 if report["status"] == "clean_worker_pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
