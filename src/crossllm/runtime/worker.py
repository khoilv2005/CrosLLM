"""Portable Docker worker command boundary for M08.02/M08.06."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .isolation import MountSpec, WorkerIsolationPolicy
from .resources import ResourceEnvelope


@dataclass(frozen=True, slots=True)
class DockerWorkerCommand:
    image_ref: str
    command: tuple[str, ...]
    argv: tuple[str, ...]
    mounts: tuple[MountSpec, ...]
    endpoint: str | None
    network_mode: str = "none"

    def as_dict(self) -> dict[str, object]:
        return {
            "image_ref": self.image_ref,
            "command": list(self.command),
            "argv": list(self.argv),
            "mounts": [
                {
                    "source": mount.source,
                    "target": mount.target,
                    "sensitivity": mount.sensitivity,
                    "read_only": mount.read_only,
                }
                for mount in self.mounts
            ],
            "endpoint": self.endpoint,
            "network_mode": self.network_mode,
            "env_file": self.env_file,
            "entrypoint": self.entrypoint,
            "allowed_network_hosts": list(self._allowed_network_hosts),
            "egress_enforcement": (
                "docker_network_none"
                if self.endpoint is None
                else "external_firewall_required"
            ),
            "gold_access": "disabled",
            "allow_broadcast": False,
        }

    # The builder attaches this only to the immutable command object. Keeping
    # it private in the dataclass avoids changing the public endpoint contract.
    _allowed_network_hosts: tuple[str, ...] = ()
    env_file: str | None = None
    entrypoint: str | None = None


class DockerWorkerCommandBuilder:
    """Construct a fail-closed worker command; actual firewall remains external."""

    def __init__(
        self,
        *,
        envelope: ResourceEnvelope | None = None,
        policy: WorkerIsolationPolicy | None = None,
    ) -> None:
        self.envelope = envelope or ResourceEnvelope()
        self.policy = policy or WorkerIsolationPolicy()

    def build(
        self,
        *,
        image_ref: str,
        command: tuple[str, ...] | list[str],
        mounts: tuple[MountSpec, ...] | list[MountSpec] = (),
        endpoint: str | None = None,
        broadcast: bool = False,
        env_file: str | None = None,
        entrypoint: str | None = None,
    ) -> DockerWorkerCommand:
        if not _is_digest_ref(image_ref):
            raise ValueError("worker image must use an immutable @sha256 digest")
        command_tuple = tuple(command)
        if not command_tuple or any(not isinstance(item, str) or not item for item in command_tuple):
            raise ValueError("worker command must contain non-empty arguments")
        if env_file is not None and (not isinstance(env_file, str) or not env_file):
            raise ValueError("env_file must be a non-empty path")
        if env_file is not None and endpoint is None:
            raise ValueError("env_file is only allowed for a provider-enabled worker")
        if entrypoint is not None and (not isinstance(entrypoint, str) or not entrypoint.startswith("/")):
            raise ValueError("entrypoint must be an absolute path")
        mount_tuple = tuple(mounts)
        self.policy.assert_compliant(mount_tuple, endpoint=endpoint, broadcast=broadcast)
        argv = (
            "docker", "run", "--rm",
            "--network=none" if endpoint is None else "--network=bridge",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--pids-limit", "512",
            "--cpus", str(self.envelope.cpu_cores),
            "--memory", f"{self.envelope.memory_bytes}b",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=1g",
        )
        if entrypoint is not None:
            argv += ("--entrypoint", entrypoint)
        if env_file is not None:
            argv += ("--env-file", env_file)
        for mount in mount_tuple:
            mode = "readonly" if mount.read_only else "rw"
            argv += ("--mount", f"type=bind,src={mount.source},dst={mount.target},{mode}")
        argv += (image_ref, *command_tuple)
        return DockerWorkerCommand(
            image_ref,
            command_tuple,
            argv,
            mount_tuple,
            endpoint,
            "none" if endpoint is None else "bridge",
            tuple(self.policy.allowed_network_hosts),
            env_file,
            entrypoint,
        )


def _is_digest_ref(image_ref: str) -> bool:
    return bool(re.search(r"@sha256:[0-9a-fA-F]{64}$", image_ref))
