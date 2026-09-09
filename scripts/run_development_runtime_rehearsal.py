#!/usr/bin/env python3
"""Run and validate the offline M08.08 runtime/e2e rehearsal.

The underlying dry-run uses only fixture data and a fake provider sender.  This
wrapper preserves the raw event JSONL files, binds their hashes, and validates
the stable end-to-end summary without treating it as a live evaluation run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crossllm.contracts.canonical import sha256_hex
from crossllm.runtime import DevelopmentDryRun


DEFAULT_OUTPUT = ROOT / "dataset" / "reports" / "m08_development_runtime_rehearsal.json"
DEFAULT_EVENTS = ROOT / "dataset" / "reports" / "m08_development_runtime.events.jsonl"
DEFAULT_FAULT_EVENTS = ROOT / "dataset" / "reports" / "m08_development_fault.events.jsonl"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stable_summary(report: Any) -> dict[str, object]:
    tracks = report.method_tracks
    fault = report.fault_rehearsal or {}
    scenarios = fault.get("scenarios", []) if isinstance(fault, dict) else []
    return {
        "proposal_compiled": report.proposal_compiled,
        "smt_status": report.smt_status.value,
        "search_status": report.search_status.value,
        "symbolic_search_status": report.symbolic_search_status.value,
        "native_replay_status": report.native_replay_status.value,
        "independent_replay_status": report.independent_replay_status,
        "replay_assessment_status": report.replay_assessment_status.value,
        "replay_assessment_reasons": list(report.replay_assessment_reasons),
        "event_count": report.event_count,
        "method_event_count": report.method_event_count,
        "resumed_same_attempt": report.resumed_same_attempt,
        "method_tracks": tracks,
        "telemetry": report.telemetry,
        "fault_event_count": fault.get("event_count") if isinstance(fault, dict) else None,
        "fault_telemetry_count": fault.get("telemetry_count") if isinstance(fault, dict) else None,
        "fault_scenarios": scenarios,
    }


def _run_once(events_path: Path, fault_path: Path) -> tuple[Any, dict[str, object]]:
    report = DevelopmentDryRun().run(events_path, fault_path)
    return report, _stable_summary(report)


def build_report(
    root: Path = ROOT,
    *,
    events_path: Path | None = None,
    fault_path: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    events = (events_path or root / DEFAULT_EVENTS.relative_to(ROOT)).resolve()
    fault = (fault_path or root / DEFAULT_FAULT_EVENTS.relative_to(ROOT)).resolve()
    dry_run, summary = _run_once(events, fault)
    body: dict[str, Any] = {
        "schema_version": 1,
        "record_type": "development_m08_runtime_rehearsal",
        "scope": "development_offline_runtime_rehearsal_only",
        "admission_eligible": False,
        "fake_provider_only": True,
        "ollama_cloud_calls": 0,
        "synthetic_provider_calls": 24,
        "events_path": str(events),
        "events_sha256": _sha256(events),
        "fault_events_path": str(fault),
        "fault_events_sha256": _sha256(fault),
        "summary": summary,
        "limitations": [
            "all provider responses are in-process synthetic fixtures",
            "faults are callback injections and do not claim OS-level kill or disk-full reproduction",
            "independent EVM replay remains unknown in the dry-run and security relevance remains unassessed",
            "the artifact is development evidence only and has no evaluation admission or reviewer sign-off",
        ],
    }
    # The raw event file is intentionally hash-bound, while event UUIDs and
    # monotonic timestamps remain in the raw export rather than being copied
    # into this stable summary.
    if dry_run.event_count != 58 or dry_run.method_event_count != 54:
        raise RuntimeError("unexpected development dry-run event shape")
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
        return [f"development runtime rehearsal unreadable: {error}"]
    if not isinstance(report, dict):
        return ["development runtime rehearsal must be an object"]
    errors: list[str] = []
    body = dict(report)
    stored_hash = body.pop("report_hash", None)
    if stored_hash != sha256_hex(body):
        errors.append("development runtime rehearsal report hash mismatch")
    for key, expected in {
        "schema_version": 1,
        "record_type": "development_m08_runtime_rehearsal",
        "scope": "development_offline_runtime_rehearsal_only",
        "admission_eligible": False,
        "fake_provider_only": True,
        "ollama_cloud_calls": 0,
        "synthetic_provider_calls": 24,
    }.items():
        if report.get(key) != expected:
            errors.append(f"{key} mismatch")
    events = Path(report.get("events_path", ""))
    fault = Path(report.get("fault_events_path", ""))
    for label, event_path, hash_key in (
        ("events", events, "events_sha256"),
        ("fault events", fault, "fault_events_sha256"),
    ):
        if not event_path.is_file():
            errors.append(f"{label} file is missing")
        elif report.get(hash_key) != _sha256(event_path):
            errors.append(f"{label} hash mismatch")
    with tempfile.TemporaryDirectory(prefix="crossllm-m08-runtime-check-") as directory:
        _, expected_summary = _run_once(Path(directory) / "events.jsonl", Path(directory) / "fault.jsonl")
    if report.get("summary") != expected_summary:
        errors.append("development runtime summary mismatch")
    summary = report.get("summary")
    if not isinstance(summary, dict):
        errors.append("development runtime summary is missing")
    else:
        if summary.get("event_count") != 58 or summary.get("method_event_count") != 54:
            errors.append("development runtime event counts mismatch")
        if summary.get("resumed_same_attempt") is not True:
            errors.append("development runtime did not resume the same attempt")
        if summary.get("fault_event_count") != 12 or summary.get("fault_telemetry_count") != 6:
            errors.append("fault rehearsal counts mismatch")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--events", type=Path, default=None)
    parser.add_argument("--fault-events", type=Path, default=None)
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
        print("OK: development M08 runtime rehearsal is valid and non-admission")
        return 0
    events = args.events.resolve() if args.events else root / DEFAULT_EVENTS.relative_to(ROOT)
    fault = args.fault_events.resolve() if args.fault_events else root / DEFAULT_FAULT_EVENTS.relative_to(ROOT)
    report = build_report(root, events_path=events, fault_path=fault)
    _atomic_json(output, report)
    print("development M08 runtime rehearsal: 58 events, 54 method events, 12 fault events")
    print("synthetic provider calls: 24; Ollama Cloud calls: 0")
    print(f"evidence written to: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
