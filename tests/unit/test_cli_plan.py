from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from crossllm.cli import main


class CLIPlanTests(unittest.TestCase):
    def test_plan_command_is_deterministic_and_writes_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            instances = root / "instances.jsonl"
            backbones = root / "backbones.json"
            config = root / "config.json"
            out = root / "plan.json"
            instances.write_text("".join(json.dumps(row) + "\n" for row in [
                {"instance_id": "i1", "lineage_id": "l1"},
                {"instance_id": "i2", "lineage_id": "l2"},
            ]), encoding="utf-8")
            backbones.write_text(json.dumps([{"backbone": "Qwen", "model_tag": "qwen:test"}]), encoding="utf-8")
            config.write_text(json.dumps({"proposal_slots": 8}), encoding="utf-8")
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                code = main([
                    "plan", "--mode", "development", "--instances", str(instances),
                    "--methods", "X,P", "--backbones", str(backbones), "--replicates", "2",
                    "--seed", "7", "--config", str(config), "--out", str(out),
                ])
            payload = json.loads(stream.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["campaign_count"], 8)
            self.assertEqual(len(json.loads(out.read_text(encoding="utf-8"))["campaigns"]), 8)

    def test_evaluation_plan_without_lock_hashes_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            instances = root / "instances.json"
            backbones = root / "backbones.json"
            config = root / "config.json"
            instances.write_text(json.dumps([{"instance_id": "i", "lineage_id": "l"}]), encoding="utf-8")
            backbones.write_text(json.dumps([{ "backbone": "Qwen", "model_tag": "qwen:test" }]), encoding="utf-8")
            config.write_text("{}", encoding="utf-8")
            with self.assertRaises(SystemExit):
                main([
                    "plan", "--mode", "evaluation", "--instances", str(instances),
                    "--methods", "X", "--backbones", str(backbones), "--replicates", "1",
                    "--seed", "1", "--config", str(config), "--out", str(root / "plan.json"),
                ])


if __name__ == "__main__":
    unittest.main()
