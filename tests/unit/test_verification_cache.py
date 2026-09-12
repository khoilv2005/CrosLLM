from pathlib import Path
import tempfile
import unittest

from crossllm.contracts.canonical import sha256_hex
from crossllm.verification.cache import FileVerificationCache, VerificationCacheKey


class VerificationCacheTests(unittest.TestCase):
    def test_cache_is_persistent_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "verification-cache.json"
            key = VerificationCacheKey("a" * 64, "b" * 64, "adapter-v1", sha256_hex({"bound": 1}), "c" * 64)
            cache = FileVerificationCache(path)
            self.assertFalse(cache.lookup(key).hit)
            outcome = {"verified_finding": False, "availability": "unknown"}
            cache.put(key, outcome)
            cache.put(key, outcome)
            restored = FileVerificationCache(path)
            lookup = restored.lookup(key)
            self.assertTrue(lookup.hit)
            self.assertEqual(lookup.record["outcome"], outcome)
            self.assertEqual(len(restored), 1)

    def test_same_key_cannot_be_rewritten_with_different_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            key = VerificationCacheKey("a" * 64, "b" * 64, "adapter-v1", "d" * 64)
            cache = FileVerificationCache(Path(directory) / "cache.json")
            cache.put(key, {"status": "passed"})
            with self.assertRaisesRegex(ValueError, "different outcome"):
                cache.put(key, {"status": "failed"})

    def test_bounds_change_produces_a_different_key(self) -> None:
        first = VerificationCacheKey("a" * 64, "b" * 64, "adapter-v1", "c" * 64)
        second = VerificationCacheKey("a" * 64, "b" * 64, "adapter-v1", "d" * 64)
        self.assertNotEqual(first.key_hash, second.key_hash)

    def test_executor_identity_change_produces_a_different_key(self) -> None:
        first = VerificationCacheKey(
            "a" * 64, "b" * 64, "adapter-v1", "c" * 64,
            executor_spec_hash="d" * 64,
        )
        second = VerificationCacheKey(
            "a" * 64, "b" * 64, "adapter-v1", "c" * 64,
            executor_spec_hash="e" * 64,
        )
        self.assertNotEqual(first.key_hash, second.key_hash)


if __name__ == "__main__":
    unittest.main()
