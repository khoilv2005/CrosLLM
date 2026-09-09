#!/usr/bin/env python3
"""Validate the reproducibility boundary used by the development worker.

This is deliberately a lock validator, not an evaluation-readiness shortcut.
It checks that Python requirements are hash-pinned for the supported platform
variants, that CI installs the same lock with hash checking enabled, and that
the container/compiler references are immutable digests.  A development probe
continues to report development status until the clean-worker installation and
evaluation lock are separately reviewed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


_REQ_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^;\\\s]+)"
    r"(?:\s*;\s*(?P<marker>[^\\]+?))?\s*(?P<options>.*)$"
)
_HASH_RE = re.compile(r"--hash=sha256:(?P<hash>[0-9a-fA-F]{64})")
_DIGEST_RE = re.compile(r"@sha256:[0-9a-fA-F]{64}$")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _logical_lines(path: Path) -> list[str]:
    logical: list[str] = []
    pending = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if pending:
            pending += " " + line
        else:
            pending = line
        if pending.endswith("\\"):
            pending = pending[:-1].rstrip()
        else:
            logical.append(pending)
            pending = ""
    if pending:
        logical.append(pending)
    return logical


def _parse_requirements(path: Path) -> tuple[list[dict[str, object]], list[str]]:
    entries: list[dict[str, object]] = []
    errors: list[str] = []
    for index, line in enumerate(_logical_lines(path), start=1):
        match = _REQ_RE.match(line)
        if not match:
            errors.append(f"requirements.lock line {index}: unsupported entry {line!r}")
            continue
        hashes = sorted(set(_HASH_RE.findall(match.group("options"))))
        if not hashes:
            errors.append(f"requirements.lock line {index}: missing sha256 hash")
        entries.append(
            {
                "name": match.group("name").lower().replace("_", "-"),
                "version": match.group("version"),
                "marker": (match.group("marker") or "").strip(),
                "hashes": [item.lower() for item in hashes],
            }
        )
    return entries, errors


def _all_digest_values(value: object, path: str = "") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            found.extend(_all_digest_values(child, f"{path}.{key}" if path else str(key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_all_digest_values(child, f"{path}[{index}]"))
    elif isinstance(value, str) and path.lower().endswith(".ref"):
        found.append((path, value))
    return found


def validate(root: Path) -> tuple[dict[str, object], list[str]]:
    errors: list[str] = []
    requirements = root / "requirements.lock"
    pyproject = root / "pyproject.toml"
    workflow = root / ".github" / "workflows" / "ci.yml"
    toolchain_path = root / "containers" / "toolchain.lock.json"
    solc_path = root / "containers" / "solc.lock.json"
    required_files = [requirements, pyproject, workflow, toolchain_path, solc_path]
    for path in required_files:
        if not path.is_file():
            errors.append(f"missing required lock input: {path.relative_to(root)}")

    entries: list[dict[str, object]] = []
    if requirements.is_file():
        entries, req_errors = _parse_requirements(requirements)
        errors.extend(req_errors)
        if not entries:
            errors.append("requirements.lock contains no pinned packages")

    if workflow.is_file():
        workflow_text = workflow.read_text(encoding="utf-8")
        if "--require-hashes" not in workflow_text:
            errors.append("CI does not install requirements.lock with --require-hashes")
        if "runs-on: ubuntu-24.04" not in workflow_text:
            errors.append("CI runner is not pinned to ubuntu-24.04")

    toolchain: dict[str, object] = {}
    if toolchain_path.is_file():
        try:
            toolchain = json.loads(toolchain_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"toolchain lock is invalid JSON: {exc}")
        if toolchain.get("status") not in {"development_probe", "evaluation_locked"}:
            errors.append("toolchain lock has an unknown status")
        if toolchain.get("python_lock_file") != "requirements.lock":
            errors.append("toolchain lock does not point to requirements.lock")
        if toolchain.get("python_lock_install") != (
            "python -m pip install --require-hashes --requirement requirements.lock"
        ):
            errors.append("toolchain lock install command is not hash checked")
        for location, value in _all_digest_values(toolchain):
            if not _DIGEST_RE.search(value):
                errors.append(f"{location} is not an immutable image digest")

    if solc_path.is_file():
        try:
            solc = json.loads(solc_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            solc = {}
            errors.append(f"solc lock is invalid JSON: {exc}")
        images = solc.get("images", {})
        if not isinstance(images, dict) or not images:
            errors.append("solc lock has no compiler images")
        else:
            for version, image in images.items():
                if not isinstance(image, str) or not _DIGEST_RE.search(image):
                    errors.append(f"solc image {version!r} is not an immutable digest")

    result = {
        "schema_version": 1,
        "status": toolchain.get("status", "invalid"),
        "requirements_lock_sha256": _sha256(requirements) if requirements.is_file() else None,
        "ci_workflow_sha256": _sha256(workflow) if workflow.is_file() else None,
        "toolchain_lock_sha256": _sha256(toolchain_path) if toolchain_path.is_file() else None,
        "solc_lock_sha256": _sha256(solc_path) if solc_path.is_file() else None,
        "hashed_requirement_entries": len(entries),
        "ci_hash_install": workflow.is_file()
        and "--require-hashes" in workflow.read_text(encoding="utf-8"),
        "admission_eligible": False,
    }
    return result, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--check", action="store_true", help="validate and emit a concise status")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    result, errors = validate(root)
    if errors:
        print("TOOLCHAIN_LOCK: FAIL")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("TOOLCHAIN_LOCK: PASS")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
