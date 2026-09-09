from __future__ import annotations

import unittest

from crossllm.artifacts import (
    ArtifactSymbol,
    SanitizationMap,
    SanitizationMapping,
)


class SanitizationTests(unittest.TestCase):
    def test_trace_rewrites_selector_signature_domains_and_identity_together(self) -> None:
        mapping = SanitizationMap([
            SanitizationMapping("domain", "chainA", "source"),
            SanitizationMapping("domain", "chainB", "destination"),
            SanitizationMapping("selector", "0xdeadbeef", "0x11111111", "source"),
            SanitizationMapping("signature", "send(address,uint256)", "send(bytes32,uint256)", "source"),
            SanitizationMapping("identifier", "0xaaa", "0x001", "source"),
        ])
        result = mapping.rewrite_trace([{
            "domain": "chainA",
            "source_domain": "chainA",
            "destination_domain": "chainB",
            "selector": "0xdeadbeef",
            "signature": "send(address,uint256)",
            "emitter": "0xaaa",
            "opaque_proof": {"private": "not interpreted"},
        }])
        event = result.events[0]
        self.assertEqual(event["domain"], "source")
        self.assertEqual(event["source_domain"], "source")
        self.assertEqual(event["destination_domain"], "destination")
        self.assertEqual(event["selector"], "0x11111111")
        self.assertEqual(event["signature"], "send(bytes32,uint256)")
        self.assertEqual(event["emitter"], "0x001")
        self.assertEqual(result.correspondence.event_count, 1)
        self.assertEqual(len(result.correspondence.sanitized_trace_hash), 64)

    def test_scoped_identifier_and_symbol_domain_are_rewritten(self) -> None:
        mapping = SanitizationMap([
            SanitizationMapping("domain", "chainA", "source"),
            SanitizationMapping("identifier", "secretFlag", "publicFlag", "source"),
            SanitizationMapping("identifier", "storage.secretFlag", "storage.publicFlag", "source"),
        ])
        symbol = ArtifactSymbol("storage.secretFlag", "Bridge.sol", "secretFlag", "source", "storage", "bool")
        public = mapping.rewrite_symbol(symbol)
        self.assertEqual(public.symbol_id, "storage.publicFlag")
        self.assertEqual(public.name, "publicFlag")
        self.assertEqual(public.domain, "source")

    def test_collisions_and_invalid_mappings_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "collision"):
            SanitizationMap([
                SanitizationMapping("selector", "0x1", "0x2"),
                SanitizationMapping("selector", "0x3", "0x2"),
            ])
        with self.assertRaisesRegex(ValueError, "mapping kind"):
            SanitizationMapping("calldata", "a", "b")


if __name__ == "__main__":
    unittest.main()
