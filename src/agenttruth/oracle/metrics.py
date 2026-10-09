"""Oracle metric evaluation over an event frame (contract §6.2, SEM-01…SEM-15).

``evaluate(metric, frame, timezone)`` is pure: the same frame, metric and timezone always give the
same value. Dates and buckets are local to ``timezone`` (the project timezone, or UTC for
``SIG_TZ_UTC``); the test-account filter (SEM-05) drops events whose person email at event time
contains ``@hedgebox-internal.example``.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from agenttruth.evidence.models import (
    CustomMetric,
    FunnelMetric,
    Metric,
    PropertyFilter,
    RetentionMetric,
    TrendsMetric,
    TruthValue,
)
from agenttruth.oracle.frame import Ev, Frame, OracleError

__all__ = ["INTERNAL_EMAIL_SUBSTRING", "evaluate"]

INTERNAL_EMAIL_SUBSTRING = "@hedgebox-internal.example"
_DAY_MS = 86_400_000
_UNIT_MS = {"second": 1_000, "minute": 60_000, "hour": 3_600_000, "day": _DAY_MS, "week": 7 * _DAY_MS}


class _View:
    """A frame seen through one timezone and one test-account setting."""

    def __init__(self, frame: Frame, timezone: str, filter_test_accounts: bool) -> None:
        self.frame = frame
        self.day = frame.dates(timezone)
        self.filter = filter_test_accounts

    def keep(self, ev: Ev) -> bool:
        return not (self.filter and ev.email is not None and INTERNAL_EMAIL_SUBSTRING in ev.email.lower())

    def within(self, ev: Ev, start: date, end: date) -> bool:
        return start <= self.day[ev.pos] <= end


def _passes(ev: Ev, filters: list[PropertyFilter]) -> bool:
    """SEM-12 property filters: event properties, or the person's email at event time."""
    for flt in filters:
        value = ev.email if flt.type == "person" and flt.key == "email" else ev.props.get(flt.key)
        if value is None:
            return False
        text = str(value)
        if flt.operator == "exact":
            if text != flt.value:
                return False
        elif flt.value.lower() not in text.lower():
            return False
    return True


def _range_days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def _trends(metric: TrendsMetric, view: _View) -> TruthValue:
    selected = [
        ev
        for ev in view.frame.by_event.get(metric.event, [])
        if view.within(ev, metric.date_from, metric.date_to) and view.keep(ev) and _passes(ev, metric.properties)
    ]

    def key_of(ev: Ev) -> tuple[str, str]:
        day = view.day[ev.pos].isoformat() if metric.interval == "day" else ""
        if metric.breakdown is None:
            return day, ""
        value = ev.props.get(metric.breakdown)
        if value is None:
            raise OracleError(f"event {ev.at_eid} has no breakdown property {metric.breakdown}")
        return day, str(value)

    if metric.math == "sum":
        if metric.breakdown is not None or metric.interval is not None:
            raise OracleError("sum with breakdown or interval is not defined in catalog v1")
        assert metric.math_property is not None
        cents = 0
        for ev in selected:
            amount = ev.props.get(metric.math_property)
            if not isinstance(amount, (int, float)) or isinstance(amount, bool):
                raise OracleError(f"event {ev.at_eid}: {metric.math_property} is not a number")
            cents += round(amount * 100)  # SEM-14: integer cents
        return cents / 100

    groups: dict[tuple[str, str], int] = defaultdict(int)
    if metric.math == "total":
        for ev in selected:
            groups[key_of(ev)] += 1
    else:
        persons: dict[tuple[str, str], set[int]] = defaultdict(set)
        for ev in selected:
            persons[key_of(ev)].add(ev.person)
        groups.update({k: len(v) for k, v in persons.items()})

    def size(key: tuple[str, str]) -> int:
        return groups.get(key, 0)

    if metric.interval is None and metric.breakdown is None:
        return size(("", ""))
    if metric.interval is None:
        return {value: size(("", value)) for _, value in sorted(groups)}
    days = [d.isoformat() for d in _range_days(metric.date_from, metric.date_to)]
    if metric.breakdown is None:
        return {d: size((d, "")) for d in days}
    values = sorted({value for _, value in groups})
    return {f"{d}|{v}": size((d, v)) for d in days for v in values}


def _funnel(metric: FunnelMetric, view: _View) -> TruthValue:
    window = metric.window.n * _UNIT_MS[metric.window.unit]
    steps = metric.steps
    reached_counts = [0] * len(steps)
    step_events = {s.event for s in steps}
    people = {
        ev.person
        for ev in view.frame.by_event.get(steps[0].event, [])
        if view.within(ev, metric.date_from, metric.date_to) and view.keep(ev)
    }
    for person in sorted(people):
        history = [
            ev
            for ev in view.frame.by_person[person]
            if view.within(ev, metric.date_from, metric.date_to)
            and view.keep(ev)
            and (metric.order == "strict" or ev.event in step_events)
        ]
        best = 0
        for start, first in enumerate(history):
            if first.event != steps[0].event or not _passes(first, steps[0].properties):
                continue
            reached, at = 1, start
            for step in steps[1:]:
                if metric.order == "ordered":
                    nxt = next(
                        (
                            i
                            for i in range(at + 1, len(history))
                            if history[i].event == step.event and _passes(history[i], step.properties)
                        ),
                        -1,
                    )
                else:
                    nxt = at + 1
                    if (
                        nxt >= len(history)
                        or history[nxt].event != step.event
                        or not _passes(history[nxt], step.properties)
                    ):
                        nxt = -1
                if nxt < 0 or history[nxt].ts - first.ts > window:
                    break
                reached, at = reached + 1, nxt
            best = max(best, reached)
        for k in range(best):
            reached_counts[k] += 1
    result = {"entered": reached_counts[0], "converted": reached_counts[-1]}
    result.update({f"step_{k + 1}": reached_counts[k] for k in range(1, len(steps) - 1)})
    return dict(sorted(result.items()))


def _bucket(period: str, day: date) -> int:
    if period == "Day":
        return day.toordinal()
    if period == "Week":
        monday = day - timedelta(days=day.weekday())
        return monday.toordinal() // 7
    return day.year * 12 + (day.month - 1)


def _retention(metric: RetentionMetric, view: _View) -> TruthValue:
    base = _bucket(metric.period, metric.date_from)
    cohort_bucket = base + metric.cohort_index
    if cohort_bucket > _bucket(metric.period, metric.date_to):
        raise OracleError("cohort_index lies beyond the cohort date range")
    starts: dict[int, list[int]] = defaultdict(list)
    for ev in view.frame.by_event.get(metric.start_event, []):
        if view.within(ev, metric.date_from, metric.date_to) and view.keep(ev):
            starts[ev.person].append(_bucket(metric.period, view.day[ev.pos]))
    cohort: set[int] = set()
    for person, buckets in starts.items():
        if metric.retention_type == "retention_first_time":
            if buckets[0] == cohort_bucket:  # events are time-ordered: buckets[0] is the first in range
                cohort.add(person)
        elif cohort_bucket in buckets:
            cohort.add(person)
    if metric.cumulative:
        wanted = range(metric.period_index, metric.total_intervals)
    else:
        wanted = range(metric.period_index, metric.period_index + 1)
    retained: set[int] = set()
    for ev in view.frame.by_event.get(metric.return_event, []):
        if ev.person in cohort and view.keep(ev) and _bucket(metric.period, view.day[ev.pos]) - cohort_bucket in wanted:
            retained.add(ev.person)
    return {"cohort_size": len(cohort), "retained": len(retained)}


def _custom(metric: CustomMetric, view: _View) -> TruthValue:
    events = view.frame.by_event.get(metric.event, [])
    if metric.function == "power_uploaders":
        assert metric.anchor_event is not None
        assert metric.min_count is not None
        assert metric.within_days is not None
        anchors: dict[int, int] = {}
        for ev in view.frame.by_event.get(metric.anchor_event, []):
            if view.within(ev, metric.date_from, metric.date_to) and view.keep(ev) and ev.person not in anchors:
                anchors[ev.person] = ev.ts
        tally: dict[int, int] = defaultdict(int)
        horizon = metric.within_days * _DAY_MS
        for ev in events:
            start = anchors.get(ev.person)
            if start is not None and view.keep(ev) and start <= ev.ts <= start + horizon:
                tally[ev.person] += 1
        return sum(1 for n in tally.values() if n >= metric.min_count)
    if metric.function == "top_values":
        assert metric.property is not None
        assert metric.top_n is not None
        counts: dict[str, int] = defaultdict(int)
        for ev in events:
            if view.within(ev, metric.date_from, metric.date_to) and view.keep(ev):
                counts[str(ev.props.get(metric.property))] += 1
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        head = ranked[: metric.top_n + 1]
        if len(ranked) < metric.top_n or len({c for _, c in head}) != len(head):
            raise OracleError(f"ranking undefined (tie or too few values): {head}")
        return [value for value, _ in ranked[: metric.top_n]]
    if metric.function == "distinct_days_users":
        assert metric.min_days_exclusive is not None
        days: dict[int, set[date]] = defaultdict(set)
        for ev in events:
            if view.within(ev, metric.date_from, metric.date_to) and view.keep(ev):
                days[ev.person].add(view.day[ev.pos])
        return sum(1 for d in days.values() if len(d) > metric.min_days_exclusive)
    if metric.function == "first_ever_in_range":
        first: dict[int, Ev] = {}
        for ev in events:  # time-ordered, so the first kept event per person is the first ever (SEM-15)
            if view.keep(ev) and ev.person not in first:
                first[ev.person] = ev
        return sum(1 for ev in first.values() if view.within(ev, metric.date_from, metric.date_to))
    raise OracleError("detect_cause is evaluated by agenttruth.oracle.detect, not as a metric")


def evaluate(metric: Metric, frame: Frame, timezone: str) -> TruthValue:
    """Evaluate a non-cause metric on ``frame`` with local dates in ``timezone``.

    Raises :class:`OracleError` when the value is undefined (a ranking tie, a missing breakdown
    property, a cohort outside its range). Complexity: O(n) per metric, O(n·k) for funnels where k is
    the number of step-1 events per person.
    """
    view = _View(frame, timezone, metric.filter_test_accounts)
    if isinstance(metric, TrendsMetric):
        return _trends(metric, view)
    if isinstance(metric, FunnelMetric):
        return _funnel(metric, view)
    if isinstance(metric, RetentionMetric):
        return _retention(metric, view)
    return _custom(metric, view)
