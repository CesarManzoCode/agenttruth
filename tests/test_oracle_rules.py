"""Known-answer tests for the oracle's semantic rules (contract §6.2, SEM-01…SEM-15)."""

from __future__ import annotations

from typing import Any

import pytest
from _factories import TZ, ev, identify

from agenttruth.evidence.models import (
    CustomMetric,
    FunnelMetric,
    RetentionMetric,
    TrendsMetric,
)
from agenttruth.oracle.frame import Frame, OracleError
from agenttruth.oracle.metrics import evaluate

INTERNAL = "staff@hedgebox-internal.example"


def trends(**kw: Any) -> TrendsMetric:
    base = {"type": "trends", "event": "signed_up", "math": "total", "filter_test_accounts": False}
    return TrendsMetric.model_validate({**base, **kw})


def funnel(**kw: Any) -> FunnelMetric:
    base = {
        "type": "funnel",
        "steps": [{"event": "a"}, {"event": "b"}],
        "window": {"n": 1, "unit": "hour"},
        "order": "ordered",
        "date_from": "2026-07-01",
        "date_to": "2026-07-31",
        "filter_test_accounts": False,
    }
    return FunnelMetric.model_validate({**base, **kw})


def retention(**kw: Any) -> RetentionMetric:
    base = {
        "type": "retention",
        "start_event": "a",
        "return_event": "b",
        "period": "Week",
        "retention_type": "retention_recurring",
        "cumulative": False,
        "total_intervals": 4,
        "date_from": "2026-07-06",
        "date_to": "2026-07-19",
        "cohort_index": 0,
        "period_index": 1,
        "filter_test_accounts": False,
    }
    return RetentionMetric.model_validate({**base, **kw})


def test_sem01_sem02_local_day_is_inclusive_to_the_last_millisecond() -> None:
    frame = Frame(
        [
            ev("signed_up", "2026-07-13T23:59:59.999", "a"),
            ev("signed_up", "2026-07-14T00:00:00.000", "b"),
            ev("signed_up", "2026-07-14T23:59:59.999", "c"),
            ev("signed_up", "2026-07-15T00:00:00.000", "d"),
        ],
        TZ,
    )
    metric = trends(date_from="2026-07-14", date_to="2026-07-14")
    assert evaluate(metric, frame, TZ) == 2
    # In UTC, 2026-07-14 is local 07-13 18:00 to 07-14 18:00: only the 23:59:59.999 of 07-13 is in it.
    assert evaluate(metric, frame, "UTC") == 2
    assert evaluate(trends(date_from="2026-07-13", date_to="2026-07-13"), frame, "UTC") == 0


def test_sem03_sem04_identify_merges_past_and_future_events() -> None:
    frame = Frame(
        [
            ev("logged_in", "2026-07-01T10:00:00.000", "anon-1"),
            identify("2026-07-02T10:00:00.000", "user-1", "anon-1", "u1@example.com"),
            ev("logged_in", "2026-07-03T10:00:00.000", "user-1"),
            ev("logged_in", "2026-07-03T11:00:00.000", "anon-2"),
        ],
        TZ,
    )
    total = trends(event="logged_in", date_from="2026-07-01", date_to="2026-07-31")
    assert evaluate(total, frame, TZ) == 3
    assert evaluate(total.model_copy(update={"math": "dau"}), frame, TZ) == 2


def test_sem04_merge_of_an_identified_id_is_refused() -> None:
    frame = Frame(
        [
            identify("2026-07-01T10:00:00.000", "user-1", None, "u1@example.com"),
            identify("2026-07-01T11:00:00.000", "user-2", None, "u2@example.com"),
            identify("2026-07-02T10:00:00.000", "user-2", "user-1", "u2@example.com"),
            ev("logged_in", "2026-07-03T10:00:00.000", "user-1"),
            ev("logged_in", "2026-07-03T10:00:01.000", "user-2"),
        ],
        TZ,
    )
    metric = trends(event="logged_in", math="dau", date_from="2026-07-01", date_to="2026-07-31")
    assert evaluate(metric, frame, TZ) == 2


def test_sem05_test_accounts_use_email_at_event_time() -> None:
    frame = Frame(
        [
            identify("2026-07-01T09:00:00.000", "staff", None, INTERNAL),
            ev("uploaded_file", "2026-07-01T10:00:00.000", "staff"),
            ev("uploaded_file", "2026-07-01T10:00:00.000", "anon-x"),
            ev("uploaded_file", "2026-07-02T10:00:00.000", "late"),
            identify("2026-07-03T10:00:00.000", "late", None, "Late@HEDGEBOX-INTERNAL.example"),
            ev("uploaded_file", "2026-07-04T10:00:00.000", "late"),
        ],
        TZ,
    )
    metric = trends(event="uploaded_file", date_from="2026-07-01", date_to="2026-07-31", filter_test_accounts=True)
    # staff (internal from its first event) and late's upload after its email is set are excluded;
    # late's earlier upload had no email at event time and is kept.
    assert evaluate(metric, frame, TZ) == 2
    assert evaluate(metric.model_copy(update={"filter_test_accounts": False}), frame, TZ) == 4


def test_sem06_ordered_allows_intervening_events_strict_does_not() -> None:
    frame = Frame(
        [
            ev("a", "2026-07-01T10:00:00.000", "p"),
            ev("x", "2026-07-01T10:00:10.000", "p"),
            ev("b", "2026-07-01T10:00:20.000", "p"),
        ],
        TZ,
    )
    assert evaluate(funnel(), frame, TZ) == {"converted": 1, "entered": 1}
    assert evaluate(funnel(order="strict"), frame, TZ) == {"converted": 0, "entered": 1}


def test_sem07_conversion_at_exactly_the_window_counts() -> None:
    frame = Frame(
        [
            ev("a", "2026-07-01T10:00:00.000", "exact"),
            ev("b", "2026-07-01T11:00:00.000", "exact"),
            ev("a", "2026-07-01T10:00:00.000", "late"),
            ev("b", "2026-07-01T11:00:00.001", "late"),
        ],
        TZ,
    )
    assert evaluate(funnel(), frame, TZ) == {"converted": 1, "entered": 2}


def test_sem08_every_step_must_be_inside_the_range() -> None:
    frame = Frame([ev("a", "2026-07-31T23:30:00.000", "p"), ev("b", "2026-08-01T00:10:00.000", "p")], TZ)
    assert evaluate(funnel(), frame, TZ) == {"converted": 0, "entered": 1}


def test_sem09_person_enters_once_with_the_furthest_step() -> None:
    frame = Frame(
        [
            ev("a", "2026-07-01T08:00:00.000", "p"),
            ev("a", "2026-07-01T10:00:00.000", "p"),
            ev("b", "2026-07-01T10:30:00.000", "p"),
        ],
        TZ,
    )
    assert evaluate(funnel(), frame, TZ) == {"converted": 1, "entered": 1}


def test_three_step_funnel_reports_step_2() -> None:
    frame = Frame(
        [
            ev("a", "2026-07-01T10:00:00.000", "p"),
            ev("b", "2026-07-01T10:10:00.000", "p"),
            ev("a", "2026-07-01T10:00:00.000", "q"),
            ev("b", "2026-07-01T10:10:00.000", "q"),
            ev("c", "2026-07-01T10:20:00.000", "q"),
        ],
        TZ,
    )
    metric = funnel(steps=[{"event": "a"}, {"event": "b"}, {"event": "c"}])
    assert evaluate(metric, frame, TZ) == {"converted": 1, "entered": 2, "step_2": 2}


def test_funnel_step_property_filter() -> None:
    frame = Frame(
        [
            ev(
                "$pageview",
                "2026-07-01T10:00:00.000",
                "p",
                **{"$current_url": "https://hedgebox.net/pricing/"},
            ),
            ev("b", "2026-07-01T10:10:00.000", "p"),
            ev("$pageview", "2026-07-01T10:00:00.000", "q", **{"$current_url": "https://hedgebox.net/"}),
            ev("b", "2026-07-01T10:10:00.000", "q"),
        ],
        TZ,
    )
    flt = [{"key": "$current_url", "type": "event", "operator": "icontains", "value": "/pricing/"}]
    metric = funnel(steps=[{"event": "$pageview", "properties": flt}, {"event": "b"}])
    assert evaluate(metric, frame, TZ) == {"converted": 1, "entered": 1}


def test_sem10_sem11_retention_first_time_recurring_and_cumulative() -> None:
    events = [
        # p: starts in week 0 (Mon 07-06) and week 1; returns in week 2.
        ev("a", "2026-07-06T10:00:00.000", "p"),
        ev("a", "2026-07-13T10:00:00.000", "p"),
        ev("b", "2026-07-20T10:00:00.000", "p"),
        # q: starts on Sunday 07-12 23:59 local (week 0), returns Monday 07-13 00:00 (week 1).
        ev("a", "2026-07-12T23:59:59.999", "q"),
        ev("b", "2026-07-13T00:00:00.000", "q"),
    ]
    frame = Frame(events, TZ)
    assert evaluate(retention(), frame, TZ) == {"cohort_size": 2, "retained": 1}
    assert evaluate(retention(cumulative=True), frame, TZ) == {"cohort_size": 2, "retained": 2}
    week1 = retention(cohort_index=1)
    assert evaluate(week1, frame, TZ) == {"cohort_size": 1, "retained": 1}
    assert evaluate(week1.model_copy(update={"retention_type": "retention_first_time"}), frame, TZ) == {
        "cohort_size": 0,
        "retained": 0,
    }


def test_sem12_breakdown_and_daily_interval_zero_filled() -> None:
    frame = Frame(
        [
            ev("u", "2026-07-01T10:00:00.000", "p", **{"$os": "iOS"}),
            ev("u", "2026-07-03T10:00:00.000", "p", **{"$os": "Android"}),
        ],
        TZ,
    )
    by_os = trends(event="u", breakdown="$os", date_from="2026-07-01", date_to="2026-07-03")
    assert evaluate(by_os, frame, TZ) == {"Android": 1, "iOS": 1}
    daily = by_os.model_copy(update={"interval": "day"})
    result = evaluate(daily, frame, TZ)
    assert isinstance(result, dict)
    assert result["2026-07-02|iOS"] == 0 and result["2026-07-03|Android"] == 1 and len(result) == 6


def test_sem14_sums_are_exact_in_cents() -> None:
    frame = Frame([ev("paid_bill", "2026-08-01T10:00:00.000", "p", amount_usd=v) for v in (0.1, 0.2, 19.99)], TZ)
    metric = trends(
        event="paid_bill",
        math="sum",
        math_property="amount_usd",
        date_from="2026-08-01",
        date_to="2026-08-31",
    )
    assert evaluate(metric, frame, TZ) == 20.29


def test_sem13_sem15_custom_functions() -> None:
    frame = Frame(
        [
            ev("signed_up", "2026-06-10T10:00:00.000", "p"),
            *[ev("uploaded_file", f"2026-06-1{d}T10:00:00.000", "p") for d in (0, 1)],
            ev("uploaded_file", "2026-06-17T10:00:00.000", "p"),  # exactly 7 days after sign-up
            ev("signed_up", "2026-06-10T10:00:00.000", "q"),
            *[ev("uploaded_file", f"2026-06-1{d}T10:00:00.000", "q") for d in (0, 1)],
            ev("uploaded_file", "2026-06-17T10:00:00.001", "q"),  # 1 ms too late
            ev("uploaded_file", "2026-05-31T23:59:59.999", "early"),
            ev("uploaded_file", "2026-06-15T10:00:00.000", "early"),
        ],
        TZ,
    )
    power = CustomMetric.model_validate(
        {"type": "custom", "function": "power_uploaders", "event": "uploaded_file", "anchor_event": "signed_up",
         "min_count": 3, "within_days": 7, "date_from": "2026-06-01", "date_to": "2026-06-30"}
    )  # fmt: skip
    assert evaluate(power, frame, TZ) == 1
    first = CustomMetric.model_validate(
        {"type": "custom", "function": "first_ever_in_range", "event": "uploaded_file",
         "date_from": "2026-06-01", "date_to": "2026-06-30"}
    )  # fmt: skip
    assert evaluate(first, frame, TZ) == 2  # "early" first uploaded in May
    days = CustomMetric.model_validate(
        {"type": "custom", "function": "distinct_days_users", "event": "uploaded_file", "min_days_exclusive": 2,
         "date_from": "2026-06-01", "date_to": "2026-06-30"}
    )  # fmt: skip
    assert evaluate(days, frame, TZ) == 2


def test_top_values_tie_is_an_error() -> None:
    frame = Frame(
        [ev("u", "2026-08-01T10:00:00.000", "p", file_type=t) for t in ("a", "a", "a", "b", "b", "c", "c")],
        TZ,
    )
    metric = CustomMetric.model_validate(
        {"type": "custom", "function": "top_values", "event": "u", "property": "file_type", "top_n": 1,
         "date_from": "2026-08-01", "date_to": "2026-08-31"}
    )  # fmt: skip
    assert evaluate(metric, frame, TZ) == ["a"]
    with pytest.raises(OracleError):  # b and c tie for second place
        evaluate(metric.model_copy(update={"top_n": 2}), frame, TZ)
