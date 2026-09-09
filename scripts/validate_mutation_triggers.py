#!/usr/bin/env python3
"""Run the development mutation harness without overstating admission evidence.

The output is a deterministic-schema smoke receipt for the checked-in,
generated control pairs. It does not establish source ancestry, independent
trigger validation or corpus admission for the locked upstream lineages.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IMAGE = "ghcr.io/foundry-rs/foundry@sha256:0c00cb0bda1ab1b91c9a6bf60f4c76c09c1a8870824b6d4718afbabacf6f9a17"
OPERATORS_PATH = ROOT / "dataset" / "benchmark" / "mutation_operators.json"
VALIDATION_SPEC_PATH = ROOT / "dataset" / "benchmark" / "mutation_validation_spec.json"
EVIDENCE_SCHEMA = "crossllm.mutation-trigger-smoke/v1"
MUTATION_SOLC_VERSION = "0.8.36"
PROPERTY_FAMILIES = {
    "replay", "input_validation", "logic", "message_handling", "quorum", "finality"
}

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataset.tools import extract_all_artifacts


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _operator_registry(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    operators = payload.get("operators") if isinstance(payload, dict) else None
    if not isinstance(operators, list) or not operators:
        raise ValueError("mutation operator registry must contain a non-empty operators array")
    registry: dict[str, dict[str, Any]] = {}
    for operator in operators:
        if not isinstance(operator, dict) or not isinstance(operator.get("operator_id"), str):
            raise ValueError("mutation operator registry contains an invalid operator")
        operator_id = operator["operator_id"]
        if operator_id in registry:
            raise ValueError(f"duplicate mutation operator: {operator_id}")
        for field in ("property_family", "transformation", "intended_security_property", "negative_control_policy"):
            if not isinstance(operator.get(field), str) or not operator[field].strip():
                raise ValueError(f"{operator_id}: missing registry field {field}")
        if operator["property_family"] not in PROPERTY_FAMILIES:
            raise ValueError(f"{operator_id}: unsupported property family {operator['property_family']}")
        registry[operator_id] = operator
    families = {operator["property_family"] for operator in registry.values()}
    if families != PROPERTY_FAMILIES:
        raise ValueError(f"registry must cover the six property families, got {sorted(families)}")
    return registry


def _validation_registry(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if payload.get("schema_version") != 1 or payload.get("scope") != "generated_development_mutation_harness_only":
        raise ValueError("mutation validation spec has an invalid schema or scope")
    if not isinstance(rows, list) or not rows:
        raise ValueError("mutation validation spec must contain a non-empty rows array")
    result: dict[str, dict[str, Any]] = {}
    required = ("operator_id", "mutant_contract", "control_contract", "test_case", "trigger", "control_expectation")
    for row in rows:
        if not isinstance(row, dict) or any(not isinstance(row.get(field), str) or not row[field].strip() for field in required):
            raise ValueError("mutation validation spec contains an incomplete row")
        operator_id = row["operator_id"]
        if operator_id in result:
            raise ValueError(f"duplicate mutation validation row: {operator_id}")
        result[operator_id] = row
    return result


def _test_cases(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    direct = payload.get("test_results")
    if isinstance(direct, dict):
        return direct
    for value in payload.values():
        if isinstance(value, dict) and isinstance(value.get("test_results"), dict):
            return value["test_results"]
    return {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    harness = (root / "dataset" / "harness" / "mutation_tests").resolve()
    if not harness.is_dir():
        print(f"[FAIL] mutation harness does not exist: {harness}", file=sys.stderr)
        return 1
    if "@sha256:" not in args.image:
        print("[FAIL] --image must be digest-pinned", file=sys.stderr)
        return 2
    try:
        registry = _operator_registry((root / OPERATORS_PATH.relative_to(ROOT)).resolve())
        validation_registry = _validation_registry((root / VALIDATION_SPEC_PATH.relative_to(ROOT)).resolve())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"[FAIL] invalid mutation operator registry: {error}", file=sys.stderr)
        return 2
    if set(validation_registry) != set(registry):
        print(
            "[FAIL] mutation validation spec coverage does not match operator registry: "
            f"missing={sorted(set(registry) - set(validation_registry))}, "
            f"extra={sorted(set(validation_registry) - set(registry))}",
            file=sys.stderr,
        )
        return 2

    source_files = [
        harness / "contracts" / "MutationTargets.sol",
        harness / "test" / "MutationTriggerVerificationTest.t.sol",
    ]
    missing = [str(path) for path in source_files if not path.is_file()]
    if missing:
        print(f"[FAIL] mutation harness source is incomplete: {', '.join(missing)}", file=sys.stderr)
        return 2
    test_source = source_files[1].read_text(encoding="utf-8")
    for operator_id, row in validation_registry.items():
        expected_fragments = (
            row["mutant_contract"], row["control_contract"], row["test_case"]
        )
        if any(fragment not in test_source for fragment in expected_fragments):
            print(
                f"[FAIL] validation spec is not traceable to test source: {operator_id}",
                file=sys.stderr,
            )
            return 2

    container_name = f"crossllm-mutation-{os.getpid()}"
    volume: str | None = None
    compiler_info: dict[str, str] | None = None
    try:
        volume = extract_all_artifacts.create_compiler_cache_volume("mutation_tests")
        compiler_info = extract_all_artifacts.populate_compiler_cache_volume(
            volume, MUTATION_SOLC_VERSION
        )
        command = [
            "docker", "run", "--rm", "--name", container_name,
            "--pull=never", "--network=none", "--read-only", "--cap-drop=ALL",
            "--security-opt=no-new-privileges", "--pids-limit", "128",
            "--memory", "2g", "--tmpfs", "/tmp:rw,exec,nosuid,size=512m",
            "--tmpfs", "/home/foundry:rw,exec,nosuid,size=512m,uid=1000,gid=1000,mode=700",
            "-e", "FOUNDRY_CACHE_PATH=/tmp/crossllm-cache",
            "-e", "FOUNDRY_OUT=/tmp/crossllm-out",
            "--mount", f"type=bind,source={harness},target=/work,readonly",
            "--mount", f"type=volume,source={volume},target=/compiler,readonly",
            "--workdir", "/work", "--entrypoint", "/usr/local/bin/forge",
            args.image, "test", "--root", "/work", "--out", "/tmp/crossllm-out",
            "--cache-path", "/tmp/crossllm-cache", "--use", "/compiler/solc",
            "--match-contract", "MutationTriggerVerificationTest", "--json",
        ]
        completed = subprocess.run(
            command, cwd=root, capture_output=True, text=True,
            timeout=args.timeout_seconds, check=False,
        )
    except subprocess.TimeoutExpired as error:
        cleanup = subprocess.run(
            ["docker", "rm", "-f", container_name],
            cwd=root, capture_output=True, text=True, check=False,
        )
        cleanup_detail = ""
        if cleanup.returncode != 0:
            cleanup_detail = (
                f"; cleanup failed with exit {cleanup.returncode}: "
                f"{cleanup.stderr.strip()}"
            )
        print(
            f"[FAIL] mutation trigger probe timed out: {error}{cleanup_detail}",
            file=sys.stderr,
        )
        return 1
    except OSError as error:
        print(f"[FAIL] unable to invoke Docker: {error}", file=sys.stderr)
        return 1
    except (RuntimeError, ValueError) as error:
        print(f"[FAIL] compiler setup failed: {error}", file=sys.stderr)
        return 1
    finally:
        if volume is not None:
            try:
                extract_all_artifacts.remove_compiler_cache_volume(volume)
            except (OSError, RuntimeError, ValueError) as error:
                print(f"[FAIL] compiler cache cleanup failed: {error}", file=sys.stderr)
    if completed.returncode != 0:
        print(f"[FAIL] mutation trigger smoke probe failed:\n{completed.stderr}\n{completed.stdout}", file=sys.stderr)
        return 1

    payload: object | None = None
    for line in reversed(completed.stdout.splitlines()):
        if line.strip().startswith("{"):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            break
    cases = _test_cases(payload)
    if not cases:
        print(f"[FAIL] no structured test results returned by forge:\n{completed.stdout}", file=sys.stderr)
        return 1

    timestamp = datetime.now(timezone.utc).isoformat()
    evidence_rows: list[dict[str, object]] = []
    observed_operator_ids: set[str] = set()
    for test_name, details in sorted(cases.items()):
        if not isinstance(test_name, str) or not test_name.startswith("test_OP_"):
            continue
        details = details if isinstance(details, dict) else {}
        passed = details.get("status") == "Success"
        operator_id = test_name.removeprefix("test_").removesuffix("()")
        if operator_id not in registry:
            print(f"[FAIL] test maps to unknown mutation operator: {operator_id}", file=sys.stderr)
            return 1
        observed_operator_ids.add(operator_id)
        record = {
            "operator_id": operator_id,
            "property_family": registry[operator_id]["property_family"],
            "test_case": test_name,
            "status": "PASS" if passed else "FAIL",
            "gas_used": details.get("gas_used"),
            "mutant_exploit_verified": passed,
            "negative_control_blocked_verified": passed,
            "control_pair_verified": passed,
            "probe_scope": "generated_development_mutation_harness_smoke_only",
            "independent_source_validation": False,
            "admission_eligible": False,
        }
        evidence_rows.append(record)
        print(f"  [{'PASS' if passed else 'FAIL'}] {record['operator_id']}")
    if not evidence_rows:
        print("[FAIL] structured output contained no mutation operator tests", file=sys.stderr)
        return 1
    missing_operators = sorted(set(registry) - observed_operator_ids)
    extra_operators = sorted(observed_operator_ids - set(registry))
    if missing_operators or extra_operators or len(evidence_rows) != len(registry):
        print(
            "[FAIL] mutation operator coverage does not match registry: "
            f"missing={missing_operators}, extra={extra_operators}",
            file=sys.stderr,
        )
        return 1

    out_file = args.out or (root / "dataset" / "benchmark" / "trigger_validation_evidence.jsonl")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    receipt_metadata = {
        "record_type": "mutation_operator_evidence",
        "evidence_schema": EVIDENCE_SCHEMA,
        "harness_id": "generated_mutation_tests",
        "harness_source_sha256": hashlib.sha256(
            "".join(_sha256_file(path) for path in source_files).encode("ascii")
        ).hexdigest(),
        "operator_registry_sha256": _sha256_file((root / OPERATORS_PATH.relative_to(ROOT)).resolve()),
        "validation_spec_sha256": _sha256_file((root / VALIDATION_SPEC_PATH.relative_to(ROOT)).resolve()),
        "compiler": compiler_info,
        "runner_image": args.image,
        "network_mode": "none",
        "control_policy": "every positive mutant is paired with a clean control in the same test",
        "independent_source_validation": False,
        "admission_eligible": False,
        "exclusion_policy": "record equivalent, unreachable or out-of-scope operators explicitly",
        "exclusion_log": [],
        "timestamp": timestamp,
    }
    evidence_rows = [{**receipt_metadata, **row} for row in evidence_rows]
    temporary = out_file.with_name(f".{out_file.name}.{os.getpid()}.tmp")
    temporary.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in evidence_rows),
        encoding="utf-8",
    )
    temporary.replace(out_file)
    passed_count = sum(row["status"] == "PASS" for row in evidence_rows)
    print(f"generated-harness smoke receipt: {passed_count}/{len(evidence_rows)} pass")
    print(f"evidence written to: {out_file.relative_to(root) if out_file.is_relative_to(root) else out_file}")
    return 0 if passed_count == len(evidence_rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
