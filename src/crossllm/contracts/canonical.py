"""Canonical serialization for hash-addressed protocol records."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> bytes:
    """Return deterministic UTF-8 JSON bytes for a JSON-compatible value."""
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_hex(value: Any) -> str:
    """Hash the canonical JSON representation of a value."""
    return hashlib.sha256(canonical_json(value)).hexdigest()
