"""Write side of the evidence store: the only path to disk for run data (contract §12, §13.1).

Every write is redacted first, then content-addressed as ``sha256/<hh>/<hash>.<ext>`` under the
store root, written atomically, and immutable: writing the same hash again verifies the bytes match.
"""

from __future__ import annotations

import gzip
import os
from pathlib import Path

from agenttruth.evidence.canonical import canonical_file_bytes, sha256_bytes
from agenttruth.evidence.read import artifact_relpath
from agenttruth.evidence.redact import Redactor

__all__ = ["EvidenceStore", "ImmutableArtifactError"]


class ImmutableArtifactError(RuntimeError):
    """Raised when an existing content-addressed file does not hold the bytes its name promises."""


class EvidenceStore:
    """Content-addressed, redacting artifact writer rooted at ``root``."""

    def __init__(self, root: Path, redactor: Redactor) -> None:
        self.root = root
        self._redactor = redactor
        self.redaction_hits: dict[str, int] = {}

    def put_text(self, text: str, ext: str = "txt", *, compress: bool = False) -> str:
        """Redact ``text``, store it (gzip with ``mtime=0`` if ``compress``) and return its hash.

        The hash is of the stored bytes. Raises :class:`ImmutableArtifactError` if a file with that
        hash already exists with different bytes, and ``OSError`` on write failure.
        """
        redaction = self._redactor.redact(text)
        for kind, count in redaction.hits.items():
            self.redaction_hits[kind] = self.redaction_hits.get(kind, 0) + count
        data = redaction.text.encode("utf-8")
        if compress:
            data = gzip.compress(data, compresslevel=9, mtime=0)
            ext = f"{ext}.gz"
        return self._put(data, ext)

    def put_json(self, obj: object) -> str:
        """Store ``obj`` as a redacted canonical JSON file and return its hash."""
        return self.put_text(canonical_file_bytes(obj).decode("utf-8"), "json")

    def _put(self, data: bytes, ext: str) -> str:
        digest = sha256_bytes(data)
        path = self.root / artifact_relpath(digest, ext)
        if path.exists():
            if path.read_bytes() != data:
                raise ImmutableArtifactError(f"{path} exists with different content")
            return digest
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        return digest
