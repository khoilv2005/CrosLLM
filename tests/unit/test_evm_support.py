from __future__ import annotations

import unittest

from crossllm.replay import EVMExecutionSupportMatrix, SupportEntry, SupportStatus


class EVMExecutionSupportMatrixTests(unittest.TestCase):
    def _matrix(self, entries: tuple[SupportEntry, ...], **kwargs: object) -> EVMExecutionSupportMatrix:
        return EVMExecutionSupportMatrix(
            matrix_id="evm-scope-v1",
            engine="geth",
            engine_revision="v1",
            entries=entries,
            **kwargs,
        )

    def test_hash_and_admission_are_order_independent(self) -> None:
        entries = (
            SupportEntry("opcode", "CALL", SupportStatus.SUPPORTED),
            SupportEntry("proxy", "eip1967", SupportStatus.CONDITIONAL, condition="implementation resolved"),
            SupportEntry("crypto", "keccak256", SupportStatus.UNKNOWN),
        )
        matrix = self._matrix(entries)
        reversed_matrix = self._matrix(tuple(reversed(entries)))
        self.assertEqual(matrix.matrix_hash, reversed_matrix.matrix_hash)
        self.assertTrue(matrix.admits((("opcode", "CALL"), ("proxy", "eip1967"))))
        self.assertFalse(matrix.admits((("crypto", "keccak256"),)))
        self.assertEqual(matrix.status_for("precompile", "blake2f"), SupportStatus.UNKNOWN)

    def test_owner_acceptance_and_entry_validation(self) -> None:
        with self.assertRaises(ValueError):
            self._matrix((), acceptance_status="owner_accepted")
        with self.assertRaises(ValueError):
            self._matrix(
                (SupportEntry("opcode", "CALL", SupportStatus.SUPPORTED),),
                acceptance_status="owner_accepted", acceptance_owner="owner", accepted_at="2026-09-09", acceptance_agent="codex",
            )
        with self.assertRaises(ValueError):
            self._matrix((SupportEntry("opcode", "CALL", SupportStatus.SUPPORTED), SupportEntry("opcode", "CALL", SupportStatus.UNKNOWN)))
        with self.assertRaises(ValueError):
            SupportEntry("proxy", "eip1967", SupportStatus.CONDITIONAL)

    def test_serialization_rechecks_matrix_hash(self) -> None:
        matrix = self._matrix((SupportEntry("opcode", "CALL", SupportStatus.SUPPORTED),))
        payload = matrix.as_dict()
        self.assertEqual(EVMExecutionSupportMatrix.from_dict(payload).matrix_hash, matrix.matrix_hash)
        payload["matrix_hash"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            EVMExecutionSupportMatrix.from_dict(payload)


if __name__ == "__main__":
    unittest.main()
