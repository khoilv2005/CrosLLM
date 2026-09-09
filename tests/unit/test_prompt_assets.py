from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

from crossllm.methods import MethodTrack, PromptPolicy, PromptTemplate


class PromptAssetTests(unittest.TestCase):
    root = Path(__file__).parents[2]

    def test_public_track_prompts_are_versioned_and_policy_safe(self) -> None:
        expected = {
            MethodTrack.CROSSLLM: "crossllm_proposer_v1.txt",
            MethodTrack.DIRECT: "direct_audit_v1.txt",
            MethodTrack.T0: "t0_proposer_v1.txt",
        }
        for track, filename in expected.items():
            text = (self.root / "prompts" / filename).read_text(encoding="utf-8")
            template = PromptTemplate(
                f"{track.value}-public-v1", "v1", text,
                PromptPolicy(allow_memory=False, allow_tools=False, allow_retrieval=False, proposal_slots=8),
            )
            self.assertEqual(text.count("{artifact_pack}"), 1)
            self.assertEqual(template.policy.proposal_slots, 8)
            self.assertNotIn("post-mortem", text.lower())
            self.assertIn("memory, tools, retrieval", text.lower())

    def test_preflight_probe_is_not_a_proposal_prompt(self) -> None:
        text = (self.root / "protocol" / "preflight_prompt.txt").read_text(encoding="utf-8")
        self.assertNotIn("{artifact_pack}", text)
        self.assertIn("connectivity", text)
        self.assertIn("model identity", text)

    def test_prompt_manifest_hashes_match_files(self) -> None:
        manifest = json.loads((self.root / "prompts" / "manifest.json").read_text(encoding="utf-8"))
        for row in manifest["files"]:
            content = (self.root / row["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(content).hexdigest(), row["sha256"])


if __name__ == "__main__":
    unittest.main()
