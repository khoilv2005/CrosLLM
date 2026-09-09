"""CLI entry point for offline CrossLLM implementation contracts."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re

from . import __version__
from .adjudication import AdjudicationLedger, BlindedFinding
from .analysis import AnalysisArtifactBuilder, AnalysisFigureBuilder, load_campaign_jsonl, write_figure_bundle
from .artifacts import ArtifactSymbol, extract_storage_symbols
from .backends import SMTControl, Z3XLIRBackend
from .calibration import (
    PrecisionSimulationConfig,
    select_common_replicates,
    estimate_budget,
    freeze_development_selection,
    load_budget_inputs,
    load_hashes,
    load_observations,
    load_selection_decision,
    load_settings,
    simulate_hierarchical_precision,
    select_development_setting,
)
from .contracts import SearchStatus
from .providers import (
    ArchiveReplay,
    OllamaClient,
    OLLAMA_CLOUD_CHAT_ENDPOINT,
    ProviderResponse,
    RetryPolicy,
    build_runtime_model_lock,
    preflight_panel,
    run_live_preflight,
)
from .runtime import (
    CampaignPlanner,
    DevelopmentDryRun,
    EvaluationLaunchGuard,
    ReadinessChecker,
    build_protocol_lock,
)
from .xlir import XLIRCompiler


def _read_json(path: Path) -> object:
    try:
        # utf-8-sig accepts ordinary UTF-8 as well as the BOM emitted by some
        # Windows tooling, while preserving the JSON content used for hashing.
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as error:
        raise ValueError(f"cannot read {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON in {path}: {error.msg}") from error


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE entries without printing or archiving secrets."""
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValueError(f"cannot read env file {path}: {error}") from error
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key.strip()):
            raise ValueError(f"invalid env entry at {path}:{line_number}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def _load_symbols(path: Path) -> list[ArtifactSymbol]:
    raw = _read_json(path)
    rows = raw.get("symbols") if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        raise ValueError("symbol table must be a JSON list or an object with a symbols list")
    symbols: list[ArtifactSymbol] = []
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError(f"symbol {index} must be an object")
        required = ("symbol_id", "path", "name", "domain", "kind", "type")
        missing = [field for field in required if not isinstance(row.get(field), str)]
        if missing:
            raise ValueError(f"symbol {index} has missing or non-string fields: {missing}")
        symbols.append(ArtifactSymbol(**{field: row[field] for field in required}))
    return symbols


def _load_contrasts(path: Path) -> dict[str, dict[str, float]]:
    """Load a contrast-family map without accepting non-finite effects."""
    raw = _read_json(path)
    if isinstance(raw, dict) and "contrasts" in raw:
        raw = raw["contrasts"]
    if not isinstance(raw, dict):
        raise ValueError("contrast input must be an object mapping names to lineage effects")
    result: dict[str, dict[str, float]] = {}
    for name, effects in raw.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(effects, dict):
            raise ValueError("contrast input must map non-empty names to objects")
        normalized: dict[str, float] = {}
        for lineage, value in effects.items():
            if not isinstance(lineage, str) or not lineage.strip() or not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError("contrast lineage effects must be numeric")
            if not (value == value and abs(value) != float("inf")):
                raise ValueError("contrast lineage effects must be finite")
            normalized[lineage] = float(value)
        result[name] = normalized
    return result


def _read_optional_json(path: Path | None) -> object | None:
    if path is None:
        return None
    if not path.exists():
        return None
    if path.suffix.lower() == ".jsonl":
        rows: list[object] = []
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows
    return _read_json(path)


def _rows_from_input(raw: object, name: str) -> list[dict[str, object]]:
    rows = raw.get(name) if isinstance(raw, dict) else raw
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"{name} input must be a JSON list/object or JSONL of objects")
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="crossllm")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command")
    xlir = commands.add_parser("xlir-validate", help="parse and ground one XLIR JSON proposal")
    xlir.add_argument("--symbols", type=Path, required=True, help="public symbol-table JSON")
    xlir.add_argument("--proposal", type=Path, required=True, help="proposal JSON object")
    xlir.add_argument("--maximum-ast-nodes", type=int, default=256)
    symbols = commands.add_parser("extract-storage-symbols", help="derive supported XLIR symbols from storage layouts")
    symbols.add_argument("--artifact-root", type=Path, required=True)
    symbols.add_argument("--domains", type=Path, required=True, help="JSON object mapping contract name to source/destination/shared")
    smt = commands.add_parser("xlir-smt-check", help="run a grounded XLIR query on the pinned Z3 core")
    smt.add_argument("--symbols", type=Path, required=True, help="public symbol-table JSON")
    smt.add_argument("--proposal", type=Path, required=True, help="proposal JSON object")
    smt.add_argument("--query", choices=("violation", "antecedent"), default="violation")
    smt.add_argument("--timeout-seconds", type=float, default=30.0)
    smt.add_argument("--maximum-ast-nodes", type=int, default=256)
    smt.add_argument("--trace-length", type=int, default=None, help="finite observation count for temporal XLIR")
    dry_run = commands.add_parser("dry-run", help="run the offline fixture-only development rehearsal")
    dry_run.add_argument("--export", type=Path, required=True, help="JSONL event export path")
    dry_run.add_argument("--fault-export", type=Path, default=None, help="optional JSONL fault-injection event export")
    dry_run.add_argument("--report", type=Path, default=None, help="optional JSON report output path")
    readiness = commands.add_parser("readiness", help="evaluate conservative G3 readiness gates")
    readiness.add_argument("--mode", choices=("development", "evaluation"), required=True)
    readiness.add_argument("--protocol", type=Path, default=Path("protocol/protocol.json"))
    readiness.add_argument("--models", type=Path, default=Path("protocol/models.json"))
    readiness.add_argument("--toolchain", type=Path, default=Path("containers/toolchain.lock.json"))
    readiness.add_argument("--plan", type=Path, default=None, help="CampaignPlan JSON or JSONL export")
    readiness.add_argument("--evidence", type=Path, default=None, help="Evidence index JSON")
    launch_check = commands.add_parser(
        "evaluation-launch-check",
        help="check the fail-closed boundary immediately before evaluation execution",
    )
    launch_check.add_argument("--protocol", type=Path, required=True)
    launch_check.add_argument("--models", type=Path, required=True)
    launch_check.add_argument("--toolchain", type=Path, required=True)
    launch_check.add_argument("--plan", type=Path, required=True)
    launch_check.add_argument("--evidence", type=Path, required=True)
    launch_check.add_argument("--report-out", type=Path, default=None)
    preflight = commands.add_parser("preflight", help="evaluate four-family provider preflight responses")
    preflight.add_argument("--models", type=Path, default=Path("protocol/models.json"), help="model metadata JSON")
    preflight.add_argument("--responses", type=Path, required=True, help="JSON object mapping family to archived ProviderResponse")
    live_preflight = commands.add_parser("preflight-live", help="run and archive one live provider probe per family")
    live_preflight.add_argument("--models", type=Path, default=Path("protocol/models.json"), help="model metadata JSON")
    live_preflight.add_argument("--prompt-file", type=Path, required=True, help="probe prompt text")
    live_preflight.add_argument("--responses-out", type=Path, required=True, help="raw ProviderResponse archive output")
    live_preflight.add_argument("--endpoint", default="https://ollama.com/api/chat", help="Ollama Cloud chat API endpoint")
    live_preflight.add_argument("--env-file", type=Path, default=Path(".env"), help="optional dotenv file; defaults to .env")
    live_preflight.add_argument("--model-lock-out", type=Path, default=None, help="optional public runtime model-lock JSON output")
    protocol_lock = commands.add_parser("protocol-lock", help="materialize a complete evaluation protocol lock")
    protocol_lock.add_argument("--protocol", type=Path, required=True, help="prospective protocol JSON")
    protocol_lock.add_argument("--model-lock-hash", required=True)
    protocol_lock.add_argument("--benchmark-manifest-hash", required=True)
    protocol_lock.add_argument("--dependency-hash", action="append", default=[], metavar="NAME=SHA256")
    protocol_lock.add_argument("--captured-at", default=None)
    protocol_lock.add_argument("--out", type=Path, required=True)
    live_preflight.add_argument("--timeout-seconds", type=float, default=180.0)
    live_preflight.add_argument("--max-retries", type=int, default=2)
    analysis = commands.add_parser("analysis-build", help="build a deterministic analysis artifact from campaign JSONL")
    analysis.add_argument("--raw", type=Path, required=True, help="frozen campaign outcome JSONL")
    analysis.add_argument("--out", type=Path, required=True, help="analysis artifact JSON output")
    analysis.add_argument("--bundle-out", type=Path, default=None, help="optional directory for CSV tables and provenance manifest")
    analysis.add_argument("--draws", type=int, default=10_000)
    analysis.add_argument("--seed", type=int, default=0)
    analysis.add_argument("--primary-contrasts", type=Path, default=None, help="JSON map of the five prespecified primary contrasts")
    analysis.add_argument("--secondary-contrasts", type=Path, default=None, help="JSON map of the separate secondary contrast family")
    analysis.add_argument("--require-prespecified-families", action="store_true", help="require exactly five primary and six secondary contrasts")
    figures = commands.add_parser("analysis-figures", help="build provenance-linked SVG figures from JSON series")
    figures.add_argument("--spec", type=Path, required=True, help="JSON figure-series specification")
    figures.add_argument("--out", type=Path, required=True, help="figure output directory")
    adjudication_export = commands.add_parser("adjudication-export", help="export method-blinded findings")
    adjudication_export.add_argument("--findings", type=Path, required=True, help="JSON list/object containing findings")
    adjudication_export.add_argument("--out", type=Path, required=True, help="blinded JSON output")
    adjudication_import = commands.add_parser("adjudication-import", help="import blinded labels into a controlled ledger")
    adjudication_import.add_argument("--blinded", type=Path, required=True, help="blinded finding export JSON")
    adjudication_import.add_argument("--labels", type=Path, required=True, help="label export JSON")
    adjudication_import.add_argument("--out", type=Path, required=True, help="controlled ledger JSON output")
    calibration_select = commands.add_parser("calibrate-select", help="select a development-only calibration setting")
    calibration_select.add_argument("--settings", type=Path, required=True)
    calibration_select.add_argument("--observations", type=Path, required=True)
    calibration_select.add_argument("--out", type=Path, required=True)
    calibration_simulate = commands.add_parser("calibrate-simulate", help="simulate hierarchical precision")
    calibration_simulate.add_argument("--config", type=Path, required=True)
    calibration_simulate.add_argument("--probabilities", type=Path, required=True)
    calibration_simulate.add_argument(
        "--replicate-candidates", type=int, nargs="+", default=None,
        help="optional prespecified R menu; selects the smallest R meeting both MCSE targets",
    )
    calibration_simulate.add_argument("--out", type=Path, required=True)
    budget = commands.add_parser("budget-estimate", help="estimate measured campaign budget components")
    budget.add_argument("--inputs", type=Path, required=True)
    budget.add_argument("--out", type=Path, required=True)
    calibration_freeze = commands.add_parser("calibrate-freeze", help="write a development-only selection freeze")
    calibration_freeze.add_argument("--selection", type=Path, required=True)
    calibration_freeze.add_argument("--hashes", type=Path, required=True)
    calibration_freeze.add_argument("--out", type=Path, required=True)
    plan = commands.add_parser("plan", help="build a deterministic campaign plan")
    plan.add_argument("--mode", choices=("development", "evaluation"), required=True)
    plan.add_argument("--instances", type=Path, required=True, help="instance JSON/JSONL")
    plan.add_argument("--methods", required=True, help="comma-separated method IDs")
    plan.add_argument("--backbones", type=Path, required=True, help="backbone JSON list")
    plan.add_argument("--replicates", type=int, required=True)
    plan.add_argument("--seed", type=int, required=True)
    plan.add_argument("--config", type=Path, default=Path("protocol/protocol.json"))
    plan.add_argument("--protocol-lock-hash", default=None)
    plan.add_argument("--model-lock-hash", default=None)
    plan.add_argument("--benchmark-manifest-hash", default=None)
    plan.add_argument("--out", type=Path, required=True, help="plan JSON artifact output")
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        if args.command == "extract-storage-symbols":
            domains = _read_json(args.domains)
            if not isinstance(domains, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in domains.items()):
                raise ValueError("domains must be a JSON object mapping contract names to domains")
            print(json.dumps(extract_storage_symbols(args.artifact_root, domains).as_dict(), sort_keys=True))
            return 0
        if args.command == "dry-run":
            report = DevelopmentDryRun().run(args.export, args.fault_export)
            payload = report.as_dict()
            if args.report is not None:
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(json.dumps(payload, sort_keys=True))
            return 0
        if args.command == "readiness":
            protocol = _read_optional_json(args.protocol)
            models = _read_optional_json(args.models)
            toolchain = _read_optional_json(args.toolchain)
            campaign_plan = _read_optional_json(args.plan)
            evidence = _read_optional_json(args.evidence)
            report = ReadinessChecker().check(
                mode=args.mode,
                protocol=protocol if isinstance(protocol, dict) else None,
                models=models if isinstance(models, dict) else None,
                toolchain=toolchain if isinstance(toolchain, dict) else None,
                campaign_plan=campaign_plan if isinstance(campaign_plan, (dict, list)) else None,
                evidence=evidence if isinstance(evidence, dict) else None,
            )
            print(json.dumps(report.as_dict(), sort_keys=True))
            return 0 if report.ready else 3
        if args.command == "evaluation-launch-check":
            protocol = _read_json(args.protocol)
            models = _read_json(args.models)
            toolchain = _read_json(args.toolchain)
            campaign_plan = _read_json(args.plan)
            evidence = _read_json(args.evidence)
            if not all(isinstance(value, dict) for value in (protocol, models, toolchain, campaign_plan, evidence)):
                raise ValueError("protocol, models, toolchain, plan and evidence must be JSON objects")
            report = ReadinessChecker().check(
                mode="evaluation",
                protocol=protocol,
                models=models,
                toolchain=toolchain,
                campaign_plan=campaign_plan,
                evidence=evidence,
            )
            decision = EvaluationLaunchGuard().check(report, campaign_plan=campaign_plan)
            payload = {"readiness": report.as_dict(), "launch": decision.as_dict()}
            if args.report_out is not None:
                _write_json(args.report_out, payload)
            print(json.dumps(payload, sort_keys=True))
            return 0 if decision.allowed else 3
        if args.command == "preflight":
            model_payload = _read_json(args.models)
            response_payload = _read_json(args.responses)
            metadata = model_payload.get("models") if isinstance(model_payload, dict) else model_payload
            if not isinstance(metadata, list) or any(not isinstance(row, dict) for row in metadata):
                raise ValueError("model metadata must be a list or an object with a models list")
            if not isinstance(response_payload, dict):
                raise ValueError("preflight responses must be an object keyed by model family")
            responses: dict[str, ProviderResponse] = {}
            for family, payload in response_payload.items():
                if not isinstance(family, str) or not isinstance(payload, dict):
                    raise ValueError("each preflight response must be an object keyed by family")
                responses[family] = ProviderResponse.from_dict(payload)
            panel = preflight_panel(metadata, responses)
            print(json.dumps(panel.as_dict(), sort_keys=True))
            return 0 if panel.ready else 3
        if args.command == "preflight-live":
            _load_env_file(args.env_file)
            if args.endpoint != OLLAMA_CLOUD_CHAT_ENDPOINT:
                raise ValueError(
                    "preflight-live is Cloud-only and requires the canonical "
                    f"endpoint {OLLAMA_CLOUD_CHAT_ENDPOINT}"
                )
            model_payload = _read_json(args.models)
            if not isinstance(model_payload, dict) or not _is_ollama_cloud_provider(model_payload.get("provider")):
                raise ValueError(
                    "preflight-live requires a model document declaring the Ollama Cloud provider"
                )
            metadata = model_payload.get("models") if isinstance(model_payload, dict) else model_payload
            if not isinstance(metadata, list) or any(not isinstance(row, dict) for row in metadata):
                raise ValueError("model metadata must be a list or an object with a models list")
            try:
                prompt = args.prompt_file.read_text(encoding="utf-8")
            except OSError as error:
                raise ValueError(f"cannot read preflight prompt: {error}") from error
            client = OllamaClient(
                args.endpoint,
                request_timeout_seconds=args.timeout_seconds,
                retry_policy=RetryPolicy(max_retries=args.max_retries),
            )
            panel, responses = run_live_preflight(metadata, prompt, client)
            ArchiveReplay(responses).save(args.responses_out)
            output = {
                "schema_version": 1,
                "panel": panel.as_dict(),
                "responses_path": str(args.responses_out),
                "response_families": sorted(responses),
            }
            if args.model_lock_out is not None:
                model_lock = build_runtime_model_lock(
                    model_payload if isinstance(model_payload, dict) else metadata,
                    metadata,
                    panel,
                    responses,
                    captured_at=datetime.now(timezone.utc).isoformat(),
                )
                _write_json(args.model_lock_out, model_lock)
                output["model_lock_path"] = str(args.model_lock_out)
                output["model_lock_status"] = model_lock["status"]
                output["model_lock_hash"] = model_lock["lock_hash"]
            print(json.dumps(output, sort_keys=True))
            return 0 if panel.ready else 3
        if args.command == "protocol-lock":
            protocol = _read_json(args.protocol)
            if not isinstance(protocol, dict):
                raise ValueError("protocol must be a JSON object")
            dependencies: dict[str, str] = {}
            for item in args.dependency_hash:
                name, separator, digest = item.partition("=")
                if not separator or not name or not digest:
                    raise ValueError("--dependency-hash must use NAME=SHA256")
                if name in dependencies:
                    raise ValueError(f"duplicate dependency hash: {name}")
                dependencies[name] = digest
            lock = build_protocol_lock(
                protocol,
                model_lock_hash=args.model_lock_hash,
                benchmark_manifest_hash=args.benchmark_manifest_hash,
                captured_at=args.captured_at or datetime.now(timezone.utc).isoformat(),
                dependency_hashes=dependencies,
            )
            _write_json(args.out, lock)
            print(json.dumps({"lock_hash": lock["lock_hash"], "path": str(args.out), "status": lock["status"]}, sort_keys=True))
            return 0
        if args.command == "analysis-build":
            rows = load_campaign_jsonl(args.raw)
            primary = _load_contrasts(args.primary_contrasts) if args.primary_contrasts is not None else {}
            secondary = _load_contrasts(args.secondary_contrasts) if args.secondary_contrasts is not None else {}
            artifact = AnalysisArtifactBuilder().build(
                rows,
                primary_contrasts=primary,
                secondary_contrasts=secondary,
                draws=args.draws,
                seed=args.seed,
                require_prespecified_families=args.require_prespecified_families,
            )
            artifact.write_json(args.out)
            output = artifact.as_dict()
            if args.bundle_out is not None:
                output["bundle_manifest"] = str(artifact.write_bundle(args.bundle_out))
            print(json.dumps(output, sort_keys=True))
            return 0
        if args.command == "analysis-figures":
            spec = _read_json(args.spec)
            if not isinstance(spec, dict):
                raise ValueError("figure specification must be a JSON object")
            paired = spec.get("paired_lineage")
            recall = spec.get("recall_at_n")
            curves = spec.get("time_curves")
            scaling = spec.get("scaling")
            failures = spec.get("failure_flow")
            if paired is not None and (not isinstance(paired, dict) or any(not isinstance(key, str) for key in paired)):
                raise ValueError("paired_lineage must be an object")
            if recall is not None and (not isinstance(recall, dict) or any(not isinstance(value, dict) for value in recall.values())):
                raise ValueError("recall_at_n must be an object of method series")
            if curves is not None and (not isinstance(curves, dict) or any(not isinstance(value, list) for value in curves.values())):
                raise ValueError("time_curves must be an object of point arrays")
            if scaling is not None and (not isinstance(scaling, dict) or any(not isinstance(value, dict) for value in scaling.values())):
                raise ValueError("scaling must be an object of method series")
            if failures is not None and (not isinstance(failures, dict) or any(not isinstance(key, str) for key in failures)):
                raise ValueError("failure_flow must be an object")
            figure_specs = AnalysisFigureBuilder().build(
                paired_lineage=paired,
                recall_at_n={method: {int(n): value for n, value in series.items()} for method, series in recall.items()} if isinstance(recall, dict) else None,
                time_curves={method: [(point[0], point[1]) for point in points] for method, points in curves.items()} if isinstance(curves, dict) else None,
                scaling={method: {int(size): value for size, value in series.items()} for method, series in scaling.items()} if isinstance(scaling, dict) else None,
                failure_flow=failures,
            )
            manifest = write_figure_bundle(figure_specs, args.out)
            print(json.dumps({
                "schema_version": 1,
                "manifest": str(manifest),
                "figures": [figure.as_dict() for figure in figure_specs],
            }, sort_keys=True))
            return 0
        if args.command == "adjudication-export":
            raw = _read_json(args.findings)
            rows = raw.get("findings") if isinstance(raw, dict) else raw
            if not isinstance(rows, list):
                raise ValueError("findings input must be a JSON list or object with a findings list")
            allowed = {"finding_id", "instance_id", "claim", "evidence_hash", "raw_claim_hash", "root_cause_id"}
            findings: list[BlindedFinding] = []
            for index, row in enumerate(rows, 1):
                if not isinstance(row, dict):
                    raise ValueError(f"finding {index} must be an object")
                unknown = sorted(set(row) - allowed)
                if unknown:
                    raise ValueError(f"finding {index} contains non-blinded fields: {', '.join(unknown)}")
                findings.append(BlindedFinding(
                    finding_id=row.get("finding_id"),
                    instance_id=row.get("instance_id"),
                    claim=row.get("claim"),
                    evidence_hash=row.get("evidence_hash"),
                    raw_claim_hash=row.get("raw_claim_hash"),
                    root_cause_id=row.get("root_cause_id"),
                ))
            ledger = AdjudicationLedger(findings)
            ledger.write_blinded(args.out)
            print(json.dumps(ledger.export_blinded(), sort_keys=True))
            return 0
        if args.command == "adjudication-import":
            blinded = _read_json(args.blinded)
            labels = _read_json(args.labels)
            if not isinstance(blinded, dict) or not isinstance(labels, dict):
                raise ValueError("blinded and labels inputs must be JSON objects")
            ledger = AdjudicationLedger.from_blinded(blinded)
            ledger.import_labels(labels)
            ledger.write_json(args.out)
            print(json.dumps(ledger.as_dict(), sort_keys=True))
            return 0
        if args.command == "calibrate-select":
            decision = select_development_setting(
                list(load_settings(args.settings)),
                list(load_observations(args.observations)),
            )
            _write_json(args.out, decision.as_dict())
            print(json.dumps(decision.as_dict(), sort_keys=True))
            return 0
        if args.command == "calibrate-simulate":
            config_raw = _read_json(args.config)
            probabilities_raw = _read_json(args.probabilities)
            if not isinstance(config_raw, dict) or not isinstance(probabilities_raw, dict):
                raise ValueError("simulation config and probabilities must be JSON objects")
            config = PrecisionSimulationConfig(**config_raw)
            probabilities = {
                str(lineage): tuple(values)
                for lineage, values in probabilities_raw.items()
                if isinstance(lineage, str) and isinstance(values, list)
            }
            if len(probabilities) != len(probabilities_raw):
                raise ValueError("probabilities must map lineage IDs to four-element arrays")
            result = (
                select_common_replicates(
                    config,
                    joint_probabilities=probabilities,
                    candidates=tuple(args.replicate_candidates),
                )
                if args.replicate_candidates is not None
                else simulate_hierarchical_precision(config, joint_probabilities=probabilities)
            )
            payload = result.as_dict()
            _write_json(args.out, payload)
            print(json.dumps(payload, sort_keys=True))
            return 0
        if args.command == "budget-estimate":
            result = estimate_budget(load_budget_inputs(args.inputs))
            _write_json(args.out, result.as_dict())
            print(json.dumps(result.as_dict(), sort_keys=True))
            return 0
        if args.command == "calibrate-freeze":
            freeze = freeze_development_selection(
                load_selection_decision(args.selection),
                hashes=load_hashes(args.hashes),
            )
            freeze.write_json(args.out)
            print(json.dumps(freeze.as_dict(), sort_keys=True))
            return 0
        if args.command == "plan":
            instances = _rows_from_input(_read_optional_json(args.instances), "instances")
            backbones = _rows_from_input(_read_optional_json(args.backbones), "backbones")
            methods = [method.strip() for method in args.methods.split(",") if method.strip()]
            config = _read_json(args.config)
            if not isinstance(config, dict):
                raise ValueError("config must be a JSON object")
            campaign_plan = CampaignPlanner().build(
                mode=args.mode,
                instances=[{"instance_id": str(row.get("instance_id", "")), "lineage_id": str(row.get("lineage_id", ""))} for row in instances],
                methods=methods,
                backbones=[{"backbone": row.get("backbone"), "model_tag": row.get("model_tag")} for row in backbones],
                replicates=args.replicates,
                seed=args.seed,
                config=config,
                protocol_lock_hash=args.protocol_lock_hash,
                model_lock_hash=args.model_lock_hash,
                benchmark_manifest_hash=args.benchmark_manifest_hash,
            )
            campaign_plan.write_json(args.out)
            print(json.dumps(campaign_plan.as_dict(), sort_keys=True))
            return 0
        symbols = _load_symbols(args.symbols)
        proposal = _read_json(args.proposal)
        result = XLIRCompiler.from_symbols(symbols, args.maximum_ast_nodes).compile(proposal)
    except ValueError as error:
        parser.error(str(error))
    if args.command == "xlir-smt-check":
        output = {
            "ok": result.ok,
            "abstained": result.abstained,
            "invariant": result.invariant.as_dict() if result.invariant else None,
            "diagnostics": [item.as_dict() for item in result.diagnostics],
            "query": args.query,
            "solver_result": None,
        }
        if result.invariant is not None and not result.diagnostics:
            backend = Z3XLIRBackend()
            checked = (
                backend.check_antecedent(
                    result.invariant,
                    control=SMTControl(args.timeout_seconds),
                    trace_length=args.trace_length,
                )
                if args.query == "antecedent"
                else backend.check_violation(
                    result.invariant,
                    control=SMTControl(args.timeout_seconds),
                    trace_length=args.trace_length,
                )
            )
            output["solver_result"] = checked.as_dict()
            print(json.dumps(output, sort_keys=True))
            return 0 if checked.status in {SearchStatus.SAT, SearchStatus.BOUNDED_UNSAT} else 3
        print(json.dumps(output, sort_keys=True))
        return 0 if result.abstained else 2
    output = {
        "ok": result.ok,
        "abstained": result.abstained,
        "invariant": result.invariant.as_dict() if result.invariant else None,
        "diagnostics": [item.as_dict() for item in result.diagnostics],
    }
    print(json.dumps(output, sort_keys=True))
    return 0 if result.ok or result.abstained else 2


def _is_ollama_cloud_provider(provider: object) -> bool:
    required = {
        "name": "ollama_cloud",
        "base_url": "https://ollama.com",
        "chat_endpoint": OLLAMA_CLOUD_CHAT_ENDPOINT,
        "auth_env": "OLLAMA_API_KEY",
        "execution_mode": "remote_cloud_api",
        "local_weights": False,
    }
    return isinstance(provider, dict) and all(provider.get(key) == value for key, value in required.items())


if __name__ == "__main__":
    raise SystemExit(main())
