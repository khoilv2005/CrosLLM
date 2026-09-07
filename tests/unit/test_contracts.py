from __future__ import annotations

import unittest
import json
from uuid import UUID
from pathlib import Path

from crossllm.contracts.canonical import canonical_json, sha256_hex
from crossllm.contracts.ids import new_id, require_id
from crossllm.contracts.status_mapping import serialize_statuses, validate_statuses
from crossllm.contracts.records import (
    AdjudicationStatus,
    CampaignStatus,
    EventLog,
    ReplayStatus,
    SearchStatus,
    validate_foreign_keys,
    validate_event_log,
)


class ContractTests(unittest.TestCase):
    def test_runtime_schema_declares_all_m01_record_types(self) -> None:
        schema_path = Path(__file__).parents[2] / "schemas" / "runtime_records.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        expected = {
            "campaign", "attempt", "slot", "artifact_pack", "symbol", "xlir_proposal", "direct_claim", "query",
            "witness", "adjudication", "model_lock", "protocol_lock",
            "campaign_plan", "resource_vector", "event",
        }
        self.assertTrue(expected.issubset(schema["$defs"]))
        self.assertEqual(
            set(schema["properties"]["record_type"]["enum"]),
            expected,
        )
        self.assertEqual(schema["properties"]["schema_version"]["const"], 1)

    def test_canonical_json_is_order_independent(self) -> None:
        self.assertEqual(canonical_json({"b": 2, "a": 1}), b'{"a":1,"b":2}')
        self.assertEqual(sha256_hex({"a": 1}), sha256_hex({"a": 1}))

    def test_status_values_preserve_protocol_vocabulary(self) -> None:
        self.assertEqual(CampaignStatus.TIMEOUT, "timeout")
        self.assertEqual(SearchStatus.BOUNDED_UNSAT, "bounded_unsat")

    def test_status_dimensions_are_serialized_without_collapsing_unknown(self) -> None:
        record = serialize_statuses(
            CampaignStatus.COMPLETED,
            SearchStatus.UNKNOWN,
            ReplayStatus.UNSUPPORTED,
            AdjudicationStatus.UNRESOLVED,
        )
        self.assertEqual(validate_statuses(record), [])
        self.assertEqual(record["search_status"], "unknown")
        self.assertEqual(record["replay_status"], "unsupported")

    def test_status_mapping_rejects_unknown_values(self) -> None:
        record = serialize_statuses(CampaignStatus.TIMEOUT)
        record["search_status"] = "unsound"
        self.assertIn("invalid search_status", validate_statuses(record)[0])

    def test_duplicate_terminal_events_are_rejected(self) -> None:
        events = [
            EventLog("e1", "started", "c1", "a1", "2026-09-07T00:00:00Z", {}),
            EventLog("e2", "completed", "c1", "a1", "2026-09-07T00:00:01Z", {}, terminal=True),
            EventLog("e3", "completed", "c1", "a1", "2026-09-07T00:00:02Z", {}, terminal=True),
        ]
        self.assertEqual(validate_event_log(events)[0], "event 3: duplicate terminal event")

    def test_event_log_rejects_backwards_monotonic_time(self) -> None:
        events = [
            EventLog("e1", "started", "c1", "a1", "2026-09-07T00:00:00Z", {}, monotonic_seconds=2),
            EventLog("e2", "finished", "c1", "a1", "2026-09-07T00:00:01Z", {}, monotonic_seconds=1),
        ]
        self.assertIn("monotonic_seconds moved backwards", validate_event_log(events)[0])

    def test_foreign_key_validator_rejects_orphan_records(self) -> None:
        records = [{"record_type": "proposal", "proposal_id": "p1", "campaign_id": "missing"}]
        self.assertIn("orphan campaign_id", validate_foreign_keys(records)[0])

    def test_event_ids_are_unique(self) -> None:
        event = EventLog("e1", "started", "c1", "a1", "2026-09-07T00:00:00Z", {})
        self.assertIn("duplicate event_id", validate_event_log([event, event])[0])

    def test_new_id_is_uuid_and_invalid_foreign_key_is_rejected(self) -> None:
        identifier = new_id()
        self.assertEqual(str(UUID(identifier)), identifier)
        self.assertEqual(require_id(identifier, "campaign_id"), identifier)
        with self.assertRaisesRegex(ValueError, "campaign_id must be a UUID"):
            require_id("campaign-1", "campaign_id")


if __name__ == "__main__":
    unittest.main()
