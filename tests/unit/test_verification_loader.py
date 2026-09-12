from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from crossllm.verification import ArchiveRoot, ArchiveValidationError, CaseRuntimeSpec, load_archives, match_campaigns


def _archive(campaign_id: str, *, method: str, instance_id: str = "instance-1", failure_slot: int | None = None) -> dict[str, object]:
    attempt_id = f"{campaign_id}:proposal-stage:1"
    slots = []
    responses = []
    budgets = []
    for index in range(8):
        failed = index == failure_slot
        slots.append({
            "slot_id": f"{attempt_id}:slot:{index}",
            "index": index,
            "status": "provider_failure" if failed else "candidate" if index == 0 else "duplicate",
            "candidate": None if failed or index else {"kind": "invariant"},
            "canonical_ast_hash": None,
        })
        responses.append({
            "http_status": 429 if failed else 200,
            "error": "http_failure" if failed else None,
            "response_hash": f"{index:064x}",
            "response_text": "" if failed else "{\"kind\":\"invariant\"}",
        })
        budgets.append({"status": "unknown" if failed else "pass", "prompt_tokens": 10, "generated_tokens": 10, "reason": None})
    return {
        "schema_version": 1,
        "campaign": {
            "campaign_id": campaign_id,
            "attempt_id": attempt_id,
            "lineage_id": "lineage-1",
            "instance_id": instance_id,
            "replicate": 1,
            "method": method,
            "backbone": "gpt-oss",
            "model_tag": "gpt-oss:test",
            "config_hash": "config",
            "request_settings_hash": "settings",
        },
        "public_artifact_pack_hash": "pack",
        "public_artifact_pack": {"gold_access": "disabled"},
        "method_run": {
            "attempt_id": attempt_id,
            "settings": {"temperature": 0.6},
            "artifact_pack_hash": "pack",
            "slots": slots,
            "provider_responses": responses,
            "budget_checks": budgets,
        },
    }


def _write(root: Path, campaign_id: str, row: dict[str, object]) -> None:
    directory = root / campaign_id
    directory.mkdir(parents=True)
    (directory / "campaigns.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")


class VerificationLoaderTests(unittest.TestCase):
    def test_runtime_spec_is_hash_bound_and_rejects_duplicate_capabilities(self) -> None:
        spec = CaseRuntimeSpec(
            case_id="case-1", lineage_id="lineage-1", instance_id="instance-1",
            source_artifact_hash="a" * 64, build_manifest_hash="b" * 64,
            deployment_hash="c" * 64, profile_hash="d" * 64,
            compiler_hash="e" * 64, source_domain="source", destination_domain="destination",
            supported_actions=("enqueue",), observation_points=("post",),
        )
        self.assertEqual(len(spec.runtime_hash), 64)
        with self.assertRaisesRegex(ValueError, "must not contain duplicates"):
            CaseRuntimeSpec(
                case_id="case-1", lineage_id="lineage-1", instance_id="instance-1",
                source_artifact_hash="a" * 64, build_manifest_hash="b" * 64,
                deployment_hash="c" * 64, profile_hash="d" * 64,
                compiler_hash="e" * 64, source_domain="source", destination_domain="destination",
                supported_actions=("enqueue", "enqueue"),
            )

    def test_loads_provider_failures_without_turning_them_into_no_alerts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "cross"
            _write(root, "x1", _archive("x1", method="crossllm_e2e", failure_slot=3))
            dataset = load_archives({"crossllm": root})
        self.assertEqual(len(dataset.campaigns), 1)
        self.assertEqual(dataset.campaigns[0].provider_failure_count, 1)
        self.assertEqual(dataset.campaigns[0].candidate_count, 1)

    def test_pairs_by_instance_and_replicate_not_campaign_id_and_is_order_independent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            cross, direct = base / "cross", base / "direct"
            _write(cross, "cross-id", _archive("cross-id", method="crossllm_e2e"))
            _write(direct, "direct-id", _archive("direct-id", method="direct_llm"))
            dataset = load_archives({"direct": direct, "crossllm": cross})
            pairs = match_campaigns(dataset)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0][0].arm, "crossllm")
        self.assertEqual(pairs[0][1].arm, "direct")

    def test_duplicate_campaign_id_is_rejected_before_queueing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            first, second = base / "first", base / "second"
            _write(first, "same", _archive("same", method="crossllm_e2e"))
            _write(second, "same-copy", _archive("same", method="crossllm_e2e"))
            with self.assertRaisesRegex(ArchiveValidationError, "duplicate campaign_id"):
                load_archives((
                    ArchiveRoot("cross-a", first),
                    ArchiveRoot("cross-b", second),
                ))

    def test_duplicate_pair_arm_is_rejected_even_when_campaign_ids_differ(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "cross"
            _write(root, "first", _archive("first", method="crossllm_e2e"))
            _write(root, "second", _archive("second", method="crossllm_e2e"))
            with self.assertRaisesRegex(ArchiveValidationError, "duplicate pair/arm"):
                load_archives({"crossllm": root})

    def test_planned_ids_reject_unknown_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "cross"
            _write(root, "unknown", _archive("unknown", method="crossllm_e2e"))
            with self.assertRaisesRegex(ArchiveValidationError, "absent from the supplied plan"):
                load_archives({"crossllm": root}, planned_campaign_ids={"known"})

    def test_providerless_t0_archive_keeps_slots_without_fabricating_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "t0"
            row = _archive("t0", method="t0")
            method_run = row["method_run"]
            assert isinstance(method_run, dict)
            method_run["track"] = "T0"
            method_run["provider_responses"] = []
            method_run["budget_checks"] = []
            _write(root, "t0", row)
            dataset = load_archives({"t0": root})
        archive = dataset.campaigns[0]
        self.assertEqual(archive.slot_count, 8)
        self.assertEqual(len(archive.candidate_inputs()), 8)
        self.assertEqual(archive.provider_failure_count, 0)
        self.assertTrue(all(candidate.raw_response == {} for candidate in archive.candidate_inputs()))


if __name__ == "__main__":
    unittest.main()
