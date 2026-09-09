from __future__ import annotations

import copy
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dataset.tools import extract_all_artifacts
from scripts import generate_benchmark_manifest


class LineageMetadataTests(unittest.TestCase):
    def test_extractor_specs_match_authoritative_source_lock(self) -> None:
        lock = extract_all_artifacts.load_source_lock()
        self.assertEqual(
            extract_all_artifacts.validate_lineage_specs(
                extract_all_artifacts.LINEAGE_SPECS, lock
            ),
            [],
        )
        self.assertEqual(extract_all_artifacts.validate_toolchain_image(), [])
        self.assertEqual(extract_all_artifacts.validate_solc_lock(), [])

    def test_extractor_rejects_stale_commit_and_repository(self) -> None:
        specs = copy.deepcopy(extract_all_artifacts.LINEAGE_SPECS)
        specs["hop"]["commit"] = "0" * 40
        specs["hop"]["source_repo"] = "https://example.invalid/stale.git"
        errors = extract_all_artifacts.validate_lineage_specs(
            specs, extract_all_artifacts.load_source_lock()
        )
        self.assertTrue(any("hop: commit=" in error for error in errors))
        self.assertTrue(any("hop: source_repo=" in error for error in errors))

    def test_extractor_rejects_malformed_build_settings_and_targets(self) -> None:
        specs = copy.deepcopy(extract_all_artifacts.LINEAGE_SPECS)
        specs["chainbridge"]["optimizer"] = "true"
        specs["chainbridge"]["optimizer_runs"] = 0
        specs["chainbridge"]["contracts"]["Bridge"] = "../outside.sol:Bridge"
        errors = extract_all_artifacts.validate_lineage_specs(
            specs, extract_all_artifacts.load_source_lock()
        )
        self.assertTrue(any("chainbridge: optimizer must be boolean" in error for error in errors))
        self.assertTrue(any("chainbridge: optimizer_runs" in error for error in errors))
        self.assertTrue(any("chainbridge: malformed contract target" in error for error in errors))

    def test_source_mount_layout_keeps_git_root_for_monorepos(self) -> None:
        root, subpath = extract_all_artifacts.source_mount_layout(
            Path("private-cache"), "hyperlane", extract_all_artifacts.LINEAGE_SPECS["hyperlane"]
        )
        self.assertEqual(root, (Path("private-cache") / "hyperlane").resolve())
        self.assertEqual(subpath, "solidity")

        root, subpath = extract_all_artifacts.source_mount_layout(
            Path("private-cache"), "layerzero_v2", extract_all_artifacts.LINEAGE_SPECS["layerzero_v2"]
        )
        self.assertEqual(root, (Path("private-cache") / "layerzero_v2").resolve())
        self.assertEqual(subpath, "packages/layerzero-v2/evm/messagelib")
        self.assertEqual(
            extract_all_artifacts.LINEAGE_SPECS["layerzero_v2"]["contracts"]["SendUln302"],
            "contracts/uln/uln302/SendUln302.sol:SendUln302",
        )

        with self.assertRaises(ValueError):
            extract_all_artifacts.source_mount_layout(
                Path("private-cache"), "hop", {"workdir": "hop/../outside"}
            )

    def test_synthetic_manifest_generation_requires_explicit_opt_in(self) -> None:
        self.assertEqual(generate_benchmark_manifest.main([]), 2)

    def test_forge_inspect_uses_hardened_argv(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout="{}", stderr="")
        with patch(
            "dataset.tools.extract_all_artifacts.subprocess.run",
            return_value=completed,
        ) as run:
            output = extract_all_artifacts.run_forge_inspect(
                Path("fixture"), "contracts/Bridge.sol:Bridge", "abi", as_json=True
            )
        self.assertEqual(output, "{}")
        command = run.call_args.args[0]
        self.assertIn("--network=none", command)
        self.assertIn("--read-only", command)
        self.assertIn("/root/.svm:rw,exec,nosuid,size=512m", command)
        self.assertIn("/tmp:rw,noexec,nosuid,size=512m", command)
        self.assertIn("FOUNDRY_CACHE_PATH=/tmp/foundry-cache", command)
        self.assertIn("FOUNDRY_OUT=/tmp/foundry-out", command)
        self.assertNotIn("/src/cache:rw,noexec,nosuid,size=256m", command)
        self.assertNotIn("/src/out:rw,noexec,nosuid,size=512m", command)
        self.assertIn("--cap-drop=ALL", command)
        self.assertIn("--entrypoint", command)
        self.assertIn("forge", command)
        self.assertTrue(any(item.endswith(":/src:ro") for item in command))
        self.assertEqual(command[-7:], ["--optimize", "false", "--optimizer-runs", "200", "contracts/Bridge.sol:Bridge", "abi", "--json"])
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_forge_inspect_can_reuse_lineage_scoped_compiler_volume(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout="{}", stderr="")
        with patch(
            "dataset.tools.extract_all_artifacts.subprocess.run",
            return_value=completed,
        ) as run:
            output = extract_all_artifacts.run_forge_inspect(
                Path("fixture"),
                "contracts/Bridge.sol:Bridge",
                "abi",
                as_json=True,
                docker_network="bridge",
                compiler_cache_volume="crossllm-solc-123-abcdef",
                timeout_seconds=37,
            )
        self.assertEqual(output, "{}")
        command = run.call_args.args[0]
        self.assertIn(
            "type=volume,source=crossllm-solc-123-abcdef,target=/compiler",
            command,
        )
        self.assertNotIn("/root/.svm:rw,exec,nosuid,size=512m", command)
        self.assertEqual(run.call_args.kwargs["timeout"], 37)

    def test_forge_inspect_mounts_dependencies_and_explicit_remappings(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout="{}", stderr="")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dependencies = root / "node_modules"
            protocol = root / "protocol"
            dependencies.mkdir()
            protocol.mkdir()
            with patch(
                "dataset.tools.extract_all_artifacts.subprocess.run",
                return_value=completed,
            ) as run:
                extract_all_artifacts.run_forge_inspect(
                    root,
                    "Bridge",
                    "abi",
                    dependency_root=dependencies,
                    dependency_mounts=((protocol, "/deps/protocol"),),
                    remappings=(("vendor/", "/deps/node_modules/vendor/"),),
                )
        command = run.call_args.args[0]
        self.assertIn(
            f"type=bind,source={dependencies.resolve()},target=/deps/node_modules,readonly",
            command,
        )
        self.assertIn(
            f"type=bind,source={protocol.resolve()},target=/deps/protocol,readonly",
            command,
        )
        self.assertIn("--remappings", command)
        self.assertIn("vendor/=/deps/node_modules/vendor/", command)
        self.assertLess(command.index("--mount"), command.index(extract_all_artifacts.DOCKER_FOUNDRY))

    def test_forge_inspect_mounts_safe_posix_scratch_paths(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout="{}", stderr="")
        with patch(
            "dataset.tools.extract_all_artifacts.subprocess.run",
            return_value=completed,
        ) as run:
            extract_all_artifacts.run_forge_inspect(
                Path("fixture"),
                "Bridge",
                "abi",
                scratch_mounts=("/src/artifacts/build-info",),
            )
        command = run.call_args.args[0]
        self.assertIn(
            "/src/artifacts/build-info:rw,exec,nosuid,size=512m",
            command,
        )
        with self.assertRaisesRegex(ValueError, "scratch mounts"):
            extract_all_artifacts.run_forge_inspect(
                Path("fixture"), "Bridge", "abi", scratch_mounts=("/tmp",)
            )

    def test_compiler_cache_volume_helpers_use_bounded_docker_argv(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout="crossllm-solc-1-abc\n", stderr="")
        with patch(
            "dataset.tools.extract_all_artifacts.subprocess.run",
            return_value=completed,
        ) as run:
            name = extract_all_artifacts.create_compiler_cache_volume("layerzero_v2")
            extract_all_artifacts.remove_compiler_cache_volume(name)
        self.assertRegex(name, r"^crossllm-solc-\d+-[0-9a-f]{12}$")
        self.assertEqual(run.call_args_list[0].args[0][:3], ["docker", "volume", "create"])
        self.assertEqual(run.call_args_list[1].args[0][:3], ["docker", "volume", "rm"])

    def test_populate_compiler_volume_requires_verified_locked_binary(self) -> None:
        with patch(
            "dataset.tools.extract_all_artifacts.subprocess.run",
            side_effect=[
                SimpleNamespace(returncode=0, stdout="", stderr=""),
                SimpleNamespace(returncode=0, stdout="", stderr=""),
                SimpleNamespace(returncode=0, stdout="", stderr=""),
                SimpleNamespace(
                    returncode=0,
                    stdout="Version: 0.8.36+commit.8a079791.Linux.clang\n",
                    stderr="",
                ),
                SimpleNamespace(returncode=0, stdout="" + "a" * 64 + "  /compiler/solc\n", stderr=""),
            ],
        ) as run:
            info = extract_all_artifacts.populate_compiler_cache_volume(
                "crossllm-solc-123-abcdef", "0.8.36"
            )
        self.assertEqual(info["version"], "0.8.36")
        self.assertEqual(info["binary_sha256"], "a" * 64)
        self.assertEqual(len(run.call_args_list), 5)
        self.assertEqual(run.call_args_list[0].args[0][:3], ["docker", "image", "inspect"])
        self.assertIn("--network=none", run.call_args_list[1].args[0])
        self.assertIn("@sha256:", run.call_args_list[1].args[0][-3])

    def test_populate_compiler_volume_rejects_version_mismatch(self) -> None:
        with patch(
            "dataset.tools.extract_all_artifacts.subprocess.run",
            side_effect=[
                SimpleNamespace(returncode=0, stdout="", stderr=""),
                SimpleNamespace(returncode=0, stdout="", stderr=""),
                SimpleNamespace(returncode=0, stdout="", stderr=""),
                SimpleNamespace(returncode=0, stdout="Version: 0.8.35+commit.bad\n", stderr=""),
            ],
        ):
            with self.assertRaisesRegex(RuntimeError, "version verification failed"):
                extract_all_artifacts.populate_compiler_cache_volume(
                    "crossllm-solc-123-abcdef", "0.8.36"
                )

    def test_forge_inspect_removes_named_container_after_timeout(self) -> None:
        timeout = subprocess.TimeoutExpired(["docker", "run"], 120)
        completed = SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch(
            "dataset.tools.extract_all_artifacts.subprocess.run",
            side_effect=[timeout, completed],
        ) as run:
            with self.assertRaises(subprocess.TimeoutExpired):
                extract_all_artifacts.run_forge_inspect(
                    Path("fixture"), "Bridge", "abi", as_json=True
                )
        cleanup = run.call_args_list[1].args[0]
        self.assertEqual(cleanup[:3], ["docker", "rm", "-f"])
        self.assertRegex(cleanup[3], r"^crossllm-inspect-\d+-[0-9a-f]{12}$")

    def test_forge_inspect_rejects_unlisted_network_mode(self) -> None:
        with self.assertRaisesRegex(ValueError, "docker_network"):
            extract_all_artifacts.run_forge_inspect(
                Path("fixture"), "Bridge", "abi", docker_network="host"
            )

    def test_empty_bytecode_is_not_accepted_as_a_build_artifact(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "no deployable deployed bytecode"):
            extract_all_artifacts._require_deployable_bytecode("AbstractBridge", "0x6000", "0x")
        with self.assertRaisesRegex(RuntimeError, "malformed creation bytecode"):
            extract_all_artifacts._require_deployable_bytecode("Bridge", "not-hex", "0x6000")

    def test_source_target_metadata_rejects_abstract_and_non_contract_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            abstract_source = root / "AbstractBridge.sol"
            abstract_source.write_text(
                "// contract AbstractBridge {}\n"
                "abstract contract AbstractBridge {}\n",
                encoding="utf-8",
            )
            metadata = extract_all_artifacts.source_target_metadata(
                abstract_source, "AbstractBridge"
            )
            self.assertEqual(metadata["kind"], "abstract_contract")
            self.assertFalse(metadata["deployable_source_target"])
            with self.assertRaisesRegex(RuntimeError, "source target is abstract_contract"):
                extract_all_artifacts.require_concrete_source_target(
                    abstract_source, "AbstractBridge"
                )

            interface_source = root / "IBridge.sol"
            interface_source.write_text("interface IBridge {}\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "source target is interface"):
                extract_all_artifacts.require_concrete_source_target(
                    interface_source, "IBridge"
                )

    def test_source_target_metadata_preserves_declaration_line(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "Bridge.sol"
            source.write_text("// comment\n\ncontract Bridge {}\n", encoding="utf-8")
            metadata = extract_all_artifacts.source_target_metadata(source, "Bridge")
            self.assertEqual(metadata["kind"], "contract")
            self.assertEqual(metadata["declaration_line"], 3)

    def test_contract_source_resolution_is_checkout_bounded_and_hashable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "contracts" / "Bridge.sol"
            source.parent.mkdir(parents=True)
            source.write_text("contract Bridge {}\n", encoding="utf-8")
            resolved = extract_all_artifacts._resolve_contract_source(
                root, "", "contracts/Bridge.sol:Bridge"
            )
            self.assertEqual(resolved, source.resolve())
            self.assertEqual(len(extract_all_artifacts._file_hash(resolved)), 64)
            with self.assertRaisesRegex(RuntimeError, "escapes locked checkout"):
                extract_all_artifacts._resolve_contract_source(
                    root, "", "../outside.sol:Outside"
                )

    def test_dependency_closure_is_deterministic_and_content_addressed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dependency = root / "node_modules" / "example" / "package.json"
            dependency.parent.mkdir(parents=True)
            dependency.write_text('{"name":"example"}\n', encoding="utf-8")
            first = extract_all_artifacts.dependency_closure(root)
            second = extract_all_artifacts.dependency_closure(root)
            self.assertEqual(first, second)
            self.assertEqual(first["file_count"], 1)
            self.assertEqual(first["roots"], ["node_modules"])
            dependency.write_text('{"name":"changed"}\n', encoding="utf-8")
            self.assertNotEqual(first["sha256"], extract_all_artifacts.dependency_closure(root)["sha256"])

    def test_dependency_closure_includes_explicit_nested_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            nested = root / "solidity" / "dependencies" / "vendor" / "Lib.sol"
            nested.parent.mkdir(parents=True)
            nested.write_text("library Lib {}\n", encoding="utf-8")
            closure = extract_all_artifacts.dependency_closure(
                root, ("solidity/dependencies",)
            )
            self.assertEqual(closure["roots"], ["solidity/dependencies"])
            self.assertEqual(closure["file_count"], 1)
            self.assertEqual(closure["files"][0]["path"], "solidity/dependencies/vendor/Lib.sol")

    def test_evaluation_specs_use_concrete_locked_targets(self) -> None:
        wormhole = extract_all_artifacts.LINEAGE_SPECS["wormhole_evm_sdk"]
        across = extract_all_artifacts.LINEAGE_SPECS["across"]
        self.assertEqual(wormhole["contracts"]["Proxy"], "src/proxy/Proxy.sol:Proxy")
        self.assertEqual(
            across["contracts"]["Ethereum_SpokePool"],
            "contracts/spoke-pools/Ethereum_SpokePool.sol:Ethereum_SpokePool",
        )
        self.assertNotIn("WormholeRelayerReceiver", wormhole["contracts"])
        self.assertNotIn("SpokePool", across["contracts"])

    def test_stable_abi_symbols_include_overload_types_and_explicit_domain(self) -> None:
        abi = [
            {
                "type": "function",
                "name": "send",
                "inputs": [{"type": "tuple", "components": [{"type": "address"}, {"type": "uint256"}]}],
            },
            {"type": "function", "name": "send", "inputs": [{"type": "bytes32"}]},
            {"type": "event", "name": "Sent", "inputs": [{"type": "uint256", "indexed": True}]},
        ]
        layout = {"storage": [{"label": "nonce", "slot": "0", "type": "t_uint256"}]}
        first = extract_all_artifacts.stable_abi_symbols(
            "Bridge", "contracts/Bridge.sol", "a" * 64, abi, layout, "source"
        )
        second = extract_all_artifacts.stable_abi_symbols(
            "Bridge", "contracts/Bridge.sol", "a" * 64, abi, layout, "source"
        )
        self.assertEqual(first, second)
        self.assertEqual(len(first), 4)
        self.assertEqual({item["domain"] for item in first}, {"source"})
        self.assertIn("send((address,uint256))", [item["signature"] for item in first])
        self.assertIn("send(bytes32)", [item["signature"] for item in first])

    def test_deterministic_source_selection_tracks_external_imports(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "contracts" / "Bridge.sol"
            source.parent.mkdir(parents=True)
            source.write_text(
                'import "./Lib.sol";\nimport "@vendor/Token.sol";\ncontract Bridge {}\n',
                encoding="utf-8",
            )
            (source.parent / "Lib.sol").write_text("library Lib {}\n", encoding="utf-8")
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            selection = extract_all_artifacts.deterministic_source_selection(
                root, "", {"Bridge": "contracts/Bridge.sol:Bridge"}
            )
            self.assertEqual(
                selection["selected_paths"], ["README.md", "contracts/Bridge.sol", "contracts/Lib.sol"]
            )
            self.assertEqual(selection["unresolved_imports"], ["contracts/Bridge.sol:@vendor/Token.sol"])

    def test_generated_harness_runner_has_pinned_rootfs_and_cleanup_boundary(self) -> None:
        rendered = extract_all_artifacts.render_harness_runner(
            "celer_cbridge", extract_all_artifacts.LINEAGE_SPECS["celer_cbridge"]
        )
        self.assertIn("@sha256:", rendered)
        self.assertIn('"--read-only"', rendered)
        self.assertIn('target=/work,readonly', rendered)
        self.assertIn("/home/foundry:rw,exec,nosuid", rendered)
        self.assertIn("uid=1000,gid=1000,mode=700", rendered)
        self.assertIn('"docker", "rm", "-f", container_name', rendered)

    def test_forced_rebuild_clears_stale_contract_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact_root = root / "artifacts" / "lineage"
            harness_root = root / "harness" / "lineage"
            for directory in ("abi", "bytecode", "storage_layout"):
                path = artifact_root / directory
                path.mkdir(parents=True, exist_ok=True)
                (path / "stale-contract.json").write_text("stale", encoding="utf-8")
            fixtures = harness_root / "fixtures"
            fixtures.mkdir(parents=True)
            (fixtures / "stale.json").write_text("stale", encoding="utf-8")

            extract_all_artifacts.clear_generated_pack_outputs(artifact_root, harness_root)

            self.assertTrue(all(not any((artifact_root / directory).iterdir()) for directory in (
                "abi", "bytecode", "storage_layout"
            )))
            self.assertFalse(any(fixtures.iterdir()))

    def test_failed_forced_rebuild_does_not_delete_existing_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "sources" / "fixture"
            (source / "contracts").mkdir(parents=True)
            (source / "contracts" / "Bridge.sol").write_text(
                "contract Bridge {}\n", encoding="utf-8"
            )
            artifact = root / "artifacts" / "fixture"
            harness = root / "harness" / "fixture"
            (artifact / "abi").mkdir(parents=True)
            (artifact / "bytecode").mkdir()
            (artifact / "storage_layout").mkdir()
            (harness / "fixtures").mkdir(parents=True)
            sentinel = artifact / "abi" / "Bridge.json"
            sentinel.write_text("known-good", encoding="utf-8")
            fixture_sentinel = harness / "fixtures" / "known-good.json"
            fixture_sentinel.write_text("known-good", encoding="utf-8")

            spec = {
                "host_id": "fixture",
                "split": "development",
                "workdir": "fixture",
                "contracts": {"Bridge": "contracts/Bridge.sol:Bridge"},
                "contract_domains": {"Bridge": "shared"},
                "solc": "0.8.9",
                "optimizer": True,
                "optimizer_runs": 200,
                "license": "MIT",
                "protocol": "Fixture",
                "source_repo": "https://example.invalid/fixture.git",
                "commit": "a" * 40,
                "channel_profile": {"channel_type": "test", "topology": "peer"},
            }
            with patch(
                "dataset.tools.extract_all_artifacts.source_snapshot",
                return_value={
                    "source_archive_sha256": "b" * 64,
                    "archive_backend": "host",
                    "dirty_worktree": False,
                    "pinned_status": "source_pinned",
                },
            ), patch(
                "dataset.tools.extract_all_artifacts.run_forge_inspect",
                side_effect=TimeoutError("compiler probe timeout"),
            ):
                with self.assertRaises(TimeoutError):
                    extract_all_artifacts.extract_lineage(
                        "fixture",
                        spec,
                        artifacts_dir=root / "artifacts",
                        harness_root=root / "harness",
                        source_cache=root / "sources",
                        force=True,
                    )
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "known-good")
            self.assertEqual(fixture_sentinel.read_text(encoding="utf-8"), "known-good")

    def test_source_snapshot_verifies_lock_and_records_dirty_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)

            def git(*args: str) -> str:
                result = subprocess.run(
                    ["git", *args], cwd=repo, check=True,
                    capture_output=True, text=True
                )
                return result.stdout.strip()

            git("init", "-q")
            git("config", "user.email", "test@example.invalid")
            git("config", "user.name", "test")
            (repo / "README").write_text("fixture\n", encoding="utf-8")
            git("add", "README")
            git("commit", "-q", "-m", "fixture")
            commit = git("rev-parse", "HEAD")
            git("remote", "add", "origin", "https://example.invalid/org/repo.git")
            spec = {"commit": commit, "source_repo": "https://example.invalid/org/repo.git"}

            snapshot = extract_all_artifacts.source_snapshot(repo, spec)
            self.assertEqual(snapshot["source_commit"], commit)
            self.assertEqual(len(snapshot["source_archive_sha256"]), 64)
            self.assertFalse(snapshot["dirty_worktree"])

            generated_dependency = repo / "node_modules" / "example" / "package.json"
            generated_dependency.parent.mkdir(parents=True)
            generated_dependency.write_text("generated\n", encoding="utf-8")
            self.assertFalse(extract_all_artifacts.source_snapshot(repo, spec)["dirty_worktree"])

            (repo / "untracked").write_text("changed\n", encoding="utf-8")
            self.assertTrue(extract_all_artifacts.source_snapshot(repo, spec)["dirty_worktree"])


if __name__ == "__main__":
    unittest.main()
