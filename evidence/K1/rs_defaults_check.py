"""Compare every round-trip-scripted (RS) value of contract §7.4 with its default in PostHog's schema.

Evidence tool for the K1 BLOCKED report. Standard library only; it parses (never imports) the
vendored ``posthog/schema.py`` and ``posthog/schema_enums.py`` snapshot from PostHog commit
``e606d69fc4d9a7920ee4c2cbcd7cac62f915f58a``.

Inputs: path to the vendored ``third_party/posthog/posthog`` directory (argument 1).
Output: canonical JSON on stdout, one record per RS key, with the schema default, the source line
and whether the RS value differs from it.
Failure modes: exits non-zero with a message if a class or field named below is missing from the
snapshot or its default expression is of a form this script does not resolve.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any

_UNSET = object()

# (RS key as written in contract §7.4, schema class, field, value requested by §7.4).
# Values the contract leaves to K1 ("a valid non-default value", "minimal valid rule") are given
# as the marker "<non-null value chosen in K1>": any such value differs from a None default.
_K1_CHOICE = "<non-null value chosen in K1>"
RS_KEYS: list[tuple[str, str, str, Any]] = [
    ("sql.display", "DataVisualizationNode", "display", "ActionsBar"),
    ("sql.chartSettings.showLegend", "ChartSettings", "showLegend", True),
    ("sql.chartSettings.legendPosition", "ChartSettings", "legendPosition", "bottom"),
    ("sql.chartSettings.showValuesOnSeries", "ChartSettings", "showValuesOnSeries", True),
    ("sql.chartSettings.stackBars100", "ChartSettings", "stackBars100", True),
    ("sql.chartSettings.showAnnotations", "ChartSettings", "showAnnotations", True),
    ("sql.chartSettings.showXAxisTicks", "ChartSettings", "showXAxisTicks", False),
    ("sql.chartSettings.showYAxisBorder", "ChartSettings", "showYAxisBorder", False),
    ("sql.chartSettings.yAxisAtZero", "ChartSettings", "yAxisAtZero", False),
    ("sql.chartSettings.chartStyle", "ChartSettings", "chartStyle", _K1_CHOICE),
    ("sql.tableSettings.pinnedColumns", "TableSettings", "pinnedColumns", _K1_CHOICE),
    ("sql.tableSettings.conditionalFormatting", "TableSettings", "conditionalFormatting", _K1_CHOICE),
    ("sql.update.chartSettings.legendPosition", "ChartSettings", "legendPosition", "top"),
    ("trends.trendsFilter.display", "TrendsFilter", "display", "ActionsBar"),
    ("trends.trendsFilter.showValuesOnSeries", "TrendsFilter", "showValuesOnSeries", True),
    ("trends.compareFilter.compare", "CompareFilter", "compare", True),
    ("trends.breakdownFilter.breakdown", "BreakdownFilter", "breakdown", "$os"),
    ("trends.interval", "TrendsQuery", "interval", "week"),
    ("funnels.funnelsFilter.funnelWindowInterval", "FunnelsFilter", "funnelWindowInterval", 7),
    ("funnels.funnelsFilter.funnelOrderType", "FunnelsFilter", "funnelOrderType", "strict"),
    ("funnels.funnelsFilter.funnelVizType", "FunnelsFilter", "funnelVizType", "trends"),
    (
        "funnels.funnelsFilter.breakdownAttributionType",
        "FunnelsFilter",
        "breakdownAttributionType",
        "last_touch",
    ),
    ("retention.retentionFilter.period", "RetentionFilter", "period", "Week"),
    ("retention.retentionFilter.totalIntervals", "RetentionFilter", "totalIntervals", 8),
    (
        "retention.retentionFilter.retentionType",
        "RetentionFilter",
        "retentionType",
        "retention_first_time",
    ),
    ("retention.retentionFilter.cumulative", "RetentionFilter", "cumulative", True),
]


def _classes(tree: ast.Module) -> dict[str, ast.ClassDef]:
    return {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}


def _enum_values(enums_tree: ast.Module) -> dict[tuple[str, str], str]:
    values: dict[tuple[str, str], str] = {}
    for cls in _classes(enums_tree).values():
        for stmt in cls.body:
            if (
                isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)
            ):
                values[(cls.name, stmt.targets[0].id)] = stmt.value.value
    return values


def _default_expr(stmt: ast.AnnAssign) -> ast.expr | None:
    value = stmt.value
    if value is None:
        return None
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "Field":
        for keyword in value.keywords:
            if keyword.arg == "default":
                return keyword.value
        if value.args:
            return value.args[0]
        return None
    return value


def _resolve(expr: ast.expr | None, enums: dict[tuple[str, str], str]) -> Any:
    if expr is None:
        return _UNSET
    if isinstance(expr, ast.Constant):
        return expr.value
    if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name):
        key = (expr.value.id, expr.attr)
        if key in enums:
            return enums[key]
    if isinstance(expr, ast.List) and not expr.elts:
        return []
    raise SystemExit(f"unresolved default expression: {ast.unparse(expr)}")


def main(argv: list[str]) -> int:
    """Print the RS-versus-default table as canonical JSON; return 1 if any RS value equals its default."""
    if len(argv) != 2:
        raise SystemExit("usage: rs_defaults_check.py <third_party/posthog/posthog>")
    root = Path(argv[1])
    schema_tree = ast.parse((root / "schema.py").read_text(encoding="utf-8"))
    enums = _enum_values(ast.parse((root / "schema_enums.py").read_text(encoding="utf-8")))
    classes = _classes(schema_tree)
    records: list[dict[str, Any]] = []
    for rs_key, class_name, field, requested in RS_KEYS:
        cls = classes.get(class_name)
        if cls is None:
            raise SystemExit(f"class not found in snapshot: {class_name}")
        for stmt in cls.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.target.id == field:
                default = _resolve(_default_expr(stmt), enums)
                break
        else:
            raise SystemExit(f"field not found in snapshot: {class_name}.{field}")
        default_out = None if default is _UNSET else default
        if requested == _K1_CHOICE:
            differs = default_out is None
        else:
            # Type-strict so that True is not mistaken for 1 or False for 0.
            differs = not (type(requested) is type(default_out) and requested == default_out)
        records.append(
            {
                "rs_key": rs_key,
                "schema_class": class_name,
                "field": field,
                "schema_line": stmt.lineno,
                "schema_default": default_out,
                "rs_value": requested,
                "differs_from_default": differs,
            }
        )
    out = {
        "schema": "agenttruth.rs-defaults-check/v1",
        "posthog_commit": "e606d69fc4d9a7920ee4c2cbcd7cac62f915f58a",
        "records": records,
        "violations": [r["rs_key"] for r in records if not r["differs_from_default"]],
    }
    sys.stdout.write(json.dumps(out, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
    return 1 if out["violations"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
