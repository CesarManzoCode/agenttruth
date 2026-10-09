"""Catalog lint (K1-C6), PostHog export, and the round-trip defaults table."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agenttruth.evidence.models import Catalog, RsDefaults
from agenttruth.evidence.read import load_json, load_yaml
from agenttruth.scenarios.export import render_posthog_tasks_v2
from agenttruth.scenarios.lint import lint_catalog
from agenttruth.scenarios.rs_defaults import extract

CATALOG = Path("scenarios/catalog.v1.yaml")
TRUTHS = Path("truths/ds1.v1.json")
DEFAULTS = Path("third_party/posthog/rs_defaults.json")


def _rules(tmp_path: Path, mutate: Any, truths: Path | None = None) -> set[str]:
    data = load_yaml(CATALOG)
    assert isinstance(data, dict)
    mutate(data)
    path = tmp_path / "catalog.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    report = lint_catalog(path, truths, DEFAULTS)
    return {issue.rule for issue in report.issues}


def _scenario(data: dict[str, Any], sid: str) -> dict[str, Any]:
    return next(s for s in data["scenarios"] if s["id"] == sid)


def test_committed_catalog_passes_lint() -> None:
    report = lint_catalog(CATALOG, TRUTHS, DEFAULTS)
    assert report.ok, report.issues
    assert report.by_kind == {
        "exact_answer": 16,
        "planted_cause": 5,
        "roundtrip_agent": 6,
        "roundtrip_scripted": 27,
    }


def test_lint_catches_structural_problems(tmp_path: Path) -> None:
    def dup(d: dict[str, Any]) -> None:
        d["scenarios"][1]["id"] = d["scenarios"][0]["id"]

    def category(d: dict[str, Any]) -> None:
        d["scenarios"][0]["category"] = "dashboards"

    def signature(d: dict[str, Any]) -> None:
        d["scenarios"][0]["agenttruth"]["signatures"].append("SIG_EVENT_teleported")

    assert "id-unique" in _rules(tmp_path, dup)
    assert "category" in _rules(tmp_path, category)
    assert "sig-exists" in _rules(tmp_path, signature)


def test_lint_rejects_an_rs_value_equal_to_its_schema_default(tmp_path: Path) -> None:
    def default_intervals(d: dict[str, Any]) -> None:
        _scenario(d, "rs-retention-totalintervals")["agenttruth"]["value"] = 8  # the 1.0.0 value (ADR-0022)

    assert "rs-default" in _rules(tmp_path, default_intervals)


def test_lint_enforces_prompt_rules(tmp_path: Path) -> None:
    def hint(d: dict[str, Any]) -> None:
        _scenario(d, "ea-signups-day-0714")["intent"] = "How many sign-ups were there on July 14, 2026, in UTC?"

    def window(d: dict[str, Any]) -> None:
        scenario = _scenario(d, "ea-funnel-signup-upload-1d")
        scenario["intent"] = scenario["intent"].replace("within 1 day", "soon")

    def phrase(d: dict[str, Any]) -> None:
        scenario = _scenario(d, "ea-uploads-july-filtered")
        scenario["intent"] = "How many files were uploaded in July 2026?"

    assert "prompt-no-hints" in _rules(tmp_path, hint)
    assert "prompt-funnel-window" in _rules(tmp_path, window)
    assert "prompt-test-accounts" in _rules(tmp_path, phrase, TRUTHS)


def test_export_has_posthog_fields_only() -> None:
    catalog = Catalog.model_validate(load_yaml(CATALOG))
    text = render_posthog_tasks_v2(catalog, "catalog")
    doc = yaml.safe_load(text)
    assert doc["version"] == 2 and len(doc["tasks"]) == 27
    allowed = {"id", "category", "intent", "expected_tools", "acceptable_tools", "success_criteria"}
    assert all(set(task) == allowed for task in doc["tasks"])
    assert render_posthog_tasks_v2(catalog, "catalog") == text


def test_rs_defaults_table_matches_the_vendored_schema() -> None:
    committed = RsDefaults.model_validate(load_json(DEFAULTS))
    assert extract(Path("third_party/posthog")) == committed
    assert committed.classes["RetentionFilter"]["totalIntervals"] == 8
    assert len(committed.classes["ChartSettings"]) == 26
