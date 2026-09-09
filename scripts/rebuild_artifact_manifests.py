#!/usr/bin/env python3
"""Rebuild deterministic per-lineage artifact manifests and checksums."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "dataset" / "artifacts"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def rebuild_lineage(artifact_root: Path) -> dict[str, object]:
    files: dict[str, str] = {}
    for path in sorted(artifact_root.rglob("*")):
        if not path.is_file() or path.name in {"manifest.json", "checksums.sha256"}:
            continue
        if any(part.startswith(".") or part == "__pycache__" for part in path.relative_to(artifact_root).parts):
            continue
        files[path.relative_to(artifact_root).as_posix()] = sha256_file(path)

    manifest_path = artifact_root / "manifest.json"
    manifest = {
        "lineage_id": artifact_root.name,
        "protocol": None,
        "split": None,
        "artifact_count": len(files),
        "files": files,
    }
    # Preserve descriptive fields from the previous manifest when available.
    if manifest_path.is_file():
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = {}
        if isinstance(previous, dict):
            for key in ("protocol", "split"):
                if isinstance(previous.get(key), str):
                    manifest[key] = previous[key]
    atomic_write(manifest_path, json.dumps(manifest, indent=2) + "\n")

    manifest_hash = sha256_file(manifest_path)
    checksum_lines = [
        f"{digest}  {relative}" for relative, digest in sorted(files.items())
    ]
    checksum_lines.append(f"{manifest_hash}  manifest.json")
    atomic_write(artifact_root / "checksums.sha256", "\n".join(checksum_lines) + "\n")
    return {"lineage_id": artifact_root.name, "artifact_count": len(files), "manifest_sha256": manifest_hash}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--lineage", action="append", default=None)
    args = parser.parse_args(argv)
    artifact_root = (args.root.resolve() / "dataset" / "artifacts")
    lineages = args.lineage or sorted(path.name for path in artifact_root.iterdir() if path.is_dir())
    results = []
    for lineage in lineages:
        path = artifact_root / lineage
        if not path.is_dir():
            raise SystemExit(f"artifact lineage does not exist: {lineage}")
        result = rebuild_lineage(path)
        results.append(result)
        print(f"{lineage}: {result['artifact_count']} files, manifest={result['manifest_sha256']}")
    print(f"rebuilt {len(results)} artifact manifests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
