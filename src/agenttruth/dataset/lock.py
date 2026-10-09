"""Write ``datasets/<id>.lock.json``: the expected SHA-256 of a fresh build's files (K1-C1).

``python -m agenttruth.dataset.lock --spec ds1`` builds the spec into a temporary directory and
writes the lock. Regenerating a lock changes what K1-C1 accepts, so every regeneration must be
explained in the sprint report (contract §14 K1 rejection conditions).
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from agenttruth.dataset.build import build_dataset, resolve_spec
from agenttruth.evidence.canonical import canonical_file_bytes, sha256_file

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    """Build ``--spec`` in a temporary directory and write its lock file."""
    parser = argparse.ArgumentParser(prog="python -m agenttruth.dataset.lock")
    parser.add_argument("--spec", required=True)
    args = parser.parse_args(argv)
    root = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="agenttruth-lock-") as tmp:
        out = Path(tmp) / "dataset"
        manifest = build_dataset(resolve_spec(args.spec, root), out, frozenset(), root)
        files = {name: sha256_file(out / name) for name in ("events.jsonl", "ledger.json", "manifest.json")}
    lock = {"schema": "agenttruth.dataset-lock/v1", "dataset_id": manifest.dataset_id, "files": files}
    target = root / "datasets" / f"{manifest.dataset_id}.lock.json"
    target.write_bytes(canonical_file_bytes(lock))
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
