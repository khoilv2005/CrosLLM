from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from crossllm.adjudication import (
    AdjudicationLedger,
    BlindedFinding,
    FirstFailure,
    Label,
    LabelStatus,
    MappingStatus,
    RequirementMapping,
)


class AdjudicationTests(unittest.TestCase):
    def finding(self, finding_id: str = "f1", root_cause_id: str | None = "r1") -> BlindedFinding:
        return BlindedFinding(finding_id, "instance-1", {"location": "Bridge.send"}, root_cause_id=root_cause_id)

    def label(self, rater_id: str, status: LabelStatus = LabelStatus.CONFIRMED, failure: FirstFailure = FirstFailure.TRUE_VULNERABILITY) -> Label:
        return Label("f1", rater_id, "expert", status, failure, created_at="t")

    def test_blinded_export_omits_method_identity_and_is_hash_addressed(self) -> None:
        ledger = AdjudicationLedger([self.finding()])
        exported = ledger.export_blinded()
        self.assertFalse(exported["method_identity_included"])
        self.assertEqual(exported["findings"][0]["finding_id"], "f1")
        self.assertEqual(len(exported["export_id"]), 64)

    def test_two_independent_labels_and_third_reconciliation_are_preserved(self) -> None:
        ledger = AdjudicationLedger([self.finding()])
        ledger.add_label(self.label("r1"))
        ledger.add_label(self.label("r2"))
        result = ledger.reconcile("f1", adjudicator_id="r3", reason="both labels agree", created_at="t")
        self.assertEqual(result.status, LabelStatus.CONFIRMED)
        self.assertEqual(len(result.label_ids), 2)
        self.assertEqual(result.rater_roles, ("expert", "expert"))
        self.assertTrue(result.role_overlap)
        with self.assertRaisesRegex(ValueError, "overwrite"):
            ledger.add_label(self.label("r1"))

    def test_reconciliation_requires_exactly_two_pre_consensus_labels(self) -> None:
        ledger = AdjudicationLedger([self.finding()])
        ledger.add_label(self.label("r1"))
        ledger.add_label(self.label("r2"))
        ledger.add_label(self.label("r4"))
        with self.assertRaisesRegex(ValueError, "exactly two"):
            ledger.reconcile("f1", adjudicator_id="r3", reason="too many labels")

    def test_disagreement_is_unresolved_until_explicit_reason_and_relabel_is_history(self) -> None:
        ledger = AdjudicationLedger([self.finding()])
        ledger.add_label(self.label("r1"))
        ledger.add_label(self.label("r2", LabelStatus.REJECTED, FirstFailure.REPLAY_FAILURE))
        with self.assertRaisesRegex(ValueError, "disagreement"):
            ledger.reconcile("f1", adjudicator_id="r3", reason="disagree")
        result = ledger.reconcile(
            "f1", adjudicator_id="r3", reason="needs source review", uncertainty_reason="labels disagree", created_at="t"
        )
        self.assertEqual(result.status, LabelStatus.UNRESOLVED)
        event = ledger.relabel("f1", LabelStatus.REJECTED, actor_id="r3", reason="new independent evidence", created_at="t2")
        self.assertEqual(event.previous_status, LabelStatus.UNRESOLVED)
        self.assertEqual(len(ledger.relabel_history), 1)

    def test_requirement_mapping_is_separate_from_downstream_success(self) -> None:
        ledger = AdjudicationLedger([self.finding()])
        ledger.map_requirement(RequirementMapping("f1", "req-1", MappingStatus.MAPPED, "reviewer", "claim maps to gold requirement", "t"))
        self.assertEqual(ledger.requirement_mappings[0].requirement_id, "req-1")
        with self.assertRaisesRegex(ValueError, "requirement_id"):
            RequirementMapping("f1", "req-2", MappingStatus.UNCERTAIN, "reviewer", "uncertain", "t")

    def test_root_cause_dedup_keeps_one_finding_per_instance_and_root_cause(self) -> None:
        ledger = AdjudicationLedger([self.finding("f1", "r1"), self.finding("f2", "r1"), self.finding("f3", "r2")])
        self.assertEqual(ledger.deduplicated_finding_ids(), ("f1", "f3"))

    def test_blinded_export_and_labels_round_trip_without_method_identity(self) -> None:
        ledger = AdjudicationLedger([self.finding()])
        ledger.add_label(self.label("r1"))
        ledger.add_label(self.label("r2"))
        blinded = ledger.export_blinded()
        restored = AdjudicationLedger.from_blinded(blinded)
        restored.import_labels(ledger.export_labels())
        self.assertEqual(restored.labels, ledger.labels)
        self.assertFalse(restored.export_blinded()["method_identity_included"])

    def test_complete_ledger_json_round_trip_preserves_consensus_and_history(self) -> None:
        ledger = AdjudicationLedger([self.finding()])
        ledger.add_label(self.label("r1"))
        ledger.add_label(self.label("r2"))
        ledger.reconcile("f1", adjudicator_id="r3", reason="reviewed", created_at="t")
        ledger.relabel("f1", LabelStatus.REJECTED, actor_id="r3", reason="new evidence", created_at="t2")
        ledger.map_requirement(RequirementMapping("f1", "req-1", MappingStatus.MAPPED, "reviewer", "mapped", "t3"))
        restored = AdjudicationLedger.from_dict(ledger.as_dict())
        self.assertEqual(restored.as_dict(), ledger.as_dict())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            ledger.write_json(path)
            self.assertEqual(AdjudicationLedger.load_json(path).as_dict(), ledger.as_dict())

    def test_blinded_claim_rejects_method_and_backbone_leakage(self) -> None:
        with self.assertRaisesRegex(ValueError, "method identity"):
            BlindedFinding("f1", "instance-1", {"method": "X", "location": "Bridge.send"})


if __name__ == "__main__":
    unittest.main()
