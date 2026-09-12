from __future__ import annotations

import hashlib
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest

from crossllm.replay import EVMReplaySpec
from crossllm.verification import (
    CandidateInput,
    PairKey,
    SharedVerificationPipeline,
    SourceBackedVerificationExecutors,
    SourceCommandSpec,
    StageStatus,
)
from crossllm.verification.adapter import public_xlir_symbols
from crossllm.verification.runtime import load_case_runtime

from tests.unit.test_runtime_binding import RuntimeBindingTests
from scripts.run_verification_stage import load_source_executors


class SourceVerificationExecutorTests(unittest.TestCase):
    def _setup(self):
        helper = RuntimeBindingTests()
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        root, lineage = helper._fixture()
        case = replace(load_case_runtime(root, lineage, "eval_fixture_mut_01"), missing_fields=())
        candidate = CandidateInput(
            campaign_id="source-campaign",
            attempt_id="source-attempt",
            pair_key=PairKey(lineage, "eval_fixture_mut_01", 1),
            arm="crossllm",
            slot_index=0,
            slot_id="source-attempt:slot:0",
            proposal_status="candidate",
            canonical_ast_hash=None,
            raw_response_hash=None,
            candidate={
                "kind": "invariant",
                "invariant_id": "flag-cleared",
                "body": {"kind": "binary", "operator": "eq",
                    "left": {"kind": "symbol", "symbol_id": "storage.Bridge.slot_0.flag", "state": "post"},
                    "right": {"kind": "literal", "type": "bool", "value": False}},
            },
            raw_response={},
        )
        return root, lineage, case, candidate

    def _command(self, root: Path, adapter_id: str, code: str, *, include_witness: bool = False) -> SourceCommandSpec:
        arguments = ("-c", code, "{request}", "{witness}") if include_witness else ("-c", code, "{request}")
        return SourceCommandSpec(
            adapter_id=adapter_id,
            executable=sys.executable,
            arguments=arguments,
            workdir=root,
            tool_revision="test-tool-v1",
            container_ref="registry.example/crossllm-test@sha256:" + "a" * 64,
            timeout_seconds=2.0,
        )

    def _replay(self, code: str, workdir: Path) -> EVMReplaySpec:
        return EVMReplaySpec(
            adapter_id="independent-test-evm",
            executable=sys.executable,
            arguments=("-c", code, "{witness}"),
            tool_revision="evm-test-v1",
            container_ref="registry.example/evm-test@sha256:" + "b" * 64,
            artifact_hash="c" * 64,
            initialization_hash="d" * 64,
            profile_hash="e" * 64,
            semantic_engine="independent-test-engine",
            timeout_seconds=2.0,
        )

    def test_source_tools_complete_all_shared_stages_with_identity_checks(self) -> None:
        root, lineage, case, candidate = self._setup()
        search_code = (
            "import json,sys; r=json.load(open(sys.argv[1])); "
            "a=r['actions'][0]; w={'witness_id':'w1','query_id':'q1','runtime_hash':r['runtime_hash'],"
            "'artifact_hash':r['artifact_hash'],'deployment_hash':r['deployment_hash'],"
            "'canonical_ast_hash':r['canonical_ast_hash'],'initial_state_hash':r['initial_state_hash'],"
            "'trace_hash':'f'*64,'actions':[{'action_id':a['action_id'],'caller':'user','caller_role':a['caller_role'],"
            "'calldata':'0x','domain':a['domain'],'contract':a['contract'],'selector':a['selector']}],"
            "'domains':['DomainA','DomainB'],'observations':[]}; "
            "print(json.dumps({'status':'sat','complete':True,'candidate_violation':True,'witness':w}))"
        )
        witness_code = (
            "import json,sys; r=json.load(open(sys.argv[1])); w=r['witness']; "
            "print(json.dumps({'status':'pass','trace_hash':w['trace_hash'],"
            "'candidate_violation':True,'property_holds':False}))"
        )
        replay_code = (
            "import json,sys; w=json.load(open(sys.argv[1])); "
            "print(json.dumps({'status':'pass','trace_hash':w['trace_hash'],"
            "'property_holds':False,'security_relevance':True}))"
        )
        search = self._command(root, "source-search", search_code)
        witness = self._command(root, "source-witness", witness_code, include_witness=True)
        replay = self._replay(replay_code, root)
        with SourceBackedVerificationExecutors(
            search=search, witness=witness, replay=replay, replay_workdir=root,
        ) as external:
            outcome = SharedVerificationPipeline(
                case, public_xlir_symbols(root, lineage), executors=external.executors(),
            ).verify(candidate)
        self.assertEqual(outcome.stage_status("symbolic_search"), StageStatus.PASSED)
        self.assertEqual(outcome.stage_status("witness_check"), StageStatus.PASSED)
        self.assertEqual(outcome.stage_status("independent_replay"), StageStatus.PASSED)
        witness_evidence = next(stage for stage in outcome.stages if stage.stage == "witness_check").evidence
        self.assertIsInstance(witness_evidence, dict)
        self.assertEqual(witness_evidence["witness_id"], "w1")
        self.assertEqual(len(witness_evidence["witness_hash"]), 64)
        self.assertEqual(witness_evidence["witness"]["trace_hash"], "f" * 64)
        self.assertTrue(outcome.verified_finding)

    def test_source_tools_receive_fresh_case_workspace_and_dynamic_addresses(self) -> None:
        root, lineage, case, candidate = self._setup()
        case = replace(case, missing_fields=("actor_addresses", "contract_addresses"))
        case_root = root / "dataset" / "artifacts" / lineage / "cases" / case.runtime.case_id
        harness_root = root / "dataset" / "harness" / lineage
        (harness_root / "contracts").mkdir(parents=True, exist_ok=True)
        (harness_root / "test").mkdir(parents=True, exist_ok=True)
        (harness_root / "contracts" / "Bridge.sol").write_text("contract BaseBridge {}\n", encoding="utf-8")
        (harness_root / "test" / "Base.t.sol").write_text("contract BaseTest {}\n", encoding="utf-8")
        source = case_root / "runtime" / "source" / "Bridge.sol"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("contract MutatedBridge {}\n", encoding="utf-8")
        paired_test = case_root / "runtime" / "test" / "Replay.t.sol"
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        test_hash = hashlib.sha256(paired_test.read_bytes()).hexdigest()
        metadata = json.loads((case_root / "metadata.json").read_text(encoding="utf-8"))
        metadata.update({"split": "evaluation", "built_source_sha256": source_hash})
        (case_root / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        build = json.loads((case_root / "build_manifest.json").read_text(encoding="utf-8"))
        build["source"] = {"path": "runtime/source/Bridge.sol", "sha256": source_hash}
        (case_root / "build_manifest.json").write_text(json.dumps(build), encoding="utf-8")
        paired = json.loads((case_root / "paired_harness.json").read_text(encoding="utf-8"))
        paired["test"] = {"path": "runtime/test/Replay.t.sol", "sha256": test_hash}
        (case_root / "paired_harness.json").write_text(json.dumps(paired), encoding="utf-8")
        (case_root / "source_identity.json").write_text(json.dumps({
            "lineage_id": lineage,
            "upstream_source_path": "contracts/Bridge.sol",
        }), encoding="utf-8")

        search_code = (
            "import json,sys; from pathlib import Path; r=json.load(open(sys.argv[1])); "
            "w=Path(r['source_workspace']); assert (w/'contracts/Bridge.sol').read_text()=='contract MutatedBridge {}\\n'; "
            "assert (w/'test/Replay.t.sol').is_file(); a=r['actions'][0]; "
            "witness={'witness_id':'w1','query_id':'q1','runtime_hash':r['runtime_hash'],"
            "'artifact_hash':r['artifact_hash'],'deployment_hash':r['deployment_hash'],"
            "'canonical_ast_hash':r['canonical_ast_hash'],'initial_state_hash':r['initial_state_hash'],"
            "'trace_hash':'f'*64,'actions':[{'action_id':a['action_id'],'caller':'user','caller_role':a['caller_role'],"
            "'calldata':'0x','domain':a['domain'],'contract':a['contract'],'selector':a['selector']}],"
            "'domains':['DomainA'],'observations':[]}; print(json.dumps({'status':'sat','complete':True,"
            "'candidate_violation':True,'witness':witness}))"
        )
        witness_code = (
            "import json,sys; r=json.load(open(sys.argv[1])); "
            "assert r['runtime_request']['source_case_identity']['case_id']=='eval_fixture_mut_01'; "
            "w=r['witness']; print(json.dumps({'status':'pass','trace_hash':w['trace_hash'],"
            "'candidate_violation':True,'property_holds':False}))"
        )
        replay_code = (
            "import json,sys; from pathlib import Path; w=json.load(open(sys.argv[1])); "
            "assert (Path(sys.argv[2])/'contracts/Bridge.sol').is_file(); "
            "print(json.dumps({'status':'pass','trace_hash':w['trace_hash'],"
            "'property_holds':False,'security_relevance':True}))"
        )
        replay = EVMReplaySpec(
            adapter_id="independent-test-evm",
            executable=sys.executable,
            arguments=("-c", replay_code, "{witness}", "{workspace}"),
            tool_revision="evm-test-v2",
            container_ref="registry.example/evm-test@sha256:" + "b" * 64,
            artifact_hash="c" * 64,
            initialization_hash="d" * 64,
            profile_hash="e" * 64,
            semantic_engine="independent-test-engine",
            timeout_seconds=2.0,
        )
        with SourceBackedVerificationExecutors(
            search=self._command(root, "source-search", search_code),
            witness=self._command(root, "source-witness", witness_code, include_witness=True),
            replay=replay,
            replay_workdir=root,
            repo_root=root,
            allow_dynamic_harness_bindings=True,
        ) as external:
            outcome = SharedVerificationPipeline(
                case, public_xlir_symbols(root, lineage), executors=external.executors(),
            ).verify(candidate)
        self.assertEqual(outcome.stage_status("symbolic_search"), StageStatus.PASSED)
        self.assertEqual(outcome.stage_status("witness_check"), StageStatus.PASSED)
        self.assertEqual(outcome.stage_status("independent_replay"), StageStatus.PASSED)
        self.assertTrue(outcome.verified_finding)

    def test_source_replay_trace_mismatch_is_not_verified(self) -> None:
        root, lineage, case, candidate = self._setup()
        search_code = (
            "import json,sys; r=json.load(open(sys.argv[1])); "
            "a=r['actions'][0]; w={'witness_id':'w1','query_id':'q1','runtime_hash':r['runtime_hash'],"
            "'artifact_hash':r['artifact_hash'],'deployment_hash':r['deployment_hash'],"
            "'canonical_ast_hash':r['canonical_ast_hash'],'initial_state_hash':r['initial_state_hash'],"
            "'trace_hash':'f'*64,'actions':[{'action_id':a['action_id'],'caller':'user','caller_role':a['caller_role'],"
            "'calldata':'0x','domain':a['domain'],'contract':a['contract'],'selector':a['selector']}],"
            "'domains':['DomainA'],'observations':[]}; "
            "print(json.dumps({'status':'sat','complete':True,'candidate_violation':True,'witness':w}))"
        )
        witness_code = (
            "import json,sys; w=json.load(open(sys.argv[1]))['witness']; "
            "print(json.dumps({'status':'pass','trace_hash':w['trace_hash'],"
            "'candidate_violation':True,'property_holds':False}))"
        )
        replay_code = "import json; print(json.dumps({'status':'pass','trace_hash':'0'*64,'property_holds':False,'security_relevance':True}))"
        with SourceBackedVerificationExecutors(
            search=self._command(root, "source-search", search_code),
            witness=self._command(root, "source-witness", witness_code, include_witness=True),
            replay=self._replay(replay_code, root),
            replay_workdir=root,
        ) as external:
            outcome = SharedVerificationPipeline(
                case, public_xlir_symbols(root, lineage), executors=external.executors(),
            ).verify(candidate)
        self.assertEqual(outcome.stage_status("independent_replay"), StageStatus.FAILED)
        self.assertFalse(outcome.verified_finding is True)

    def test_source_timeout_preserves_missingness(self) -> None:
        root, lineage, case, candidate = self._setup()
        search_code = "import json; print(json.dumps({'status':'timeout','complete':False}))"
        witness_code = "import json; print(json.dumps({'status':'unsupported'}))"
        replay_code = "import json; print(json.dumps({'status':'unsupported'}))"
        with SourceBackedVerificationExecutors(
            search=self._command(root, "source-search", search_code),
            witness=self._command(root, "source-witness", witness_code, include_witness=True),
            replay=self._replay(replay_code, root),
            replay_workdir=root,
        ) as external:
            outcome = SharedVerificationPipeline(
                case, public_xlir_symbols(root, lineage), executors=external.executors(),
            ).verify(candidate)
        self.assertEqual(outcome.stage_status("symbolic_search"), StageStatus.TIMEOUT)
        self.assertEqual(outcome.stage_status("witness_check"), StageStatus.NOT_APPLICABLE)
        self.assertIsNone(outcome.verified_finding)

    def test_source_witness_rejects_wrong_caller_and_invalid_calldata(self) -> None:
        root, lineage, case, candidate = self._setup()

        def run_bad_search(caller_role: str, calldata: str):
            search_code = (
                "import json,sys; r=json.load(open(sys.argv[1])); a=r['actions'][0]; "
                "w={'witness_id':'w1','query_id':'q1','runtime_hash':r['runtime_hash'],"
                "'artifact_hash':r['artifact_hash'],'deployment_hash':r['deployment_hash'],"
                "'canonical_ast_hash':r['canonical_ast_hash'],'initial_state_hash':r['initial_state_hash'],"
                "'trace_hash':'f'*64,'actions':[{'action_id':a['action_id'],'caller':'user',"
                + f"'caller_role':{caller_role!r},'calldata':{calldata!r},"
                + "'domain':a['domain'],'contract':a['contract'],'selector':a['selector']}],"
                "'domains':['DomainA'],'observations':[]}; "
                "print(json.dumps({'status':'sat','complete':True,'candidate_violation':True,'witness':w}))"
            )
            with SourceBackedVerificationExecutors(
                search=self._command(root, "source-search", search_code),
                witness=self._command(root, "source-witness", "import json; print(json.dumps({'status':'unsupported'}))", include_witness=True),
                replay=self._replay("import json; print(json.dumps({'status':'unsupported'}))", root),
                replay_workdir=root,
            ) as external:
                return SharedVerificationPipeline(
                    case, public_xlir_symbols(root, lineage), executors=external.executors(),
                ).verify(candidate)

        invalid_calldata = run_bad_search("user", "0x0")
        self.assertEqual(invalid_calldata.stage_status("symbolic_search"), StageStatus.UNKNOWN)
        self.assertEqual(invalid_calldata.first_failure, "symbolic_search")
        wrong_caller = run_bad_search("attacker", "0x00")
        self.assertEqual(wrong_caller.stage_status("symbolic_search"), StageStatus.UNKNOWN)

    def test_source_unsupported_backend_status_is_preserved(self) -> None:
        root, lineage, case, candidate = self._setup()
        with SourceBackedVerificationExecutors(
            search=self._command(root, "source-search", "import json; print(json.dumps({'status':'unsupported','complete':False}))"),
            witness=self._command(root, "source-witness", "import json; print(json.dumps({'status':'unsupported'}))", include_witness=True),
            replay=self._replay("import json; print(json.dumps({'status':'unsupported'}))", root),
            replay_workdir=root,
        ) as external:
            outcome = SharedVerificationPipeline(
                case, public_xlir_symbols(root, lineage), executors=external.executors(),
            ).verify(candidate)
        self.assertEqual(outcome.stage_status("symbolic_search"), StageStatus.UNSUPPORTED)
        self.assertEqual(outcome.first_failure, "symbolic_search")

    def test_runner_loads_explicit_pinned_executor_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {
                "search": {
                    "adapter_id": "search",
                    "executable": sys.executable,
                    "arguments": ["-c", "print('{}')", "{request}"],
                    "workdir": ".",
                    "tool_revision": "search-v1",
                    "container_ref": "registry.example/search@sha256:" + "a" * 64,
                },
                "witness": {
                    "adapter_id": "witness",
                    "executable": sys.executable,
                    "arguments": ["-c", "print('{}')", "{request}", "{witness}"],
                    "workdir": ".",
                    "tool_revision": "witness-v1",
                    "container_ref": "registry.example/witness@sha256:" + "b" * 64,
                },
                "replay": {
                    "adapter_id": "replay",
                    "executable": sys.executable,
                    "arguments": ["-c", "print('{}')", "{witness}"],
                    "workdir": ".",
                    "tool_revision": "replay-v1",
                    "container_ref": "registry.example/replay@sha256:" + "c" * 64,
                    "artifact_hash": "d" * 64,
                    "initialization_hash": "e" * 64,
                    "profile_hash": "f" * 64,
                    "semantic_engine": "test-evm",
                },
            }
            path = root / "executors.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            executors = load_source_executors(path)
            try:
                self.assertEqual(executors.search_spec.adapter_id, "search")
                self.assertEqual(executors.replay_spec.semantic_engine, "test-evm")
                self.assertEqual(len(executors.spec_hash), 64)
                self.assertEqual(executors.executors().spec_hash, executors.spec_hash)
            finally:
                executors.close()


if __name__ == "__main__":
    unittest.main()
