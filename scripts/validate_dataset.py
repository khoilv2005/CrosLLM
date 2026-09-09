#!/usr/bin/env python3
"""Strict dataset integrity/readiness validator.

This command deliberately separates local artifact integrity from evaluation
admission. Generated Foundry projects and pre-recorded traces are useful
development fixtures, but they are not evidence that a locked upstream source
was built, initialized, and replayed. The command therefore never executes a
generated harness as a substitute for source-backed admission and never emits
a benchmark-ready message while any admission gate is open.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = ROOT / "dataset"
# The source-backed harness validator is imported after ROOT is established so
# this file remains executable both as ``python scripts/validate_dataset.py``
# and as an imported module from the test suite.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.source_backed_harnesses import build_source_manifest, canonical_hash
from scripts.review_historical_candidates import validate_report as validate_historical_candidate_report
from scripts.build_evm_support_matrix import validate_report as validate_evm_support_matrix_report
from scripts.build_development_support_matrix import (
    LINEAGES as DEVELOPMENT_MATRIX_LINEAGES,
    validate_report as validate_development_support_matrix_report,
)
from scripts.validate_source_mutations import validate_report as validate_source_mutation_report
from scripts.run_source_backed_replay import validate_report as validate_source_backed_replay_report
from scripts.run_source_backed_replays import validate_report as validate_source_backed_replays_report
from scripts.validate_replay_negative_controls import validate_report as validate_replay_negative_controls_report
from scripts.run_isolation_canary import validate_report as validate_isolation_canary_report
from scripts.run_differential_spike import validate_report as validate_differential_spike_report
from scripts.validate_toolchain_lock import validate as validate_toolchain_lock
from scripts.run_development_calibration_rehearsal import validate_report as validate_calibration_rehearsal_report
from scripts.run_provider_contract_rehearsal import validate_report as validate_provider_contract_rehearsal_report
from scripts.run_canary_version_rehearsal import validate_report as validate_canary_version_rehearsal_report
from scripts.run_development_runtime_rehearsal import validate_report as validate_development_runtime_rehearsal_report
from scripts.validate_reconciliation import validate_report as validate_reconciliation_report
from scripts.run_clean_worker_probe import validate_report as validate_clean_worker_report
from scripts.run_analysis_rehearsal import validate_report as validate_analysis_rehearsal_report
from scripts.run_baseline_and_recall_rehearsal import (
    validate_recall_report as validate_m07_recall_report,
    validate_selection_report as validate_m07_selection_report,
)
from scripts.run_backend_feasibility_spike import validate_report as validate_backend_feasibility_report
from scripts.run_sensitivity_matrix_rehearsal import validate_report as validate_sensitivity_matrix_report

LINEAGES = (
    "celer_cbridge", "chainbridge", "hop", "layerzero_v2",
    "hyperlane", "axelar_gmp", "synapse", "wormhole_evm_sdk",
    "across", "stargate", "arbitrum_token_bridge", "optimism",
    "zksync_era", "polygon_zkevm", "scroll", "linea",
)


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _source_cache_for(lineage: str) -> Path:
    """Prefer the clean pinned checkout used to build canonical evidence."""

    lineage_specific = {
        # Polygon's Windows sparse-checkout source receipt was built from the
        # populated clean3 checkout; the default clean root is intentionally
        # retained as an empty sparse root for archive provenance.
        "polygon_zkevm": [ROOT.parent / "crossllm_private_sources_clean3"],
        # Optimism's pinned checkout keeps its Foundry submodules populated in
        # the canonical cache; the clean sparse checkout has empty dependency
        # directories and cannot validate the copied source closure.
        "optimism": [ROOT.parent / "crossllm_private_sources"],
    }
    candidates = [
        ROOT.parent / "crossllm_private_sources_clean_chainbridge"
        if lineage == "chainbridge" else None,
        *lineage_specific.get(lineage, []),
        ROOT.parent / "crossllm_private_sources_clean",
        ROOT.parent / "crossllm_private_sources",
    ]
    for candidate in candidates:
        if candidate is not None and (candidate / lineage).is_dir():
            return candidate
    return ROOT.parent / "crossllm_private_sources"


def _jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: expected an object")
        rows.append(value)
    return rows


def _required_artifact_paths(lineage: str) -> tuple[Path, ...]:
    artifact = DATASET_DIR / "artifacts" / lineage
    harness = DATASET_DIR / "harness" / lineage
    return (
        artifact / "symbols.json",
        artifact / "manifest.json",
        artifact / "checksums.sha256",
        artifact / "scope.json",
        artifact / "channel_profile.json",
        artifact / "build_info.json",
        artifact / "source_receipt.json",
        artifact / "deployment.json",
        artifact / "normal_workflow.json",
        artifact / "license.json",
        artifact / "abi",
        artifact / "bytecode",
        artifact / "storage_layout",
        harness / "environment.json",
        harness / "harness_config.json",
        harness / "normal_workflow_test.py",
    )


def _local_integrity() -> list[str]:
    """Run checks that are valid for files currently present in this repo."""

    errors: list[str] = []
    for lineage in LINEAGES:
        missing = [
            str(path.relative_to(ROOT))
            for path in _required_artifact_paths(lineage)
            if not path.exists()
        ]
        if missing:
            errors.extend(f"{lineage}: missing {path}" for path in missing)

    for lineage in LINEAGES:
        for path in (DATASET_DIR / "artifacts" / lineage / "bytecode").glob("*.hex"):
            value = path.read_text(encoding="utf-8").strip()
            if len(value) <= 2 or value.lower() == "0x":
                errors.append(f"{path.relative_to(ROOT)}: empty/placeholder bytecode")

    for lineage in LINEAGES:
        checksum_file = DATASET_DIR / "artifacts" / lineage / "checksums.sha256"
        if not checksum_file.is_file():
            continue
        for line_number, line in enumerate(checksum_file.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) != 2 or len(parts[0]) != 64:
                errors.append(f"{checksum_file.relative_to(ROOT)}:{line_number}: malformed checksum")
                continue
            target = checksum_file.parent / parts[1]
            if not target.is_file():
                errors.append(f"{target.relative_to(ROOT)}: checksum target missing")
                continue
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
            if actual != parts[0]:
                errors.append(f"{target.relative_to(ROOT)}: checksum mismatch")
    errors.extend(
        f"historical candidate review: {error}"
        for error in validate_historical_candidate_report(ROOT)
    )
    errors.extend(
        f"development mutation evidence: {error}"
        for error in _development_mutation_evidence_errors()
    )
    errors.extend(
        f"source-backed mutation evidence: {error}"
        for error in validate_source_mutation_report(ROOT)
    )
    errors.extend(
        f"EVM support matrix: {error}"
        for error in validate_evm_support_matrix_report(ROOT)
    )
    for lineage in DEVELOPMENT_MATRIX_LINEAGES:
        errors.extend(
            f"{lineage} EVM support matrix: {error}"
            for error in validate_development_support_matrix_report(ROOT, lineage)
        )
    errors.extend(
        f"source-backed replay evidence: {error}"
        for error in validate_source_backed_replay_report(ROOT)
    )
    errors.extend(
        f"source-backed replay collection: {error}"
        for error in validate_source_backed_replays_report(ROOT)
    )
    errors.extend(
        f"replay negative controls: {error}"
        for error in validate_replay_negative_controls_report(ROOT)
    )
    errors.extend(
        f"isolation canary: {error}"
        for error in validate_isolation_canary_report(ROOT)
    )
    errors.extend(
        f"symbolic-to-source differential spike: {error}"
        for error in validate_differential_spike_report(ROOT)
    )
    _, toolchain_errors = validate_toolchain_lock(ROOT)
    errors.extend(f"toolchain lock: {error}" for error in toolchain_errors)
    errors.extend(
        f"calibration rehearsal: {error}"
        for error in validate_calibration_rehearsal_report(ROOT)
    )
    errors.extend(
        f"provider contract rehearsal: {error}"
        for error in validate_provider_contract_rehearsal_report(ROOT)
    )
    errors.extend(
        f"canary version rehearsal: {error}"
        for error in validate_canary_version_rehearsal_report(ROOT)
    )
    errors.extend(
        f"development runtime rehearsal: {error}"
        for error in validate_development_runtime_rehearsal_report(ROOT)
    )
    errors.extend(
        f"reconciliation map: {error}"
        for error in validate_reconciliation_report(ROOT)
    )
    errors.extend(
        f"clean worker probe: {error}"
        for error in validate_clean_worker_report(ROOT)
    )
    errors.extend(
        f"analysis rehearsal: {error}"
        for error in validate_analysis_rehearsal_report(ROOT)
    )
    errors.extend(
        f"M07 selection rehearsal: {error}"
        for error in validate_m07_selection_report(ROOT)
    )
    errors.extend(
        f"M07 recall rehearsal: {error}"
        for error in validate_m07_recall_report()
    )
    errors.extend(
        f"backend feasibility spike: {error}"
        for error in validate_backend_feasibility_report(ROOT)
    )
    errors.extend(
        f"sensitivity matrix rehearsal: {error}"
        for error in validate_sensitivity_matrix_report(ROOT)
    )
    return errors


def _source_backed_harness_errors(
    lineage: str,
    locked: dict[str, object],
    harness: dict[str, object],
    receipt: dict[str, object],
) -> list[str]:
    """Independently verify source-backed harness metadata and probe evidence."""

    errors: list[str] = []
    harness_root = DATASET_DIR / "harness" / lineage
    artifact_root = DATASET_DIR / "artifacts" / lineage

    manifest_name = harness.get("source_manifest")
    if not isinstance(manifest_name, str) or Path(manifest_name).name != manifest_name:
        return [f"{lineage}: source-backed harness has invalid source_manifest path"]
    manifest_path = harness_root / manifest_name
    try:
        manifest = _load(manifest_path)
    except (OSError, json.JSONDecodeError) as error:
        return [f"{lineage}: source-backed manifest unreadable ({error})"]
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    if harness.get("source_manifest_sha256") != manifest_hash:
        errors.append(f"{lineage}: harness source_manifest_sha256 mismatch")
    if manifest.get("source_commit") != locked.get("commit"):
        errors.append(f"{lineage}: source manifest commit does not match source lock")
    if manifest.get("source_repository") != locked.get("repository"):
        errors.append(f"{lineage}: source manifest repository does not match source lock")

    try:
        expected = build_source_manifest(
            lineage,
            root=ROOT,
            source_cache=_source_cache_for(lineage),
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        errors.append(f"{lineage}: source manifest recomputation failed ({error})")
        expected = None
    if expected is not None and manifest.get("manifest_sha256") != expected.get("manifest_sha256"):
        errors.append(f"{lineage}: source manifest content/hash mismatch")

    expected_artifact_hash = hashlib.sha256((artifact_root / "manifest.json").read_bytes()).hexdigest()
    if manifest.get("artifact_manifest_sha256") != expected_artifact_hash:
        errors.append(f"{lineage}: source manifest artifact manifest hash mismatch")
    # Harness evidence is intentionally kept outside source_receipt.json to
    # avoid a circular artifact-manifest hash. It is checked through the
    # harness config and probe report below.
    evidence = harness.get("evidence")
    if not isinstance(evidence, dict):
        errors.append(f"{lineage}: source-backed harness has no evidence object")
        return errors
    report_name = evidence.get("probe_report")
    if not isinstance(report_name, str):
        errors.append(f"{lineage}: source-backed harness has no probe report")
        return errors
    report_path = ROOT / report_name
    try:
        report = _load(report_path)
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"{lineage}: probe report unreadable ({error})")
        return errors
    rows = report.get("probes")
    row = next(
        (item for item in rows if isinstance(item, dict) and item.get("lineage_id") == lineage),
        None,
    ) if isinstance(rows, list) else None
    if not isinstance(row, dict):
        errors.append(f"{lineage}: probe report has no lineage row")
        return errors
    if row.get("status") != "pass":
        errors.append(f"{lineage}: source-backed probe is not pass")
    if row.get("source_manifest_sha256") != manifest.get("manifest_sha256"):
        errors.append(f"{lineage}: probe is bound to a different source manifest")
    recorded_row_hash = row.get("probe_row_sha256")
    row_without_hash = dict(row)
    row_without_hash.pop("probe_row_sha256", None)
    if recorded_row_hash != canonical_hash(row_without_hash):
        errors.append(f"{lineage}: probe row hash mismatch")
    recorded_report_hash = report.get("report_hash")
    report_without_hash = dict(report)
    report_without_hash.pop("report_hash", None)
    if recorded_report_hash != canonical_hash(report_without_hash):
        errors.append(f"{lineage}: probe report hash mismatch")
    if evidence.get("probe_status") != "pass" or evidence.get("probe_row_sha256") != recorded_row_hash:
        errors.append(f"{lineage}: harness evidence metadata does not match probe report")
    if receipt.get("artifact_admission_status") != "source_pinned_and_built":
        errors.append(f"{lineage}: source-backed receipt is not source_pinned_and_built")
    return errors


def _development_mutation_evidence_errors() -> list[str]:
    """Validate the generated mutation receipt without treating it as admission."""

    benchmark = DATASET_DIR / "benchmark"
    operators_path = benchmark / "mutation_operators.json"
    spec_path = benchmark / "mutation_validation_spec.json"
    evidence_path = benchmark / "trigger_validation_evidence.jsonl"
    errors: list[str] = []
    for path in (operators_path, spec_path, evidence_path):
        if not path.is_file():
            errors.append(f"missing development mutation evidence file: {path.relative_to(ROOT)}")
    if errors:
        return errors

    try:
        operators_payload = _load(operators_path)
        spec_payload = _load(spec_path)
        evidence_rows = _jsonl(evidence_path)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        return [f"development mutation evidence unreadable: {error}"]

    operators = operators_payload.get("operators") if isinstance(operators_payload, dict) else None
    spec_rows = spec_payload.get("rows") if isinstance(spec_payload, dict) else None
    if not isinstance(operators, list) or not operators:
        errors.append("development mutation operator registry has no operators")
        return errors
    if not isinstance(spec_rows, list) or not spec_rows:
        errors.append("development mutation validation spec has no rows")
        return errors
    operator_by_id = {
        row.get("operator_id"): row
        for row in operators
        if isinstance(row, dict) and isinstance(row.get("operator_id"), str)
    }
    spec_by_id = {
        row.get("operator_id"): row
        for row in spec_rows
        if isinstance(row, dict) and isinstance(row.get("operator_id"), str)
    }
    if set(operator_by_id) != set(spec_by_id):
        errors.append("development mutation registry and validation spec coverage differ")

    mutation_root = DATASET_DIR / "harness" / "mutation_tests"
    source_paths = (
        mutation_root / "contracts" / "MutationTargets.sol",
        mutation_root / "test" / "MutationTriggerVerificationTest.t.sol",
    )
    if any(not path.is_file() for path in source_paths):
        errors.append("development mutation harness source is incomplete")
        return errors
    source_digest = hashlib.sha256(
        "".join(hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths).encode("ascii")
    ).hexdigest()
    operator_digest = hashlib.sha256(operators_path.read_bytes()).hexdigest()
    spec_digest = hashlib.sha256(spec_path.read_bytes()).hexdigest()
    seen: set[str] = set()
    families: set[str] = set()
    metadata_fields = (
        "record_type", "evidence_schema", "harness_id", "harness_source_sha256",
        "operator_registry_sha256", "validation_spec_sha256", "runner_image",
        "network_mode", "control_policy", "independent_source_validation",
        "admission_eligible", "probe_scope",
    )
    for row in evidence_rows:
        if not isinstance(row, dict):
            errors.append("development mutation evidence row is not an object")
            continue
        operator_id = row.get("operator_id")
        if not isinstance(operator_id, str) or operator_id not in operator_by_id:
            errors.append(f"unknown development mutation operator: {operator_id}")
            continue
        if operator_id in seen:
            errors.append(f"duplicate development mutation evidence: {operator_id}")
        seen.add(operator_id)
        expected_operator = operator_by_id[operator_id]
        if row.get("property_family") != expected_operator.get("property_family"):
            errors.append(f"{operator_id}: property family does not match registry")
        expected_test = spec_by_id.get(operator_id, {}).get("test_case")
        if row.get("test_case") != expected_test:
            errors.append(f"{operator_id}: test case does not match validation spec")
        for field in metadata_fields:
            if field not in row:
                errors.append(f"{operator_id}: missing evidence metadata {field}")
        if row.get("record_type") != "mutation_operator_evidence":
            errors.append(f"{operator_id}: unexpected evidence record type")
        if row.get("evidence_schema") != "crossllm.mutation-trigger-smoke/v1":
            errors.append(f"{operator_id}: unexpected evidence schema")
        if row.get("harness_source_sha256") != source_digest:
            errors.append(f"{operator_id}: harness source hash mismatch")
        if row.get("operator_registry_sha256") != operator_digest:
            errors.append(f"{operator_id}: operator registry hash mismatch")
        if row.get("validation_spec_sha256") != spec_digest:
            errors.append(f"{operator_id}: validation spec hash mismatch")
        runner_image = row.get("runner_image")
        if not isinstance(runner_image, str) or "@sha256:" not in runner_image:
            errors.append(f"{operator_id}: runner image is not digest-pinned")
        compiler = row.get("compiler")
        if not isinstance(compiler, dict):
            errors.append(f"{operator_id}: compiler identity is missing")
        else:
            if compiler.get("version") != "0.8.36":
                errors.append(f"{operator_id}: compiler version is not the locked mutation version")
            if compiler.get("path") != "/compiler/solc":
                errors.append(f"{operator_id}: compiler path is not the mounted locked binary")
            if not isinstance(compiler.get("image"), str) or "@sha256:" not in compiler["image"]:
                errors.append(f"{operator_id}: compiler image is not digest-pinned")
            binary_hash = compiler.get("binary_sha256")
            if not isinstance(binary_hash, str) or len(binary_hash) != 64:
                errors.append(f"{operator_id}: compiler binary hash is malformed")
        if row.get("network_mode") != "none":
            errors.append(f"{operator_id}: development mutation probe must use network_mode=none")
        if row.get("independent_source_validation") is not False:
            errors.append(f"{operator_id}: generated receipt must declare independent validation false")
        if row.get("admission_eligible") is not False:
            errors.append(f"{operator_id}: generated receipt must remain non-admission")
        if row.get("probe_scope") != "generated_development_mutation_harness_smoke_only":
            errors.append(f"{operator_id}: generated receipt has an invalid probe scope")
        if row.get("status") not in {"PASS", "FAIL"}:
            errors.append(f"{operator_id}: invalid smoke status")
        if not isinstance(row.get("control_pair_verified"), bool):
            errors.append(f"{operator_id}: control_pair_verified must be boolean")
        families.add(str(row.get("property_family")))
    if seen != set(operator_by_id):
        errors.append(
            f"development mutation evidence coverage mismatch: missing={sorted(set(operator_by_id) - seen)}"
        )
    if families != {"replay", "input_validation", "logic", "message_handling", "quorum", "finality"}:
        errors.append(f"development mutation evidence does not cover six property families: {sorted(families)}")
    return errors


def _admission_blockers() -> list[str]:
    """Return blockers for the Experiment Guide's evaluation admission gate."""

    blockers: list[str] = []
    lock = _load(DATASET_DIR / "sources" / "source_lock.json")
    if not isinstance(lock, dict):
        return ["source_lock.json is not an object"]
    lineages = lock.get("lineages")
    if not isinstance(lineages, list):
        return ["source_lock.json has no lineages array"]
    lock_by_lineage = {
        row.get("lineage_id"): row
        for row in lineages
        if isinstance(row, dict) and isinstance(row.get("lineage_id"), str)
    }

    review_path = DATASET_DIR / "artifacts" / "lineage_reviews.jsonl"
    reviews = _jsonl(review_path) if review_path.is_file() else []
    review_by_lineage = {row.get("lineage_id"): row for row in reviews}
    for lineage in LINEAGES:
        review = review_by_lineage.get(lineage)
        if not isinstance(review, dict) or review.get("ancestry_status") != "reviewed":
            blockers.append(f"{lineage}: ancestry review is not reviewed")

    for lineage in LINEAGES:
        locked = lock_by_lineage.get(lineage)
        if not isinstance(locked, dict):
            blockers.append(f"{lineage}: missing source lock record")
            continue
        receipt_path = DATASET_DIR / "artifacts" / lineage / "source_receipt.json"
        try:
            receipt = _load(receipt_path)
        except (OSError, json.JSONDecodeError) as error:
            blockers.append(f"{lineage}: source receipt unreadable ({error})")
            continue
        if not isinstance(receipt, dict):
            blockers.append(f"{lineage}: source receipt is not an object")
            continue
        if receipt.get("source_commit") != locked.get("commit"):
            blockers.append(f"{lineage}: artifact source commit does not match source lock")
        if receipt.get("artifact_admission_status") != "source_pinned_and_built":
            blockers.append(f"{lineage}: source receipt is not source_pinned_and_built")

        harness_path = DATASET_DIR / "harness" / lineage / "harness_config.json"
        try:
            harness = _load(harness_path)
        except (OSError, json.JSONDecodeError) as error:
            blockers.append(f"{lineage}: harness config unreadable ({error})")
            continue
        if not isinstance(harness, dict):
            blockers.append(f"{lineage}: harness config is not an object")
            continue
        if harness.get("source_backed") is not True:
            blockers.append(f"{lineage}: harness is not declared source_backed")
        if harness.get("source_commit") != locked.get("commit"):
            blockers.append(f"{lineage}: harness source commit is absent or mismatched")
        if harness.get("source_backed") is True:
            blockers.extend(_source_backed_harness_errors(lineage, locked, harness, receipt))

    protocol = _load(ROOT / "protocol" / "protocol.json")
    if not isinstance(protocol, dict) or protocol.get("status") != "EVALUATION_LOCKED":
        blockers.append("protocol/protocol.json is not EVALUATION_LOCKED")
    elif not isinstance(protocol.get("evaluation_replicates"), int) or protocol["evaluation_replicates"] <= 0:
        blockers.append("protocol evaluation_replicates is not locked to a positive integer")

    models = _load(ROOT / "protocol" / "models.json")
    if not isinstance(models, dict) or models.get("status") != "RUNTIME_ATTESTATION_LOCKED":
        blockers.append("protocol/models.json is not RUNTIME_ATTESTATION_LOCKED")

    manifest = ROOT / "benchmark.public.jsonl"
    if not manifest.is_file():
        manifest = DATASET_DIR / "benchmark" / "benchmark.public.jsonl"
    tool = ROOT / "tools" / "protocol_tool.py"
    result = subprocess.run(
        [sys.executable, str(tool), "validate", "--manifest", str(manifest), "--mode", "final"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        summary = (result.stdout + result.stderr).strip().replace("\n", " ")
        blockers.append(f"protocol final-manifest validator rejected manifest: {summary[:500]}")

    return blockers


def main() -> int:
    print("CrossLLM dataset integrity/readiness validator")
    print("This command does not treat generated/mock harnesses as source evidence.")

    local_errors = _local_integrity()
    print(f"LOCAL_INTEGRITY: {'PASS' if not local_errors else 'FAIL'}")
    if local_errors:
        for error in local_errors[:40]:
            print(f"  - {error}")
        if len(local_errors) > 40:
            print(f"  - ... {len(local_errors) - 40} additional errors")
        return 1

    blockers = _admission_blockers()
    if blockers:
        print("EVALUATION_READINESS: BLOCKED")
        print(f"ADMISSION_BLOCKERS: {len(blockers)}")
        for blocker in blockers[:80]:
            print(f"  - {blocker}")
        if len(blockers) > 80:
            print(f"  - ... {len(blockers) - 80} additional blockers")
        print("Generated artifacts remain development fixtures; no evaluation admission was asserted.")
        return 2

    print("EVALUATION_READINESS: PASS")
    print("All source, harness, lock, and admission gates were independently verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
