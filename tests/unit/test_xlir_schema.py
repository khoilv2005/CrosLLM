from __future__ import annotations

import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator


class XLIRSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "schemas" / "xlir_proposal.schema.json"
        cls.schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema)

    def assert_valid(self, payload: dict[str, object]) -> None:
        errors = list(self.validator.iter_errors(payload))
        self.assertEqual(errors, [], errors)

    def test_invariant_and_abstention_shapes_are_valid(self) -> None:
        self.assert_valid({
            "kind": "invariant",
            "body": {
                "kind": "binary", "operator": "eq",
                "left": {"kind": "literal", "type": "uint256", "value": 7},
                "right": {"kind": "literal", "type": "uint256", "value": 7},
            },
        })
        self.assert_valid({"abstain": True, "reason": "not grounded"})

    def test_schema_rejects_unknown_fields_and_invalid_typed_literals(self) -> None:
        unknown = {
            "kind": "invariant",
            "body": {"kind": "literal", "type": "bool", "value": True, "secret": "leak"},
        }
        self.assertTrue(list(self.validator.iter_errors(unknown)))
        invalid = {
            "kind": "invariant",
            "body": {"kind": "literal", "type": "address", "value": "0x1234"},
        }
        self.assertTrue(list(self.validator.iter_errors(invalid)))

    def test_schema_covers_extended_operator_and_finite_construct_shapes(self) -> None:
        self.assert_valid({
            "kind": "invariant",
            "body": {
                "kind": "temporal", "operator": "globally",
                "operand": {
                    "kind": "quantifier", "operator": "forall",
                    "variable": "nonce", "variable_type": "uint256",
                    "domain": [{"kind": "literal", "type": "uint256", "value": 0}],
                    "body": {
                        "kind": "binary", "operator": "sar",
                        "left": {"kind": "literal", "type": "int256", "value": -4},
                        "right": {"kind": "literal", "type": "uint256", "value": 1},
                    },
                },
            },
        })


if __name__ == "__main__":
    unittest.main()
