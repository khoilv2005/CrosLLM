"""Harness test executing a pinned-container EVM workflow for linea (Linea)."""

import json
import os
import subprocess
from pathlib import Path

DEFAULT_FOUNDRY_IMAGE = "ghcr.io/foundry-rs/foundry@sha256:0c00cb0bda1ab1b91c9a6bf60f4c76c09c1a8870824b6d4718afbabacf6f9a17"


def run_forge_test(harness_dir: Path, contract_name: str):
    """Run Forge through argv with read-only source and disposable scratch."""
    image = os.environ.get("CROSSLLM_FOUNDRY_IMAGE", DEFAULT_FOUNDRY_IMAGE)
    if "@sha256:" not in image:
        raise ValueError("CROSSLLM_FOUNDRY_IMAGE must be digest-pinned")
    container_name = f"crossllm-harness-{harness_dir.name}-{os.getpid()}"
    command = [
        "docker", "run", "--rm", "--name", container_name, "--network=bridge",
        "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--pids-limit", "128", "--memory", "2g",
        "--tmpfs", "/tmp:rw,exec,nosuid,size=512m",
        "--tmpfs", "/home/foundry:rw,exec,nosuid,size=512m,uid=1000,gid=1000,mode=700",
        "-e", "FOUNDRY_CACHE_PATH=/tmp/crossllm-cache",
        "-e", "FOUNDRY_OUT=/tmp/crossllm-out",
        "--mount", f"type=bind,source={harness_dir.resolve()},target=/work,readonly",
        "--workdir", "/work", "--entrypoint", "/usr/local/bin/forge",
        image, "test", "--root", "/work", "--out", "/tmp/crossllm-out",
        "--cache-path", "/tmp/crossllm-cache", "--match-contract", contract_name,
        "--json",
    ]
    try:
        result = subprocess.run(
            command, cwd=harness_dir, capture_output=True, text=True,
            timeout=300, check=False,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as error:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True, text=True, check=False,
        )
        return 124, str(error.stdout or ""), str(error.stderr or "") + "\nforge timeout"
    except OSError as error:
        return 127, "", str(error)


def test_linea_normal_workflow():
    harness_dir = Path(__file__).resolve().parent
    contract_test = "LineaRollupSourceBackedHarnessTest"
    ret, stdout, stderr = run_forge_test(harness_dir, contract_test)
    assert ret == 0, f"Foundry fixture harness failed for linea:\n{stderr}\n{stdout}"
    output_lines = [line for line in stdout.splitlines() if line.strip().startswith("{")]
    assert output_lines, "No JSON test results returned by forge test"
    json.loads(output_lines[-1])

    fixtures_dir = harness_dir / "fixtures"
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    trace_record = {
        "lineage_id": "linea",
        "protocol": "Linea",
        "test_suite": contract_test,
        "execution_engine": "Foundry EVM in pinned Docker image",
        "status": "PASS",
        "evidence_scope": "source_backed_development_probe_only",
    }
    with (fixtures_dir / "execution_trace.json").open("w", encoding="utf-8") as stream:
        json.dump(trace_record, stream, indent=2)


if __name__ == "__main__":
    test_linea_normal_workflow()
