"""Canonical JSON and SHA-256 digests. The same payload always hashes the same, whatever key order it arrived in."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> bytes:
    """Sorted keys, no whitespace, UTF-8, NaN and Infinity rejected. pydantic models are dumped in JSON mode first."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256_of(value: Any) -> str:
    """`sha256:<64 hex>` of the canonical JSON of `value`."""
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def sha256_text(text: str) -> str:
    """`sha256:<64 hex>` of a string; used for parameter values and actor ids so logs and provenance carry no text."""
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
