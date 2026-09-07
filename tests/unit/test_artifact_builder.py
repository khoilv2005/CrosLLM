from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from crossllm.artifacts import ArtifactBuilder, ArtifactSymbol


class ArtifactBuilderTests(unittest.TestCase):
    def test_build_is_deterministic_and_hashes_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Bridge.sol").write_text("contract Bridge {}\n", encoding="utf-8")
            symbol = ArtifactSymbol("sym.bridge", "Bridge.sol", "Bridge", "shared", "contract", "address")
            first = ArtifactBuilder().build(root, symbols=[symbol])
            second = ArtifactBuilder().build(root, symbols=[symbol])
            self.assertEqual(first.as_dict(), second.as_dict())
            self.assertEqual(first.pack_id, first.as_dict()["pack_id"])
            self.assertEqual(first.symbols_hash, second.symbols_hash)

    def test_private_material_and_escape_paths_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Bridge.sol").write_text("contract Bridge {}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "escapes source_root"):
                ArtifactBuilder().build(root, selected_paths=["../secret.sol"])
            with self.assertRaisesRegex(ValueError, "private material"):
                ArtifactBuilder().build(root, selected_paths=["gold_property.json"])

    def test_symbol_outside_selected_pack_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Bridge.sol").write_text("contract Bridge {}\n", encoding="utf-8")
            symbol = ArtifactSymbol("sym.other", "Other.sol", "Other", "shared", "contract", "address")
            with self.assertRaisesRegex(ValueError, "not in artifact pack"):
                ArtifactBuilder().build(root, selected_paths=["Bridge.sol"], symbols=[symbol])


if __name__ == "__main__":
    unittest.main()
