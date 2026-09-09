from __future__ import annotations

import json
import unittest

from crossllm.methods import OrderedProposalSlots, PromptPolicy, PromptTemplate, ProposalSlotStatus, classify_response
from crossllm.providers import ProviderResponse, TokenBudget, TransportResponse, validate_usage


class MethodSlotTests(unittest.TestCase):
    def response(self, text: str, *, partial: bool = False, error: str | None = None, usage=None) -> ProviderResponse:
        return ProviderResponse("a" * 64, "b" * 64, 200, text, "served", "stop", usage or {"prompt_tokens": 2, "generated_tokens": 3}, 1, partial, error)

    def test_prompt_policy_hash_and_render_are_explicit(self) -> None:
        template = PromptTemplate("crossllm", "v1", "Audit pack:\n{artifact_pack}")
        self.assertEqual(template.render("Bridge.sol"), "Audit pack:\nBridge.sol")
        self.assertEqual(len(template.template_hash), 64)
        with self.assertRaisesRegex(ValueError, "forbids"):
            PromptPolicy(allow_tools=True)

    def test_eight_slots_consume_invalid_abstain_and_truncated_responses(self) -> None:
        slots = OrderedProposalSlots("attempt-1")
        classifications = [
            classify_response(self.response(json.dumps({"abstain": True, "reason": "none"}))),
            classify_response(self.response("not json")),
            classify_response(self.response("partial", partial=True)),
            classify_response(self.response("{}"), candidate={"kind": "invariant"}),
        ]
        expected = [ProposalSlotStatus.ABSTAIN, ProposalSlotStatus.INVALID, ProposalSlotStatus.TRUNCATED, ProposalSlotStatus.CANDIDATE]
        for index, (classification, status) in enumerate(zip(classifications, expected)):
            actual_status, candidate, reason = classification
            self.assertEqual(actual_status, status)
            slots.record(index, actual_status, raw_response_hash="a" * 64, candidate=candidate, reason=reason)
        with self.assertRaisesRegex(ValueError, "already"):
            slots.record(0, ProposalSlotStatus.INVALID)
        self.assertFalse(slots.complete())

    def test_usage_caps_and_unknown_usage_are_separate(self) -> None:
        self.assertEqual(validate_usage(self.response("{}"), TokenBudget(2, 3)).status.value, "pass")
        self.assertEqual(validate_usage(self.response("{}", usage={"prompt_tokens": 3, "generated_tokens": 1}), TokenBudget(2, 3)).reason, "input_token_cap_exceeded")
        self.assertEqual(validate_usage(self.response("{}", usage={"prompt_tokens": None, "generated_tokens": 1})).status.value, "unknown")

    def test_provider_failure_consumes_a_slot(self) -> None:
        status, candidate, reason = classify_response(self.response("", error="transport_failure"))
        self.assertEqual(status, ProposalSlotStatus.PROVIDER_FAILURE)
        self.assertIsNone(candidate)
        self.assertEqual(reason, "transport_failure")


if __name__ == "__main__":
    unittest.main()
