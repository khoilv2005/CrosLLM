from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).parents[2] / "scripts" / "select_baseline_subsets.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("crossllm_select_baseline_subsets", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load selection script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BaselineSelectionCliTests(unittest.TestCase):
    def test_cli_writes_a_frozen_record_and_refuses_overwrite(self) -> None:
        module = _load_script()
        rows = [
            {
                "instance_id": f"i{index}",
                "lineage_id": f"l{index % 2}",
                "family": f"f{index % 2}",
                "ground_truth": "positive" if index % 2 else "negative",
            }
            for index in range(8)
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "records.jsonl"
            output = root / "selection.json"
            source.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            self.assertEqual(
                module.main([
                    "--input", str(source), "--output", str(output), "--target-size", "4",
                    "--seed", "7", "--min-lineages", "2", "--min-families", "2",
                ]),
                0,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["target_size"], 4)
            with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                module.main([
                    "--input", str(source), "--output", str(output), "--target-size", "4",
                    "--seed", "7", "--min-lineages", "2", "--min-families", "2",
                ])


if __name__ == "__main__":
    unittest.main()
