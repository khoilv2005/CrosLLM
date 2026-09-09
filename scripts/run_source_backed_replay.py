#!/usr/bin/env python3
"""Run and validate one source-backed independent Foundry EVM replay.

This command exercises the exact Celer development harness through the shared
``FoundryDockerReplay`` boundary.  It binds the replay result to the current
source, artifact, deployment, profile and compiler identities.  The receipt is
development evidence only: the Solidity test is a native harness assertion,
not an independent evaluator or an evaluation-admission record.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crossllm.contracts import ReplayStatus
from crossllm.replay import FoundryDockerReplay, FoundryReplaySpec
from dataset.tools import extract_all_artifacts
from scripts import build_evm_support_matrix
from scripts.source_backed_harnesses import canonical_hash


LINEAGE_ID = "celer_cbridge"
SOLC_VERSION = "0.8.9"
HARNESS_REL = Path("dataset") / "harness" / LINEAGE_ID
ARTIFACT_REL = Path("dataset") / "artifacts" / LINEAGE_ID
SUPPORT_MATRIX_REL = Path("dataset") / "reports" / "evm_support_matrix_celer_cbridge.json"
DEFAULT_OUTPUT = ROOT / "dataset" / "reports" / "source_backed_replay.json"
FOUNDRY_IMAGE = extract_all_artifacts.DOCKER_FOUNDRY


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def build_replay_spec(root: Path, compiler_volume: str) -> FoundryReplaySpec:
    root = root.resolve()
    harness_root = root / HARNESS_REL
    artifact_root = root / ARTIFACT_REL
    if not harness_root.is_dir() or not artifact_root.is_dir():
        raise ValueError("Celer source-backed harness or artifact pack is missing")
    manifest = _load_object(harness_root / "source_manifest.json")
    config = _load_object(harness_root / "harness_config.json")
    if manifest.get("lineage_id") != LINEAGE_ID or config.get("source_commit") != manifest.get("source_commit"):
        raise ValueError("Celer source-backed manifest/config identity mismatch")
    matrix, matrix_metadata = build_evm_support_matrix.build_matrix(root)
    matrix_path = root / SUPPORT_MATRIX_REL
    if not matrix_path.is_file():
        raise ValueError("Celer EVM support matrix report is missing")
    if matrix_metadata.get("matrix", {}).get("matrix_hash") != matrix.matrix_hash:
        raise ValueError("Celer EVM support matrix is not canonical")
    return FoundryReplaySpec(
        image_ref=FOUNDRY_IMAGE,
        project_path=harness_root,
        tool_revision="foundry-1.8.1",
        artifact_hash=sha256_file(artifact_root / "manifest.json"),
        initialization_hash=sha256_file(artifact_root / "deployment.json"),
        profile_hash=sha256_file(artifact_root / "channel_profile.json"),
        semantic_engine="independent-foundry-evm",
        compiler_version=SOLC_VERSION,
        test_filter=None,
        network_mode="none",
        timeout_seconds=300.0,
        compiler_volume=compiler_volume,
        compiler_image_ref=extract_all_artifacts.solc_image_for_version(SOLC_VERSION),
        support_matrix_hash=matrix.matrix_hash,
    )


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def build_receipt(
    root: Path,
    spec: FoundryReplaySpec,
    result: Any,
    compiler: dict[str, str],
    *,
    observed_at: str,
) -> dict[str, Any]:
    root = root.resolve()
    harness_root = root / HARNESS_REL
    artifact_root = root / ARTIFACT_REL
    manifest = _load_object(harness_root / "source_manifest.json")
    source_path = harness_root / "contracts" / "CBridge.sol"
    body: dict[str, Any] = {
        "schema_version": 1,
        "record_type": "source_backed_independent_evm_replay",
        "scope": "source_backed_development_replay_only",
        "lineage_id": LINEAGE_ID,
        "source_repository": manifest.get("source_repository"),
        "source_commit": manifest.get("source_commit"),
        "source_manifest_sha256": sha256_file(harness_root / "source_manifest.json"),
        "source_file_sha256": sha256_file(source_path),
        "artifact_manifest_sha256": sha256_file(artifact_root / "manifest.json"),
        "initialization_sha256": sha256_file(artifact_root / "deployment.json"),
        "profile_sha256": sha256_file(artifact_root / "channel_profile.json"),
        "replay_spec": spec.as_dict(),
        "result": result.as_dict(),
        "compiler": compiler,
        "source_backed": True,
        "native_evm_replay": True,
        "independent_evaluator": False,
        "independent_property_validation": False,
        "independent_trigger_validation": False,
        "admission_eligible": False,
        "network_mode": "none",
        "evidence_scope": "source_backed_development_replay_only",
        "observed_at": observed_at,
    }
    body["report_hash"] = canonical_hash(body)
    return body


def validate_report(root: Path = ROOT, report_path: Path | None = None) -> list[str]:
    root = root.resolve()
    path = report_path or root / DEFAULT_OUTPUT
    errors: list[str] = []
    try:
        report = _load_object(path)
        errors.extend(
            f"support matrix: {error}"
            for error in build_evm_support_matrix.validate_report(root)
        )
        harness_root = root / HARNESS_REL
        artifact_root = root / ARTIFACT_REL
        manifest = _load_object(harness_root / "source_manifest.json")
        source_path = harness_root / "contracts" / "CBridge.sol"
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [f"source-backed replay report unreadable: {error}"]

    stored_hash = report.get("report_hash")
    body = dict(report)
    body.pop("report_hash", None)
    if stored_hash != canonical_hash(body):
        errors.append("report hash mismatch")
    expected_scalars = {
        "schema_version": 1,
        "record_type": "source_backed_independent_evm_replay",
        "scope": "source_backed_development_replay_only",
        "lineage_id": LINEAGE_ID,
        "source_repository": manifest.get("source_repository"),
        "source_commit": manifest.get("source_commit"),
        "source_manifest_sha256": sha256_file(harness_root / "source_manifest.json"),
        "source_file_sha256": sha256_file(source_path),
        "artifact_manifest_sha256": sha256_file(artifact_root / "manifest.json"),
        "initialization_sha256": sha256_file(artifact_root / "deployment.json"),
        "profile_sha256": sha256_file(artifact_root / "channel_profile.json"),
        "source_backed": True,
        "native_evm_replay": True,
        "independent_evaluator": False,
        "independent_property_validation": False,
        "independent_trigger_validation": False,
        "admission_eligible": False,
        "network_mode": "none",
        "evidence_scope": "source_backed_development_replay_only",
    }
    for key, expected in expected_scalars.items():
        if report.get(key) != expected:
            errors.append(f"{key} mismatch")

    spec_data = report.get("replay_spec")
    result_data = report.get("result")
    compiler = report.get("compiler")
    if not isinstance(spec_data, dict) or not isinstance(result_data, dict) or not isinstance(compiler, dict):
        return errors + ["replay spec, result or compiler identity is missing"]
    try:
        spec = FoundryReplaySpec(
            image_ref=spec_data["image_ref"],
            project_path=Path(spec_data["project_path"]),
            tool_revision=spec_data["tool_revision"],
            artifact_hash=spec_data["artifact_hash"],
            initialization_hash=spec_data["initialization_hash"],
            profile_hash=spec_data["profile_hash"],
            semantic_engine=spec_data["semantic_engine"],
            compiler_version=spec_data.get("compiler_version"),
            test_filter=spec_data.get("test_filter"),
            network_mode=spec_data["network_mode"],
            timeout_seconds=float(spec_data["timeout_seconds"]),
            support_matrix_hash=spec_data.get("support_matrix_hash"),
            compiler_volume=spec_data.get("compiler_volume"),
            compiler_image_ref=spec_data.get("compiler_image_ref"),
        )
    except (KeyError, TypeError, ValueError) as error:
        errors.append(f"replay spec invalid: {error}")
        return errors
    if spec.as_dict() != spec_data:
        errors.append("replay spec hash or fields are not canonical")
    if spec.project_path != harness_root.resolve():
        errors.append("replay project is not the locked Celer harness")
    try:
        matrix, _ = build_evm_support_matrix.build_matrix(root)
        if spec.support_matrix_hash != matrix.matrix_hash:
            errors.append("replay spec is not bound to the current support matrix")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        errors.append(f"support matrix identity unavailable: {error}")
    if result_data.get("spec_hash") != spec.spec_hash:
        errors.append("replay result/spec hash mismatch")
    if result_data.get("status") != ReplayStatus.PASS.value:
        errors.append("source-backed replay did not pass")
    if result_data.get("exit_code") != 0:
        errors.append("source-backed replay exit code is not zero")
    if not isinstance(result_data.get("test_count"), int) or result_data["test_count"] <= 0:
        errors.append("source-backed replay has no test count")
    if result_data.get("passed_tests") != result_data.get("test_count") or result_data.get("failed_tests") != 0:
        errors.append("source-backed replay test counts are not all passing")
    if compiler.get("version") != SOLC_VERSION or compiler.get("image") != spec.compiler_image_ref:
        errors.append("compiler identity does not match replay spec")
    if compiler.get("path") != "/compiler/solc" or not isinstance(compiler.get("binary_sha256"), str):
        errors.append("compiler binary identity is incomplete")
    return errors


def run(root: Path = ROOT, output: Path = DEFAULT_OUTPUT) -> int:
    root = root.resolve()
    volume = extract_all_artifacts.create_compiler_cache_volume("source-replay-celer_cbridge")
    try:
        compiler = extract_all_artifacts.populate_compiler_cache_volume(volume, SOLC_VERSION)
        spec = build_replay_spec(root, volume)
        result = FoundryDockerReplay().run(spec)
        receipt = build_receipt(
            root,
            spec,
            result,
            compiler,
            observed_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )
        if result.status is not ReplayStatus.PASS:
            print(f"[FAIL] source-backed replay status={result.status.value} reason={result.reason}")
            return 1
        _atomic_json(output.resolve(), receipt)
        print(
            f"source-backed independent EVM replay: {result.passed_tests}/{result.test_count} pass"
        )
        print(f"evidence written to: {output.resolve()}")
        return 0
    finally:
        extract_all_artifacts.remove_compiler_cache_volume(volume)


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
            print("OK: source-backed independent EVM replay is valid and non-admission")
            return 0
        return run(root, output)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"[FAIL] {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
