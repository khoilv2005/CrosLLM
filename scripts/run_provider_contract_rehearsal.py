#!/usr/bin/env python3
"""Run a deterministic, synthetic rehearsal of the M06 provider contract.

The rehearsal exercises the provider, preflight, budget, tokenizer, prompt,
and X/P/T0 slot boundaries against an in-process fake sender.  It never calls
Ollama Cloud and therefore cannot establish model identity, quota, or measured
research outcomes.  The report stores only assertion results and hashes; raw
fixture prompts/responses stay in memory.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crossllm.contracts.canonical import sha256_bytes, sha256_hex
from crossllm.methods import MethodRunner, MethodTrack, PromptTemplate
from crossllm.providers import (
    ArchiveReplay,
    ExactTokenCounter,
    FakeProviderServer,
    OllamaClient,
    ProviderRequest,
    RetryPolicy,
    TokenBudget,
    TokenizationError,
    TransportResponse,
    preflight_panel,
    run_live_preflight,
    validate_measurement,
    validate_usage,
    TokenizerIdentity,
)


DEFAULT_OUTPUT = ROOT / "dataset" / "reports" / "m06_provider_contract_rehearsal.json"
CASE_IDS = (
    "success_raw_capture",
    "malformed_missing_partial",
    "retry_429_5xx_timeout",
    "cancellation_and_deadline",
    "archive_hash_round_trip",
    "ordered_slot_statuses",
    "budget_and_tokenizer_boundaries",
    "four_family_preflight_boundary",
    "x_p_t0_shared_call_boundary",
)


def _response(body: bytes, status: int = 200) -> TransportResponse:
    return TransportResponse(status, {"Content-Type": "application/json"}, body)


def _json_response(payload: object, status: int = 200) -> TransportResponse:
    return _response(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"), status)


def _client(
    responses: list[TransportResponse | Exception],
    *,
    retries: int = 0,
    sleeps: list[float] | None = None,
) -> tuple[OllamaClient, FakeProviderServer]:
    server = FakeProviderServer(responses)
    client = OllamaClient(
        sender=server.send,
        retry_policy=RetryPolicy(
            max_retries=retries,
            backoff_seconds=(2.0, 10.0),
        ),
        sleeper=(sleeps.append if sleeps is not None else (lambda _seconds: None)),
    )
    return client, server


def _case(case_id: str, assertions: dict[str, bool], evidence: object) -> dict[str, object]:
    return {
        "case_id": case_id,
        "passed": all(assertions.values()),
        "assertions": assertions,
        "evidence_sha256": sha256_hex(evidence),
    }


def _request() -> ProviderRequest:
    return ProviderRequest(
        "qwen3.5:397b-cloud",
        "Return one protocol candidate.",
        {"temperature": 0.7, "top_p": 0.95, "num_predict": 8192},
    )


def _success_payload(text: str = "{}", *, model: str = "qwen3.5:397b-cloud") -> bytes:
    return json.dumps(
        {
            "model": model,
            "message": {"content": text},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 12,
            "eval_count": 4,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _success_raw_capture() -> tuple[dict[str, object], int]:
    body = _success_payload()
    request = _request()
    client, server = _client([_response(body)])
    result = client.propose(request)
    assertions = {
        "ok": result.ok,
        "request_hash_bound": result.request_hash == request.request_hash,
        "request_bytes_captured": result.request_body == request.body(),
        "response_bytes_captured": result.response_body == body,
        "response_hash_bound": result.response_hash == sha256_bytes(body),
        "server_model_captured": result.response_model == request.model,
        "finish_reason_captured": result.finish_reason == "stop",
        "usage_captured": result.usage == {"prompt_tokens": 12, "generated_tokens": 4},
        "http_metadata_captured": result.response_headers == {"Content-Type": "application/json"},
        "one_attempt": result.attempts == 1 and len(server.requests) == 1,
    }
    return _case("success_raw_capture", assertions, {
        "request_hash": request.request_hash,
        "response_hash": result.response_hash,
        "usage": result.usage,
        "attempts": result.attempts,
    }), len(server.requests)


def _malformed_missing_partial() -> tuple[dict[str, object], int]:
    request = _request()
    client, malformed_server = _client([_response(b"not-json")])
    malformed = client.propose(request)
    client, missing_server = _client([_json_response({})])
    missing = client.propose(request)
    client, partial_server = _client([_json_response({"response": "partial", "done": False})])
    partial = client.propose(request)
    assertions = {
        "malformed_is_explicit": malformed.error == "malformed_json" and malformed.response_body == b"not-json",
        "missing_content_is_explicit": missing.error == "missing_content" and missing.response_body is not None,
        "partial_is_preserved": partial.ok and partial.partial and partial.response_text == "partial",
        "all_raw_responses_captured": all(
            result.response_hash is not None
            for result in (malformed, missing, partial)
        ),
    }
    return _case("malformed_missing_partial", assertions, {
        "errors": [malformed.error, missing.error, partial.error],
        "partial": partial.partial,
        "request_hash": request.request_hash,
    }), len(malformed_server.requests) + len(missing_server.requests) + len(partial_server.requests)


def _retry_429_5xx_timeout() -> tuple[dict[str, object], int]:
    sleeps: list[float] = []
    client, server = _client(
        [_response(b"busy", 429), _response(b"busy", 503), TimeoutError("synthetic timeout")],
        retries=2,
        sleeps=sleeps,
    )
    result = client.propose(_request())
    assertions = {
        "retryable_statuses_retried": len(server.requests) == 3,
        "two_retries_max": result.attempts == 3,
        "backoff_2_10": sleeps == [2.0, 10.0],
        "terminal_transport_failure": result.error == "transport_failure",
        "last_raw_response_preserved": result.response_body == b"busy" and result.http_status == 503,
    }
    return _case("retry_429_5xx_timeout", assertions, {
        "attempts": result.attempts,
        "sleeps": sleeps,
        "error": result.error,
        "http_status": result.http_status,
    }), len(server.requests)


def _cancellation_and_deadline() -> tuple[dict[str, object], int]:
    client, cancelled_server = _client([_response(_success_payload())])
    cancelled = client.propose(_request(), cancelled=lambda: True)
    client, deadline_server = _client([_response(_success_payload())])
    deadline = client.propose(_request(), campaign_deadline_seconds=1e-12)
    assertions = {
        "cancelled_before_call": cancelled.error == "cancelled" and cancelled.attempts == 0,
        "cancelled_makes_no_request": len(cancelled_server.requests) == 0,
        "deadline_before_call": deadline.error == "campaign_deadline" and deadline.attempts == 0,
        "deadline_makes_no_request": len(deadline_server.requests) == 0,
    }
    return _case("cancellation_and_deadline", assertions, {
        "cancelled_error": cancelled.error,
        "deadline_error": deadline.error,
        "cancelled_requests": len(cancelled_server.requests),
        "deadline_requests": len(deadline_server.requests),
    }), len(cancelled_server.requests) + len(deadline_server.requests)


def _archive_hash_round_trip() -> tuple[dict[str, object], int]:
    request = _request()
    body = _success_payload("archived")
    client, server = _client([_response(body)])
    original = client.propose(request)
    archive = ArchiveReplay()
    archive.record(request, original)
    with tempfile.TemporaryDirectory(prefix="crossllm-m06-archive-") as directory:
        path = Path(directory) / "responses.json"
        archive.save(path)
        restored = ArchiveReplay.load(path)
        replayed = restored.replay(request)
        missed = restored.replay(ProviderRequest("other:model", request.prompt, request.settings))
        temporary_absent = not path.with_name(path.name + ".tmp").exists()
    assertions = {
        "round_trip_ok": replayed.ok,
        "request_hash_addressed": replayed.request_hash == request.request_hash,
        "raw_response_round_trip": replayed.response_body == body and replayed.response_hash == sha256_bytes(body),
        "replay_attempt_is_one": replayed.attempts == 1,
        "archive_miss_is_explicit": missed.error == "archive_miss",
        "temporary_file_cleaned": temporary_absent,
    }
    return _case("archive_hash_round_trip", assertions, {
        "request_hash": request.request_hash,
        "response_hash": original.response_hash,
        "replayed_attempts": replayed.attempts,
        "miss_error": missed.error,
    }), len(server.requests)


def _ordered_slot_statuses() -> tuple[dict[str, object], int]:
    candidate = json.dumps({
        "kind": "invariant",
        "body": {"kind": "literal", "type": "bool", "value": True},
    }, sort_keys=True)
    responses: list[TransportResponse | Exception] = [
        _json_response({"model": "served", "response": candidate, "done": True}),
        _json_response({"model": "served", "response": candidate, "done": True}),
        _json_response({"model": "served", "response": json.dumps({"abstain": True, "reason": "uncertain"}), "done": True}),
        _json_response({"model": "served", "response": "not-json", "done": True}),
        _json_response({"model": "served", "response": candidate, "done": False}),
        _json_response({}),
        TimeoutError("synthetic provider timeout"),
        _json_response({"model": "served", "response": "", "done": True}),
    ]
    client, server = _client(responses)
    run = MethodRunner(client).run(
        track=MethodTrack.CROSSLLM,
        backbone="GLM",
        model="glm-5.3:cloud",
        attempt_id="m06-slot-rehearsal",
        template=PromptTemplate("x", "m06-v1", "Audit this pack:\n{artifact_pack}"),
        artifact_pack_text="public synthetic artifact pack",
        artifact_pack_hash="a" * 64,
        settings={"temperature": 0.7},
        parse_candidate=lambda text: json.loads(text),
    )
    observed = [slot.status.value for slot in run.slots]
    expected = ["candidate", "duplicate", "abstain", "invalid", "truncated", "provider_failure", "provider_failure", "refusal"]
    assertions = {
        "exactly_eight_requests": len(server.requests) == 8,
        "fixed_order_preserved": observed == expected,
        "all_slots_terminal": len(run.slots) == 8 and run.slots[-1].index == 7,
        "duplicate_is_not_candidate": run.slots[1].candidate is None,
        "provider_failures_consume_slots": run.slots[5].raw_response_hash is not None and run.slots[6].raw_response_hash is None,
        "no_quality_retry": len(server.requests) == 8,
    }
    return _case("ordered_slot_statuses", assertions, {
        "statuses": observed,
        "slot_count": len(run.slots),
        "request_count": len(server.requests),
    }), len(server.requests)


def _budget_and_tokenizer_boundaries() -> tuple[dict[str, object], int]:
    candidate = json.dumps({
        "kind": "invariant",
        "body": {"kind": "literal", "type": "bool", "value": True},
    })
    payloads = [
        _json_response({
            "model": "served", "response": candidate, "done": True,
            "prompt_eval_count": 3, "eval_count": 1,
        })
        for _ in range(8)
    ]
    client, server = _client(payloads)
    run = MethodRunner(
        client,
        token_budget=TokenBudget(input_native_token_cap=2, generated_native_token_cap=2),
    ).run(
        track=MethodTrack.DIRECT,
        backbone="Qwen",
        model="qwen3.5:397b-cloud",
        attempt_id="m06-budget-rehearsal",
        template=PromptTemplate("p", "m06-v1", "Audit:\n{artifact_pack}"),
        artifact_pack_text="pack",
        artifact_pack_hash="b" * 64,
        settings={},
        parse_candidate=lambda text: json.loads(text),
    )
    identity = TokenizerIdentity("synthetic-encoding", "revision-1", "f" * 64)
    counter = ExactTokenCounter(identity, lambda text: list(range(len(text))))
    measurement = counter.measure("abc", "xy")
    unknown = counter.measure("abc", None)
    unknown_client, unknown_server = _client([_json_response({"response": "usage unavailable"})])
    usage_unknown = validate_usage(unknown_client.propose(_request()))
    measurement_check = validate_measurement(measurement, TokenBudget(3, 2))
    try:
        ExactTokenCounter(identity, lambda _text: "word fallback") .count("abc")
        string_encoder_rejected = False
    except TokenizationError:
        string_encoder_rejected = True
    assertions = {
        "native_input_cap_rejects": all(slot.status.value == "invalid" for slot in run.slots),
        "budget_ledger_has_eight_checks": len(run.budget_checks) == 8,
        "unknown_native_usage_is_explicit": usage_unknown.status.value == "unknown",
        "identified_encoder_counts_exact_fixture": measurement.prompt_tokens == 3 and measurement.generated_tokens == 2,
        "identified_measurement_passes": measurement_check.status.value == "pass",
        "missing_generated_is_unknown": unknown.generated_tokens is None and "generated_tokens" in unknown.missing_field_reasons,
        "no_word_fallback": string_encoder_rejected,
        "eight_requests_consumed": len(server.requests) == 8,
    }
    return _case("budget_and_tokenizer_boundaries", assertions, {
        "statuses": [slot.status.value for slot in run.slots],
        "budget_statuses": [check.status.value for check in run.budget_checks],
        "measurement": measurement.as_dict(),
        "unknown": unknown.as_dict(),
    }), len(server.requests) + len(unknown_server.requests)


def _four_family_preflight_boundary() -> tuple[dict[str, object], int]:
    families = ("GLM", "DeepSeek", "Qwen", "gpt-oss")
    metadata = [
        {
            "family": family,
            "preferred_execution_tag": f"{family.lower()}:cloud",
            "starting_research_settings": {"temperature": 0.7, "top_p": 0.95},
        }
        for family in families
    ]
    responses = [
        _json_response({
            "model": row["preferred_execution_tag"],
            "message": {"content": "ok"},
            "done": True,
        })
        for row in metadata
    ]
    client, server = _client(responses)
    panel, captured = run_live_preflight(metadata, "preflight fixture", client)
    results = {result.family: result for result in panel.results}
    assertions = {
        "all_four_families_present": tuple(result.family for result in panel.results) == families,
        "one_probe_per_family": len(server.requests) == 4 and sorted(captured) == sorted(families),
        "requested_models_used": all(
            json.loads(request)["model"] == row["preferred_execution_tag"]
            for request, row in zip(server.requests, metadata)
        ),
        "response_models_captured": all(
            results[family].response_model == f"{family.lower()}:cloud"
            for family in families
        ),
        "missing_identity_is_explicit": all(
            not results[family].ready
            and "served_weight_digest" in results[family].missing_field_reasons
            and "effective_api_settings" in results[family].missing_field_reasons
            for family in families
        ),
        "panel_not_overclaimed_ready": panel.ready is False,
    }
    return _case("four_family_preflight_boundary", assertions, {
        "families": list(families),
        "ready": panel.ready,
        "response_models": [results[family].response_model for family in families],
        "missing_fields": [results[family].missing_field_reasons for family in families],
    }), len(server.requests)


def _x_p_t0_shared_call_boundary() -> tuple[dict[str, object], int]:
    candidate_template = {
        "kind": "invariant",
        "body": {"kind": "literal", "type": "bool", "value": True},
    }
    responses = [
        _json_response({
            "model": "served",
            "response": json.dumps(candidate_template | {"slot": index}),
            "done": True,
            "prompt_eval_count": 10,
            "eval_count": 2,
        })
        for index in range(24)
    ]
    client, server = _client(responses)
    template = PromptTemplate("shared", "m06-v1", "Audit:\n{artifact_pack}")
    runs = [
        MethodRunner(client).run(
            track=track,
            backbone="GLM",
            model="glm-5.3:cloud",
            attempt_id=f"m06-{track.value}",
            template=template,
            artifact_pack_text="the same public pack",
            artifact_pack_hash="c" * 64,
            settings={"temperature": 0.7, "top_p": 0.95},
            parse_candidate=lambda text: json.loads(text),
        )
        for track in (MethodTrack.CROSSLLM, MethodTrack.DIRECT, MethodTrack.T0)
    ]
    request_bodies = {request for request in server.requests}
    assertions = {
        "all_tracks_exercised": [run.track.value for run in runs] == ["X", "P", "T0"],
        "eight_slots_each": all(len(run.slots) == 8 for run in runs),
        "same_prompt_settings_and_pack": len(request_bodies) == 1,
        "same_call_cap": len(server.requests) == 24,
        "usage_checks_present": all(len(run.budget_checks) == 8 for run in runs),
        "usage_within_caps": all(check.status.value == "pass" for run in runs for check in run.budget_checks),
        "no_memory_tools_retrieval": template.policy.as_dict() == {
            "allow_memory": False, "allow_tools": False, "allow_retrieval": False, "proposal_slots": 8,
        },
    }
    return _case("x_p_t0_shared_call_boundary", assertions, {
        "tracks": [run.track.value for run in runs],
        "request_count": len(server.requests),
        "unique_request_bodies": len(request_bodies),
        "template_hash": template.template_hash,
    }), len(server.requests)


def _hash_inputs(root: Path) -> dict[str, str]:
    paths = (
        "src/crossllm/providers/ollama.py",
        "src/crossllm/providers/preflight.py",
        "src/crossllm/providers/budget.py",
        "src/crossllm/providers/tokenizer.py",
        "src/crossllm/methods/proposal.py",
        "src/crossllm/methods/runner.py",
    )
    return {
        path: sha256_bytes((root / path).read_bytes())
        for path in paths
    }


def build_report(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    builders = (
        _success_raw_capture,
        _malformed_missing_partial,
        _retry_429_5xx_timeout,
        _cancellation_and_deadline,
        _archive_hash_round_trip,
        _ordered_slot_statuses,
        _budget_and_tokenizer_boundaries,
        _four_family_preflight_boundary,
        _x_p_t0_shared_call_boundary,
    )
    cases: list[dict[str, object]] = []
    synthetic_calls = 0
    for builder in builders:
        result, calls = builder()
        cases.append(result)
        synthetic_calls += calls
    body: dict[str, Any] = {
        "schema_version": 1,
        "record_type": "synthetic_m06_provider_contract_rehearsal",
        "scope": "development_provider_contract_rehearsal_only",
        "admission_eligible": False,
        "fake_server_only": True,
        "ollama_cloud_calls": 0,
        "synthetic_transport_calls": synthetic_calls,
        "endpoint_policy": "https://ollama.com/api/chat",
        "case_ids": list(CASE_IDS),
        "cases": cases,
        "case_count": len(cases),
        "passed_count": sum(bool(case["passed"]) for case in cases),
        "all_passed": all(bool(case["passed"]) for case in cases),
        "hash_inputs": _hash_inputs(root),
        "limitations": [
            "no Ollama Cloud calls were executed",
            "fake transport responses are synthetic fixtures, not model outcomes",
            "preflight readiness remains false without served-weight digest and effective settings",
            "the report cannot establish quota, catalog/license evidence, checkpoint identity, or provider availability",
            "the rehearsal is development evidence only and has no independent reviewer",
        ],
    }
    body["report_hash"] = sha256_hex(body)
    return body


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def validate_report(root: Path = ROOT, report_path: Path | None = None) -> list[str]:
    root = root.resolve()
    path = report_path or root / DEFAULT_OUTPUT.relative_to(ROOT)
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"provider contract rehearsal unreadable: {error}"]
    if not isinstance(report, dict):
        return ["provider contract rehearsal must be an object"]
    errors: list[str] = []
    body = dict(report)
    stored_hash = body.pop("report_hash", None)
    if stored_hash != sha256_hex(body):
        errors.append("provider contract rehearsal report hash mismatch")
    expected = build_report(root)
    for key in (
        "schema_version", "record_type", "scope", "admission_eligible",
        "fake_server_only", "ollama_cloud_calls", "synthetic_transport_calls",
        "endpoint_policy", "case_ids", "cases", "case_count", "passed_count",
        "all_passed", "hash_inputs", "limitations",
    ):
        if report.get(key) != expected.get(key):
            errors.append(f"{key} mismatch")
    if report.get("admission_eligible") is not False:
        errors.append("provider contract rehearsal must remain non-admission")
    if report.get("ollama_cloud_calls") != 0:
        errors.append("provider contract rehearsal must have zero Ollama Cloud calls")
    if report.get("case_ids") != list(CASE_IDS):
        errors.append("provider contract rehearsal case coverage mismatch")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=None)
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
        print("OK: synthetic M06 provider contract rehearsal is valid and non-admission")
        return 0
    report = build_report(root)
    _atomic_json(output, report)
    print(f"synthetic M06 provider contract rehearsal: {report['passed_count']}/{report['case_count']} pass")
    print(f"synthetic transport calls: {report['synthetic_transport_calls']}; Ollama Cloud calls: 0")
    print(f"evidence written to: {output}")
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
