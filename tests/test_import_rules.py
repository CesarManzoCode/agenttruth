"""AST test of the contract §4.1 import rules (K1-C8). Independent of the gate's own checker.

Rules: ``oracle`` imports from ``dataset`` only the event-file reader and the spec model (which in
turn import only ``evidence``) and never names the ledger; ``gates`` imports only the read side of
``evidence`` and the standard library; nothing outside ``gates`` imports it; components import only
``evidence`` and themselves (top-level tooling excepted); no dynamic imports.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
PACKAGE = SRC / "agenttruth"
READ_SIDE = {"agenttruth.evidence.read", "agenttruth.evidence.canonical", "agenttruth.evidence.models"}
ORACLE_VISIBLE = {"agenttruth.dataset.reader", "agenttruth.dataset.spec"}
COMPONENT_DEPS = {
    "evidence": {"evidence"},
    "dataset": {"evidence", "dataset"},
    "oracle": {"evidence", "oracle"},
    "scenarios": {"evidence", "scenarios"},
}
THIRD_PARTY_GATES: set[str] = set()


def _modules() -> dict[str, Path]:
    out = {}
    for path in PACKAGE.rglob("*.py"):
        parts = list(path.relative_to(SRC).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        out[".".join(parts)] = path
    return out


def _targets(name: str, path: Path, modules: dict[str, Path]) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = name if path.name == "__init__.py" else name.rpartition(".")[0]
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")[: len(package.split(".")) - node.level + 1]
                module = ".".join(base + ([node.module] if node.module else []))
            else:
                module = node.module or ""
            found.append(module)
            found += [f"{module}.{a.name}" for a in node.names if f"{module}.{a.name}" in modules]
    return found


def _component(module: str) -> str:
    return module.split(".")[1] if module.count(".") >= 1 else ""


def test_import_rules_hold() -> None:
    modules = _modules()
    assert "agenttruth.oracle.compute" in modules and "agenttruth.gates.k1" in modules
    problems = []
    for name, path in sorted(modules.items()):
        component = _component(name)
        for target in _targets(name, path, modules):
            top = target.split(".")[0]
            if top in {"importlib", "runpy"}:
                problems.append(f"{name}: dynamic import {target}")
            if target == "agenttruth":
                continue  # the root package (version constants) is importable by everyone
            if top != "agenttruth":
                if component == "gates" and top not in sys.stdlib_module_names and top != "__future__":
                    problems.append(f"{name}: gates import third-party {target}")
                continue
            tc = _component(target)
            if tc == "gates" and component != "gates":
                problems.append(f"{name}: imports gates ({target})")
            elif component == "gates" and tc != "gates" and target not in READ_SIDE and target != "agenttruth.evidence":
                problems.append(f"{name}: gates import {target} (only the evidence read side is allowed)")
            elif name in ORACLE_VISIBLE and tc != "evidence" and target not in ORACLE_VISIBLE:
                problems.append(f"{name}: oracle-visible module imports {target}")
            elif component == "oracle" and tc == "dataset" and target not in ORACLE_VISIBLE | {"agenttruth.dataset"}:
                problems.append(f"{name}: oracle imports {target}")
            elif (
                component in COMPONENT_DEPS
                and tc not in COMPONENT_DEPS[component]
                and not (component == "oracle" and tc == "dataset")
            ):
                problems.append(f"{name}: {component} imports {target}")
    assert problems == []


def test_oracle_never_reads_the_ledger() -> None:
    for path in sorted((PACKAGE / "oracle").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docs = {
            id(n.body[0].value)
            for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body and isinstance(n.body[0], ast.Expr)
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
                assert "ledger" not in node.value.lower(), f"{path.name}:{node.lineno}"
            if isinstance(node, ast.Name):
                assert node.id != "Ledger", f"{path.name}:{node.lineno}"


def test_nothing_calls_dunder_import() -> None:
    for path in sorted(PACKAGE.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id != "__import__", f"{path}:{node.lineno}"
