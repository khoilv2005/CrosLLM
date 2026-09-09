"""Prepare a source-backed, development-only campaign input bundle.

This command is the bridge between the checked-in development harnesses and
the generic campaign planner.  It deliberately does not read benchmark rows or
sealed labels.  The resulting bundle is executable input for a development
probe, not an evaluation lock and not an admission decision.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

from crossllm.artifacts import extract_storage_symbols
from crossllm.contracts.canonical import canonical_json, sha256_hex
from crossllm.runtime import CampaignPlanner


ROOT = Path(__file__).resolve().parents[1]
DEVELOPMENT_LINEAGES = ("celer_cbridge", "chainbridge", "layerzero_v2")
DEFAULT_METHODS = ("X", "P", "T0")
DEFAULT_FAMILIES = ("GLM", "DeepSeek", "Qwen", "gpt-oss")
_FORBIDDEN_PUBLIC_KEYS = frozenset({
    "ground_truth",
    "gold_property",
    "gold_property_id",
    "trigger",
    "trigger_validation_status",
    "vulnerable",
    "patched",
    "mutation_operator_id",
})


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read JSON {path}: {error}") from error


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise ValueError(f"cannot hash {path}: {error}") from error
    return digest.hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    try:
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_jsonl(path: Path, rows: Iterable[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        "".join(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )
    try:
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _assert_public_payload(value: object, *, path: str = "payload") -> None:
    """Reject label/trigger-shaped fields before a pack reaches a model."""
    if isinstance(value, dict):
        for key, nested in value.items():
            if isinstance(key, str) and key.lower() in _FORBIDDEN_PUBLIC_KEYS:
                raise ValueError(f"{path} contains forbidden evaluation field: {key}")
            _assert_public_payload(nested, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _assert_public_payload(nested, path=f"{path}[{index}]")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as error:
        raise ValueError(f"cannot read JSONL {path}: {error}") from error
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid JSONL at {path}:{line_number}: {error}") from error
        if not isinstance(row, dict):
            raise ValueError(f"JSONL row at {path}:{line_number} must be an object")
        rows.append(row)
    return rows


def _validate_source_backed_lineage(
    root: Path,
    lineage: str,
    probe_report: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    harness_root = root / "dataset" / "harness" / lineage
    artifact_root = root / "dataset" / "artifacts" / lineage
    config = _load_json(harness_root / "harness_config.json")
    if not isinstance(config, dict):
        raise ValueError(f"{lineage}: harness config must be an object")
    if config.get("split") != "development":
        raise ValueError(f"{lineage}: only development harnesses may enter this bundle")
    if config.get("source_backed") is not True or config.get("harness_status") != "source_backed_development":
        raise ValueError(f"{lineage}: harness is not source-backed development")

    evidence = config.get("evidence")
    if not isinstance(evidence, dict) or evidence.get("probe_status") != "pass":
        raise ValueError(f"{lineage}: passing source-backed probe evidence is required")
    rows = probe_report.get("probes")
    if not isinstance(rows, list):
        raise ValueError("source-backed probe report has no probes list")
    probe = next((row for row in rows if isinstance(row, dict) and row.get("lineage_id") == lineage), None)
    if not isinstance(probe, dict) or probe.get("status") != "pass":
        raise ValueError(f"{lineage}: source-backed probe row is not passing")
    if evidence.get("probe_row_sha256") != probe.get("probe_row_sha256"):
        raise ValueError(f"{lineage}: harness probe row hash does not match the report")

    source_manifest = harness_root / str(config.get("source_manifest", ""))
    artifact_manifest = artifact_root / "manifest.json"
    if not source_manifest.is_file() or not artifact_manifest.is_file():
        raise ValueError(f"{lineage}: source and artifact manifests are required")
    source_hash = _sha256_file(source_manifest)
    artifact_hash = _sha256_file(artifact_manifest)
    if config.get("source_manifest_sha256") != source_hash:
        raise ValueError(f"{lineage}: source manifest hash mismatch")
    if config.get("artifact_manifest_sha256") != artifact_hash:
        raise ValueError(f"{lineage}: artifact manifest hash mismatch")

    source_data = _load_json(source_manifest)
    artifact_data = _load_json(artifact_manifest)
    if not isinstance(source_data, dict) or not isinstance(artifact_data, dict):
        raise ValueError(f"{lineage}: manifests must be objects")
    return config, probe, {
        "source_manifest_sha256": source_hash,
        "artifact_manifest_sha256": artifact_hash,
        "source_manifest": source_data,
        "artifact_manifest": artifact_data,
    }


def _build_public_pack(
    root: Path,
    lineage: str,
    config: dict[str, Any],
    probe: dict[str, Any],
    manifests: dict[str, Any],
) -> dict[str, Any]:
    artifact_root = root / "dataset" / "artifacts" / lineage
    files: dict[str, Any] = {}
    for name in ("symbols.json", "scope.json", "channel_profile.json", "normal_workflow.json"):
        path = artifact_root / name
        if not path.is_file():
            raise ValueError(f"{lineage}: public artifact file is missing: {name}")
        value = _load_json(path)
        _assert_public_payload(value, path=f"{lineage}.{name}")
        files[name] = value
    domain_assignments = files["symbols.json"].get("domain_assignments")
    if not isinstance(domain_assignments, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in domain_assignments.items()
    ):
        raise ValueError(f"{lineage}: explicit storage symbol domain assignments are missing")
    extraction = extract_storage_symbols(root / "dataset" / "artifacts" / lineage, domain_assignments)
    files["storage_symbols.json"] = {
        "schema_version": 1,
        "symbols": [symbol.as_dict() for symbol in extraction.symbols],
        "skipped": [item.as_dict() for item in extraction.skipped],
    }
    _assert_public_payload(files["storage_symbols.json"], path=f"{lineage}.storage_symbols.json")
    pack = {
        "schema_version": 1,
        "record_type": "public_development_artifact_pack",
        "admission_eligible": False,
        "split": "development",
        "lineage_id": lineage,
        "protocol": config.get("protocol"),
        "source_backed": True,
        "source_commit": config.get("source_commit"),
        "source_repository": config.get("source_repository"),
        "source_manifest_sha256": manifests["source_manifest_sha256"],
        "artifact_manifest_sha256": manifests["artifact_manifest_sha256"],
        "probe_report": config["evidence"]["probe_report"],
        "probe_row_sha256": probe["probe_row_sha256"],
        "compiler": config.get("compiler"),
        "public_files": files,
    }
    _assert_public_payload(pack)
    return pack


def build_bundle(
    *,
    root: Path = ROOT,
    out_dir: Path,
    methods: Iterable[str] = DEFAULT_METHODS,
    families: Iterable[str] = DEFAULT_FAMILIES,
    lineages: Iterable[str] = DEVELOPMENT_LINEAGES,
    replicates: int = 1,
    seed: int = 20260909,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build a new development bundle and return its manifest."""
    root = Path(root).resolve()
    out_dir = Path(out_dir).resolve()
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ValueError(f"refusing to overwrite non-empty output directory: {out_dir}")
    if replicates <= 0:
        raise ValueError("replicates must be a positive integer")
    methods = tuple(dict.fromkeys(methods))
    families = tuple(dict.fromkeys(families))
    lineages = tuple(dict.fromkeys(lineages))
    if not methods or any(method not in DEFAULT_METHODS for method in methods):
        raise ValueError("methods must be a non-empty subset of X, P and T0")
    if not families or any(family not in DEFAULT_FAMILIES for family in families):
        raise ValueError("families must be a non-empty subset of the four locked families")
    if not lineages or any(lineage not in DEVELOPMENT_LINEAGES for lineage in lineages):
        raise ValueError("lineages must be a non-empty subset of source-backed development lineages")

    protocol = _load_json(root / "protocol" / "protocol.json")
    models_doc = _load_json(root / "protocol" / "models.json")
    prompt_manifest = _load_json(root / "prompts" / "manifest.json")
    probe_report = _load_json(root / "dataset" / "reports" / "source_backed_harnesses.json")
    if not isinstance(protocol, dict) or not isinstance(models_doc, dict) or not isinstance(prompt_manifest, dict):
        raise ValueError("protocol, models and prompt manifest must be objects")

    model_rows = models_doc.get("models")
    if not isinstance(model_rows, list):
        raise ValueError("model document has no models list")
    models: dict[str, dict[str, Any]] = {}
    for row in model_rows:
        if not isinstance(row, dict) or row.get("family") not in families:
            continue
        family = str(row["family"])
        tag = row.get("preferred_execution_tag") or row.get("requested_tag")
        if not isinstance(tag, str) or not tag:
            raise ValueError(f"{family}: preferred execution tag is missing")
        settings = row.get("starting_research_settings")
        if not isinstance(settings, dict):
            raise ValueError(f"{family}: starting research settings are missing")
        if family in models:
            raise ValueError(f"duplicate model family: {family}")
        models[family] = {"model_tag": tag, "settings": settings}
    missing_families = sorted(set(families) - set(models))
    if missing_families:
        raise ValueError("model families missing: " + ", ".join(missing_families))

    packs: dict[str, dict[str, Any]] = {}
    instances: list[dict[str, Any]] = []
    for lineage in lineages:
        config, probe, manifests = _validate_source_backed_lineage(root, lineage, probe_report)
        pack = _build_public_pack(root, lineage, config, probe, manifests)
        pack_hash = sha256_hex(pack)
        packs[lineage] = {"pack": pack, "pack_hash": pack_hash}
        instances.append({
            "instance_id": f"dev_{lineage}_source_backed",
            "lineage_id": lineage,
            "split": "development",
            "source_backed": True,
            "artifact_pack": f"artifact_packs/{lineage}.json",
            "artifact_pack_hash": pack_hash,
            "source_manifest_sha256": manifests["source_manifest_sha256"],
            "artifact_manifest_sha256": manifests["artifact_manifest_sha256"],
            "probe_row_sha256": probe["probe_row_sha256"],
        })

    prompt_hashes = {
        row["track"]: row["sha256"]
        for row in prompt_manifest.get("files", [])
        if isinstance(row, dict) and isinstance(row.get("track"), str) and isinstance(row.get("sha256"), str)
    }
    required_tracks = {"X", "P", "T0"}.intersection(methods)
    if not required_tracks.issubset(prompt_hashes):
        raise ValueError("prompt manifest lacks a hash for every selected method")
    config = {
        "schema_version": 1,
        "record_type": "development_campaign_config",
        "mode": "development",
        "split": "development",
        "admission_eligible": False,
        "sealed_data_read": False,
        "benchmark_manifest_hash": None,
        "methods": list(methods),
        "families": list(families),
        "replicates": replicates,
        "seed": seed,
        "proposal_slots": protocol.get("proposal_slots"),
        "budgets": protocol.get("budgets"),
        "provider": models_doc.get("provider"),
        "models": models,
        "prompt_manifest_sha256": _sha256_file(root / "prompts" / "manifest.json"),
        "prompt_hashes": prompt_hashes,
        "source_probe_report_sha256": _sha256_file(root / "dataset" / "reports" / "source_backed_harnesses.json"),
        "artifact_packs": {lineage: value["pack_hash"] for lineage, value in packs.items()},
    }

    plan = CampaignPlanner().build(
        mode="development",
        instances=[{"instance_id": row["instance_id"], "lineage_id": row["lineage_id"]} for row in instances],
        methods=list(methods),
        backbones=[{"backbone": family, "model_tag": models[family]["model_tag"]} for family in families],
        replicates=replicates,
        seed=seed,
        config=config,
        created_at=created_at or datetime.now(timezone.utc).isoformat(),
    )
    plan_payload = plan.as_dict()
    plan_rows = [campaign.as_dict() for campaign in plan.campaigns]

    for lineage, value in packs.items():
        _write_json(out_dir / "artifact_packs" / f"{lineage}.json", value["pack"])
    _write_jsonl(out_dir / "instances.jsonl", instances)
    _write_json(out_dir / "backbones.json", [
        {"backbone": family, "model_tag": models[family]["model_tag"]}
        for family in families
    ])
    _write_json(out_dir / "config.json", config)
    _write_json(out_dir / "campaigns.plan.json", plan_payload)
    _write_jsonl(out_dir / "campaigns.plan.jsonl", plan_rows)

    generated = {
        "instances.jsonl": _sha256_file(out_dir / "instances.jsonl"),
        "backbones.json": _sha256_file(out_dir / "backbones.json"),
        "config.json": _sha256_file(out_dir / "config.json"),
        "campaigns.plan.json": _sha256_file(out_dir / "campaigns.plan.json"),
        "campaigns.plan.jsonl": _sha256_file(out_dir / "campaigns.plan.jsonl"),
        "artifact_packs": {
            lineage: _sha256_file(out_dir / "artifact_packs" / f"{lineage}.json")
            for lineage in packs
        },
    }
    manifest = {
        "schema_version": 1,
        "record_type": "development_campaign_input_bundle",
        "status": "development_execution_input",
        "mode": "development",
        "split": "development",
        "admission_eligible": False,
        "sealed_data_read": False,
        "evaluation_lock": False,
        "campaign_count": len(plan.campaigns),
        "lineages": list(lineages),
        "methods": list(methods),
        "families": list(families),
        "replicates": replicates,
        "seed": seed,
        "plan_id": plan.plan_id,
        "plan_hash": plan_payload["plan_hash"],
        "campaigns_hash": plan.campaigns_hash,
        "generated_files": generated,
        "limitations": [
            "development source-backed probes only; no evaluation or sealed benchmark rows were read",
            "lineage review, owner acceptance, independent property/trigger validation and runtime model identity remain pending",
            "preflight-live must pass immediately before any Ollama Cloud campaign",
        ],
    }
    # The manifest hash is defined over the payload without the hash field;
    # hashing the file including its own digest would create an impossible
    # fixed point.
    manifest["manifest_sha256"] = sha256_hex(manifest)
    _write_json(out_dir / "manifest.json", manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out-dir", type=Path, default=Path("build/development_campaign"))
    parser.add_argument("--methods", default=",".join(DEFAULT_METHODS))
    parser.add_argument("--families", default=",".join(DEFAULT_FAMILIES))
    parser.add_argument("--lineages", default=",".join(DEVELOPMENT_LINEAGES))
    parser.add_argument("--replicates", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260909)
    parser.add_argument("--created-at", default=None)
    args = parser.parse_args(argv)
    try:
        manifest = build_bundle(
            root=args.root,
            out_dir=args.out_dir,
            methods=tuple(part.strip() for part in args.methods.split(",") if part.strip()),
            families=tuple(part.strip() for part in args.families.split(",") if part.strip()),
            lineages=tuple(part.strip() for part in args.lineages.split(",") if part.strip()),
            replicates=args.replicates,
            seed=args.seed,
            created_at=args.created_at,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"[FAIL] {error}")
        return 1
    print(json.dumps({
        "status": manifest["status"],
        "campaign_count": manifest["campaign_count"],
        "plan_id": manifest["plan_id"],
        "plan_hash": manifest["plan_hash"],
        "out_dir": str(Path(args.out_dir).resolve()),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
