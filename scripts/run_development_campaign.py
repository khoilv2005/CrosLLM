"""Run a bounded development proposal campaign through Ollama Cloud.

The command consumes the bundle produced by ``prepare_development_campaign``.
It is intentionally proposal-collection only: native EVM replay, gold labels
and evaluation admission are separate stages.  Without ``--execute`` it only
validates the bundle and preflight archive, so inspecting a command cannot
spend provider quota.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from crossllm.artifacts import ArtifactSymbol
from crossllm.contracts.canonical import canonical_json, sha256_hex
from crossllm.contracts import CampaignStatus
from crossllm.methods import MethodRunner, MethodTrack, PromptPolicy, PromptTemplate
from crossllm.providers import (
    OllamaClient,
    OLLAMA_CLOUD_CHAT_ENDPOINT,
    ProviderRequest,
    ProviderResponse,
    RetryPolicy,
    TokenBudget,
)
from crossllm.runtime import (
    AppendOnlyEventStore,
    CampaignStateMachine,
    PersistentEventStore,
    ResourceEnvelope,
    ResourceRequest,
    ResourceUsage,
    WorkerExecution,
    WorkerResourceScheduler,
    WorkerRunner,
    WorkerTask,
)
from crossllm.runtime.events import AttemptState, InterruptionKind
from crossllm.xlir import XLIRCompiler


ROOT = Path(__file__).resolve().parents[1]
PROMPT_FILES = {
    "X": "prompts/crossllm_proposer_v1.txt",
    "P": "prompts/direct_audit_v1.txt",
    "T0": "prompts/t0_proposer_v1.txt",
}
_SUPPORTED_TYPES = {"bool", "uint256", "int256", "address", "bytes32"}


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
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


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as error:
        raise ValueError(f"cannot read JSONL {path}: {error}") from error
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid JSONL at {path}:{number}: {error}") from error
        if not isinstance(row, dict):
            raise ValueError(f"JSONL row at {path}:{number} must be an object")
        rows.append(row)
    return rows


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    try:
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_jsonl(path: Path, rows: list[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text("".join(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n" for row in rows), encoding="utf-8", newline="\n")
    try:
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _recover_inflight_attempts(store: PersistentEventStore) -> int:
    """Mark unfinished attempts uncertain before WorkerRunner resumes them."""
    identities = sorted({
        (event.campaign_id, event.attempt_id)
        for event in store.events
    })
    recovered = 0
    for campaign_id, attempt_id in identities:
        selected = [
            event for event in store.events
            if event.campaign_id == campaign_id and event.attempt_id == attempt_id
        ]
        if not selected or any(event.terminal for event in selected):
            continue
        machine = CampaignStateMachine.restore(campaign_id, attempt_id, store)
        if machine.state is AttemptState.RUNNING:
            machine.mark_uncertain(
                "controller_restart_recovered_inflight_attempt",
                InterruptionKind.WORKER_RESTART,
            )
            recovered += 1
    return recovered


def _load_dotenv(path: Path) -> None:
    """Load only simple KEY=VALUE lines; never print or archive the value."""
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as error:
        raise ValueError(f"cannot read env file {path}: {error}") from error
    for line_number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.strip() or key.strip().lower() in {"path", "prompt", "password"}:
            if not separator:
                raise ValueError(f"invalid env line {line_number}")
            continue
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _verify_hash(path: Path, expected: object, label: str) -> None:
    if not isinstance(expected, str) or _sha256_file(path) != expected:
        raise ValueError(f"{label} hash mismatch")


def validate_bundle(bundle_dir: Path) -> dict[str, Any]:
    """Validate all immutable inputs needed by the proposal runner."""
    bundle_dir = Path(bundle_dir).resolve()
    manifest_path = bundle_dir / "manifest.json"
    manifest = _load_json(manifest_path)
    if not isinstance(manifest, dict):
        raise ValueError("bundle manifest must be an object")
    declared_manifest_hash = manifest.get("manifest_sha256")
    body = dict(manifest)
    body.pop("manifest_sha256", None)
    if declared_manifest_hash != sha256_hex(body):
        raise ValueError("bundle manifest hash mismatch")
    if (
        manifest.get("status") != "development_execution_input"
        or manifest.get("mode") != "development"
        or manifest.get("split") != "development"
        or manifest.get("admission_eligible") is not False
        or manifest.get("sealed_data_read") is not False
        or manifest.get("evaluation_lock") is not False
    ):
        raise ValueError("bundle is not a non-admission development input")
    generated = manifest.get("generated_files")
    if not isinstance(generated, dict):
        raise ValueError("bundle generated_files are missing")
    for name in ("instances.jsonl", "backbones.json", "config.json", "campaigns.plan.json", "campaigns.plan.jsonl"):
        path = bundle_dir / name
        if not path.is_file():
            raise ValueError(f"bundle file is missing: {name}")
        _verify_hash(path, generated.get(name), name)
    pack_hashes = generated.get("artifact_packs")
    if not isinstance(pack_hashes, dict):
        raise ValueError("bundle artifact pack hashes are missing")
    for lineage, expected in pack_hashes.items():
        _verify_hash(bundle_dir / "artifact_packs" / f"{lineage}.json", expected, f"{lineage} artifact pack")

    config = _load_json(bundle_dir / "config.json")
    plan = _load_json(bundle_dir / "campaigns.plan.json")
    instances = _read_jsonl(bundle_dir / "instances.jsonl")
    if not isinstance(config, dict) or not isinstance(plan, dict):
        raise ValueError("bundle config and plan must be objects")
    if config.get("sealed_data_read") is not False or config.get("benchmark_manifest_hash") is not None:
        raise ValueError("bundle config contains evaluation input")
    if plan.get("mode") != "development" or plan.get("benchmark_manifest_hash") is not None:
        raise ValueError("campaign plan is not development-only")
    if not instances or any(row.get("split") != "development" or row.get("source_backed") is not True for row in instances):
        raise ValueError("all bundle instances must be source-backed development rows")
    campaign_rows = plan.get("campaigns")
    if not isinstance(campaign_rows, list) or len(campaign_rows) != manifest.get("campaign_count"):
        raise ValueError("campaign plan count mismatch")
    instance_ids = {row.get("instance_id") for row in instances}
    if any(row.get("instance_id") not in instance_ids for row in campaign_rows):
        raise ValueError("campaign plan references an unknown instance")
    if len({row.get("campaign_id") for row in campaign_rows}) != len(campaign_rows):
        raise ValueError("campaign plan contains duplicate campaign IDs")
    return {"manifest": manifest, "config": config, "plan": plan, "instances": instances}


def validate_run_report(bundle_dir: Path, run_dir: Path) -> list[str]:
    """Validate a completed development run without contacting the provider."""
    run_dir = Path(run_dir).resolve()
    report_path = run_dir / "report.json"
    try:
        report = _load_json(report_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [f"run report unreadable: {error}"]
    if not isinstance(report, dict):
        return ["run report must be an object"]

    errors: list[str] = []
    unsigned = dict(report)
    supplied_hash = unsigned.pop("report_hash", None)
    if supplied_hash != sha256_hex(unsigned):
        errors.append("run report hash mismatch")
    for key, expected in {
        "schema_version": 1,
        "record_type": "development_cloud_proposal_campaign",
        "scope": "source_backed_development_proposal_collection_only",
        "mode": "development",
        "admission_eligible": False,
        "sealed_data_read": False,
    }.items():
        if report.get(key) != expected:
            errors.append(f"{key} mismatch")
    if not isinstance(report.get("preflight"), dict) or report["preflight"].get("status") != "transport_and_model_match":
        errors.append("preflight status is not transport_and_model_match")

    try:
        inputs = validate_bundle(bundle_dir)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        errors.append(f"bundle validation failed: {error}")
        inputs = None
    if inputs is not None:
        manifest = inputs["manifest"]
        for key, expected in {
            "bundle_manifest_sha256": manifest.get("manifest_sha256"),
            "plan_id": manifest.get("plan_id"),
            "plan_hash": manifest.get("plan_hash"),
        }.items():
            if report.get(key) != expected:
                errors.append(f"{key} mismatch")

    expected_paths = {
        "events_path": run_dir / "events.jsonl",
        "runs_path": run_dir / "runs.jsonl",
    }
    loaded_events: AppendOnlyEventStore | None = None
    run_rows: list[dict[str, Any]] = []
    for field, expected_path in expected_paths.items():
        value = report.get(field)
        try:
            actual_path = Path(value).resolve()
        except (TypeError, ValueError):
            errors.append(f"{field} is not a valid path")
            continue
        if actual_path != expected_path.resolve():
            errors.append(f"{field} points outside the run directory")
        if not expected_path.is_file():
            errors.append(f"run file is missing: {expected_path.name}")
            continue
        hash_field = "events_sha256" if field == "events_path" else "runs_sha256"
        expected_hash = report.get(hash_field)
        if expected_hash != _sha256_file(expected_path):
            errors.append(f"{hash_field} mismatch")
        try:
            if field == "events_path":
                loaded_events = AppendOnlyEventStore.load_jsonl(expected_path)
            else:
                run_rows = _read_jsonl(expected_path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            errors.append(f"{field} is invalid: {error}")

    if loaded_events is not None:
        terminal_events = {
            (event.campaign_id, event.attempt_id): event
            for event in loaded_events.events
            if event.event_type == "campaign_terminal" and event.terminal
        }
    else:
        terminal_events = {}
    campaign_ids: set[str] = set()
    status_counts: dict[str, int] = {}
    provider_calls = 0
    for row in run_rows:
        for field in ("campaign_id", "attempt_id", "status", "terminal"):
            if field not in row:
                errors.append(f"run row missing {field}")
        campaign_id = row.get("campaign_id")
        attempt_id = row.get("attempt_id")
        if not isinstance(campaign_id, str) or not isinstance(attempt_id, str):
            continue
        if campaign_id in campaign_ids:
            errors.append(f"duplicate run campaign_id: {campaign_id}")
        campaign_ids.add(campaign_id)
        status = row.get("status")
        if isinstance(status, str):
            status_counts[status] = status_counts.get(status, 0) + 1
            try:
                CampaignStatus(status)
            except ValueError:
                errors.append(f"unknown run status: {status}")
        if row.get("terminal") is not True:
            errors.append(f"run is not terminal: {campaign_id}")
        terminal = terminal_events.get((campaign_id, attempt_id))
        if terminal is None:
            errors.append(f"missing terminal event: {campaign_id}/{attempt_id}")
        elif isinstance(status, str) and terminal.payload.get("status") != status:
            errors.append(f"terminal status mismatch: {campaign_id}")
        result = row.get("result")
        if isinstance(result, dict):
            method_run = result.get("method_run")
            if isinstance(method_run, dict):
                responses = method_run.get("provider_responses")
                if isinstance(responses, list):
                    provider_calls += len(responses)
                else:
                    errors.append(f"method_run provider_responses missing: {campaign_id}")

    if report.get("selected_campaign_count") != len(run_rows):
        errors.append("selected_campaign_count mismatch")
    expected_counts = {
        "provider_call_count": provider_calls,
        "completed_count": status_counts.get(CampaignStatus.COMPLETED.value, 0),
        "provider_failure_count": status_counts.get(CampaignStatus.PROVIDER_FAILURE.value, 0),
        "no_valid_proposal_count": status_counts.get(CampaignStatus.NO_VALID_PROPOSAL.value, 0),
    }
    for key, expected in expected_counts.items():
        if report.get(key) != expected:
            errors.append(f"{key} mismatch")
    return errors


def _load_preflight_archive(
    root: Path,
    config: dict[str, Any],
    preflight_path: Path,
) -> dict[str, Any]:
    """Require prior four-family transport/model-match evidence.

    Ollama Cloud does not expose an immutable served-weight digest through this
    endpoint, so this gate checks the authenticated archive's request/response
    model binding only.  It intentionally does not promote the result to an
    evaluation model lock.
    """
    raw_archive = _load_json(preflight_path)
    if not isinstance(raw_archive, dict):
        raise ValueError("preflight archive must be an object")
    responses_by_key: dict[str, ProviderResponse] = {}
    for key, value in raw_archive.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            raise ValueError("preflight archive entries must be objects keyed by family or request hash")
        responses_by_key[key] = ProviderResponse.from_dict(value)
    models = config.get("models")
    expected_families = {"GLM", "DeepSeek", "Qwen", "gpt-oss"}
    if not isinstance(models, dict) or not models or not set(models).issubset(expected_families):
        raise ValueError("development run requires a non-empty subset of the four model families")
    prompt_path = root / "protocol" / "preflight_prompt.txt"
    prompt = prompt_path.read_text(encoding="utf-8")
    matched: dict[str, dict[str, Any]] = {}
    for family, details in models.items():
        if not isinstance(details, dict) or not isinstance(details.get("model_tag"), str):
            raise ValueError(f"{family}: model tag is missing")
        settings = details.get("settings")
        if not isinstance(settings, dict):
            raise ValueError(f"{family}: model settings are missing")
        request = ProviderRequest(details["model_tag"], prompt, dict(settings))
        response = responses_by_key.get(family) or responses_by_key.get(request.request_hash)
        if response is None:
            raise ValueError(f"{family}: preflight archive has no response for the configured request")
        if response.request_hash != request.request_hash:
            raise ValueError(f"{family}: preflight archive request hash does not match the configured request")
        if response.error is not None or response.partial or response.response_model != details["model_tag"]:
            raise ValueError(f"{family}: preflight archive does not match the configured Cloud model tag")
        matched[family] = {
            "request_hash": request.request_hash,
            "response_hash": response.response_hash,
            "response_model": response.response_model,
        }
    return {
        "status": "transport_and_model_match",
        "archive_sha256": _sha256_file(preflight_path),
        "families": matched,
        "limitations": [
            "served-weight digest unavailable from Ollama Cloud preflight",
            "effective API settings unavailable from Ollama Cloud preflight",
        ],
    }


def _compiler_for_pack(pack: dict[str, Any]) -> XLIRCompiler:
    public_files = pack.get("public_files")
    symbols_doc = public_files.get("symbols.json") if isinstance(public_files, dict) else None
    extracted_doc = public_files.get("storage_symbols.json") if isinstance(public_files, dict) else None
    rows = extracted_doc.get("symbols") if isinstance(extracted_doc, dict) else None
    if not isinstance(rows, list):
        raise ValueError(f"{pack.get('lineage_id')}: stable symbols are missing")
    symbols: list[ArtifactSymbol] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("type") not in _SUPPORTED_TYPES:
            continue
        # The public storage-symbol projection uses ``path`` (the canonical
        # ArtifactSymbol field is also named ``path``). Accept the older
        # source_path spelling as a compatibility fallback for hand-built
        # packs, but do not silently discard valid symbols.
        values = (row.get("symbol_id"), row.get("path") or row.get("source_path"), row.get("name"), row.get("domain"), row.get("kind"), row.get("type"))
        if not all(isinstance(value, str) and value for value in values):
            continue
        symbols.append(ArtifactSymbol(*values))
    # A source-backed pack can be executable while still exposing no lossless
    # primitive storage symbols (for example, a mapping-valued ABI surface).
    # Keep the compiler empty in that case so provider responses are captured
    # and classified as grounding failures instead of dropping the campaign
    # before its eight ordered slots are consumed.
    return XLIRCompiler.from_symbols(symbols)


def _prompt_template(root: Path, track: str, prompt_hashes: dict[str, Any]) -> PromptTemplate:
    path = root / PROMPT_FILES[track]
    expected = prompt_hashes.get(track)
    _verify_hash(path, expected, f"{track} prompt")
    text = path.read_text(encoding="utf-8")
    return PromptTemplate(
        f"development-{track.lower()}-public-v1",
        "v1",
        text,
        PromptPolicy(proposal_slots=8),
    )


def _usage(method_run: Any) -> ResourceUsage:
    responses = method_run.provider_responses
    elapsed = sum(float(response.elapsed_seconds or 0.0) for response in responses)
    input_tokens = [response.usage.get("prompt_tokens") for response in responses]
    generated_tokens = [response.usage.get("generated_tokens") for response in responses]
    missing: dict[str, str] = {}
    if any(value is None for value in input_tokens):
        missing["input_tokens"] = "provider_usage_unavailable"
    if any(value is None for value in generated_tokens):
        missing["generated_tokens"] = "provider_usage_unavailable"
    return ResourceUsage(
        cpu_core_seconds=elapsed,
        wall_seconds=elapsed,
        input_tokens=sum(value for value in input_tokens if isinstance(value, int)) if not missing.get("input_tokens") else None,
        generated_tokens=sum(value for value in generated_tokens if isinstance(value, int)) if not missing.get("generated_tokens") else None,
        missing_field_reasons=missing,
    )


def run_campaign(
    *,
    root: Path,
    bundle_dir: Path,
    preflight_path: Path,
    out_dir: Path,
    max_campaigns: int | None = None,
    endpoint: str = OLLAMA_CLOUD_CHAT_ENDPOINT,
    env_file: Path | None = None,
    timeout_seconds: float = 180.0,
    max_retries: int = 2,
) -> dict[str, Any]:
    if endpoint != OLLAMA_CLOUD_CHAT_ENDPOINT:
        raise ValueError(f"development campaign is Cloud-only and requires {OLLAMA_CLOUD_CHAT_ENDPOINT}")
    inputs = validate_bundle(bundle_dir)
    preflight = _load_preflight_archive(root, inputs["config"], preflight_path)
    plan_rows = inputs["plan"]["campaigns"]
    if max_campaigns is not None and (max_campaigns <= 0 or max_campaigns > len(plan_rows)):
        raise ValueError("max_campaigns must be between 1 and the plan campaign count")
    selected = plan_rows[:max_campaigns] if max_campaigns is not None else plan_rows
    out_dir = Path(out_dir).resolve()
    events_path = out_dir / "events.jsonl"
    if out_dir.exists() and any(out_dir.iterdir()) and not events_path.is_file():
        raise ValueError(f"refusing to overwrite non-empty run directory: {out_dir}")
    if env_file is not None:
        _load_dotenv(env_file)
    client = OllamaClient(
        endpoint,
        request_timeout_seconds=timeout_seconds,
        retry_policy=RetryPolicy(max_retries=max_retries),
    )
    config = inputs["config"]
    model_config = config["models"]
    packs: dict[str, dict[str, Any]] = {}
    for lineage in {row["lineage_id"] for row in selected}:
        pack_path = bundle_dir / "artifact_packs" / f"{lineage}.json"
        pack = _load_json(pack_path)
        if not isinstance(pack, dict) or pack.get("admission_eligible") is not False:
            raise ValueError(f"{lineage}: invalid non-admission artifact pack")
        packs[lineage] = pack
    prompt_hashes = config.get("prompt_hashes")
    if not isinstance(prompt_hashes, dict):
        raise ValueError("prompt hashes are missing")
    templates = {track: _prompt_template(root, track, prompt_hashes) for track in config["methods"]}
    token_budgets = config.get("budgets")
    if not isinstance(token_budgets, dict):
        raise ValueError("protocol budgets are missing")
    token_budget = TokenBudget(
        int(token_budgets.get("input_native_token_cap", 32768)),
        int(token_budgets.get("generated_native_token_cap", 8192)),
    )

    store = PersistentEventStore(events_path)
    recovered_attempts = _recover_inflight_attempts(store)
    envelope = ResourceEnvelope(
        cpu_cores=4,
        memory_bytes=16 * 1024**3,
        max_concurrent_campaigns=1,
        max_solver_processes_per_profile=1,
    )
    scheduler = WorkerResourceScheduler(envelope)
    runner = WorkerRunner(scheduler, event_store=store, worker_id="development-cloud-controller")
    instance_by_id = {row["instance_id"]: row for row in inputs["instances"]}
    tasks: list[WorkerTask] = []
    for campaign in selected:
        instance = instance_by_id[campaign["instance_id"]]
        lineage = campaign["lineage_id"]
        pack = packs[lineage]
        artifact_text = canonical_json(pack).decode("ascii")
        artifact_hash = pack_hash = sha256_hex(pack)
        track = MethodTrack(campaign["method"])
        family = campaign["backbone"]
        details = model_config.get(family)
        if not isinstance(details, dict):
            raise ValueError(f"{family}: model configuration is missing")
        model_tag = details.get("model_tag")
        settings = details.get("settings")
        if not isinstance(model_tag, str) or not isinstance(settings, dict):
            raise ValueError(f"{family}: model tag/settings are invalid")

        def execute(
            campaign: dict[str, Any] = campaign,
            instance: dict[str, Any] = instance,
            pack: dict[str, Any] = pack,
            artifact_text: str = artifact_text,
            artifact_hash: str = artifact_hash,
            track: MethodTrack = track,
            family: str = family,
            model_tag: str = model_tag,
            settings: dict[str, Any] = dict(settings),
        ) -> WorkerExecution:
            compiler = _compiler_for_pack(pack)

            def parse_candidate(text: str) -> object | None:
                raw = json.loads(text)
                if isinstance(raw, dict) and raw.get("abstain") is True:
                    return None
                result = compiler.compile(raw)
                return result.invariant if result.ok else None

            method_run = MethodRunner(
                client,
                proposal_slots=int(config.get("proposal_slots") or 8),
                token_budget=token_budget,
            ).run(
                track=track,
                backbone=family,
                model=model_tag,
                attempt_id=f"{campaign['campaign_id']}:attempt:1",
                template=templates[track.value],
                artifact_pack_text=artifact_text,
                artifact_pack_hash=artifact_hash,
                settings=settings,
                parse_candidate=parse_candidate,
                expected_response_model=model_tag,
                campaign_deadline_seconds=float(token_budgets.get("campaign_wall_seconds", 3600)),
            )
            from crossllm.runtime.method_events import append_method_run_events
            append_method_run_events(
                store,
                method_run,
                campaign_id=campaign["campaign_id"],
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            failures = [response for response in method_run.provider_responses if response.error is not None]
            candidate_count = sum(slot.status.value == "candidate" for slot in method_run.slots)
            if failures:
                status = CampaignStatus.PROVIDER_FAILURE
            elif candidate_count == 0:
                status = CampaignStatus.NO_VALID_PROPOSAL
            else:
                status = CampaignStatus.COMPLETED
            return WorkerExecution(
                status=status,
                result={
                    "stage": "proposal_collection_only",
                    "admission_eligible": False,
                    "campaign": campaign,
                    "instance": instance,
                    "method_run": method_run.as_dict(),
                    "limitations": [
                        "native EVM search/replay is not executed by this command",
                        "proposal validity is not a security-legitimacy judgment",
                    ],
                },
                usage=_usage(method_run),
                payload={
                    "stage": "proposal_collection_only",
                    "lineage_id": instance["lineage_id"],
                    "method": campaign["method"],
                    "backbone": campaign["backbone"],
                    "artifact_pack_hash": pack_hash,
                    "preflight_status": preflight["status"],
                },
            )

        tasks.append(WorkerTask(
            campaign_id=campaign["campaign_id"],
            attempt_id=f"{campaign['campaign_id']}:attempt:1",
            request=ResourceRequest(
                campaign_id=campaign["campaign_id"],
                cpu_cores=4,
                memory_bytes=16 * 1024**3,
                estimated_core_seconds=float(token_budgets.get("campaign_wall_seconds", 3600)),
            ),
            execute=execute,
            max_resumes=1,
        ))
    batch = runner.run(tasks)
    runs_path = out_dir / "runs.jsonl"
    _write_jsonl(runs_path, [run.as_dict() for run in batch.runs])
    report = {
        "schema_version": 1,
        "record_type": "development_cloud_proposal_campaign",
        "scope": "source_backed_development_proposal_collection_only",
        "mode": "development",
        "admission_eligible": False,
        "sealed_data_read": False,
        "execution_boundary": "local_controller_to_ollama_cloud; Docker isolation is not asserted by this command",
        "bundle_manifest_sha256": inputs["manifest"]["manifest_sha256"],
        "plan_id": inputs["manifest"]["plan_id"],
        "plan_hash": inputs["manifest"]["plan_hash"],
        "preflight": preflight,
        "recovered_inflight_attempts": recovered_attempts,
        "selected_campaign_count": len(selected),
        "provider_call_count": sum(len(run.result.get("method_run", {}).get("provider_responses", [])) for run in batch.runs if isinstance(run.result, dict)),
        "completed_count": sum(run.status is CampaignStatus.COMPLETED for run in batch.runs),
        "provider_failure_count": sum(run.status is CampaignStatus.PROVIDER_FAILURE for run in batch.runs),
        "no_valid_proposal_count": sum(run.status is CampaignStatus.NO_VALID_PROPOSAL for run in batch.runs),
        "events_path": str(events_path),
        "events_sha256": _sha256_file(events_path),
        "runs_path": str(runs_path),
        "runs_sha256": _sha256_file(runs_path),
        "limitations": [
            "this command executes proposal collection only; no native EVM search/replay or gold adjudication",
            "Ollama Cloud served-weight identity and effective settings remain unavailable",
            "the local controller does not prove Docker firewall enforcement",
        ],
    }
    report["report_hash"] = sha256_hex(report)
    _write_json(out_dir / "report.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--preflight-responses", type=Path, required=False)
    parser.add_argument("--out-dir", type=Path, required=False)
    parser.add_argument("--check-run-dir", type=Path, default=None, help="validate an existing run without provider calls")
    parser.add_argument("--execute", action="store_true", help="make Ollama Cloud calls; without this only validate inputs")
    parser.add_argument("--max-campaigns", type=int, default=1, help="bounded prefix; pass the full count explicitly for a larger run")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--endpoint", default=OLLAMA_CLOUD_CHAT_ENDPOINT)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--max-retries", type=int, default=2)
    args = parser.parse_args(argv)
    try:
        inputs = validate_bundle(args.bundle_dir)
        if args.check_run_dir is not None:
            errors = validate_run_report(args.bundle_dir, args.check_run_dir)
            if errors:
                print("FAILED")
                print("\n".join(errors))
                return 1
            print("OK: development Cloud run report is valid and non-admission")
            return 0
        if args.preflight_responses is None:
            raise ValueError("--preflight-responses is required unless --check-run-dir is used")
        if args.out_dir is None:
            raise ValueError("--out-dir is required unless --check-run-dir is used")
        preflight = _load_preflight_archive(args.root.resolve(), inputs["config"], args.preflight_responses.resolve())
        if not args.execute:
            print(json.dumps({
                "status": "validated_not_executed",
                "campaign_count": inputs["manifest"]["campaign_count"],
                "preflight_status": preflight["status"],
                "quota_calls": 0,
            }, sort_keys=True))
            return 0
        report = run_campaign(
            root=args.root,
            bundle_dir=args.bundle_dir,
            preflight_path=args.preflight_responses,
            out_dir=args.out_dir,
            max_campaigns=args.max_campaigns,
            endpoint=args.endpoint,
            env_file=args.env_file,
            timeout_seconds=args.timeout_seconds,
            max_retries=args.max_retries,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"[FAIL] {error}")
        return 1
    print(json.dumps({
        "status": "executed_development_proposal_collection",
        "selected_campaign_count": report["selected_campaign_count"],
        "provider_call_count": report["provider_call_count"],
        "report": str((Path(args.out_dir) / "report.json").resolve()),
        "admission_eligible": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
