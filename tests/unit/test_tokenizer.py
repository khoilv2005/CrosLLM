from __future__ import annotations

import unittest

from crossllm.providers import ExactTokenCounter, TokenizationError, TokenizerIdentity


class TokenizerTests(unittest.TestCase):
    def counter(self) -> ExactTokenCounter:
        identity = TokenizerIdentity("test-encoding", "rev-1", "artifact-sha256")
        return ExactTokenCounter(identity, lambda text: list(range(len(text))))

    def test_prompt_and_generated_counts_use_pinned_identity(self) -> None:
        measurement = self.counter().measure("prompt", "answer")
        self.assertEqual(measurement.prompt_tokens, 6)
        self.assertEqual(measurement.generated_tokens, 6)
        self.assertEqual(measurement.tokenizer.encoding_id, "test-encoding")
        self.assertEqual(len(measurement.tokenizer.identity_hash), 64)
        self.assertFalse(measurement.missing_field_reasons)

    def test_missing_text_and_encoder_failure_remain_unknown(self) -> None:
        missing = self.counter().measure("prompt", None)
        self.assertEqual(missing.prompt_tokens, 6)
        self.assertIsNone(missing.generated_tokens)
        self.assertEqual(missing.missing_field_reasons["generated_tokens"], "generated_text_unavailable")

        failing = ExactTokenCounter(
            TokenizerIdentity("test", "rev", "hash"),
            lambda _text: (_ for _ in ()).throw(RuntimeError("not installed")),
        )
        with self.assertRaisesRegex(TokenizationError, "encoder_failed"):
            failing.count("prompt")

    def test_approximation_or_invalid_token_ids_are_rejected(self) -> None:
        string_result = ExactTokenCounter(TokenizerIdentity("test", "rev", "hash"), lambda _text: "tokens")
        with self.assertRaisesRegex(TokenizationError, "sequence"):
            string_result.count("prompt")
        invalid = ExactTokenCounter(TokenizerIdentity("test", "rev", "hash"), lambda _text: [0, -1])
        with self.assertRaisesRegex(TokenizationError, "invalid token"):
            invalid.count("prompt")


if __name__ == "__main__":
    unittest.main()
