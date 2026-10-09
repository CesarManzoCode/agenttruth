"""JSON Schema generation for persisted models, with a drift check (deliverable of contract §14 K1).

``python -m agenttruth.schemagen --write`` regenerates ``schemas/``; ``--check`` exits 1 and
names every file that differs from what the models generate.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pydantic import BaseModel

from agenttruth.dataset.spec import DatasetSpec
from agenttruth.evidence.canonical import canonical_dumps
from agenttruth.evidence.models import (
    Catalog,
    DatasetLock,
    Event,
    GateReport,
    Ledger,
    LintReport,
    Manifest,
    RsDefaults,
    Truths,
)

__all__ = ["SCHEMA_MODELS", "check", "render", "write"]

# File stem → model. The stem matches the ``schema`` tag: agenttruth.<stem>/v1.
SCHEMA_MODELS: dict[str, type[BaseModel]] = {
    "catalog": Catalog,
    "dataset-lock": DatasetLock,
    "dataset-spec": DatasetSpec,
    "event": Event,
    "gate-report": GateReport,
    "ledger": Ledger,
    "lint-report": LintReport,
    "manifest": Manifest,
    "rs-defaults": RsDefaults,
    "truths": Truths,
}


def render() -> dict[str, str]:
    """Return ``{file name: JSON Schema text}`` for every persisted model, deterministically."""
    out: dict[str, str] = {}
    for stem, model in sorted(SCHEMA_MODELS.items()):
        schema = model.model_json_schema(by_alias=True, mode="validation")
        schema["$id"] = f"https://agenttruth.dev/schemas/{stem}.v1.json"
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        out[f"{stem}.v1.json"] = canonical_dumps(schema) + "\n"
    return out


def write(directory: Path) -> list[str]:
    """Write every schema into ``directory`` and return the file names written."""
    directory.mkdir(parents=True, exist_ok=True)
    rendered = render()
    for name, text in rendered.items():
        (directory / name).write_text(text, encoding="utf-8")
    return sorted(rendered)


def check(directory: Path) -> list[str]:
    """Return a problem description for every schema file that is missing, stale or unexpected."""
    rendered = render()
    problems = []
    for name, text in sorted(rendered.items()):
        path = directory / name
        if not path.exists():
            problems.append(f"missing {path}")
        elif path.read_text(encoding="utf-8") != text:
            problems.append(f"stale {path} (run: python -m agenttruth.schemagen --write)")
    if directory.exists():
        problems.extend(f"unexpected {p}" for p in sorted(directory.glob("*.json")) if p.name not in rendered)
    return problems


def main(argv: list[str] | None = None) -> int:
    """CLI: ``--write`` or ``--check`` the schemas directory (default ``schemas``)."""
    parser = argparse.ArgumentParser(prog="python -m agenttruth.schemagen")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--dir", type=Path, default=Path("schemas"))
    args = parser.parse_args(argv)
    if args.write:
        for name in write(args.dir):
            print(f"wrote {args.dir / name}")
        return 0
    problems = check(args.dir)
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
