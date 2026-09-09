from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from crossllm.contracts import CampaignStatus, EventLog
from crossllm.contracts.canonical import sha256_hex
from crossllm.runtime import CampaignStateMachine, PersistentEventStore

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_development_campaign.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("crossllm_run_development_campaign", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load development campaign runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RunDevelopmentCampaignTests(unittest.TestCase):
    def test_run_report_validator_checks_terminal_ledger_without_provider_calls(self) -> None:
        prepare = importlib.util.spec_from_file_location(
            "crossllm_prepare_for_run_report",
            ROOT / "scripts" / "prepare_development_campaign.py",
        )
        if prepare is None or prepare.loader is None:
            raise RuntimeError("could not load preparation script")
        preparation = importlib.util.module_from_spec(prepare)
        prepare.loader.exec_module(preparation)
        runner = _load_script()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "bundle"
            preparation.build_bundle(root=ROOT, out_dir=bundle, created_at="2026-09-09T00:00:00Z")
            manifest = runner.validate_bundle(bundle)["manifest"]
            run_dir = root / "run"
            run_dir.mkdir()
            events_path = run_dir / "events.jsonl"
            store = PersistentEventStore(events_path)
            machine = CampaignStateMachine("campaign-1", "attempt-1", store)
            machine.start({"test": True})
            machine.finish(CampaignStatus.UNSUPPORTED, {"reason": "test"})
            runs_path = run_dir / "runs.jsonl"
            runs_path.write_text(json.dumps({
                "campaign_id": "campaign-1",
                "attempt_id": "attempt-1",
                "status": "unsupported",
                "state": "terminal",
                "terminal": True,
                "result": None,
                "error": None,
                "usage": {},
                "admission_reason": "test",
                "resume_count": 0,
            }) + "\n", encoding="utf-8")
            report = {
                "schema_version": 1,
                "record_type": "development_cloud_proposal_campaign",
                "scope": "source_backed_development_proposal_collection_only",
                "mode": "development",
                "admission_eligible": False,
                "sealed_data_read": False,
                "execution_boundary": "test",
                "bundle_manifest_sha256": manifest["manifest_sha256"],
                "plan_id": manifest["plan_id"],
                "plan_hash": manifest["plan_hash"],
                "preflight": {"status": "transport_and_model_match"},
                "recovered_inflight_attempts": 0,
                "selected_campaign_count": 1,
                "provider_call_count": 0,
                "completed_count": 0,
                "provider_failure_count": 0,
                "no_valid_proposal_count": 0,
                "events_path": str(events_path.resolve()),
                "events_sha256": runner._sha256_file(events_path),
                "runs_path": str(runs_path.resolve()),
                "runs_sha256": runner._sha256_file(runs_path),
                "limitations": [],
            }
            report["report_hash"] = sha256_hex(report)
            (run_dir / "report.json").write_text(json.dumps(report) + "\n", encoding="utf-8")
            self.assertEqual(runner.validate_run_report(bundle, run_dir), [])

    def test_compiler_loads_public_storage_symbol_path(self) -> None:
        runner = _load_script()
        pack = {
            "lineage_id": "chainbridge",
            "public_files": {
                "storage_symbols.json": {
                    "symbols": [
                        {
                            "symbol_id": "storage.Bridge.slot_0._paused",
                            "path": "contracts/Bridge.sol",
                            "name": "_paused",
                            "domain": "shared",
                            "kind": "storage",
                            "type": "bool",
                        }
                    ]
                }
            },
        }
        compiler = runner._compiler_for_pack(pack)
        result = compiler.compile({
            "kind": "invariant",
            "body": {
                "kind": "binary",
                "operator": "eq",
                "left": {"kind": "symbol", "symbol_id": "storage.Bridge.slot_0._paused", "state": "post"},
                "right": {"kind": "symbol", "symbol_id": "storage.Bridge.slot_0._paused", "state": "pre"},
            },
        })
        self.assertTrue(result.ok, [diagnostic.as_dict() for diagnostic in result.diagnostics])

    def test_prepared_bundle_validates_without_provider_calls(self) -> None:
        prepare = importlib.util.spec_from_file_location(
            "crossllm_prepare_for_runner",
            ROOT / "scripts" / "prepare_development_campaign.py",
        )
        if prepare is None or prepare.loader is None:
            raise RuntimeError("could not load preparation script")
        preparation = importlib.util.module_from_spec(prepare)
        prepare.loader.exec_module(preparation)
        runner = _load_script()
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "bundle"
            preparation.build_bundle(root=ROOT, out_dir=bundle, created_at="2026-09-09T00:00:00Z")
            inputs = runner.validate_bundle(bundle)
            self.assertFalse(inputs["manifest"]["admission_eligible"])
            self.assertEqual(inputs["manifest"]["campaign_count"], 36)

    def test_manifest_self_hash_is_verified_without_fixed_point(self) -> None:
        prepare = importlib.util.spec_from_file_location(
            "crossllm_prepare_for_runner_hash",
            ROOT / "scripts" / "prepare_development_campaign.py",
        )
        if prepare is None or prepare.loader is None:
            raise RuntimeError("could not load preparation script")
        preparation = importlib.util.module_from_spec(prepare)
        prepare.loader.exec_module(preparation)
        runner = _load_script()
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "bundle"
            preparation.build_bundle(root=ROOT, out_dir=bundle, created_at="2026-09-09T00:00:00Z")
            manifest = runner.validate_bundle(bundle)["manifest"]
            self.assertRegex(manifest["manifest_sha256"], r"^[0-9a-f]{64}$")
            (bundle / "config.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                runner.validate_bundle(bundle)

    def test_inflight_attempt_is_recovered_as_uncertain_without_new_attempt_id(self) -> None:
        module = _load_script()
        with tempfile.TemporaryDirectory() as directory:
            events_path = Path(directory) / "events.jsonl"
            store = PersistentEventStore(events_path)
            store.append(EventLog(
                event_id="event-start",
                event_type="campaign_started",
                campaign_id="campaign-1",
                attempt_id="attempt-1",
                timestamp="2026-09-09T00:00:00Z",
                payload={"controller": "test"},
                monotonic_seconds=1.0,
            ))
            self.assertEqual(module._recover_inflight_attempts(store), 1)
            self.assertEqual(len(store.events), 2)
            self.assertEqual(store.events[-1].event_type, "attempt_uncertain")
            self.assertEqual(store.events[-1].attempt_id, "attempt-1")
            self.assertEqual(module._recover_inflight_attempts(store), 0)


if __name__ == "__main__":
    unittest.main()
