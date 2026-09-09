"""Build deterministic, gold-free artifact packs from an approved source tree."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
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


@dataclass(frozen=True, slots=True)
class ArtifactSelection:
    """Deterministic source/document closure selected for one public pack."""

    entry_paths: tuple[str, ...]
    document_paths: tuple[str, ...]
    selected_paths: tuple[str, ...]
    unresolved_imports: tuple[str, ...]
    selection_hash: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "entry_paths": list(self.entry_paths),
            "document_paths": list(self.document_paths),
            "selected_paths": list(self.selected_paths),
            "unresolved_imports": list(self.unresolved_imports),
            "selection_hash": self.selection_hash,
        }


class ArtifactPackSelector:
    """Resolve an explicitly declared import/document closure.

    The selector never infers source/destination domains or follows files by
    basename.  Every import must resolve inside ``source_root`` (unless the
    caller explicitly permits unresolved external dependencies); this keeps a
    missing dependency visible instead of silently producing an incomplete
    artifact pack.
    """

    _IMPORT = re.compile(r"\bimport\s+(?:[^;]*?\s+from\s+)?[\"']([^\"']+)[\"']\s*;")

    def select(
        self,
        source_root: Path,
        entry_paths: Iterable[str],
        *,
        document_paths: Iterable[str] = (),
        allow_unresolved_imports: bool = False,
    ) -> ArtifactSelection:
        root = source_root.resolve()
        if not root.is_dir():
            raise ValueError(f"source_root is not a directory: {source_root}")
        entries = self._normalize_paths(entry_paths, "entry")
        documents = self._normalize_paths(document_paths, "document")
        if not entries:
            raise ValueError("at least one entry path is required")
        selected: set[str] = set(documents)
        unresolved: set[str] = set()
        queue = list(entries)
        while queue:
            relative = queue.pop(0)
            if relative in selected:
                continue
            path = root / Path(relative)
            self._require_file(path, relative)
            selected.add(relative)
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError as error:
                raise ValueError(f"source file is not UTF-8: {relative}") from error
            for import_name in sorted(set(self._IMPORT.findall(text))):
                resolved = self._resolve_import(root, relative, import_name)
                if resolved is None:
                    unresolved.add(f"{relative}:{import_name}")
                elif resolved not in selected:
                    queue.append(resolved)
        for relative in documents:
            self._require_file(root / Path(relative), relative)
        if unresolved and not allow_unresolved_imports:
            raise ValueError(f"unresolved imports in artifact closure: {sorted(unresolved)}")
        selected_paths = tuple(sorted(selected))
        return ArtifactSelection(
            tuple(entries),
            tuple(documents),
            selected_paths,
            tuple(sorted(unresolved)),
            sha256_hex({
                "entry_paths": list(entries),
                "document_paths": list(documents),
                "selected_paths": list(selected_paths),
                "unresolved_imports": sorted(unresolved),
            }),
        )

    @staticmethod
    def _normalize_paths(values: Iterable[str], label: str) -> tuple[str, ...]:
        normalized: set[str] = set()
        for value in values:
            path = PurePosixPath(str(value).replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise ValueError(f"{label} path escapes source_root: {value}")
            if any(forbidden in part.lower() for part in path.parts for forbidden in FORBIDDEN_NAMES):
                raise ValueError(f"{label} path may expose private material: {value}")
            normalized.add(path.as_posix())
        return tuple(sorted(normalized))

    @staticmethod
    def _require_file(path: Path, relative: str) -> None:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"artifact closure path must be a regular file: {relative}")

    @classmethod
    def _resolve_import(cls, root: Path, importer: str, import_name: str) -> str | None:
        if import_name.startswith("."):
            candidate = (root / Path(importer).parent / Path(import_name)).resolve()
            try:
                relative = candidate.relative_to(root).as_posix()
            except ValueError:
                return None
            return relative if candidate.is_file() else None
        candidate = (root / Path(import_name)).resolve()
        try:
            relative = candidate.relative_to(root).as_posix()
        except ValueError:
            return None
        return relative if candidate.is_file() else None


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
