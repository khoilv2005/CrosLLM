from __future__ import annotations

import sys
import unittest

from crossllm.contracts import ReplayStatus
from crossllm.replay import EVMReplaySpec, IndependentEVMReplay


class IndependentEVMReplayTests(unittest.TestCase):
    def make_spec(self, code: str, *, executable: str | None = None) -> EVMReplaySpec:
        return EVMReplaySpec(
            adapter_id="reference-evm-subprocess",
            executable=executable or sys.executable,
            arguments=("-c", code),
            tool_revision="adapter-revision-1",
            container_ref="registry.example/evm@sha256:" + "a" * 64,
            artifact_hash="b" * 64,
            initialization_hash="c" * 64,
            profile_hash="d" * 64,
            semantic_engine="independent-reference-engine",
            timeout_seconds=2.0,
        )

    def test_explicit_pass_is_recorded_with_trace_and_io_hashes(self) -> None:
        spec = self.make_spec(
            "import json; print(json.dumps({'status': 'pass', 'trace_hash': '" + "e" * 64 + "'}))"
        )
        result = IndependentEVMReplay().run(spec, self._workdir())
        self.assertEqual(result.status, ReplayStatus.PASS)
        self.assertEqual(result.trace_hash, "e" * 64)
        self.assertEqual(len(result.stdout_hash or ""), 64)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.spec_hash, spec.spec_hash)

    def test_malformed_output_is_unknown(self) -> None:
        spec = self.make_spec("print('not replay json')")
        result = IndependentEVMReplay().run(spec, self._workdir())
        self.assertEqual(result.status, ReplayStatus.UNKNOWN)
        self.assertTrue((result.reason or "").startswith("replay_output_parse_failure:"))

    def test_pass_requires_lowercase_trace_hash(self) -> None:
        missing = self.make_spec("import json; print(json.dumps({'status': 'pass'}))")
        result = IndependentEVMReplay().run(missing, self._workdir())
        self.assertEqual(result.status, ReplayStatus.UNKNOWN)
        self.assertEqual(result.reason, "replay_output_missing_trace_hash")

        malformed = self.make_spec(
            "import json; print(json.dumps({'status': 'pass', 'trace_hash': '" + "E" * 64 + "'}))"
        )
        result = IndependentEVMReplay().run(malformed, self._workdir())
        self.assertEqual(result.status, ReplayStatus.UNKNOWN)
        self.assertEqual(result.reason, "replay_output_invalid_trace_hash")

    def test_nonzero_adapter_exit_is_fail(self) -> None:
        spec = self.make_spec("import sys; print('adapter failure', file=sys.stderr); sys.exit(7)")
        result = IndependentEVMReplay().run(spec, self._workdir())
        self.assertEqual(result.status, ReplayStatus.FAIL)
        self.assertEqual(result.exit_code, 7)
        self.assertEqual(result.reason, "replay_nonzero_exit")

    def test_cancellation_terminates_running_adapter(self) -> None:
        spec = self.make_spec("import time; time.sleep(30)")
        calls = iter((False, True))
        result = IndependentEVMReplay().run(
            spec,
            self._workdir(),
            cancelled=lambda: next(calls, True),
        )
        self.assertEqual(result.status, ReplayStatus.UNKNOWN)
        self.assertEqual(result.reason, "cancelled")

    def test_missing_executable_is_unsupported(self) -> None:
        spec = self.make_spec("pass", executable="crossllm-executable-that-does-not-exist")
        result = IndependentEVMReplay().run(spec, self._workdir())
        self.assertEqual(result.status, ReplayStatus.UNSUPPORTED)
        self.assertEqual(result.reason, "executable_missing")

    def test_digest_and_native_adapter_are_required(self) -> None:
        with self.assertRaisesRegex(ValueError, "sha256 digest"):
            EVMReplaySpec(
                adapter_id="reference-evm-subprocess",
                executable=sys.executable,
                arguments=(),
                tool_revision="r1",
                container_ref="registry.example/evm:latest",
                artifact_hash="a",
                initialization_hash="b",
                profile_hash="c",
                semantic_engine="evm",
            )
        with self.assertRaisesRegex(ValueError, "artifact_hash"):
            EVMReplaySpec(
                adapter_id="reference-evm-subprocess",
                executable=sys.executable,
                arguments=(),
                tool_revision="r1",
                container_ref="registry.example/evm@sha256:" + "a" * 64,
                artifact_hash="A" * 64,
                initialization_hash="b" * 64,
                profile_hash="c" * 64,
                semantic_engine="evm",
            )

    def test_support_matrix_hash_is_part_of_replay_identity(self) -> None:
        first = self.make_spec("pass", executable=sys.executable)
        second = EVMReplaySpec(
            adapter_id=first.adapter_id,
            executable=first.executable,
            arguments=first.arguments,
            tool_revision=first.tool_revision,
            container_ref=first.container_ref,
            artifact_hash=first.artifact_hash,
            initialization_hash=first.initialization_hash,
            profile_hash=first.profile_hash,
            semantic_engine=first.semantic_engine,
            timeout_seconds=first.timeout_seconds,
            support_matrix_hash="e" * 64,
        )
        self.assertNotEqual(first.spec_hash, second.spec_hash)
        with self.assertRaisesRegex(ValueError, "support matrix hash"):
            EVMReplaySpec(
                adapter_id=first.adapter_id,
                executable=first.executable,
                arguments=first.arguments,
                tool_revision=first.tool_revision,
                container_ref=first.container_ref,
                artifact_hash=first.artifact_hash,
                initialization_hash=first.initialization_hash,
                profile_hash=first.profile_hash,
                semantic_engine=first.semantic_engine,
                support_matrix_hash="E" * 64,
            )
        with self.assertRaisesRegex(ValueError, "native fixture"):
            EVMReplaySpec(
                adapter_id="native",
                executable=sys.executable,
                arguments=(),
                tool_revision="r1",
                container_ref="registry.example/evm@sha256:" + "a" * 64,
                artifact_hash="a",
                initialization_hash="b",
                profile_hash="c",
                semantic_engine="evm",
            )

    @staticmethod
    def _workdir():
        from pathlib import Path

        return Path.cwd()


if __name__ == "__main__":
    unittest.main()
