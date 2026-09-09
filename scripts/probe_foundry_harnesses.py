"""Run Foundry harness smoke probes in clean, read-only containers.

This probe is intentionally scoped to generated harnesses. It records enough
identity to reproduce the command and hashes combined stdout/stderr, while
never treating a generated mock harness as a source-pinned host build.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any


DEFAULT_IMAGE = "ghcr.io/foundry-rs/foundry@sha256:0c00cb0bda1ab1b91c9a6bf60f4c76c09c1a8870824b6d4718afbabacf6f9a17"
SOLC_VERSION_RE = re.compile(r'^solc_version\s*=\s*"([^"]+)"', re.MULTILINE)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    harness_root = root / "dataset" / "harness"
    if not harness_root.is_dir():
        raise SystemExit(f"harness root does not exist: {harness_root}")
    output_path = args.out or (root / "containers" / "foundry-harness-probe.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for harness in sorted(path for path in harness_root.iterdir() if path.is_dir()):
        config_path = harness / "foundry.toml"
        if not config_path.is_file():
            continue
        config = config_path.read_text(encoding="utf-8")
        match = SOLC_VERSION_RE.search(config)
        solc_version = match.group(1) if match else None
        container_name = f"crossllm-probe-{harness.name}-{os.getpid()}"
        command = [
            "docker", "run", "--rm", "--name", container_name, "--network", "bridge",
            "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "--pids-limit", "128", "--memory", "2g",
            "--tmpfs", "/tmp:rw,exec,nosuid,size=512m",
            "--tmpfs", "/home/foundry:rw,exec,nosuid,size=512m,uid=1000,gid=1000,mode=700",
            "-e", "FOUNDRY_CACHE_PATH=/tmp/crossllm-cache",
            "-e", "FOUNDRY_OUT=/tmp/crossllm-out",
            "--mount", f"type=bind,source={harness},target=/work,readonly",
            "--workdir", "/work", "--entrypoint", "/usr/local/bin/forge",
            args.image, "test", "--root", "/work",
            "--out", "/tmp/crossllm-out", "--cache-path", "/tmp/crossllm-cache", "-q",
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=args.timeout_seconds,
                check=False,
            )
            combined = (completed.stdout + completed.stderr).encode("utf-8", errors="replace")
            rows.append({
                "lineage": harness.name,
                "solc_version": solc_version,
                "status": "pass" if completed.returncode == 0 else "fail",
                "exit_code": completed.returncode,
                "output_sha256": hashlib.sha256(combined).hexdigest(),
            })
        except subprocess.TimeoutExpired as error:
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                capture_output=True, text=True, check=False,
            )
            combined = (str(error.stdout or "") + str(error.stderr or "")).encode("utf-8", errors="replace")
            rows.append({
                "lineage": harness.name,
                "solc_version": solc_version,
                "status": "timeout",
                "exit_code": None,
                "output_sha256": hashlib.sha256(combined).hexdigest(),
            })
        print(f"{harness.name}: {rows[-1]['status']} (solc={solc_version})")

    payload: dict[str, Any] = {
        "schema_version": 1,
        "probe_date": "2026-09-08",
        "scope": "generated_foundry_harness_smoke_only",
        "source_admission": "not_proven",
        "image": args.image,
        "network_mode": "bridge_for_svm_compiler_download",
        "mount_mode": "read_only",
        "compiler_source": "Foundry SVM runtime download; compiler is not embedded in the image",
        "harnesses": rows,
    }
    payload["report_hash"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    output_path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    passed = sum(row["status"] == "pass" for row in rows)
    print(f"summary: {passed}/{len(rows)} pass; report={output_path}")
    return 0 if rows and passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
