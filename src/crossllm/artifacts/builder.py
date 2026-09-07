"""Build deterministic, gold-free artifact packs from an approved source tree."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

from ..contracts.canonical import sha256_bytes, sha256_hex

FORBIDDEN_NAMES = {
    "gold_property",
    "trigger_calldata",
    "exploit_payload",
    "mutation_diff",
    "private_key",
    "rpc_url",
}


@dataclass(frozen=True, slots=True)
class ArtifactSymbol:
    """A stable, public symbol binding supplied by an approved extractor."""

    symbol_id: str
    path: str
    name: str
    domain: str
    kind: str
    type: str

    def as_dict(self) -> dict[str, str]:
        return {
            "symbol_id": self.symbol_id,
            "path": self.path,
            "name": self.name,
            "domain": self.domain,
            "kind": self.kind,
            "type": self.type,
        }


@dataclass(frozen=True, slots=True)
class ArtifactPack:
    """Content-addressed metadata for the files exposed to a proposer."""

    pack_id: str
    source_hash: str
    manifest_hash: str
    symbols_hash: str
    files: tuple[dict[str, str | int], ...]
    symbols: tuple[ArtifactSymbol, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "pack_id": self.pack_id,
            "source_hash": self.source_hash,
            "manifest_hash": self.manifest_hash,
            "symbols_hash": self.symbols_hash,
            "files": list(self.files),
            "symbols": [symbol.as_dict() for symbol in self.symbols],
            "gold_access": "disabled",
        }


class ArtifactBuilder:
    """Construct a deterministic pack without reading private gold storage."""

    def build(
        self,
        source_root: Path,
        selected_paths: Iterable[str] | None = None,
        symbols: Iterable[ArtifactSymbol] = (),
    ) -> ArtifactPack:
        root = source_root.resolve()
        if not root.is_dir():
            raise ValueError(f"source_root is not a directory: {source_root}")

        relative_paths = self._select_paths(root, selected_paths)
        files: list[dict[str, str | int]] = []
        for relative in relative_paths:
            path = root / Path(relative)
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"artifact path must be a regular file: {relative}")
            content = path.read_bytes()
            files.append({
                "path": relative,
                "sha256": sha256_bytes(content),
                "size": len(content),
            })

        normalized_symbols = tuple(sorted(symbols, key=lambda symbol: symbol.symbol_id))
        self._validate_symbols(root, normalized_symbols, relative_paths)
        manifest_hash = sha256_hex(files)
        symbols_hash = sha256_hex([symbol.as_dict() for symbol in normalized_symbols])
        source_hash = sha256_hex({"files": files, "symbols_hash": symbols_hash})
        pack_id = sha256_hex({"source_hash": source_hash, "manifest_hash": manifest_hash})
        return ArtifactPack(
            pack_id=pack_id,
            source_hash=source_hash,
            manifest_hash=manifest_hash,
            symbols_hash=symbols_hash,
            files=tuple(files),
            symbols=normalized_symbols,
        )

    @staticmethod
    def _select_paths(root: Path, selected_paths: Iterable[str] | None) -> tuple[str, ...]:
        if selected_paths is None:
            candidates = (path.relative_to(root).as_posix() for path in root.rglob("*"))
        else:
            candidates = selected_paths
        normalized: set[str] = set()
        for value in candidates:
            path = PurePosixPath(str(value).replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise ValueError(f"artifact path escapes source_root: {value}")
            if any(
                forbidden in part.lower()
                for part in path.parts
                for forbidden in FORBIDDEN_NAMES
            ):
                raise ValueError(f"artifact path may expose private material: {value}")
            normalized.add(path.as_posix())
        return tuple(sorted(normalized))

    @staticmethod
    def _validate_symbols(
        root: Path,
        symbols: tuple[ArtifactSymbol, ...],
        relative_paths: tuple[str, ...],
    ) -> None:
        known_paths = set(relative_paths)
        seen_ids: set[str] = set()
        for symbol in symbols:
            if not symbol.symbol_id or symbol.symbol_id in seen_ids:
                raise ValueError(f"duplicate or empty symbol_id: {symbol.symbol_id!r}")
            seen_ids.add(symbol.symbol_id)
            if symbol.path not in known_paths or not (root / symbol.path).is_file():
                raise ValueError(f"symbol path is not in artifact pack: {symbol.path}")
            if symbol.domain not in {"source", "destination", "shared"}:
                raise ValueError(f"invalid symbol domain: {symbol.domain}")
            if not symbol.name or not symbol.kind or not symbol.type:
                raise ValueError(f"symbol metadata is incomplete: {symbol.symbol_id}")
