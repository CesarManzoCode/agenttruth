"""Reader for ``events.jsonl`` and the dataset ``manifest.json``; importable by the oracle (§4.1).

The reader validates every line against :class:`agenttruth.evidence.models.Event` and never looks at
the construction ledger.
"""

from __future__ import annotations

from pathlib import Path

from agenttruth.evidence.canonical import sha256_file
from agenttruth.evidence.models import Event, Manifest
from agenttruth.evidence.read import iter_jsonl, load_json

__all__ = ["DatasetFiles", "read_events", "read_manifest"]


class DatasetFiles:
    """Paths of a built dataset directory (``events.jsonl`` and ``manifest.json``)."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.events = directory / "events.jsonl"
        self.manifest = directory / "manifest.json"


def read_events(path: Path) -> list[Event]:
    """Parse and validate every line of ``events.jsonl``; order is preserved.

    Raises ``FileNotFoundError`` if missing and ``ValueError`` naming the line if a line is invalid.
    Complexity: O(n) in the number of events.
    """
    events = []
    for number, obj in enumerate(iter_jsonl(path), start=1):
        try:
            events.append(Event.model_validate(obj))
        except ValueError as exc:
            raise ValueError(f"{path}:{number}: invalid event: {exc}") from exc
    return events


def read_manifest(directory: Path) -> tuple[Manifest, str]:
    """Return the dataset manifest of ``directory`` and the SHA-256 of its file.

    Raises ``FileNotFoundError`` if the manifest is missing and ``ValueError`` if it is invalid.
    """
    path = DatasetFiles(directory).manifest
    return Manifest.model_validate(load_json(path)), sha256_file(path)
