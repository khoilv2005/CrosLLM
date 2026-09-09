from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from crossllm.contracts.canonical import sha256_hex
from crossllm.cli import main
from crossllm.runtime import build_protocol_lock


class ProtocolLockTests(unittest.TestCase):
    def protocol(self, *, complete: bool) -> dict[str, object]:
        return {
            "schema_version": 2,
            "status": "PROSPECTIVE_PLANNING_NOT_AN_EXECUTION_LOCK",
            "model_families": ["GLM", "DeepSeek", "Qwen", "gpt-oss"],
            "budgets": {"campaign_wall_seconds": 3600},
            "proposal_slots": 8,
            "evaluation_replicates": 10 if complete else None,
            "missing_execution_fields": [] if complete else ["actual stochastic R"],
        }

    def test_incomplete_prospective_protocol_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing execution fields"):
            build_protocol_lock(
                self.protocol(complete=False), model_lock_hash="a" * 64,
                benchmark_manifest_hash="b" * 64, captured_at="2026-09-08T00:00:00Z",
            )

    def test_complete_lock_is_hash_addressed_and_preserves_scientific_config(self) -> None:
        lock = build_protocol_lock(
            self.protocol(complete=True), model_lock_hash="a" * 64,
            benchmark_manifest_hash="b" * 64, captured_at="2026-09-08T00:00:00Z",
            dependency_hashes={"toolchain": "c" * 64, "prompt": "d" * 64},
        )
        without_hash = dict(lock)
        lock_hash = without_hash.pop("lock_hash")
        self.assertEqual(lock_hash, sha256_hex(without_hash))
        self.assertEqual(lock["status"], "EVALUATION_LOCKED")
        self.assertEqual(lock["missing_execution_fields"], [])
        self.assertEqual(lock["dependency_hashes"]["toolchain"], "c" * 64)

    def test_credential_like_protocol_field_is_rejected(self) -> None:
        protocol = self.protocol(complete=True)
        protocol["secret"] = "must-not-be-copied"
        with self.assertRaisesRegex(ValueError, "credential-like"):
            build_protocol_lock(
                protocol, model_lock_hash="a" * 64,
                benchmark_manifest_hash="b" * 64, captured_at="2026-09-08T00:00:00Z",
            )

    def test_cli_does_not_write_lock_for_current_prospective_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protocol = root / "protocol.json"
            output = root / "protocol.lock.json"
            protocol.write_text(json.dumps(self.protocol(complete=False)), encoding="utf-8")
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                with self.assertRaises(SystemExit) as raised:
                    main([
                        "protocol-lock", "--protocol", str(protocol),
                        "--model-lock-hash", "a" * 64,
                        "--benchmark-manifest-hash", "b" * 64,
                        "--out", str(output),
                    ])
            self.assertEqual(raised.exception.code, 2)
            self.assertFalse(output.exists())
            self.assertIn("missing execution fields", error.getvalue())


if __name__ == "__main__":
    unittest.main()
