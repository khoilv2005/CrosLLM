#!/usr/bin/env python3
"""Run source-backed development mutations against their clean controls.

The runner copies a source file from the locked private checkout into a
temporary, read-only Docker workspace, applies one exact textual patch, and
runs a separate control and mutant test. It records hashes and concrete test
statuses only after both sides pass. The output is development evidence and is
explicitly ineligible for evaluation admission or independent gold claims.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import difflib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataset.tools import extract_all_artifacts
from scripts import source_backed_harnesses


SPEC_PATH = ROOT / "dataset" / "benchmark" / "source_mutation_validation_spec.json"
TEST_SOURCE = ROOT / "dataset" / "harness" / "source_mutations" / "celer_cbridge" / "test" / "SourceMutationProbe.t.sol"
BASE_HARNESS = ROOT / "dataset" / "harness" / "celer_cbridge"
DEFAULT_OUTPUT = ROOT / "dataset" / "reports" / "source_mutation_evidence.jsonl"
LINEAGE_ID = "celer_cbridge"
SOLC_VERSION = "0.8.9"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_spec(path: Path = SPEC_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or payload.get("scope") != "source_backed_development_mutation_probe_only":
        raise ValueError("source mutation spec has an invalid schema or scope")
    if payload.get("lineage") != LINEAGE_ID or payload.get("contract_name") != "CBridge":
        raise ValueError("source mutation spec is not scoped to the locked CBridge development host")
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("source mutation spec must contain rows")
    required = (
        "operator_id", "property_family", "patch_anchor", "patch_replacement",
        "control_test", "mutant_test", "trigger", "control_expectation",
        "mutant_expectation",
    )
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or any(not isinstance(row.get(field), str) for field in required):
            raise ValueError("source mutation spec contains an incomplete row")
        operator_id = row["operator_id"]
        if operator_id in seen:
            raise ValueError(f"duplicate source mutation operator: {operator_id}")
        seen.add(operator_id)
    return payload


def _source_file_from_manifest(manifest: dict[str, Any], source_cache: Path) -> tuple[Path, str]:
    selected = manifest.get("artifact_selection_files")
    if not isinstance(selected, list):
        raise ValueError("source manifest has no artifact selection files")
    candidates = [
        item for item in selected
        if isinstance(item, dict) and item.get("source_path") == "contracts/CBridge.sol"
    ]
    if len(candidates) != 1 or not isinstance(candidates[0].get("sha256"), str):
        raise ValueError("source manifest does not select exactly contracts/CBridge.sol")
    path = source_cache / LINEAGE_ID / "contracts" / "CBridge.sol"
    if not path.is_file():
        raise ValueError(f"locked source file is missing: {path}")
    expected = candidates[0]["sha256"]
    actual = sha256_file(path)
    if actual != expected:
        raise ValueError("locked CBridge source hash does not match source manifest")
    return path, actual


def _write_project(root: Path, source_text: str) -> None:
    (root / "contracts").mkdir(parents=True, exist_ok=True)
    (root / "test").mkdir(parents=True, exist_ok=True)
    (root / "contracts" / "CBridge.sol").write_text(source_text, encoding="utf-8", newline="\n")
    shutil.copy2(TEST_SOURCE, root / "test" / TEST_SOURCE.name)
    (root / "foundry.toml").write_text(
        "[profile.default]\n"
        "src = \"contracts\"\n"
        "test = \"test\"\n"
        "optimizer = true\n"
        "optimizer_runs = 800\n"
        "remappings = [\n"
        "    \"@openzeppelin/contracts/=/base/node_modules/@openzeppelin/contracts/\",\n"
        "    \"ds-test/=/base/lib/forge-std/lib/ds-test/src/\",\n"
        "    \"forge-std/=/base/lib/forge-std/src/\"\n"
        "]\n",
        encoding="utf-8",
        newline="\n",
    )


def _docker_command(stage: Path, test_name: str, volume: str) -> list[str]:
    container_name = f"crossllm-source-mutation-{test_name}-{os.getpid()}"
    return [
        "docker", "run", "--rm", "--name", container_name,
        "--pull=never", "--network=none", "--read-only", "--cap-drop=ALL",
        "--security-opt=no-new-privileges", "--pids-limit", "128",
        "--memory", "2g", "--tmpfs", "/tmp:rw,exec,nosuid,size=512m",
        "--tmpfs", "/home/foundry:rw,exec,nosuid,size=512m,uid=1000,gid=1000,mode=700",
        "--mount", f"type=bind,source={stage.resolve()},target=/work,readonly",
        "--mount", f"type=bind,source={BASE_HARNESS.resolve()},target=/base,readonly",
        "--mount", f"type=volume,source={volume},target=/compiler,readonly",
        "--workdir", "/work", "--entrypoint", "/usr/local/bin/forge",
        extract_all_artifacts.DOCKER_FOUNDRY,
        "test", "--root", "/work", "--out", "/tmp/crossllm-out",
        "--cache-path", "/tmp/crossllm-cache", "--use", "/compiler/solc",
        "--match-contract", "SourceMutationProbeTest", "--match-test", test_name, "--json",
    ]


def _test_status(output: str, test_name: str) -> str | None:
    wanted = {test_name, f"{test_name}()"}
    for line in reversed(output.splitlines()):
        if not line.strip().startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        found: str | None = None

        def visit(value: object) -> None:
            nonlocal found
            if isinstance(value, dict):
                results = value.get("test_results")
                if isinstance(results, dict):
                    for name, result in results.items():
                        if name in wanted and isinstance(result, dict) and isinstance(result.get("status"), str):
                            found = result["status"].upper()
                for child in value.values():
                    if found is None:
                        visit(child)
            elif isinstance(value, list):
                for child in value:
                    if found is None:
                        visit(child)

        visit(payload)
        if found is not None:
            return "PASS" if found in {"SUCCESS", "PASS", "PASSED"} else "FAIL"
    return None


def _run_one(stage: Path, test_name: str, volume: str, timeout_seconds: float) -> dict[str, Any]:
    command = _docker_command(stage, test_name, volume)
    try:
        result = subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True, check=False,
            timeout=timeout_seconds,
        )
        stdout = result.stdout
        stderr = result.stderr
        status = _test_status(stdout, test_name) if result.returncode == 0 else "FAIL"
        return {
            "status": status or "FAIL",
            "exit_code": result.returncode,
            "stdout_sha256": sha256_bytes(stdout.encode("utf-8", errors="replace")),
            "stderr_sha256": sha256_bytes(stderr.encode("utf-8", errors="replace")),
            "stdout_tail": stdout[-4000:],
            "stderr_tail": stderr[-4000:],
        }
    except subprocess.TimeoutExpired as error:
        subprocess.run(
            ["docker", "rm", "-f", f"crossllm-source-mutation-{test_name}-{os.getpid()}"],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        return {
            "status": "FAIL",
            "exit_code": None,
            "stdout_sha256": sha256_bytes(str(error.stdout or "").encode()),
            "stderr_sha256": sha256_bytes(str(error.stderr or "").encode()),
            "stdout_tail": str(error.stdout or "")[-4000:],
            "stderr_tail": str(error.stderr or "")[-4000:],
        }


def _patch_source(base_text: str, anchor: str, replacement: str) -> tuple[str, str]:
    count = base_text.count(anchor)
    if count != 1:
        raise ValueError(f"mutation anchor must occur exactly once, observed {count}")
    mutant_text = base_text.replace(anchor, replacement, 1)
    if mutant_text == base_text:
        raise ValueError("mutation did not change source")
    diff = "".join(
        difflib.unified_diff(
            base_text.splitlines(keepends=True),
            mutant_text.splitlines(keepends=True),
            fromfile="control/contracts/CBridge.sol",
            tofile="mutant/contracts/CBridge.sol",
        )
    )
    return mutant_text, sha256_bytes(diff.encode("utf-8"))


def run(
    *, root: Path = ROOT, source_cache: Path | None = None,
    output: Path = DEFAULT_OUTPUT, timeout_seconds: float = 300.0,
) -> int:
    root = root.resolve()
    source_cache = (source_cache or root.parent / "crossllm_private_sources").resolve()
    spec = load_spec(root / SPEC_PATH.relative_to(ROOT))
    if not TEST_SOURCE.is_file() or not BASE_HARNESS.is_dir():
        raise ValueError("source mutation test source or base harness is missing")
    manifest_path = root / "dataset" / "harness" / LINEAGE_ID / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_file, base_hash = _source_file_from_manifest(manifest, source_cache)
    base_text = source_file.read_text(encoding="utf-8")
    source_manifest_hash = sha256_file(manifest_path)
    test_hash = sha256_file(TEST_SOURCE)
    compiler_volume = extract_all_artifacts.create_compiler_cache_volume("source_mutations")
    compiler_info: dict[str, str] | None = None
    records: list[dict[str, Any]] = []
    try:
        compiler_info = extract_all_artifacts.populate_compiler_cache_volume(compiler_volume, SOLC_VERSION)
        with tempfile.TemporaryDirectory(prefix="crossllm-source-mutations-") as temporary:
            temporary_root = Path(temporary)
            for row in sorted(spec["rows"], key=lambda item: item["operator_id"]):
                mutant_text, patch_hash = _patch_source(
                    base_text, row["patch_anchor"], row["patch_replacement"]
                )
                operator_dir = temporary_root / row["operator_id"]
                control_dir = operator_dir / "control"
                mutant_dir = operator_dir / "mutant"
                _write_project(control_dir, base_text)
                _write_project(mutant_dir, mutant_text)
                control = _run_one(control_dir, row["control_test"], compiler_volume, timeout_seconds)
                mutant = _run_one(mutant_dir, row["mutant_test"], compiler_volume, timeout_seconds)
                if control["status"] != "PASS" or mutant["status"] != "PASS":
                    print(f"[FAIL] {row['operator_id']}: control={control['status']} mutant={mutant['status']}")
                    for label, result in (("control", control), ("mutant", mutant)):
                        print(f"[{label}] exit_code={result['exit_code']}")
                        if result.get("stdout_tail"):
                            print(result["stdout_tail"])
                        if result.get("stderr_tail"):
                            print(result["stderr_tail"])
                    return 1
                records.append({
                    "schema_version": 1,
                    "record_type": "source_backed_mutation_evidence",
                    "scope": "source_backed_development_mutation_probe_only",
                    "operator_id": row["operator_id"],
                    "property_family": row["property_family"],
                    "lineage_id": LINEAGE_ID,
                    "source_repository": manifest["source_repository"],
                    "source_commit": manifest["source_commit"],
                    "source_manifest_sha256": source_manifest_hash,
                    "source_mutation_spec_sha256": sha256_file(root / SPEC_PATH.relative_to(ROOT)),
                    "source_path": spec["source_path"],
                    "base_source_sha256": base_hash,
                    "mutant_source_sha256": sha256_bytes(mutant_text.encode("utf-8")),
                    "patch_sha256": patch_hash,
                    "test_source_sha256": test_hash,
                    "control_test": row["control_test"],
                    "mutant_test": row["mutant_test"],
                    "control_status": control["status"],
                    "mutant_status": mutant["status"],
                    "control_stdout_sha256": control["stdout_sha256"],
                    "control_stderr_sha256": control["stderr_sha256"],
                    "mutant_stdout_sha256": mutant["stdout_sha256"],
                    "mutant_stderr_sha256": mutant["stderr_sha256"],
                    "patch_changed_source": True,
                    "control_pair_verified": True,
                    "source_backed": True,
                    "independent_property_validation": False,
                    "independent_trigger_validation": False,
                    "admission_eligible": False,
                    "network_mode": "none",
                    "runner_image": extract_all_artifacts.DOCKER_FOUNDRY,
                    "compiler": compiler_info,
                    "evidence_scope": "source_backed_development_mutation_probe_only",
                    "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                })
    finally:
        extract_all_artifacts.remove_compiler_cache_volume(compiler_volume)
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    temporary.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in records),
        encoding="utf-8",
    )
    temporary.replace(output)
    print(f"source-backed development mutation probe: {len(records)}/{len(spec['rows'])} pass")
    print(f"evidence written to: {output}")
    return 0


def validate_report(root: Path = ROOT, report_path: Path | None = None) -> list[str]:
    root = root.resolve()
    output = report_path or root / DEFAULT_OUTPUT
    errors: list[str] = []
    try:
        spec_path = root / SPEC_PATH.relative_to(ROOT)
        spec = load_spec(spec_path)
        rows = [
            json.loads(line)
            for line in output.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        manifest_path = root / "dataset" / "harness" / LINEAGE_ID / "source_manifest.json"
        source_path = root / "dataset" / "harness" / LINEAGE_ID / "contracts" / "CBridge.sol"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [f"source mutation report unreadable: {error}"]
    spec_by_id = {row["operator_id"]: row for row in spec["rows"]}
    if set(row.get("operator_id") for row in rows) != set(spec_by_id):
        errors.append("source mutation report/operator spec coverage mismatch")
    base_hash = sha256_file(source_path)
    manifest_hash = sha256_file(manifest_path)
    spec_hash = sha256_file(root / SPEC_PATH.relative_to(ROOT))
    for row in rows:
        operator_id = row.get("operator_id")
        expected = spec_by_id.get(operator_id)
        if expected is None:
            continue
        if row.get("source_manifest_sha256") != manifest_hash:
            errors.append(f"{operator_id}: source manifest hash mismatch")
        if row.get("source_mutation_spec_sha256") != spec_hash:
            errors.append(f"{operator_id}: mutation spec hash mismatch")
        if row.get("source_repository") != manifest.get("source_repository"):
            errors.append(f"{operator_id}: source repository mismatch")
        if row.get("source_commit") != manifest.get("source_commit"):
            errors.append(f"{operator_id}: source commit mismatch")
        if row.get("source_path") != spec["source_path"]:
            errors.append(f"{operator_id}: source path mismatch")
        if row.get("base_source_sha256") != base_hash:
            errors.append(f"{operator_id}: base source hash mismatch")
        if row.get("property_family") != expected.get("property_family"):
            errors.append(f"{operator_id}: property family mismatch")
        for field, value in {
            "control_test": expected["control_test"],
            "mutant_test": expected["mutant_test"],
            "control_status": "PASS",
            "mutant_status": "PASS",
            "patch_changed_source": True,
            "control_pair_verified": True,
            "source_backed": True,
            "independent_property_validation": False,
            "independent_trigger_validation": False,
            "admission_eligible": False,
            "network_mode": "none",
            "evidence_scope": "source_backed_development_mutation_probe_only",
        }.items():
            if row.get(field) != value:
                errors.append(f"{operator_id}: {field} has an invalid value")
        if not isinstance(row.get("mutant_source_sha256"), str) or row["mutant_source_sha256"] == base_hash:
            errors.append(f"{operator_id}: mutant source hash is missing or unchanged")
        if not isinstance(row.get("patch_sha256"), str) or len(row["patch_sha256"]) != 64:
            errors.append(f"{operator_id}: patch hash is malformed")
        compiler = row.get("compiler")
        if not isinstance(compiler, dict) or compiler.get("version") != SOLC_VERSION or compiler.get("path") != "/compiler/solc":
            errors.append(f"{operator_id}: compiler identity is not locked")
        if not isinstance(row.get("runner_image"), str) or "@sha256:" not in row["runner_image"]:
            errors.append(f"{operator_id}: runner image is not digest-pinned")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--source-cache", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    output = args.out.resolve() if args.out else root / DEFAULT_OUTPUT
    if args.check:
        errors = validate_report(root, output)
        if errors:
            print("FAILED")
            print("\n".join(errors))
            return 1
        print("OK: source-backed development mutation evidence is valid and non-admission")
        return 0
    try:
        return run(root=root, source_cache=args.source_cache, output=output, timeout_seconds=args.timeout_seconds)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"[FAIL] {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
