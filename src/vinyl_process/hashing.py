"""Content addressing.

Reproducibility here is checked by hashing, so the rules live in one leaf module
that nothing else in the package depends on:

* files are hashed as raw bytes;
* JSON is hashed after canonicalisation (sorted keys, no insignificant
  whitespace, UTF-8) so reformatting a document never changes its digest;
* every digest in every contract is SHA-256 rendered as lowercase hex, with no
  algorithm prefix — the field names (``sha256``, ``params_digest``, ``run_key``)
  are documented as SHA-256 in ``docs/data-contracts.md``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

__all__ = [
    "DIGEST_ALGORITHM",
    "canonical_json",
    "digest_bytes",
    "digest_file",
    "digest_json",
    "short_digest",
]

DIGEST_ALGORITHM = "sha256"
_CHUNK = 1 << 20


def digest_bytes(data: bytes) -> str:
    """SHA-256 of ``data`` as lowercase hex."""
    return hashlib.sha256(data).hexdigest()


def digest_file(path: str | Path) -> str:
    """SHA-256 of the file at ``path``, streamed so huge recordings are fine."""
    hasher = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            hasher.update(chunk)
    return hasher.hexdigest()


def canonical_json(value: Any) -> bytes:
    """Serialise ``value`` to the canonical byte form used for digests."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def digest_json(value: Any) -> str:
    """SHA-256 of the canonical JSON encoding of ``value``."""
    return digest_bytes(canonical_json(value))


def short_digest(digest: str, length: int = 12) -> str:
    """First ``length`` hex characters, for log lines and error messages."""
    return digest[:length]
