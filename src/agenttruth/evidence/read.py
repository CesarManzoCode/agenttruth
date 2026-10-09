"""Read side of the evidence store: loaders, content-address layout, and verification (§13).

This module performs no writes. Gates may import it (contract §4.1).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from agenttruth.evidence.canonical import sha256_file

__all__ = [
    "ARTIFACT_NAME",
    "VerifyResult",
    "artifact_relpath",
    "iter_jsonl",
    "load_json",
    "load_yaml",
    "referenced_hashes",
    "verify_store",
]

ARTIFACT_NAME = re.compile(r"^(?P<hash>[0-9a-f]{64})\.(?P<ext>[a-z0-9]+(?:\.[a-z0-9]+)*)$")
_HASH = re.compile(r"^[0-9a-f]{64}$")


def load_json(path: Path) -> object:
    """Parse the JSON file at ``path``.

    Raises ``FileNotFoundError`` if missing and ``json.JSONDecodeError`` with the file position if
    the content is not valid JSON.
    """
    with path.open("r", encoding="utf-8") as handle:
        result: object = json.load(handle)
    return result


def load_yaml(path: Path) -> object:
    """Parse the YAML file at ``path`` with the safe loader (ISO dates become ``datetime.date``).

    Raises ``FileNotFoundError`` if missing and ``yaml.YAMLError`` if the content is not valid YAML.
    """
    with path.open("r", encoding="utf-8") as handle:
        result: object = yaml.safe_load(handle)
    return result


def iter_jsonl(path: Path) -> Iterator[dict[str, object]]:
    """Yield each line of a JSON Lines file as a dict.

    Raises ``ValueError`` naming the 1-based line number if a line is not a JSON object.
    """
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            obj: object = json.loads(line)
            if not isinstance(obj, dict):
                raise ValueError(f"{path}:{number}: expected a JSON object")
            yield obj


def artifact_relpath(sha256: str, ext: str) -> str:
    """Return the store-relative path of an artifact: ``sha256/<hh>/<hash>.<ext>`` (§13.1)."""
    if not _HASH.match(sha256):
        raise ValueError(f"not a SHA-256 hex digest: {sha256!r}")
    return f"sha256/{sha256[:2]}/{sha256}.{ext}"


def referenced_hashes(obj: object) -> set[str]:
    """Collect artifact hashes a manifest references: values of ``evidence`` lists and ``sha256`` keys
    inside ``artifacts`` lists, at any depth.
    """
    found: set[str] = set()

    def walk(node: object, key: str | None) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, str(k))
        elif isinstance(node, list):
            if key == "evidence":
                found.update(x for x in node if isinstance(x, str) and _HASH.match(x))
            elif key == "artifacts":
                for item in node:
                    if isinstance(item, dict) and isinstance(item.get("sha256"), str):
                        found.add(str(item["sha256"]))
            for item in node:
                walk(item, None)

    walk(obj, None)
    return found


@dataclass
class VerifyResult:
    """Outcome of :func:`verify_store`."""

    artifacts: int = 0
    manifests: int = 0
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when no problem was found."""
        return not self.problems


def verify_store(root: Path) -> VerifyResult:
    """Re-hash every content-addressed artifact under ``root`` and check manifest references.

    Inputs: a directory (an evidence directory such as ``evidence/K1``) or a single artifact file.
    Every file under a ``sha256/<hh>/`` directory must be named ``<sha256 of its bytes>.<ext>`` with
    ``<hh>`` equal to the first two hex digits. Every other ``*.json`` file is a manifest whose
    referenced hashes (see :func:`referenced_hashes`) must exist in the store. Problems are returned,
    not raised; ``FileNotFoundError`` is raised only if ``root`` does not exist.
    Complexity: O(total bytes) for hashing.
    """
    if not root.exists():
        raise FileNotFoundError(f"no such evidence path: {root}")
    result = VerifyResult()
    files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
    stored: set[str] = set()
    manifests: list[Path] = []
    for path in files:
        if path.parent.parent.name == "sha256":
            match = ARTIFACT_NAME.match(path.name)
            if match is None or path.parent.name != match["hash"][:2]:
                result.problems.append(f"{path}: not a content-addressed name")
                continue
            actual = sha256_file(path)
            result.artifacts += 1
            if actual != match["hash"]:
                result.problems.append(f"{path}: content hash {actual} does not match its name")
                continue
            stored.add(actual)
        elif path.suffix == ".json":
            manifests.append(path)
    for manifest in manifests:
        result.manifests += 1
        try:
            data = load_json(manifest)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            result.problems.append(f"{manifest}: unreadable manifest ({exc})")
            continue
        for missing in sorted(referenced_hashes(data) - stored):
            result.problems.append(f"{manifest}: references missing artifact {missing}")
    return result
