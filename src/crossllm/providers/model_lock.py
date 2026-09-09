"""Build a hash-addressed runtime model lock from provider preflight facts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..contracts.canonical import sha256_hex
from .ollama import ProviderResponse
from .preflight import PreflightPanel, PreflightResult


_PUBLIC_MODEL_FIELDS = (
    "model",
    "upstream_weights",
    "license",
    "license_source",
    "public_weight_and_license_evidence",
    "sources",
)
_PUBLIC_PROVIDER_FIELDS = (
    "name",
    "base_url",
    "chat_endpoint",
    "auth_env",
    "execution_mode",
    "local_weights",
)


def build_runtime_model_lock(
    model_document: Mapping[str, object] | Sequence[Mapping[str, object]],
    metadata: Sequence[Mapping[str, object]],
    panel: PreflightPanel,
    responses: Mapping[str, ProviderResponse],
    *,
    captured_at: str,
) -> dict[str, object]:
    """Create a public model lock without copying credentials or response text.

    The catalogue/model document supplies only the allowlisted public evidence;
    the preflight panel and captured responses supply execution-time facts. The
    returned lock hashes the payload before ``lock_hash`` is added, so it can
    be used as a dependency in a campaign plan.
    """
    if not isinstance(captured_at, str) or not captured_at.strip():
        raise ValueError("captured_at must be a non-empty string")
    expected = tuple(panel.expected_families)
    if not expected or len(set(expected)) != len(expected):
        raise ValueError("preflight panel expected families must be unique and non-empty")

    rows = list(metadata)
    by_family: dict[str, Mapping[str, object]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("model metadata rows must be objects")
        family = row.get("family")
        if not isinstance(family, str) or not family:
            raise ValueError("each model metadata row requires a family")
        if family in by_family:
            raise ValueError(f"duplicate model family metadata: {family}")
        by_family[family] = row
    unexpected = sorted(set(by_family) - set(expected))
    missing = sorted(set(expected) - set(by_family))
    if unexpected:
        raise ValueError(f"unexpected model families: {', '.join(unexpected)}")
    if missing:
        raise ValueError(f"model families missing: {', '.join(missing)}")

    result_by_family: dict[str, PreflightResult] = {}
    for result in panel.results:
        if result.family in result_by_family:
            raise ValueError(f"duplicate preflight result family: {result.family}")
        result_by_family[result.family] = result
    missing_results = sorted(set(expected) - set(result_by_family))
    unexpected_results = sorted(set(result_by_family) - set(expected))
    if missing_results:
        raise ValueError(f"preflight results missing families: {', '.join(missing_results)}")
    if unexpected_results:
        raise ValueError(f"unexpected preflight result families: {', '.join(unexpected_results)}")
    missing_responses = sorted(set(expected) - set(responses))
    unexpected_responses = sorted(set(responses) - set(expected))
    if missing_responses:
        raise ValueError(f"preflight responses missing families: {', '.join(missing_responses)}")
    if unexpected_responses:
        raise ValueError(f"unexpected preflight response families: {', '.join(unexpected_responses)}")

    provider = _public_provider(model_document)
    model_rows = [
        _lock_row(by_family[family], result_by_family[family], responses[family], captured_at)
        for family in expected
    ]
    payload: dict[str, object] = {
        "schema_version": 1,
        "status": "RUNTIME_ATTESTATION_LOCKED" if panel.ready else "RUNTIME_PREFLIGHT_PENDING",
        "captured_at": captured_at,
        "provider": provider,
        "expected_families": list(expected),
        "preflight_ready": panel.ready,
        "models": model_rows,
    }
    payload["lock_hash"] = sha256_hex(payload)
    return payload


def _public_provider(model_document: Mapping[str, object] | Sequence[Mapping[str, object]]) -> dict[str, object] | None:
    if not isinstance(model_document, Mapping):
        return None
    provider = model_document.get("provider")
    if not isinstance(provider, Mapping):
        return None
    return {key: provider[key] for key in _PUBLIC_PROVIDER_FIELDS if key in provider}


def _lock_row(
    metadata: Mapping[str, object],
    result: PreflightResult,
    response: ProviderResponse,
    captured_at: str,
) -> dict[str, object]:
    row: dict[str, object] = {"family": result.family}
    for key in _PUBLIC_MODEL_FIELDS:
        value = metadata.get(key)
        if key == "sources":
            if isinstance(value, list) and all(isinstance(source, str) for source in value):
                row[key] = list(value)
        elif isinstance(value, str):
            row[key] = value

    row.update(
        {
            "requested_tag": result.requested_tag,
            "response_model": result.response_model,
            "served_weight_digest": result.served_weight_digest,
            "effective_api_settings": result.effective_settings,
            "preflight_status": "passed" if result.ready else "blocked",
            "preflight_checks": [
                {"name": check.name, "passed": check.passed, "detail": check.detail}
                for check in result.checks
            ],
            "missing_field_reasons": dict(result.missing_field_reasons),
            "run_date": captured_at,
            "request_hash": response.request_hash,
            "response_hash": response.response_hash,
            "http_status": response.http_status,
            "attempts": response.attempts,
            "partial": response.partial,
            "usage": dict(response.usage),
            # Ollama Cloud does not expose an immutable served-weight identity
            # in the captured chat response. A tag or catalogue digest is not
            # promoted to an execution attestation.
            "immutable_served_weights_guaranteed": False,
        }
    )
    if not row["immutable_served_weights_guaranteed"]:
        row["identity_limitations"] = (
            "Ollama Cloud chat preflight did not authenticate an immutable served-weight "
            "digest; requested tag and catalogue metadata are not sufficient."
        )
    return row
