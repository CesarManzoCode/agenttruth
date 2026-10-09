"""Signature transforms of contract §6.3."""

from __future__ import annotations

from datetime import date

import pytest

from agenttruth.evidence.models import FunnelMetric, RetentionMetric, TrendsMetric
from agenttruth.oracle.frame import OracleError
from agenttruth.oracle.signatures import transform

TZ = "America/Mexico_City"
JULY = TrendsMetric.model_validate(
    {"type": "trends", "event": "uploaded_file", "math": "total", "date_from": "2026-07-01", "date_to": "2026-07-31",
     "filter_test_accounts": True}
)  # fmt: skip


def test_period_shifts_use_the_range_length() -> None:
    prev, _ = transform(JULY, "SIG_PERIOD_PREV", TZ)
    nxt, _ = transform(JULY, "SIG_PERIOD_NEXT", TZ)
    assert (prev.date_from, prev.date_to) == (date(2026, 5, 31), date(2026, 6, 30))
    assert (nxt.date_from, nxt.date_to) == (date(2026, 8, 1), date(2026, 8, 31))
    excl, _ = transform(JULY, "SIG_PERIOD_EXCL_END", TZ)
    extra, _ = transform(JULY, "SIG_PERIOD_EXTRA_DAY", TZ)
    assert excl.date_to == date(2026, 7, 30) and extra.date_to == date(2026, 8, 1)


def test_timezone_filter_and_aggregation() -> None:
    assert transform(JULY, "SIG_TZ_UTC", TZ) == (JULY, "UTC")
    flipped, _ = transform(JULY, "SIG_TEST_ACCOUNTS", TZ)
    assert flipped.filter_test_accounts is False
    unique, _ = transform(JULY, "SIG_AGG_UNIQUE", TZ)
    assert isinstance(unique, TrendsMetric) and unique.math == "dau"
    with pytest.raises(OracleError):
        transform(JULY, "SIG_AGG_TOTAL", TZ)


def test_event_confusion_replaces_the_partner_event() -> None:
    swapped, _ = transform(JULY, "SIG_EVENT_downloaded_file", TZ)
    assert isinstance(swapped, TrendsMetric) and swapped.event == "downloaded_file"
    with pytest.raises(OracleError):
        transform(JULY, "SIG_EVENT_logged_in", TZ)


def test_funnel_and_retention_signatures() -> None:
    funnel = FunnelMetric.model_validate(
        {"type": "funnel", "steps": [{"event": "$pageview", "properties": [{"key": "$current_url", "operator":
         "icontains", "value": "/pricing/"}]}, {"event": "signed_up"}], "window": {"n": 1, "unit": "hour"},
         "order": "ordered", "date_from": "2026-06-01", "date_to": "2026-06-30", "filter_test_accounts": True}
    )  # fmt: skip
    default, _ = transform(funnel, "SIG_FUNNEL_WINDOW_DEFAULT", TZ)
    assert isinstance(default, FunnelMetric) and (default.window.n, default.window.unit) == (14, "day")
    strict, _ = transform(funnel, "SIG_FUNNEL_ORDER", TZ)
    assert isinstance(strict, FunnelMetric) and strict.order == "strict"
    dropped, _ = transform(funnel, "SIG_FILTER_DROPPED", TZ)
    assert isinstance(dropped, FunnelMetric) and not dropped.steps[0].properties
    with pytest.raises(OracleError):
        transform(default, "SIG_FUNNEL_WINDOW_DEFAULT", TZ)
    retention = RetentionMetric.model_validate(
        {"type": "retention", "start_event": "signed_up", "return_event": "uploaded_file", "period": "Week",
         "retention_type": "retention_first_time", "cumulative": False, "total_intervals": 8,
         "date_from": "2026-06-08", "date_to": "2026-06-14", "cohort_index": 0, "period_index": 1,
         "filter_test_accounts": False}
    )  # fmt: skip
    kind, _ = transform(retention, "SIG_RETENTION_TYPE", TZ)
    cumulative, _ = transform(retention, "SIG_RETENTION_CUMULATIVE", TZ)
    assert isinstance(kind, RetentionMetric) and kind.retention_type == "retention_recurring"
    assert isinstance(cumulative, RetentionMetric) and cumulative.cumulative
    with pytest.raises(OracleError):
        transform(retention, "SIG_FILTER_DROPPED", TZ)


def test_one_day_range_has_no_exclusive_end() -> None:
    day = JULY.model_copy(update={"date_to": JULY.date_from})
    with pytest.raises(OracleError):
        transform(day, "SIG_PERIOD_EXCL_END", TZ)
