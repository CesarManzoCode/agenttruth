"""Canonical JSON encoding and SHA-256 helpers (contract §5.1, §13.1).

Canonical JSON is UTF-8, keys sorted, separators ``(",", ":")``, no NaN/Infinity, non-ASCII kept
as is. Floats use Python's ``repr`` (shortest round-tripping form). A canonical *file* is the
canonical text followed by a single ``\\n``; a canonical JSON Lines file has one canonical object per
line, each terminated by ``\\n``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path

__all__ = [
    "canonical_dumps",
    "canonical_file_bytes",
    "canonical_jsonl_bytes",
    "sha256_bytes",
    "sha256_file",
    "sha256_json",
]

_CHUNK = 1 << 20


def canonical_dumps(obj: object) -> str:
    """Encode ``obj`` as canonical JSON text (no trailing newline).

    Raises ``ValueError`` for NaN or infinite floats and ``TypeError`` for values JSON cannot encode.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def canonical_file_bytes(obj: object) -> bytes:
    """Return the bytes of a canonical JSON file for ``obj`` (canonical text plus ``\\n``)."""
    return (canonical_dumps(obj) + "\n").encode("utf-8")


def canonical_jsonl_bytes(objs: Iterable[object]) -> bytes:
    """Return the bytes of a canonical JSON Lines file, one object per line, in the given order."""
    return "".join(canonical_dumps(obj) + "\n" for obj in objs).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    """Return the lowercase hex SHA-256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def sha256_json(obj: object) -> str:
    """Return the SHA-256 of the canonical JSON text of ``obj`` (no trailing newline)."""
    return sha256_bytes(canonical_dumps(obj).encode("utf-8"))


def sha256_file(path: Path) -> str:
    """Return the SHA-256 of the file at ``path``, read in 1 MiB chunks.

    Raises ``FileNotFoundError`` if the file does not exist.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()
