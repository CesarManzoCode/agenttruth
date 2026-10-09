"""L0 on fresh data: the journey-based ledger and the event-based oracle agree metric by metric.

Every exact-answer metric of catalog v1, plus extra variants, is evaluated both ways on a reduced
``ds1`` (faults on, so F3's split identities are covered) and on ``ds0``.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from test_generator import small_ds1

from agenttruth.dataset.build import load_spec
from agenttruth.dataset.generate import build_journeys, event_record
from agenttruth.dataset.ledger_eval import LedgerError, evaluate, persons_of
from agenttruth.dataset.spec import DatasetSpec
from agenttruth.dataset.timeutil import Clock
from agenttruth.evidence.models import Catalog, EASpec, Event, Metric, TrendsMetric
from agenttruth.evidence.read import load_yaml
from agenttruth.oracle import metrics
from agenttruth.oracle.frame import Frame, OracleError


def _catalog_metrics() -> list[Metric]:
    catalog = Catalog.model_validate(load_yaml(Path("scenarios/catalog.v1.yaml")))
    return [s.agenttruth.metric for s in catalog.scenarios if isinstance(s.agenttruth, EASpec)]


def _variants(window: tuple[date, date]) -> list[Metric]:
    start, end = window
    out: list[Metric] = []
    for metric in _catalog_metrics():
        out.append(metric)
        out.append(metric.model_copy(update={"date_from": start, "date_to": end}))
        out.append(metric.model_copy(update={"filter_test_accounts": not metric.filter_test_accounts}))
    for math in ("total", "dau"):
        for event in ("$pageview", "logged_in", "shared_file_link"):
            base = {"type": "trends", "event": event, "math": math, "date_from": start, "date_to": end,
                    "filter_test_accounts": False}  # fmt: skip
            out.append(TrendsMetric.model_validate(base))
            out.append(TrendsMetric.model_validate({**base, "breakdown": "$browser", "interval": "day"}))
    return out


def _compare(spec: DatasetSpec) -> int:
    journeys = build_journeys(spec, frozenset())
    events = [
        Event.model_validate(event_record(spec.dataset_id, j, a)) for j in journeys for a in j.actions if a.emitted
    ]
    frame = Frame(events, spec.timezone)
    persons = persons_of(journeys)
    clock = Clock(spec.timezone)
    checked = 0
    for metric in _variants((spec.window.date_from, spec.window.date_to)):
        ledger: Any
        oracle: Any
        try:
            ledger = evaluate(metric, persons, clock, "@hedgebox-internal.example")
        except LedgerError:
            ledger = "undefined"
        try:
            oracle = metrics.evaluate(metric, frame, spec.timezone)
        except OracleError:
            oracle = "undefined"
        assert ledger == oracle, metric
        checked += 1
    return checked


@pytest.mark.parametrize("which", ["ds0", "small-ds1"])
def test_ledger_and_oracle_agree(which: str) -> None:
    spec = load_spec(Path("datasets/ds0.spec.yaml")) if which == "ds0" else small_ds1()
    assert _compare(spec) == 60
