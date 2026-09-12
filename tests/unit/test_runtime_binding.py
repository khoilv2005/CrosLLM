import json
from pathlib import Path
import tempfile
import unittest

from crossllm.verification import CandidateInput, PairKey, SharedVerificationPipeline, StageResult, StageStatus, VerificationExecutors
from crossllm.verification.cache import FileVerificationCache
from crossllm.verification.adapter import AdapterStatus, RuntimeCandidateAdapter, public_xlir_symbols
from crossllm.verification.runtime import BindingStatus, build_runtime_binding_matrix, load_case_runtime


class RuntimeBindingTests(unittest.TestCase):
    def _fixture(self) -> tuple[Path, str]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        lineage = "fixture"
        case_id = "eval_fixture_mut_01"
        lineage_root = root / "dataset" / "artifacts" / lineage
        case_root = lineage_root / "cases" / case_id
        harness_root = root / "dataset" / "harness" / lineage
        (lineage_root / "storage_layout").mkdir(parents=True)
        (case_root / "runtime" / "artifacts").mkdir(parents=True)
        (case_root / "runtime" / "test").mkdir(parents=True)
        harness_root.mkdir(parents=True)

        digest = "a" * 64
        _write(lineage_root / "symbols.json", {
            "stable_symbols": [
                {"symbol_id": "abi_function.Bridge.deposit.1", "contract": "Bridge", "name": "deposit", "signature": "deposit(uint256)", "kind": "abi_function", "domain": "shared"},
                {"symbol_id": "storage.Bridge.slot_0.flag", "contract": "Bridge", "name": "flag", "signature": "storage(0)", "kind": "storage", "domain": "source", "type": "t_bool"},
                {"symbol_id": "storage.Bridge.slot_1.mapping", "contract": "Bridge", "name": "mapping", "signature": "storage(1)", "kind": "storage", "domain": "source", "type": "t_mapping(t_address,t_uint256)"},
            ],
            "domain_assignments": {"Bridge": "source"},
        })
        _write(lineage_root / "scope.json", {"entry_points": ["Bridge.deposit"]})
        _write(lineage_root / "channel_profile.json", {"channel_type": "message", "topology": "paired"})
        (lineage_root / "storage_layout" / "Bridge.json").write_text(json.dumps({"storage": [{"label": "flag", "slot": "0", "offset": 0, "type": "t_bool"}, {"label": "mapping", "slot": "1", "offset": 0, "type": "t_mapping(t_address,t_uint256)"}]}), encoding="utf-8")
        _write(harness_root / "harness_config.json", {
            "source_backed": True,
            "harness_status": "source_backed_development",
            "harness_version": "2.0.0",
            "protocol": "Fixture",
            "test_runner": "foundry",
            "test_contract": "FixtureTest",
            "compiler": {"binary_sha256": digest},
            "domain_pair": {"source": {"name": "DomainA"}, "destination": {"name": "DomainB"}},
            "workflow_coverage": {
                "allowed_actions": {"user": ["Bridge.deposit"]},
                "normal_workflow": {"assertions": ["balance"], "steps": ["deposit"]},
                "state_initialization": {"isolated_per_test": True},
            },
        })
        _write(case_root / "metadata.json", {
            "lineage_id": lineage, "instance_id": case_id,
            "built_source_sha256": digest, "artifact_manifest_sha256": "b" * 64,
            "deployment_config_sha256": "c" * 64,
        })
        _write(case_root / "build_manifest.json", {"artifacts": [{"path": "runtime/artifacts/Bridge.json", "sha256": digest}], "source": {"sha256": digest}})
        _write(case_root / "deployment.json", {"deployment_result": {"status": "success"}, "scope": "local"})
        _write(case_root / "paired_harness.json", {"runner": "foundry", "test": {"path": "runtime/test/Replay.t.sol"}})
        (case_root / "runtime" / "test" / "Replay.t.sol").write_text("contract Replay {}", encoding="utf-8")
        _write(case_root / "runtime" / "artifacts" / "Bridge.json", {
            "abi": [{"type": "function", "name": "deposit", "inputs": []}],
            "methodIdentifiers": {"deposit(uint256)": "d0e30db0"},
        })
        return root, lineage

    def test_case_binds_scalar_storage_and_action_from_public_artifacts(self) -> None:
        root, lineage = self._fixture()
        case = load_case_runtime(root, lineage, "eval_fixture_mut_01")
        flag = next(item for item in case.symbols if item.symbol_id.endswith("flag"))
        action = case.actions[0]
        self.assertEqual(flag.status, BindingStatus.BOUND)
        self.assertEqual(flag.offset_bytes, 0)
        self.assertEqual(action.status, BindingStatus.BOUND)
        self.assertTrue(action.executable)
        self.assertEqual(action.selector, "0xd0e30db0")
        self.assertIn("contract_addresses", case.missing_fields)

    def test_unsupported_storage_type_is_explicit(self) -> None:
        root, lineage = self._fixture()
        case = load_case_runtime(root, lineage, "eval_fixture_mut_01")
        mapping = next(item for item in case.symbols if item.symbol_id.endswith("mapping"))
        self.assertEqual(mapping.status, BindingStatus.UNSUPPORTED)
        self.assertEqual(mapping.reason, "storage_type_not_supported_by_xlir")

    def test_matrix_scans_cases_in_stable_order(self) -> None:
        root, lineage = self._fixture()
        matrix = build_runtime_binding_matrix(root, (lineage,))
        self.assertEqual(len(matrix.cases), 1)
        self.assertEqual(matrix.cases[0].runtime.case_id, "eval_fixture_mut_01")
        self.assertFalse(matrix.as_dict()["gold_fields_read"])

    def test_candidate_is_compiled_and_resolved_without_becoming_verified(self) -> None:
        root, lineage = self._fixture()
        case = load_case_runtime(root, lineage, "eval_fixture_mut_01")
        candidate = CandidateInput(
            campaign_id="campaign",
            attempt_id="attempt",
            pair_key=PairKey(lineage, "eval_fixture_mut_01", 1),
            arm="crossllm",
            slot_index=0,
            slot_id="attempt:slot:0",
            proposal_status="candidate",
            canonical_ast_hash=None,
            raw_response_hash=None,
            candidate={
                "kind": "invariant",
                "invariant_id": "flag-is-true",
                "body": {
                    "kind": "binary", "operator": "eq",
                    "left": {"kind": "symbol", "symbol_id": "storage.Bridge.slot_0.flag", "state": "post"},
                    "right": {"kind": "literal", "type": "bool", "value": True},
                },
            },
            raw_response={},
        )
        plan = RuntimeCandidateAdapter(case, public_xlir_symbols(root, lineage)).adapt(candidate)
        self.assertEqual(plan.status, AdapterStatus.GROUNDED)
        self.assertIsNotNone(plan.canonical_ast_hash)
        self.assertIsNotNone(plan.search_request)
        self.assertFalse(plan.executable)

    def test_unresolved_symbol_is_not_silently_dropped(self) -> None:
        root, lineage = self._fixture()
        case = load_case_runtime(root, lineage, "eval_fixture_mut_01")
        candidate = CandidateInput(
            campaign_id="campaign", attempt_id="attempt", pair_key=PairKey(lineage, "eval_fixture_mut_01", 1),
            arm="crossllm", slot_index=0, slot_id="attempt:slot:0", proposal_status="candidate",
            canonical_ast_hash=None, raw_response_hash=None,
            candidate={
                "kind": "invariant", "body": {"kind": "binary", "operator": "eq",
                    "left": {"kind": "symbol", "symbol_id": "storage.Bridge.slot_0.not_public", "state": "post"},
                    "right": {"kind": "literal", "type": "bool", "value": True}},
            }, raw_response={},
        )
        plan = RuntimeCandidateAdapter(case, public_xlir_symbols(root, lineage)).adapt(candidate)
        self.assertEqual(plan.status, AdapterStatus.INVALID)
        self.assertTrue(any(item.startswith("unresolved_symbol:") for item in plan.diagnostics))

    def test_shared_pipeline_preserves_unconfigured_stage_missingness(self) -> None:
        root, lineage = self._fixture()
        case = load_case_runtime(root, lineage, "eval_fixture_mut_01")
        outcome = SharedVerificationPipeline(case, public_xlir_symbols(root, lineage)).verify(self._candidate(lineage))
        self.assertEqual(outcome.stage_status("grounding"), StageStatus.PASSED)
        self.assertEqual(outcome.stage_status("symbolic_search"), StageStatus.UNSUPPORTED)
        self.assertEqual(outcome.stage_status("witness_check"), StageStatus.NOT_APPLICABLE)
        self.assertIsNone(outcome.verified_finding)

    def test_shared_pipeline_can_verify_only_after_all_common_stages_pass(self) -> None:
        root, lineage = self._fixture()
        case = load_case_runtime(root, lineage, "eval_fixture_mut_01")

        def passed(name: str, evidence: dict[str, object] | None = None):
            return lambda _plan: StageResult(name, StageStatus.PASSED, evidence=evidence)

        executors = VerificationExecutors(
            symbolic_search=passed("symbolic_search"),
            witness_check=passed("witness_check", {"candidate_violation": True, "property_holds": True}),
            independent_replay=passed("independent_replay", {"security_relevance": True}),
        )
        outcome = SharedVerificationPipeline(case, public_xlir_symbols(root, lineage), executors=executors).verify(self._candidate(lineage))
        self.assertTrue(outcome.verified_finding)

    def test_shared_pipeline_resume_uses_cache_without_rerunning_stages(self) -> None:
        root, lineage = self._fixture()
        case = load_case_runtime(root, lineage, "eval_fixture_mut_01")
        with tempfile.TemporaryDirectory() as directory:
            cache = FileVerificationCache(Path(directory) / "cache.json")
            pipeline = SharedVerificationPipeline(case, public_xlir_symbols(root, lineage), cache=cache)
            first = pipeline.verify(self._candidate(lineage))
            second = pipeline.verify(self._candidate(lineage))
        self.assertFalse(first.cache_hit)
        self.assertTrue(second.cache_hit)
        self.assertEqual(first.stage_status("symbolic_search"), second.stage_status("symbolic_search"))
        self.assertEqual(len(cache), 1)

    def _candidate(self, lineage: str) -> CandidateInput:
        return CandidateInput(
            campaign_id="campaign", attempt_id="attempt", pair_key=PairKey(lineage, "eval_fixture_mut_01", 1),
            arm="crossllm", slot_index=0, slot_id="attempt:slot:0", proposal_status="candidate",
            canonical_ast_hash=None, raw_response_hash=None,
            candidate={
                "kind": "invariant", "invariant_id": "flag-is-true",
                "body": {"kind": "binary", "operator": "eq",
                    "left": {"kind": "symbol", "symbol_id": "storage.Bridge.slot_0.flag", "state": "post"},
                    "right": {"kind": "literal", "type": "bool", "value": True}},
            }, raw_response={},
        )


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
