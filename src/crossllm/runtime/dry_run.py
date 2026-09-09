"""Offline development rehearsal for the CrossLLM pipeline (M08.08)."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from ..analysis import CampaignOutcome, OutcomeAvailability, analyze_outcomes
from ..artifacts import ArtifactSymbol
from ..backends import BoundedPairedExplorer, SymbolicPairedExplorer, Z3XLIRBackend
from ..contracts import CampaignStatus, ReplayStatus, SearchStatus
from ..methods import MethodRunner, MethodTrack, PromptTemplate
from ..providers import FakeProviderServer, OllamaClient, TransportResponse
from ..replay import NativeReplay, WitnessAssessmentStatus, WitnessProjector, assess_witness
from ..semantics import Message, PairedFixture, TransitionBounds
from ..xlir import XLIRCompiler
from .events import AppendOnlyEventStore, CampaignStateMachine, InterruptionKind
from .method_events import append_method_run_events
from .resources import ResourceUsage
from .telemetry import EffortPhase, TelemetryLedger, TelemetryRecord
from .rehearsal import run_fault_rehearsal


@dataclass(frozen=True, slots=True)
class DryRunReport:
    proposal_compiled: bool
    smt_status: SearchStatus
    search_status: SearchStatus
    symbolic_search_status: SearchStatus
    native_replay_status: ReplayStatus
    independent_replay_status: str
    replay_assessment_status: WitnessAssessmentStatus
    replay_assessment_reasons: tuple[str, ...]
    event_count: int
    method_event_count: int
    resumed_same_attempt: bool
    exported_path: str
    analysis: dict[str, object]
    method_tracks: dict[str, object]
    telemetry: dict[str, object]
    fault_exported_path: str | None = None
    fault_rehearsal: dict[str, object] | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "proposal_compiled": self.proposal_compiled,
            "smt_status": self.smt_status.value,
            "search_status": self.search_status.value,
            "symbolic_search_status": self.symbolic_search_status.value,
            "native_replay_status": self.native_replay_status.value,
            "independent_replay_status": self.independent_replay_status,
            "replay_assessment_status": self.replay_assessment_status.value,
            "replay_assessment_reasons": list(self.replay_assessment_reasons),
            "event_count": self.event_count,
            "method_event_count": self.method_event_count,
            "resumed_same_attempt": self.resumed_same_attempt,
            "exported_path": self.exported_path,
            "analysis": self.analysis,
            "method_tracks": self.method_tracks,
            "telemetry": self.telemetry,
            "fault_exported_path": self.fault_exported_path,
            "fault_rehearsal": self.fault_rehearsal,
        }


class DevelopmentDryRun:
    """Run a deterministic fixture-only rehearsal with no remote provider calls."""

    def run(self, export_path: Path, fault_export_path: Path | None = None) -> DryRunReport:
        if not export_path:
            raise ValueError("export_path is required")
        compiler = XLIRCompiler.from_symbols([
            ArtifactSymbol("sym.source.ready", "Bridge.sol", "ready", "source", "storage", "bool"),
            ArtifactSymbol("sym.destination.ready", "Bridge.sol", "ready", "destination", "storage", "bool"),
        ])
        proposal = compiler.compile({
            "kind": "invariant",
            "body": {
                "kind": "binary",
                "operator": "eq",
                "left": {"kind": "symbol", "symbol_id": "sym.source.ready", "state": "post"},
                "right": {"kind": "symbol", "symbol_id": "sym.destination.ready", "state": "post"},
            },
        })
        if not proposal.ok or proposal.invariant is None:
            raise RuntimeError("development proposal did not compile")
        smt = Z3XLIRBackend().check_violation(proposal.invariant)

        message = Message("source", "destination", "bridge", "receiver", 1, "commit-1")
        initial = PairedFixture(bounds=TransitionBounds(2, 2, 1))
        search = BoundedPairedExplorer([message]).search(
            initial,
            lambda state: bool(state.delivered) and state.delivered[0].nonce == 1,
        )
        if search.status is not SearchStatus.SAT:
            raise RuntimeError(f"development search did not find expected fixture trace: {search.status}")
        symbolic_search = SymbolicPairedExplorer([message]).search(
            initial,
            lambda state: bool(state.delivered) and state.delivered[0].nonce == 1,
        )
        if symbolic_search.status is not search.status or not symbolic_search.complete:
            raise RuntimeError(
                "symbolic and exhaustive fixture searches disagree: "
                f"{symbolic_search.status} vs {search.status}"
            )
        witness = WitnessProjector().project(
            search,
            initial,
            witness_id="dry-run-witness",
            query_id="dry-run-query",
            created_at="2026-09-08T00:00:00Z",
            proof_objects={"fixture_only": True},
        )
        replay = NativeReplay().check(witness, initial)
        assessment = assess_witness(
            witness_id=witness.witness_id,
            model_trace_valid=replay.status is ReplayStatus.PASS,
            native_replay_status=replay.status,
            independent_replay_status=ReplayStatus(witness.independent_replay_status),
            security_relevance=None,
            allowed_capabilities=witness.allowed_capabilities,
        )

        # Exercise all three method tracks through the same eight-slot provider
        # contract without making a remote call. The fake responses are unique
        # per slot so duplicate classification cannot hide a missing request.
        provider_responses = []
        for track in (MethodTrack.CROSSLLM, MethodTrack.DIRECT, MethodTrack.T0):
            for slot in range(8):
                candidate = json.dumps({
                    "kind": "invariant",
                    "invariant_id": f"dry-run-{track.value}-{slot}",
                    "body": {"kind": "literal", "type": "bool", "value": True},
                })
                provider_responses.append(TransportResponse(
                    200,
                    {"X-Model": "fixture-served"},
                    json.dumps({
                        "model": "fixture-served",
                        "response": candidate,
                        "done": True,
                        "done_reason": "stop",
                    }).encode("utf-8"),
                ))
        method_server = FakeProviderServer(provider_responses)
        method_runner = MethodRunner(OllamaClient(sender=method_server.send))
        method_template = PromptTemplate("dry-run-method", "v1", "Audit pack:\n{artifact_pack}")
        method_runs: dict[str, object] = {}
        method_run_objects = []
        request_hashes: set[str] = set()
        for track in (MethodTrack.CROSSLLM, MethodTrack.DIRECT, MethodTrack.T0):
            method_run = method_runner.run(
                track=track,
                backbone="fixture-backbone",
                model="fixture:ollama-cloud",
                attempt_id=f"dry-run-{track.value.lower()}",
                template=method_template,
                artifact_pack_text="public fixture pack",
                artifact_pack_hash="d" * 64,
                settings={"temperature": 0.7, "top_p": 0.95},
                parse_candidate=json.loads,
            )
            request_hashes.update(response.request_hash for response in method_run.provider_responses)
            method_run_objects.append(method_run)
            method_runs[track.value] = {
                "slot_count": len(method_run.slots),
                "candidate_count": sum(slot.status.value == "candidate" for slot in method_run.slots),
                "provider_call_count": len(method_run.provider_responses),
                "template_hash": method_run.template_hash,
            }
        if len(method_server.requests) != 24 or len(request_hashes) != 1:
            raise RuntimeError("offline method tracks did not share the expected 24 calls and request hash")
        method_runs["shared_request_hash"] = next(iter(request_hashes))

        store = AppendOnlyEventStore()
        clock_values = iter([1.0, 2.0, 3.0, 4.0, 5.0])
        machine = CampaignStateMachine(
            "dry-run-campaign",
            "dry-run-attempt",
            store,
            clock=lambda: next(clock_values),
            timestamp=lambda: "2026-09-08T00:00:00Z",
        )
        machine.start({"fixture_only": True})
        method_event_count = sum(
            append_method_run_events(
                store,
                method_run,
                campaign_id="dry-run-campaign",
                timestamp="2026-09-08T00:00:00Z",
            )
            for method_run in method_run_objects
        )
        machine.mark_uncertain("injected_worker_restart", InterruptionKind.WORKER_RESTART)
        machine.resume(InterruptionKind.WORKER_RESTART)
        machine.finish(CampaignStatus.COMPLETED, {"search_status": search.status.value, "replay_status": replay.status.value})
        store.export_jsonl(export_path)

        report = analyze_outcomes([
            CampaignOutcome(
                "dry-run-campaign", "dry-run-instance", "dry-run-lineage", "X", 1, "positive",
                detected=True, useful_proposal=True, native_witness=True, independent_replay=None,
                claim_time_seconds=0.5, witness_time_seconds=0.25, horizon_seconds=10,
                availability=OutcomeAvailability.AVAILABLE,
            )
        ])
        telemetry = TelemetryLedger()
        telemetry.append(TelemetryRecord(
            EffortPhase.METHOD_HORIZON,
            ResourceUsage(
                cpu_core_seconds=0.1, solver_seconds=0.02, wall_seconds=0.2, input_tokens=None,
                generated_tokens=None, missing_field_reasons={"input_tokens": "dry_run_no_provider"},
            ),
            campaign_id="dry-run-campaign", attempt_id="dry-run-attempt",
        ))
        fault_report = run_fault_rehearsal(fault_export_path) if fault_export_path is not None else None
        return DryRunReport(
            proposal_compiled=True,
            smt_status=smt.status,
            search_status=search.status,
            symbolic_search_status=symbolic_search.status,
            native_replay_status=replay.status,
            independent_replay_status=witness.independent_replay_status,
            replay_assessment_status=assessment.status,
            replay_assessment_reasons=assessment.reasons,
            event_count=len(store.events),
            method_event_count=method_event_count,
            resumed_same_attempt=machine.snapshot().attempt_id == "dry-run-attempt",
            exported_path=str(export_path),
            analysis=report.as_dict(),
            method_tracks=method_runs,
            telemetry=telemetry.aggregate(EffortPhase.METHOD_HORIZON),
            fault_exported_path=fault_report.export_path if fault_report else None,
            fault_rehearsal=fault_report.as_dict() if fault_report else None,
        )
