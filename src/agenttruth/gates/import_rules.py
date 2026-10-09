"""The gate's own AST check of the contract §4.1 import rules (K1-C8). Standard library only.

Components are the first package level under ``agenttruth``. Allowed AgentTruth imports:

- ``evidence``: ``evidence``.
- ``dataset``: ``evidence``, ``dataset``.
- ``oracle``: ``evidence``, ``oracle`` and only ``dataset.reader`` / ``dataset.spec`` (the event-file
  reader and the dataset spec model); those two modules may import only ``evidence``. The oracle
  never names the ledger.
- ``scenarios``: ``evidence``, ``scenarios``.
- ``gates``: ``evidence.read``, ``evidence.canonical``, ``evidence.models`` (read side) and ``gates``;
  third-party packages are not allowed in ``gates`` at all.
- top-level tooling (``cli``, ``schemagen``, ``__main__``): any component except ``gates``.
- Nothing outside ``gates`` imports ``gates``; the root package ``agenttruth`` is importable by all.

Dynamic imports (``importlib.import_module``, ``__import__``, ``runpy``) are forbidden everywhere,
so the rules cannot be bypassed with strings.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

__all__ = ["Violation", "check_tree"]

_THIRD_PARTY: dict[str, frozenset[str]] = {
    "evidence": frozenset({"pydantic", "yaml", "jsonschema"}),
    "dataset": frozenset({"pydantic", "yaml"}),
    "oracle": frozenset({"pydantic"}),
    "scenarios": frozenset({"pydantic", "yaml"}),
    "gates": frozenset(),
    "cli": frozenset({"pydantic"}),
    "schemagen": frozenset({"pydantic"}),
    "__main__": frozenset(),
    "__init__": frozenset(),
}
_READ_SIDE = frozenset({"agenttruth.evidence.read", "agenttruth.evidence.canonical", "agenttruth.evidence.models"})
_ORACLE_DATASET = frozenset({"agenttruth.dataset.reader", "agenttruth.dataset.spec"})


@dataclass(frozen=True)
class Violation:
    """One import-rule violation."""

    module: str
    line: int
    rule: str
    detail: str


def _module_name(src: Path, path: Path) -> str:
    parts = list(path.relative_to(src).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _component(module: str) -> str:
    parts = module.split(".")
    return parts[1] if len(parts) > 1 else "__init__"


def _imports(tree: ast.Module, module: str, is_package: bool, modules: set[str]) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    package = module if is_package else module.rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - (node.level - 1)]
                target = ".".join([*base, node.module] if node.module else base)
            else:
                target = node.module or ""
            found.append((node.lineno, target))
            # ``from agenttruth.dataset import build`` imports the submodule too.
            found.extend(
                (node.lineno, f"{target}.{alias.name}") for alias in node.names if f"{target}.{alias.name}" in modules
            )
    return found


def _allowed_internal(component: str, module: str, target: str) -> str | None:
    if target == "agenttruth":
        return None
    target_component = _component(target)
    if target_component == "gates" and component != "gates":
        return "nothing imports gates"
    if component == "gates":
        if target_component == "gates" or target in _READ_SIDE or target == "agenttruth.evidence":
            return None
        return "gates import only the read side of evidence"
    if module in _ORACLE_DATASET:
        return (
            None
            if target_component == "evidence" or target in _ORACLE_DATASET
            else "oracle-visible dataset modules import only evidence"
        )
    allowed = {
        "evidence": {"evidence"},
        "dataset": {"evidence", "dataset"},
        "oracle": {"evidence", "oracle"},
        "scenarios": {"evidence", "scenarios"},
    }.get(component)
    if allowed is None:  # top-level tooling
        return None
    if target_component in allowed:
        return None
    if component == "oracle" and target in _ORACLE_DATASET | {"agenttruth.dataset"}:
        return None
    return f"{component} may not import {target}"


def check_tree(src: Path) -> list[Violation]:
    """Check every module under ``src/agenttruth``; return all violations (empty when clean)."""
    stdlib = set(sys.stdlib_module_names)
    violations: list[Violation] = []
    paths = sorted((src / "agenttruth").rglob("*.py"))
    modules = {_module_name(src, path) for path in paths}
    for path in paths:
        module = _module_name(src, path)
        component = _component(module)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for line, target in _imports(tree, module, path.name == "__init__.py", modules):
            top = target.split(".")[0]
            if top == "agenttruth":
                reason = _allowed_internal(component, module, target)
                if reason:
                    violations.append(Violation(module, line, "component", f"{target}: {reason}"))
            elif top in {"importlib", "runpy"}:
                violations.append(Violation(module, line, "dynamic-import", f"{target} is not allowed"))
            elif top not in stdlib and top != "__future__" and top not in _THIRD_PARTY.get(component, frozenset()):
                violations.append(Violation(module, line, "third-party", f"{component} may not import {target}"))
        docstrings = {
            id(owner.body[0].value)
            for owner in ast.walk(tree)
            if isinstance(owner, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and owner.body
            and isinstance(owner.body[0], ast.Expr)
            and isinstance(owner.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "__import__":
                violations.append(Violation(module, node.lineno, "dynamic-import", "__import__ is not allowed"))
            if (
                component == "oracle"
                and isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
                and "ledger" in node.value.lower()
            ):
                violations.append(
                    Violation(module, node.lineno, "oracle-ledger", "the oracle must not name the ledger")
                )
            if component == "oracle" and isinstance(node, (ast.Name, ast.Attribute)):
                name = node.id if isinstance(node, ast.Name) else node.attr
                if name == "Ledger":
                    violations.append(
                        Violation(module, node.lineno, "oracle-ledger", "the oracle must not use the Ledger model")
                    )
    return violations
