"""Data paths never use ``random``, ``numpy``, ``uuid4``, ``secrets`` or the wall clock (§5.1, K1 rejection).

Data paths: the dataset generator, the oracle, the scenario tooling and the evidence models/encoding.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "agenttruth"
DATA_PATHS = ["dataset", "oracle", "scenarios", "evidence"]
BANNED_MODULES = {"random", "numpy", "secrets"}
BANNED_CALLS = {
    ("uuid", "uuid4"),
    ("uuid", "uuid1"),
    ("time", "time"),
    ("time", "time_ns"),
    ("datetime", "now"),
    ("datetime", "utcnow"),
    ("datetime", "today"),
    ("date", "today"),
}


@pytest.mark.parametrize("component", DATA_PATHS)
def test_no_randomness_or_clock(component: str) -> None:
    for path in sorted((PACKAGE / component).rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not {a.name.split(".")[0] for a in node.names} & BANNED_MODULES, f"{path}:{node.lineno}"
            if isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in BANNED_MODULES, f"{path}:{node.lineno}"
                assert not {(node.module, a.name) for a in node.names} & BANNED_CALLS, f"{path}:{node.lineno}"
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                assert (node.value.id, node.attr) not in BANNED_CALLS, f"{path}:{node.lineno}"
