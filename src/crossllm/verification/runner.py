"""Run proposal methods through the shared candidate verification pipeline."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..methods.runner import MethodRun
from .cache import FileVerificationCache
from .inputs import candidates_from_method_run
from .pipeline import SharedVerificationPipeline, VerificationExecutors
from .records import CandidateInput, PairKey, VerificationOutcome
from .runtime import CaseRuntimeBindings


def verify_candidates(
    candidates: Iterable[CandidateInput],
    case: CaseRuntimeBindings,
    symbols: list[Any],
    *,
    executors: VerificationExecutors | None = None,
    cache: FileVerificationCache | None = None,
    adapter_revision: str = "runtime-adapter-v1",
    bounds: dict[str, Any] | None = None,
    replay_spec_hash: str | None = None,
) -> tuple[VerificationOutcome, ...]:
    """Verify ordered candidates with one shared adapter/pipeline instance.

    Keeping one pipeline instance per case is important for stateful backend
    hooks such as fixture search and witness projection.  It also guarantees
    that X, P and T0 receive identical adapter revision, bounds and cache
    semantics; only their candidate archive is different.
    """

    pipeline = SharedVerificationPipeline(
        case,
        symbols,
        executors=executors,
        cache=cache,
        adapter_revision=adapter_revision,
        bounds=bounds,
        replay_spec_hash=replay_spec_hash,
    )
    return tuple(pipeline.verify(candidate) for candidate in candidates)


def verify_method_run(
    method_run: MethodRun,
    *,
    campaign_id: str,
    pair_key: PairKey,
    arm: str,
    case: CaseRuntimeBindings,
    symbols: list[Any],
    executors: VerificationExecutors | None = None,
    cache: FileVerificationCache | None = None,
    adapter_revision: str = "runtime-adapter-v1",
    bounds: dict[str, Any] | None = None,
    replay_spec_hash: str | None = None,
) -> tuple[VerificationOutcome, ...]:
    """Convert X/P/T0 output and send it through the common verifier."""

    candidates = candidates_from_method_run(
        method_run,
        campaign_id=campaign_id,
        pair_key=pair_key,
        arm=arm,
    )
    return verify_candidates(
        candidates,
        case,
        symbols,
        executors=executors,
        cache=cache,
        adapter_revision=adapter_revision,
        bounds=bounds,
        replay_spec_hash=replay_spec_hash,
    )


__all__ = ["verify_candidates", "verify_method_run"]
