"""Execution-time model preflight without overclaiming served identity."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping

from .ollama import OllamaClient, ProviderRequest, ProviderResponse


@dataclass(frozen=True, slots=True)
class PreflightCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class PreflightResult:
    family: str
    requested_tag: str
    ready: bool
    response_model: str | None
    served_weight_digest: str | None
    effective_settings: dict[str, object] | None
    missing_field_reasons: dict[str, str]
    checks: tuple[PreflightCheck, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "family": self.family,
            "requested_tag": self.requested_tag,
            "ready": self.ready,
            "response_model": self.response_model,
            "served_weight_digest": self.served_weight_digest,
            "effective_settings": self.effective_settings,
            "missing_field_reasons": dict(self.missing_field_reasons),
            "checks": [
                {"name": check.name, "passed": check.passed, "detail": check.detail}
                for check in self.checks
            ],
        }


@dataclass(frozen=True, slots=True)
class PreflightPanel:
    """One aggregate record for the required four-family preflight."""

    results: tuple[PreflightResult, ...]
    expected_families: tuple[str, ...] = ("GLM", "DeepSeek", "Qwen", "gpt-oss")

    @property
    def ready(self) -> bool:
        return (
            tuple(sorted(result.family for result in self.results)) == tuple(sorted(self.expected_families))
            and all(result.ready for result in self.results)
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "ready": self.ready,
            "expected_families": list(self.expected_families),
            "results": [result.as_dict() for result in self.results],
        }


def preflight_panel(
    metadata: list[Mapping[str, object]],
    responses: Mapping[str, ProviderResponse],
    *,
    expected_families: tuple[str, ...] = ("GLM", "DeepSeek", "Qwen", "gpt-oss"),
) -> PreflightPanel:
    """Run per-family checks and fail closed on missing or duplicate metadata."""
    if not expected_families or len(set(expected_families)) != len(expected_families):
        raise ValueError("expected_families must contain unique non-empty family names")
    if any(not isinstance(family, str) or not family for family in expected_families):
        raise ValueError("expected_families must contain non-empty strings")
    by_family: dict[str, Mapping[str, object]] = {}
    for row in metadata:
        family = row.get("family")
        if not isinstance(family, str) or not family:
            raise ValueError("each model metadata row requires a family")
        if family in by_family:
            raise ValueError(f"duplicate model family metadata: {family}")
        by_family[family] = row
    unexpected = sorted(set(by_family) - set(expected_families))
    if unexpected:
        raise ValueError(f"unexpected model families: {', '.join(unexpected)}")
    results: list[PreflightResult] = []
    for family in expected_families:
        row = by_family.get(family)
        response = responses.get(family)
        if row is None or response is None:
            results.append(PreflightResult(
                family,
                row.get("preferred_execution_tag", row.get("requested_tag", "")) if row else "",
                False,
                None,
                None,
                None,
                {"panel": "metadata_or_response_missing"},
                (PreflightCheck("panel", False, "metadata or preflight response missing"),),
            ))
            continue
        results.append(preflight_model(row, response))
    return PreflightPanel(tuple(results), expected_families)


def preflight_model(metadata: Mapping[str, object], response: ProviderResponse) -> PreflightResult:
    family = metadata.get("family") if isinstance(metadata.get("family"), str) else "unknown"
    requested = metadata.get("preferred_execution_tag") or metadata.get("requested_tag")
    requested_tag = requested if isinstance(requested, str) else ""
    checks: list[PreflightCheck] = []
    checks.append(PreflightCheck("requested_tag", bool(requested_tag), "tag is present" if requested_tag else "missing tag"))
    checks.append(PreflightCheck("transport", response.error is None, response.error or "response received"))
    response_model = response.response_model
    checks.append(PreflightCheck("response_model", response_model is not None, response_model or "served model not reported"))
    digest = metadata.get("served_weight_digest")
    missing: dict[str, str] = {}
    if not isinstance(digest, str) or not digest:
        digest = None
        missing["served_weight_digest"] = "provider response/metadata did not authenticate immutable served weights"
    effective = metadata.get("effective_api_settings")
    if not isinstance(effective, dict):
        effective = None
        missing["effective_api_settings"] = "effective settings were not returned by the provider"
    checks.append(PreflightCheck("served_weight_digest", digest is not None, digest or missing["served_weight_digest"]))
    checks.append(PreflightCheck("effective_api_settings", effective is not None, effective is not None and "settings captured" or missing["effective_api_settings"]))
    ready = all(check.passed for check in checks)
    return PreflightResult(family, requested_tag, ready, response_model, digest, effective, missing, tuple(checks))


def run_live_preflight(
    metadata: list[Mapping[str, object]],
    prompt: str,
    client: OllamaClient,
    *,
    expected_families: tuple[str, ...] = ("GLM", "DeepSeek", "Qwen", "gpt-oss"),
) -> tuple[PreflightPanel, dict[str, ProviderResponse]]:
    """Execute one captured probe per declared family and build its panel.

    This function only records what the provider returns. In particular, it
    never derives a served-weight digest from a model tag or treats the local
    metadata's requested settings as effective settings.
    """
    if not isinstance(prompt, str) or not prompt:
        raise ValueError("preflight prompt must be a non-empty string")
    if not expected_families or len(set(expected_families)) != len(expected_families):
        raise ValueError("expected_families must contain unique non-empty family names")
    if any(not isinstance(family, str) or not family for family in expected_families):
        raise ValueError("expected_families must contain non-empty strings")
    declared_families = [row.get("family") for row in metadata]
    if any(not isinstance(family, str) or not family for family in declared_families):
        raise ValueError("each model metadata row requires a non-empty family")
    unexpected = sorted(
        family for family in declared_families
        if family not in expected_families
    )
    if unexpected:
        raise ValueError(f"unexpected model families: {', '.join(unexpected)}")
    responses: dict[str, ProviderResponse] = {}
    for row in metadata:
        family = row.get("family")
        if not isinstance(family, str) or not family:
            raise ValueError("each model metadata row requires a family")
        if family in responses:
            raise ValueError(f"duplicate model family metadata: {family}")
        requested = row.get("preferred_execution_tag") or row.get("requested_tag")
        if not isinstance(requested, str) or not requested:
            raise ValueError(f"{family} is missing a requested execution tag")
        settings = row.get("starting_research_settings", {})
        if not isinstance(settings, dict):
            raise ValueError(f"{family}.starting_research_settings must be an object")
        responses[family] = client.propose(ProviderRequest(requested, prompt, dict(settings)))
    return preflight_panel(metadata, responses, expected_families=expected_families), responses
