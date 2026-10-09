"""``agenttruth scenarios lint``: mechanical checks of the catalog (contract §7.2, §7.4, K1-C6).

Structure: the catalog validates against its model; ids are unique, kebab-case and at most 64
characters (PostHog's limit); categories are PostHog ``TASK_CATEGORIES`` in scope; every SEM and SIG
id exists; tools are in-scope MCP tools; each fault has exactly one planted-cause scenario.

Round trip: every RS value differs from its default in the vendored ``posthog/schema.py``.

Prompts (where mechanical): absolute dates; no pitfall hints; the test-account phrase when
flipping the filter changes the truth (and only the phrase that matches the filter); funnels state
their window and strict order; mapping and ranking answers name their keys or say "using the values
exactly as recorded"; planted-cause prompts do not name the planted property or value.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from pydantic import JsonValue, ValidationError

from agenttruth.evidence.canonical import sha256_bytes
from agenttruth.evidence.models import (
    Catalog,
    CustomMetric,
    EASpec,
    FunnelMetric,
    LintIssue,
    LintReport,
    PCSpec,
    RASpec,
    RsDefaults,
    RSSpec,
    TrendsMetric,
    Truths,
)
from agenttruth.evidence.read import load_json, load_yaml

__all__ = ["DATASET_EVENTS", "MCP_TOOLS", "lint_catalog"]

CATEGORIES = frozenset({"product-analytics", "sql", "insights"})
MCP_TOOLS = frozenset(
    {
        "read-data-schema",
        "query-trends",
        "query-funnel",
        "query-retention",
        "execute-sql",
        "insight-get",
        "insights-list",
        "insight-query",
        "insight-create",
        "insight-update",
        "insight-delete",
    }
)
DATASET_EVENTS = frozenset(
    {
        "$pageview",
        "$identify",
        "signed_up",
        "logged_in",
        "uploaded_file",
        "downloaded_file",
        "shared_file_link",
        "deleted_file",
        "upgraded_plan",
        "downgraded_plan",
        "invited_team_member",
        "paid_bill",
    }
)
SEMANTIC_RULES = frozenset(f"SEM-{n:02d}" for n in range(1, 16))
SIGNATURES = frozenset(
    {
        "SIG_PERIOD_PREV",
        "SIG_PERIOD_NEXT",
        "SIG_PERIOD_EXCL_END",
        "SIG_PERIOD_EXTRA_DAY",
        "SIG_TZ_UTC",
        "SIG_TEST_ACCOUNTS",
        "SIG_AGG_TOTAL",
        "SIG_AGG_UNIQUE",
        "SIG_FUNNEL_WINDOW_DEFAULT",
        "SIG_FUNNEL_ORDER",
        "SIG_RETENTION_TYPE",
        "SIG_RETENTION_CUMULATIVE",
        "SIG_FILTER_DROPPED",
    }
)
EXCLUDING = "excluding internal and test users"
INCLUDING = "including internal and test users"
RECORDED = "using the values exactly as recorded"
_KEBAB = re.compile(r"^[a-z0-9][a-z0-9-]+$")
_MONTH = re.compile(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\b")
# Words that would teach to the test: how PostHog computes, which tool to use, which trap to avoid.
_HINTS = (
    "timezone",
    "time zone",
    "utc",
    "gmt",
    "posthog",
    "hogql",
    "sql",
    "insight",
    "query",
    "filter",
    "test account",
    "conversion window",
    "persons on events",
    "$identify",
    "distinct id",
    "warm-up",
    "local time",
    "project time",
    "calendar",
)
_PC_HINTS = (
    "outage",
    "duplicate",
    "identity",
    "internal",
    "$os",
    "$browser",
    "$current_url",
    "email",
    "new_plan",
)
_UNIT_WORDS = {"second": "second", "minute": "minute", "hour": "hour", "day": "day", "week": "week"}


def _issue(issues: list[LintIssue], scenario_id: str | None, rule: str, message: str) -> None:
    issues.append(LintIssue(scenario_id=scenario_id, rule=rule, message=message))


def _check_prompt_common(issues: list[LintIssue], sid: str, intent: str) -> None:
    lowered = intent.lower()
    if "2026" not in intent or not _MONTH.search(intent):
        _issue(issues, sid, "prompt-absolute-date", "intent must state absolute dates (month name and year)")
    for hint in _HINTS:
        if re.search(rf"(?<![a-z]){re.escape(hint)}(?![a-z])", lowered):
            _issue(issues, sid, "prompt-no-hints", f"intent must not mention {hint!r}")


def _check_ea_prompt(
    issues: list[LintIssue], sid: str, intent: str, info: EASpec, truths: dict[str, JsonValue] | None
) -> None:
    lowered = intent.lower()
    metric = info.metric
    _check_prompt_common(issues, sid, intent)
    if isinstance(metric, TrendsMetric) and metric.math == "dau":
        if "unique" not in lowered:
            _issue(issues, sid, "prompt-unique", "a unique-persons metric must ask for unique users")
    elif "unique" in lowered:
        _issue(issues, sid, "prompt-unique", "only unique-persons questions may say 'unique'")
    has_excl, has_incl = EXCLUDING in lowered, INCLUDING in lowered
    if has_excl and not metric.filter_test_accounts:
        _issue(issues, sid, "prompt-test-accounts", f"'{EXCLUDING}' but the metric does not filter test accounts")
    if has_incl and metric.filter_test_accounts:
        _issue(issues, sid, "prompt-test-accounts", f"'{INCLUDING}' but the metric filters test accounts")
    if truths is not None:
        record = truths.get(sid)
        if not isinstance(record, dict):
            _issue(issues, sid, "truths", "no truth record for this scenario")
        elif record.get("test_accounts_flipped") != record.get("value") and not (has_excl or has_incl):
            _issue(
                issues,
                sid,
                "prompt-test-accounts",
                f"flipping the test-account filter changes the truth: intent must say '{EXCLUDING}' or '{INCLUDING}'",
            )
    if isinstance(metric, FunnelMetric):
        unit = _UNIT_WORDS[metric.window.unit]
        if not re.search(rf"within {metric.window.n} {unit}s?\b", lowered):
            _issue(
                issues,
                sid,
                "prompt-funnel-window",
                f"intent must state the window 'within {metric.window.n} {unit}'",
            )
        strict_words = "very next action" in lowered
        if strict_words != (metric.order == "strict"):
            _issue(issues, sid, "prompt-funnel-order", "strict order must be stated, and only for strict funnels")
        keys = ["entered", "converted"] + [f"step_{k}" for k in range(2, len(metric.steps))]
        missing = [k for k in keys if k not in intent]
        if missing:
            _issue(issues, sid, "prompt-mapping-keys", f"intent must name the answer keys {missing}")
    if info.answer_kind == "mapping" and metric.type == "retention":
        missing = [k for k in ("cohort_size", "retained") if k not in intent]
        if missing:
            _issue(issues, sid, "prompt-mapping-keys", f"intent must name the answer keys {missing}")
    breakdown = isinstance(metric, TrendsMetric) and metric.breakdown is not None
    if (breakdown or info.answer_kind == "ranking") and RECORDED not in lowered:
        _issue(issues, sid, "prompt-recorded-values", f"intent must say '{RECORDED}'")


def lint_catalog(catalog_path: Path, truths_path: Path | None, rs_defaults_path: Path) -> LintReport:
    """Lint ``catalog_path``; returns a report whose ``ok`` is False if any issue was found.

    ``truths_path`` (optional) enables the test-account phrase rule and truth-consistency checks.
    Raises ``FileNotFoundError`` for missing inputs; every catalog problem becomes an issue.
    """
    issues: list[LintIssue] = []
    data = catalog_path.read_bytes()
    truths_sha = None
    truths_by_id: dict[str, JsonValue] | None = None
    if truths_path is not None:
        truths_sha = sha256_bytes(truths_path.read_bytes())
        truths = Truths.model_validate(load_json(truths_path))
        truths_by_id = {r.scenario_id: r.model_dump(mode="json") for r in truths.truths}
        if truths.catalog_sha256 != sha256_bytes(data):
            _issue(
                issues,
                None,
                "truths",
                "truths were computed from a different catalog (catalog_sha256 differs)",
            )
    try:
        catalog = Catalog.model_validate(load_yaml(catalog_path))
    except ValidationError as exc:
        _issue(issues, None, "schema", str(exc))
        return _report(data, truths_sha, issues, None)
    defaults = RsDefaults.model_validate(load_json(rs_defaults_path))

    ids = Counter(s.id for s in catalog.scenarios)
    for sid, count in sorted(ids.items()):
        if count > 1:
            _issue(issues, sid, "id-unique", f"id appears {count} times")
    faults = Counter(s.agenttruth.fault for s in catalog.scenarios if isinstance(s.agenttruth, PCSpec))
    for fault in ("F1", "F2", "F3", "F4", "F5"):
        if faults.get(fault, 0) != 1:
            _issue(issues, None, "pc-per-fault", f"{fault} needs exactly one planted-cause scenario")

    for scenario in catalog.scenarios:
        sid, info = scenario.id, scenario.agenttruth
        if not _KEBAB.match(sid) or len(sid) > 64:
            _issue(issues, sid, "id-kebab", "ids are kebab-case, at most 64 characters")
        if scenario.category not in CATEGORIES:
            _issue(issues, sid, "category", f"category {scenario.category!r} is not one of {sorted(CATEGORIES)}")
        if len(scenario.intent) < 10 or len(scenario.success_criteria) < 10:
            _issue(issues, sid, "text-length", "intent and success_criteria need at least 10 characters")
        tools = [*scenario.expected_tools, *scenario.acceptable_tools]
        if not scenario.expected_tools or any(t not in MCP_TOOLS for t in tools):
            _issue(issues, sid, "tools", f"tools must be in-scope MCP tools: {sorted(set(tools) - MCP_TOOLS)}")
        if isinstance(info, (EASpec, PCSpec)):
            for sem in info.semantics:
                if sem not in SEMANTIC_RULES:
                    _issue(issues, sid, "sem-exists", f"unknown semantic rule {sem}")
        if isinstance(info, EASpec):
            for sig in info.signatures:
                event = sig.removeprefix("SIG_EVENT_") if sig.startswith("SIG_EVENT_") else None
                if sig not in SIGNATURES and (event is None or event not in DATASET_EVENTS):
                    _issue(issues, sid, "sig-exists", f"unknown signature {sig}")
            if len(set(info.signatures)) != len(info.signatures):
                _issue(issues, sid, "sig-unique", "a signature is declared twice")
            if isinstance(info.metric, CustomMetric) and info.posthog_query == "auto":
                _issue(issues, sid, "posthog-query", "custom metrics carry their reviewed HogQL")
            if not isinstance(info.metric, CustomMetric) and info.posthog_query != "auto":
                _issue(
                    issues,
                    sid,
                    "posthog-query",
                    "non-custom metrics compile automatically (posthog_query: auto)",
                )
            _check_ea_prompt(issues, sid, scenario.intent, info, truths_by_id)
        elif isinstance(info, PCSpec):
            _check_prompt_common(issues, sid, scenario.intent)
            lowered = scenario.intent.lower()
            for hint in _PC_HINTS:
                if hint in lowered:
                    _issue(issues, sid, "prompt-no-hints", f"planted-cause intent must not mention {hint!r}")
            record = truths_by_id.get(sid) if truths_by_id is not None else None
            if isinstance(record, dict) and isinstance(record.get("value"), dict):
                value = str(record["value"].get("value") or "")  # type: ignore[union-attr]
                if len(value) >= 5 and value.lower() in lowered:
                    _issue(issues, sid, "prompt-no-hints", f"planted-cause intent must not name {value!r}")
                if info.value_match.rule == "contains" and (info.value_match.substring or "") not in value:
                    _issue(issues, sid, "value-match", "the truth value does not contain the planted substring")
        elif isinstance(info, RSSpec):
            known = defaults.classes.get(info.schema_default.schema_class)
            if known is None or info.schema_default.schema_field not in known:
                _issue(issues, sid, "rs-default", f"{info.schema_default} is not in the vendored schema snapshot")
            else:
                default = known[info.schema_default.schema_field]
                provable = not (isinstance(default, dict) and ("$expr" in default or "$required" in default))
                if not provable or _same_json(info.value, default):
                    _issue(
                        issues,
                        sid,
                        "rs-default",
                        f"RS value {info.value!r} must differ from schema default {default!r}",
                    )
            if info.path.rsplit(".", 1)[-1] != info.schema_default.schema_field:
                _issue(issues, sid, "rs-path", "the path must end with the schema field it sets")
        elif isinstance(info, RASpec):
            if f"at-rt-{{run_id}}-{sid}" not in scenario.intent:
                _issue(issues, sid, "ra-name", f"intent must name the insight at-rt-{{run_id}}-{sid}")
    return _report(data, truths_sha, issues, catalog)


def _same_json(a: JsonValue, b: JsonValue) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    return a == b


def _report(data: bytes, truths_sha: str | None, issues: list[LintIssue], catalog: Catalog | None) -> LintReport:
    scenarios = catalog.scenarios if catalog is not None else []
    return LintReport.model_validate(
        {
            "schema": "agenttruth.lint-report/v1",
            "catalog_sha256": sha256_bytes(data),
            "truths_sha256": truths_sha,
            "ok": not issues,
            "scenarios": len(scenarios),
            "by_kind": dict(sorted(Counter(s.agenttruth.kind for s in scenarios).items())),
            "signatures": sum(len(s.agenttruth.signatures) for s in scenarios if isinstance(s.agenttruth, EASpec)),
            "issues": [i.model_dump() for i in issues],
        }
    )
