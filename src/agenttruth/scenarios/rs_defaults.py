"""Defaults table for the round-trip lint, extracted from the vendored PostHog schema (§7.4).

PostHog's ``posthog/schema.py`` is parsed with :mod:`ast` (never imported) together with
``posthog/schema_enums.py``. For every field of the classes RS settings live in, the table records
the field's default: a JSON value, ``{"$required": true}`` for fields without a default, or
``{"$expr": "<source>"}`` for defaults this extractor does not evaluate (never needed by RS lint,
and treated as "cannot prove different" if they ever are).

``python -m agenttruth.scenarios.rs_defaults --write`` regenerates
``third_party/posthog/rs_defaults.json``; ``--check`` exits 1 if it is stale.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

from pydantic import JsonValue

from agenttruth.evidence.canonical import canonical_file_bytes, sha256_bytes
from agenttruth.evidence.models import RsDefaults, dump

__all__ = ["CLASSES", "POSTHOG_COMMIT", "extract", "main"]

POSTHOG_COMMIT = "e606d69fc4d9a7920ee4c2cbcd7cac62f915f58a"
CLASSES = (
    "BreakdownFilter",
    "ChartSettings",
    "CompareFilter",
    "DataVisualizationNode",
    "FunnelsFilter",
    "RetentionFilter",
    "TableSettings",
    "TrendsFilter",
    "TrendsQuery",
)
DEFAULT_ROOT = Path("third_party/posthog")
OUTPUT = "rs_defaults.json"


def _enum_values(tree: ast.Module) -> dict[tuple[str, str], str]:
    values: dict[tuple[str, str], str] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.Assign)
                    and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name)
                    and isinstance(stmt.value, ast.Constant)
                    and isinstance(stmt.value.value, str)
                ):
                    values[(node.name, stmt.targets[0].id)] = stmt.value.value
    return values


def _literal(expr: ast.expr, enums: dict[tuple[str, str], str]) -> JsonValue:
    if isinstance(expr, ast.Constant) and (expr.value is None or isinstance(expr.value, (bool, int, float, str))):
        return expr.value
    if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name):
        key = (expr.value.id, expr.attr)
        if key in enums:
            return enums[key]
    if isinstance(expr, (ast.List, ast.Tuple)):
        return [_literal(item, enums) for item in expr.elts]
    if isinstance(expr, ast.Dict) and all(isinstance(k, ast.Constant) and isinstance(k.value, str) for k in expr.keys):
        return {str(k.value): _literal(v, enums) for k, v in zip(expr.keys, expr.values, strict=True)}  # type: ignore[union-attr]
    return {"$expr": ast.unparse(expr)}


def _default(stmt: ast.AnnAssign, enums: dict[tuple[str, str], str]) -> JsonValue:
    value = stmt.value
    if value is None:
        return {"$required": True}
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "Field":
        for keyword in value.keywords:
            if keyword.arg == "default":
                return _literal(keyword.value, enums)
            if keyword.arg == "default_factory":
                return {"$expr": ast.unparse(value)}
        if value.args and not (isinstance(value.args[0], ast.Constant) and value.args[0].value is Ellipsis):
            return _literal(value.args[0], enums)
        return {"$required": True}
    return _literal(value, enums)


def extract(root: Path) -> RsDefaults:
    """Extract the defaults table from ``root/posthog/schema.py`` and ``root/posthog/schema_enums.py``.

    Raises ``KeyError`` naming any class of :data:`CLASSES` missing from the snapshot.
    """
    schema_path = root / "posthog" / "schema.py"
    enums_path = root / "posthog" / "schema_enums.py"
    schema = ast.parse(schema_path.read_text(encoding="utf-8"))
    enums = _enum_values(ast.parse(enums_path.read_text(encoding="utf-8")))
    classes = {node.name: node for node in schema.body if isinstance(node, ast.ClassDef)}
    table: dict[str, dict[str, JsonValue]] = {}
    for name in CLASSES:
        if name not in classes:
            raise KeyError(f"class {name} not found in {schema_path}")
        table[name] = {
            stmt.target.id: _default(stmt, enums)
            for stmt in classes[name].body
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
        }
    return RsDefaults.model_validate(
        {
            "schema": "agenttruth.rs-defaults/v1",
            "posthog_commit": POSTHOG_COMMIT,
            "sources": {
                "posthog/schema.py": f"sha256:{sha256_bytes(schema_path.read_bytes())}",
                "posthog/schema_enums.py": f"sha256:{sha256_bytes(enums_path.read_bytes())}",
            },
            "classes": table,
        }
    )


def main(argv: list[str] | None = None) -> int:
    """CLI: ``--write`` or ``--check`` ``third_party/posthog/rs_defaults.json``."""
    parser = argparse.ArgumentParser(prog="python -m agenttruth.scenarios.rs_defaults")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    data = canonical_file_bytes(dump(extract(args.root)))
    target = args.root / OUTPUT
    if args.write:
        target.write_bytes(data)
        print(f"wrote {target}")
        return 0
    if not target.exists() or target.read_bytes() != data:
        print(f"stale {target} (run: python -m agenttruth.scenarios.rs_defaults --write)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
