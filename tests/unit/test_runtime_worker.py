from __future__ import annotations

import unittest

from crossllm.runtime import DockerWorkerCommandBuilder, MountSpec, ResourceEnvelope, WorkerIsolationPolicy


class RuntimeWorkerTests(unittest.TestCase):
    IMAGE = "registry.example/crossllm@sha256:" + "a" * 64

    def test_command_contains_resource_and_isolation_limits(self) -> None:
        command = DockerWorkerCommandBuilder().build(
            image_ref=self.IMAGE,
            command=("python", "-m", "worker"),
            mounts=[MountSpec("artifacts", "/input", "public_artifact")],
        )
        self.assertIn("--read-only", command.argv)
        self.assertIn("--network=none", command.argv)
        self.assertIn("--cap-drop=ALL", command.argv)
        self.assertIn("--tmpfs", command.argv)
        self.assertIn("--cpus", command.argv)
        self.assertIn(str(ResourceEnvelope().memory_bytes) + "b", command.argv)
        self.assertEqual(command.as_dict()["gold_access"], "disabled")

    def test_private_gold_and_broadcast_are_blocked(self) -> None:
        builder = DockerWorkerCommandBuilder()
        with self.assertRaisesRegex(PermissionError, "private gold"):
            builder.build(
                image_ref=self.IMAGE,
                command=("worker",),
                mounts=[MountSpec("gold", "/gold", "private_gold")],
            )
        with self.assertRaisesRegex(PermissionError, "broadcast"):
            builder.build(image_ref=self.IMAGE, command=("worker",), broadcast=True)

    def test_digest_and_network_allowlist_are_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "digest"):
            DockerWorkerCommandBuilder().build(image_ref="registry.example/worker:latest", command=("worker",))
        policy = WorkerIsolationPolicy(allowed_network_hosts=("provider.example",))
        builder = DockerWorkerCommandBuilder(policy=policy)
        command = builder.build(
            image_ref=self.IMAGE,
            command=("worker",),
            endpoint="https://provider.example/api",
        )
        self.assertEqual(command.endpoint, "https://provider.example/api")
        self.assertIn("--network=bridge", command.argv)
        self.assertEqual(command.as_dict()["egress_enforcement"], "external_firewall_required")
        with self.assertRaisesRegex(PermissionError, "outside provider allowlist"):
            builder.build(image_ref=self.IMAGE, command=("worker",), endpoint="https://other.example/api")

        default_provider = DockerWorkerCommandBuilder().build(
            image_ref=self.IMAGE,
            command=("worker",),
            endpoint="https://ollama.com/api/chat",
        )
        self.assertEqual(default_provider.network_mode, "bridge")
        self.assertIn("ollama.com", default_provider.as_dict()["allowed_network_hosts"])

    def test_provider_env_file_is_injected_without_being_a_mount(self) -> None:
        policy = WorkerIsolationPolicy(allowed_network_hosts=("ollama.com",))
        command = DockerWorkerCommandBuilder(policy=policy).build(
            image_ref=self.IMAGE,
            command=("worker",),
            endpoint="https://ollama.com/api/chat",
            env_file=".env",
        )
        self.assertEqual(command.env_file, ".env")
        self.assertEqual(command.as_dict()["env_file"], ".env")
        self.assertIn(("--env-file", ".env")[0], command.argv)
        self.assertIn(("--env-file", ".env")[1], command.argv)
        self.assertNotIn(".env", [mount.source for mount in command.mounts])
        with self.assertRaisesRegex(ValueError, "only allowed"):
            DockerWorkerCommandBuilder().build(
                image_ref=self.IMAGE,
                command=("worker",),
                env_file=".env",
            )

    def test_entrypoint_is_explicit_and_model_mount_is_blocked(self) -> None:
        command = DockerWorkerCommandBuilder().build(
            image_ref=self.IMAGE,
            command=("-c", "true"),
            entrypoint="/bin/sh",
        )
        self.assertEqual(command.entrypoint, "/bin/sh")
        self.assertIn("--entrypoint", command.argv)
        self.assertIn("/bin/sh", command.argv)
        with self.assertRaisesRegex(PermissionError, "model-weight"):
            DockerWorkerCommandBuilder().build(
                image_ref=self.IMAGE,
                command=("worker",),
                mounts=[MountSpec("cache", "/models", "public_artifact")],
            )


if __name__ == "__main__":
    unittest.main()
