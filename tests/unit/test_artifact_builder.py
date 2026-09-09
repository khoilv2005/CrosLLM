from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from crossllm.artifacts import ArtifactBuilder, ArtifactPackSelector, ArtifactSymbol, extract_storage_symbols


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

    def test_selector_resolves_relative_imports_and_documents_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "contracts").mkdir()
            (root / "docs").mkdir()
            (root / "contracts" / "Bridge.sol").write_text(
                'import "./Lib.sol";\ncontract Bridge {}\n', encoding="utf-8"
            )
            (root / "contracts" / "Lib.sol").write_text("library Lib {}\n", encoding="utf-8")
            (root / "docs" / "scope.md").write_text("public scope\n", encoding="utf-8")
            selector = ArtifactPackSelector()
            first = selector.select(root, ["contracts/Bridge.sol"], document_paths=["docs/scope.md"])
            second = selector.select(root, ["contracts/Bridge.sol"], document_paths=["docs/scope.md"])
            self.assertEqual(first.as_dict(), second.as_dict())
            self.assertEqual(
                first.selected_paths,
                ("contracts/Bridge.sol", "contracts/Lib.sol", "docs/scope.md"),
            )
            self.assertEqual(len(first.selection_hash), 64)

    def test_selector_fails_closed_on_unresolved_imports_and_private_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Bridge.sol").write_text('import "missing.sol";\ncontract Bridge {}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unresolved imports"):
                ArtifactPackSelector().select(root, ["Bridge.sol"])
            with self.assertRaisesRegex(ValueError, "private material"):
                ArtifactPackSelector().select(root, ["gold_property.sol"])

    def test_storage_symbol_extraction_requires_explicit_domains_and_skips_lossy_types(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            layouts = root / "storage_layout"
            layouts.mkdir()
            (layouts / "Bridge.json").write_text(
                '{"storage":['
                '{"contract":"contracts/Bridge.sol:Bridge","label":"nonce","slot":"1","type":"t_uint256"},'
                '{"contract":"contracts/Bridge.sol:Bridge","label":"spent","slot":"2","type":"t_mapping(t_bytes32,t_bool)"}'
                ']}',
                encoding="utf-8",
            )
            result = extract_storage_symbols(root, {"Bridge": "source"})
            self.assertEqual(result.symbols[0].symbol_id, "storage.Bridge.slot_1.nonce")
            self.assertEqual(result.symbols[0].domain, "source")
            self.assertEqual(result.skipped[0].reason, "unsupported_or_lossy_type")
            with self.assertRaisesRegex(ValueError, "invalid contract domains"):
                extract_storage_symbols(root, {"Bridge": "automatic"})


if __name__ == "__main__":
    unittest.main()
