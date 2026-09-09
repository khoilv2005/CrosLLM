#!/usr/bin/env python3
"""Extract a selected Across contract's Foundry artifacts safely.

The source tree is mounted read-only into a digest-pinned Foundry container;
the command never invokes a shell and never changes the source cache.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IMAGE = "ghcr.io/foundry-rs/foundry@sha256:0c00cb0bda1ab1b91c9a6bf60f4c76c09c1a8870824b6d4718afbabacf6f9a17"


def _inspect(source: Path, image: str, contract: str, field: str, timeout: float) -> str:
    command = [
        "docker", "run", "--rm", "--network=none",
        "--mount", f"type=bind,source={source.resolve()},target=/src,readonly",
        "--workdir", "/src", "--entrypoint", "/usr/local/bin/forge",
        image, "inspect", contract, field,
    ]
    try:
        completed = subprocess.run(
            command, cwd=source, capture_output=True, text=True,
            timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"forge inspect {field} failed to start: {error}") from error
    if completed.returncode != 0:
        raise RuntimeError(f"forge inspect {field} failed: {completed.stderr.strip()}")
    return completed.stdout


def _first_hex(output: str, field: str) -> str:
    for line in output.splitlines():
        value = line.strip()
        if value.startswith("0x"):
            return value
    raise ValueError(f"forge inspect {field} returned no hexadecimal value")


def _json_fragment(output: str, opening: str, closing: str, field: str) -> object:
    start = output.find(opening)
    end = output.rfind(closing)
    if start < 0 or end < start:
        raise ValueError(f"forge inspect {field} returned no JSON fragment")
    try:
        return json.loads(output[start:end + 1])
    except json.JSONDecodeError as error:
        raise ValueError(f"forge inspect {field} returned invalid JSON: {error}") from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="private source checkout")
    parser.add_argument("--out", type=Path, default=ROOT / "dataset" / "artifacts" / "across")
    parser.add_argument("--contract", default="Ethereum_SpokePool")
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    args = parser.parse_args(argv)
    if "@sha256:" not in args.image:
        parser.error("--image must be digest-pinned")
    source = args.source.resolve()
    if not source.is_dir():
        parser.error(f"source directory does not exist: {source}")
    out = args.out.resolve()
    try:
        creation = _first_hex(_inspect(source, args.image, args.contract, "bytecode", args.timeout_seconds), "bytecode")
        deployed = _first_hex(_inspect(source, args.image, args.contract, "deployed-bytecode", args.timeout_seconds), "deployed-bytecode")
        abi = _json_fragment(_inspect(source, args.image, args.contract, "abi", args.timeout_seconds), "[", "]", "abi")
        storage = _json_fragment(_inspect(source, args.image, args.contract, "storage-layout", args.timeout_seconds), "{", "}", "storage-layout")
    except (RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    out.joinpath("bytecode").mkdir(parents=True, exist_ok=True)
    out.joinpath("abi").mkdir(parents=True, exist_ok=True)
    out.joinpath("storage_layout").mkdir(parents=True, exist_ok=True)
    out.joinpath("bytecode", "SpokePool.creation.hex").write_text(creation + "\n", encoding="utf-8")
    out.joinpath("bytecode", "SpokePool.deployed.hex").write_text(deployed + "\n", encoding="utf-8")
    out.joinpath("abi", "SpokePool.json").write_text(json.dumps(abi, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out.joinpath("storage_layout", "SpokePool.json").write_text(json.dumps(storage, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Extracted {args.contract} artifacts to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
