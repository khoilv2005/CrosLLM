from __future__ import annotations

import unittest
from uuid import UUID

from crossllm.contracts.canonical import canonical_json, sha256_hex
from crossllm.contracts.ids import new_id, require_id
from crossllm.contracts.records import (
    CampaignStatus,
    EventLog,
    SearchStatus,
    validate_event_log,
)


class ContractTests(unittest.TestCase):
    def test_canonical_json_is_order_independent(self) -> None:
        self.assertEqual(canonical_json({"b": 2, "a": 1}), b'{"a":1,"b":2}')
        self.assertEqual(sha256_hex({"a": 1}), sha256_hex({"a": 1}))

    def test_status_values_preserve_protocol_vocabulary(self) -> None:
        self.assertEqual(CampaignStatus.TIMEOUT, "timeout")
        self.assertEqual(SearchStatus.BOUNDED_UNSAT, "bounded_unsat")

    def test_duplicate_terminal_events_are_rejected(self) -> None:
        events = [
            EventLog("e1", "started", "c1", "a1", "2026-09-07T00:00:00Z", {}),
            EventLog("e2", "completed", "c1", "a1", "2026-09-07T00:00:01Z", {}, terminal=True),
            EventLog("e3", "completed", "c1", "a1", "2026-09-07T00:00:02Z", {}, terminal=True),
        ]
        self.assertEqual(validate_event_log(events)[0], "event 3: duplicate terminal event")

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
