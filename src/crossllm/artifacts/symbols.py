"""Extract stable, typed storage symbols from compiler storage-layout artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .builder import ArtifactSymbol


@dataclass(frozen=True, slots=True)
class SkippedStorageSymbol:
    contract: str
    label: str
    storage_type: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {
            "contract": self.contract,
            "label": self.label,
            "storage_type": self.storage_type,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class StorageSymbolExtraction:
    symbols: tuple[ArtifactSymbol, ...]
    skipped: tuple[SkippedStorageSymbol, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "symbols": [symbol.as_dict() for symbol in self.symbols],
            "skipped": [item.as_dict() for item in self.skipped],
        }


_TYPE_MAP = {
    "t_bool": "bool",
    "t_uint256": "uint256",
    "t_int256": "int256",
    "t_address": "address",
    "t_bytes32": "bytes32",
}


def extract_storage_symbols(
    artifact_root: Path, contract_domains: Mapping[str, str]
) -> StorageSymbolExtraction:
    """Extract only losslessly supported storage fields.

    `contract_domains` must explicitly assign every requested artifact contract
    to `source`, `destination`, or `shared`. The extractor never infers a
    domain from file order or contract name.
    """
    root = artifact_root.resolve()
    layouts = root / "storage_layout"
    if not layouts.is_dir():
        raise ValueError(f"missing storage_layout directory: {layouts}")
    invalid = set(contract_domains.values()) - {"source", "destination", "shared"}
    if invalid:
        raise ValueError(f"invalid contract domains: {sorted(invalid)}")
    symbols: list[ArtifactSymbol] = []
    skipped: list[SkippedStorageSymbol] = []
    for contract, domain in sorted(contract_domains.items()):
        layout_path = layouts / f"{contract}.json"
        if not layout_path.is_file():
            raise ValueError(f"missing storage layout for contract {contract!r}")
        try:
            layout = json.loads(layout_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid storage layout JSON for {contract!r}: {error.msg}") from error
        storage = layout.get("storage")
        if not isinstance(storage, list):
            raise ValueError(f"storage layout for {contract!r} has no storage list")
        for entry in storage:
            if not isinstance(entry, dict):
                raise ValueError(f"storage layout for {contract!r} contains a non-object entry")
            label, storage_type, slot = entry.get("label"), entry.get("type"), entry.get("slot")
            if not all(isinstance(value, str) and value for value in (label, storage_type, slot)):
                raise ValueError(f"storage layout for {contract!r} has incomplete entry")
            value_type = _TYPE_MAP.get(storage_type)
            if value_type is None:
                skipped.append(SkippedStorageSymbol(contract, label, storage_type, "unsupported_or_lossy_type"))
                continue
            raw_contract = entry.get("contract")
            source_path = raw_contract.split(":", 1)[0] if isinstance(raw_contract, str) and raw_contract else layout_path.name
            symbol_id = f"storage.{contract}.slot_{slot}.{label}"
            symbols.append(ArtifactSymbol(symbol_id, source_path, label, domain, "storage", value_type))
    ids = [symbol.symbol_id for symbol in symbols]
    if len(ids) != len(set(ids)):
        raise ValueError("storage extraction produced duplicate symbol IDs")
    return StorageSymbolExtraction(tuple(sorted(symbols, key=lambda item: item.symbol_id)), tuple(skipped))
