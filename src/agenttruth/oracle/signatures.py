"""Error-signature transforms of a metric spec (contract §6.3).

A signature is the value an agent would report after one specific mistake. ``transform`` returns
the mistaken metric and the timezone to evaluate it in; it raises :class:`OracleError` when the
signature does not apply to the metric (the catalog must then not declare it).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from agenttruth.evidence.models import (
    CustomMetric,
    FunnelMetric,
    FunnelStep,
    Metric,
    RetentionMetric,
    TrendsMetric,
)
from agenttruth.oracle.frame import OracleError

__all__ = ["CONFUSABLE_EVENTS", "SIGNATURES", "transform"]

SIGNATURES = (
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
)
# SIG_EVENT_<name>: <name> is mistaken for its declared confusable partner.
CONFUSABLE_EVENTS = {
    "uploaded_file": "downloaded_file",
    "downloaded_file": "uploaded_file",
    "signed_up": "logged_in",
    "logged_in": "signed_up",
    "upgraded_plan": "downgraded_plan",
    "downgraded_plan": "upgraded_plan",
}


def _shift(metric: Metric, days_from: int, days_to: int) -> Metric:
    return metric.model_copy(
        update={
            "date_from": metric.date_from + timedelta(days=days_from),
            "date_to": metric.date_to + timedelta(days=days_to),
        }
    )


def _replace_event(metric: Metric, mistaken: str) -> Metric:
    original = CONFUSABLE_EVENTS.get(mistaken)
    if original is None:
        raise OracleError(f"SIG_EVENT_{mistaken}: no declared confusable partner")
    update: dict[str, Any] = {}
    if isinstance(metric, (TrendsMetric, CustomMetric)) and metric.event == original:
        update["event"] = mistaken
    if isinstance(metric, FunnelMetric):
        steps = [
            FunnelStep(event=mistaken, properties=s.properties) if s.event == original else s for s in metric.steps
        ]
        if steps != metric.steps:
            update["steps"] = steps
    if isinstance(metric, RetentionMetric):
        if metric.start_event == original:
            update["start_event"] = mistaken
        if metric.return_event == original:
            update["return_event"] = mistaken
    if not update:
        raise OracleError(f"SIG_EVENT_{mistaken}: the metric does not use {original}")
    return metric.model_copy(update=update)


def transform(metric: Metric, signature: str, timezone: str) -> tuple[Metric, str]:
    """Return ``(mistaken metric, timezone)`` for ``signature``. Raises if it does not apply."""
    length = (metric.date_to - metric.date_from).days + 1
    if signature == "SIG_PERIOD_PREV":
        return _shift(metric, -length, -length), timezone
    if signature == "SIG_PERIOD_NEXT":
        return _shift(metric, length, length), timezone
    if signature == "SIG_PERIOD_EXCL_END":
        if length < 2:
            raise OracleError("SIG_PERIOD_EXCL_END on a one-day range leaves no range")
        return _shift(metric, 0, -1), timezone
    if signature == "SIG_PERIOD_EXTRA_DAY":
        return _shift(metric, 0, 1), timezone
    if signature == "SIG_TZ_UTC":
        if timezone == "UTC":
            raise OracleError("SIG_TZ_UTC with a UTC project")
        return metric, "UTC"
    if signature == "SIG_TEST_ACCOUNTS":
        return metric.model_copy(update={"filter_test_accounts": not metric.filter_test_accounts}), timezone
    if signature in {"SIG_AGG_TOTAL", "SIG_AGG_UNIQUE"}:
        target, source = ("total", "dau") if signature == "SIG_AGG_TOTAL" else ("dau", "total")
        if not isinstance(metric, TrendsMetric) or metric.math != source:
            raise OracleError(f"{signature} applies to trends with math={source}")
        return metric.model_copy(update={"math": target}), timezone
    if signature == "SIG_FUNNEL_WINDOW_DEFAULT":
        if not isinstance(metric, FunnelMetric) or (metric.window.n, metric.window.unit) == (14, "day"):
            raise OracleError("SIG_FUNNEL_WINDOW_DEFAULT applies to funnels whose stated window is not 14 days")
        return metric.model_copy(update={"window": metric.window.model_copy(update={"n": 14, "unit": "day"})}), timezone
    if signature == "SIG_FUNNEL_ORDER":
        if not isinstance(metric, FunnelMetric):
            raise OracleError("SIG_FUNNEL_ORDER applies to funnels")
        return metric.model_copy(update={"order": "strict" if metric.order == "ordered" else "ordered"}), timezone
    if signature == "SIG_RETENTION_TYPE":
        if not isinstance(metric, RetentionMetric):
            raise OracleError("SIG_RETENTION_TYPE applies to retention")
        swapped = "retention_recurring" if metric.retention_type == "retention_first_time" else "retention_first_time"
        return metric.model_copy(update={"retention_type": swapped}), timezone
    if signature == "SIG_RETENTION_CUMULATIVE":
        if not isinstance(metric, RetentionMetric):
            raise OracleError("SIG_RETENTION_CUMULATIVE applies to retention")
        return metric.model_copy(update={"cumulative": not metric.cumulative}), timezone
    if signature == "SIG_FILTER_DROPPED":
        if isinstance(metric, TrendsMetric) and metric.properties:
            return metric.model_copy(update={"properties": []}), timezone
        if isinstance(metric, FunnelMetric) and any(s.properties for s in metric.steps):
            steps = [FunnelStep(event=s.event) for s in metric.steps]
            return metric.model_copy(update={"steps": steps}), timezone
        raise OracleError("SIG_FILTER_DROPPED applies to metrics with a property filter")
    if signature.startswith("SIG_EVENT_"):
        return _replace_event(metric, signature.removeprefix("SIG_EVENT_")), timezone
    raise OracleError(f"unknown signature {signature}")
