"""Scenario values implied by the journeys (construction ledger, contract §5.4).

This is the generator-side derivation of every EA/PC truth. It reads journey structures — who each
person is (ground-truth identity, not ``$identify`` resolution), which steps were emitted, which
faults touched what — and never ``events.jsonl``. K1-C2 compares its values with the oracle's,
which derives the same metrics from emitted events alone.

Semantics follow contract §6.2 (SEM-01…SEM-15) and the metric definitions in
:mod:`agenttruth.evidence.models`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import pairwise
from typing import Any
from urllib.parse import urlsplit

from agenttruth.dataset.generate import BASE_URL, Journey, event_properties
from agenttruth.dataset.spec import FaultSpec
from agenttruth.dataset.timeutil import DAY_MS, Clock
from agenttruth.evidence.models import (
    Cause,
    CustomMetric,
    FunnelMetric,
    Metric,
    PropertyFilter,
    RetentionMetric,
    TrendsMetric,
    TruthValue,
)

__all__ = ["LedgerError", "Step", "evaluate", "persons_of", "planted_cause"]

_WINDOW_MS = {"second": 1_000, "minute": 60_000, "hour": 3_600_000, "day": DAY_MS, "week": 7 * DAY_MS}


class LedgerError(RuntimeError):
    """A scenario value is undefined for these journeys (e.g. a ranking tie)."""


@dataclass(frozen=True, slots=True)
class Step:
    """An emitted step as one person's history sees it."""

    ts: int
    at_eid: str
    event: str
    props: dict[str, Any]
    email: str | None


def persons_of(journeys: Iterable[Journey]) -> list[list[Step]]:
    """Group emitted steps into persons using ground-truth identity.

    A user whose ``$identify`` was emitted is one person across both ids; otherwise each id is its own
    person (F3, or a removed identify). The person's email is known from the identify step onwards
    (persons-on-events at event time, SEM-05); before it, and for unmerged users, it is unknown.
    """
    persons: list[list[Step]] = []
    for journey in journeys:
        identify = journey.identify_action()
        email_since: int | None = None
        email: str | None = None
        if identify is not None and identify.emitted:
            email_since = identify.ts
            email = str(identify.props["$set"]["email"])
        groups: dict[str, list[Step]] = {}
        merged = journey.kind != "user" or journey.merged
        for action in journey.actions:
            if not action.emitted:
                continue
            key = "all" if merged else action.distinct_id
            known = email if email_since is not None and action.ts >= email_since else None
            groups.setdefault(key, []).append(
                Step(
                    action.ts,
                    action.at_eid,
                    action.event,
                    event_properties(journey, action.props, action.url),
                    known,
                )
            )
        for steps in groups.values():
            steps.sort(key=lambda s: (s.ts, s.at_eid))
            persons.append(steps)
    return persons


# --------------------------------------------------------------------------------------------------
# Shared predicates
# --------------------------------------------------------------------------------------------------


class _Ctx:
    def __init__(self, clock: Clock, internal_substring: str) -> None:
        self.clock = clock
        self.internal = internal_substring.lower()
        self._dates: dict[int, date] = {}

    def day(self, ts: int) -> date:
        cached = self._dates.get(ts)
        if cached is None:
            cached = self.clock.local_date(ts)
            self._dates[ts] = cached
        return cached

    def kept(self, step: Step, filter_test_accounts: bool) -> bool:
        return not (filter_test_accounts and step.email is not None and self.internal in step.email.lower())


def _matches(step: Step, filters: list[PropertyFilter]) -> bool:
    for flt in filters:
        raw = step.email if (flt.type == "person" and flt.key == "email") else step.props.get(flt.key)
        if raw is None:
            return False
        text = raw if isinstance(raw, str) else str(raw)
        if flt.operator == "exact" and text != flt.value:
            return False
        if flt.operator == "icontains" and flt.value.lower() not in text.lower():
            return False
    return True


def _in(ctx: _Ctx, step: Step, start: date, end: date) -> bool:
    return start <= ctx.day(step.ts) <= end


# --------------------------------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------------------------------


def _trends(metric: TrendsMetric, persons: list[list[Step]], ctx: _Ctx) -> TruthValue:
    totals: dict[str, int] = {}
    people: dict[str, set[int]] = {}
    for pid, steps in enumerate(persons):
        for step in steps:
            if (
                step.event != metric.event
                or not _in(ctx, step, metric.date_from, metric.date_to)
                or not ctx.kept(step, metric.filter_test_accounts)
                or not _matches(step, metric.properties)
            ):
                continue
            parts = []
            if metric.interval == "day":
                parts.append(ctx.day(step.ts).isoformat())
            if metric.breakdown is not None:
                value = step.props.get(metric.breakdown)
                if value is None:
                    raise LedgerError(f"step {step.at_eid} lacks breakdown property {metric.breakdown}")
                parts.append(str(value))
            key = "|".join(parts)
            if metric.math == "sum":
                assert metric.math_property is not None
                amount = step.props[metric.math_property]
                totals[key] = totals.get(key, 0) + round(float(amount) * 100)
            else:
                totals[key] = totals.get(key, 0) + 1
                people.setdefault(key, set()).add(pid)
    agg = {k: len(v) for k, v in people.items()} if metric.math == "dau" else totals
    if metric.interval is None and metric.breakdown is None:
        value = agg.get("", 0)
        return value / 100 if metric.math == "sum" else value
    if metric.math == "sum":
        raise LedgerError("sum metrics with breakdown or interval are not used in catalog v1")
    if metric.interval == "day":
        days = [metric.date_from + timedelta(days=i) for i in range((metric.date_to - metric.date_from).days + 1)]
        if metric.breakdown is None:
            return {d.isoformat(): agg.get(d.isoformat(), 0) for d in days}
        values = sorted({k.split("|", 1)[1] for k in agg})
        return {f"{d.isoformat()}|{v}": agg.get(f"{d.isoformat()}|{v}", 0) for d in days for v in values}
    return dict(sorted(agg.items()))


def _funnel_reach(metric: FunnelMetric, steps: list[Step]) -> int:
    window = metric.window.n * _WINDOW_MS[metric.window.unit]
    best = 0
    for i, first in enumerate(steps):
        if first.event != metric.steps[0].event or not _matches(first, metric.steps[0].properties):
            continue
        reached = 1
        cursor = i
        for spec in metric.steps[1:]:
            if metric.order == "strict":
                nxt = cursor + 1
                found = (
                    nxt
                    if nxt < len(steps)
                    and steps[nxt].event == spec.event
                    and _matches(steps[nxt], spec.properties)
                    and steps[nxt].ts - first.ts <= window
                    else None
                )
            else:
                found = next(
                    (
                        j
                        for j in range(cursor + 1, len(steps))
                        if steps[j].event == spec.event and _matches(steps[j], spec.properties)
                    ),
                    None,
                )
                if found is not None and steps[found].ts - first.ts > window:
                    found = None
            if found is None:
                break
            reached += 1
            cursor = found
        best = max(best, reached)
        if best == len(metric.steps):
            break
    return best


def _funnel(metric: FunnelMetric, persons: list[list[Step]], ctx: _Ctx) -> TruthValue:
    counts = [0] * len(metric.steps)
    for steps in persons:
        in_range = [
            s
            for s in steps
            if _in(ctx, s, metric.date_from, metric.date_to) and ctx.kept(s, metric.filter_test_accounts)
        ]
        reached = _funnel_reach(metric, in_range)
        for k in range(reached):
            counts[k] += 1
    out = {"entered": counts[0], "converted": counts[-1]}
    for k in range(1, len(counts) - 1):
        out[f"step_{k + 1}"] = counts[k]
    return dict(sorted(out.items()))


def _bucket(ctx: _Ctx, period: str, day: date) -> int:
    if period == "Day":
        return day.toordinal()
    if period == "Week":
        return (day - timedelta(days=day.weekday())).toordinal() // 7
    return day.year * 12 + day.month - 1


def _retention(metric: RetentionMetric, persons: list[list[Step]], ctx: _Ctx) -> TruthValue:
    first_bucket = _bucket(ctx, metric.period, metric.date_from)
    cohort_bucket = first_bucket + metric.cohort_index
    if cohort_bucket > _bucket(ctx, metric.period, metric.date_to):
        raise LedgerError("cohort_index beyond the cohort date range")
    cohort = retained = 0
    for steps in persons:
        starts = [
            s
            for s in steps
            if s.event == metric.start_event
            and _in(ctx, s, metric.date_from, metric.date_to)
            and ctx.kept(s, metric.filter_test_accounts)
        ]
        if not starts:
            continue
        if metric.retention_type == "retention_first_time":
            in_cohort = _bucket(ctx, metric.period, ctx.day(starts[0].ts)) == cohort_bucket
        else:
            in_cohort = any(_bucket(ctx, metric.period, ctx.day(s.ts)) == cohort_bucket for s in starts)
        if not in_cohort:
            continue
        cohort += 1
        returns = {
            _bucket(ctx, metric.period, ctx.day(s.ts)) - cohort_bucket
            for s in steps
            if s.event == metric.return_event and ctx.kept(s, metric.filter_test_accounts)
        }
        wanted = set(range(metric.period_index, metric.total_intervals)) if metric.cumulative else {metric.period_index}
        if returns & wanted:
            retained += 1
    return {"cohort_size": cohort, "retained": retained}


def _custom(metric: CustomMetric, persons: list[list[Step]], ctx: _Ctx) -> TruthValue:
    ftc = metric.filter_test_accounts
    if metric.function == "power_uploaders":
        assert metric.anchor_event
        assert metric.min_count is not None
        assert metric.within_days is not None
        count = 0
        for steps in persons:
            anchors = [
                s
                for s in steps
                if s.event == metric.anchor_event and _in(ctx, s, metric.date_from, metric.date_to) and ctx.kept(s, ftc)
            ]
            if not anchors:
                continue
            start = anchors[0].ts
            end = start + metric.within_days * DAY_MS
            n = sum(1 for s in steps if s.event == metric.event and start <= s.ts <= end and ctx.kept(s, ftc))
            if n >= metric.min_count:
                count += 1
        return count
    if metric.function == "top_values":
        assert metric.property is not None
        assert metric.top_n is not None
        tally: dict[str, int] = {}
        for steps in persons:
            for s in steps:
                if s.event == metric.event and _in(ctx, s, metric.date_from, metric.date_to) and ctx.kept(s, ftc):
                    key = str(s.props[metric.property])
                    tally[key] = tally.get(key, 0) + 1
        ranked = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))
        counts = [c for _, c in ranked[: metric.top_n + 1]]
        if len(ranked) < metric.top_n or any(a == b for a, b in pairwise(counts)):
            raise LedgerError(f"top_values tie or too few values: {ranked[: metric.top_n + 1]}")
        return [k for k, _ in ranked[: metric.top_n]]
    if metric.function == "distinct_days_users":
        assert metric.min_days_exclusive is not None
        count = 0
        for steps in persons:
            days = {
                ctx.day(s.ts)
                for s in steps
                if s.event == metric.event and _in(ctx, s, metric.date_from, metric.date_to) and ctx.kept(s, ftc)
            }
            if len(days) > metric.min_days_exclusive:
                count += 1
        return count
    if metric.function == "first_ever_in_range":
        count = 0
        for steps in persons:
            first = next((s for s in steps if s.event == metric.event and ctx.kept(s, ftc)), None)
            if first is not None and _in(ctx, first, metric.date_from, metric.date_to):
                count += 1
        return count
    raise LedgerError(f"{metric.function} is evaluated from the fault plan, not as a metric")


def evaluate(metric: Metric, persons: list[list[Step]], clock: Clock, internal_substring: str) -> TruthValue:
    """Evaluate a non-cause metric over ledger persons. Raises :class:`LedgerError` if undefined."""
    ctx = _Ctx(clock, internal_substring)
    if isinstance(metric, TrendsMetric):
        return _trends(metric, persons, ctx)
    if isinstance(metric, FunnelMetric):
        return _funnel(metric, persons, ctx)
    if isinstance(metric, RetentionMetric):
        return _retention(metric, persons, ctx)
    return _custom(metric, persons, ctx)


# --------------------------------------------------------------------------------------------------
# Planted causes
# --------------------------------------------------------------------------------------------------


def _single(values: set[str], what: str) -> str:
    if len(values) != 1:
        raise LedgerError(f"planted fault touched {len(values)} distinct {what} values: {sorted(values)}")
    return next(iter(values))


def planted_cause(fault: FaultSpec, journeys: list[Journey], clock: Clock) -> Cause:
    """The cause a planted fault implies, read from the journeys it touched; ``none`` if untouched."""
    touched = [(j, a) for j in journeys for a in j.actions if fault.id in a.faults]
    if not touched:
        return Cause(cause_type="none", property=None, value=None, start_date=None, end_date=None)
    if fault.id == "F1":
        prop, value = "$os", _single({j.os for j, _ in touched}, "$os")
        days = [clock.local_date(a.ts) for _, a in touched]
    elif fault.id == "F2":
        prop, value = "$browser", _single({j.browser for j, _ in touched}, "$browser")
        days = [clock.local_date(a.ts) for _, a in touched]
    elif fault.id == "F3":
        prop = "$current_url"
        value = _single({urlsplit(BASE_URL + (j.signup_url or "")).path for j, _ in touched}, "sign-up path")
        days = [clock.local_date(next(x.ts for x in j.actions if x.event == "signed_up")) for j, _ in touched]
    elif fault.id == "F4":
        prop, value = (
            "email",
            _single({(j.email or "").rsplit("@", 1)[-1] for j, _ in touched}, "email domain"),
        )
        days = [clock.local_date(a.ts) for _, a in touched]
    else:
        prop = fault.property
        value = _single({str(a.props[fault.property]) for _, a in touched}, fault.property)
        days = [clock.local_date(a.ts) for _, a in touched]
    return Cause(cause_type=fault.cause_type, property=prop, value=value, start_date=min(days), end_date=max(days))
