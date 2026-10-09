"""Planted-cause truth from events alone (contract §6, §7.4 PC scenarios).

``detect_cause`` runs five generic detectors over the symptom event in the scenario's date range
and requires that at most one finds an anomaly; two or more is an error (the truth would be
ambiguous), none yields ``cause_type: none``. Detectors look at every candidate property; nothing
tells them which property or value was planted.

- tracking_outage: a property value whose daily count is zero on one contiguous run of days strictly
  inside the range and at least ``OUTAGE_MIN_DAILY`` on every other day.
- duplicate_events: at least ``DUP_MIN`` events that repeat, within ``DUP_MAX_MS``, an event of the same
  person with identical properties; reported on the one property whose single value covers every
  duplicate while covering under half of the other events.
- identity_break: at least ``BREAK_MIN`` ``signed_up`` events in range whose distinct id is never merged
  by an ``$identify``; reported on the ``$current_url`` path they share.
- internal_traffic: an email domain (person email at event time) whose daily count reaches
  ``SPIKE_FACTOR`` times its median daily count on one contiguous run of days.
- property_value_change: a property value absent before some day and present from it, while another
  value present before that day (at least ``CHANGE_MIN`` times) is absent from it on.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from statistics import median
from urllib.parse import urlsplit

from agenttruth.evidence.models import Cause, CustomMetric
from agenttruth.oracle.frame import Ev, Frame, OracleError

__all__ = ["detect_cause"]

OUTAGE_MIN_DAILY = 3
DUP_MIN = 5
DUP_MAX_MS = 1_000
BREAK_MIN = 3
SPIKE_FACTOR = 10
CHANGE_MIN = 3
_SKIP = frozenset({"at_eid", "at_ds", "$host", "$lib"})


def _string_props(ev: Ev) -> dict[str, str]:
    return {k: v for k, v in ev.props.items() if isinstance(v, str) and k not in _SKIP}


def _runs(days: list[date]) -> list[tuple[date, date]]:
    out: list[tuple[date, date]] = []
    for day in sorted(days):
        if out and out[-1][1] + timedelta(days=1) == day:
            out[-1] = (out[-1][0], day)
        else:
            out.append((day, day))
    return out


def _finding(cause_type: str, prop: str, value: str, start: date, end: date) -> Cause:
    return Cause.model_validate(
        {"cause_type": cause_type, "property": prop, "value": value, "start_date": start, "end_date": end}
    )


def _tracking_outage(events: list[Ev], day: list[date], days: list[date]) -> list[Cause]:
    counts: dict[tuple[str, str], dict[date, int]] = defaultdict(lambda: defaultdict(int))
    for ev in events:
        for prop, value in _string_props(ev).items():
            counts[(prop, value)][day[ev.pos]] += 1
    found = []
    for (prop, value), daily in sorted(counts.items()):
        zero = [d for d in days if daily.get(d, 0) == 0]
        runs = _runs(zero)
        if len(runs) != 1 or runs[0][0] == days[0] or runs[0][1] == days[-1]:
            continue
        if min(daily.get(d, 0) for d in days if d not in zero) >= OUTAGE_MIN_DAILY:
            found.append(_finding("tracking_outage", prop, value, *runs[0]))
    return found


def _duplicate_events(events: list[Ev], day: list[date]) -> list[Cause]:
    last_seen: dict[tuple[int, tuple[tuple[str, str], ...]], int] = {}
    duplicates: list[Ev] = []
    for ev in events:
        signature = tuple(sorted((k, repr(v)) for k, v in ev.props.items() if k != "at_eid"))
        key = (ev.person, signature)
        previous = last_seen.get(key)
        if previous is not None and ev.ts - previous <= DUP_MAX_MS:
            duplicates.append(ev)
        last_seen[key] = ev.ts
    if len(duplicates) < DUP_MIN:
        return []
    dup_ids = {ev.at_eid for ev in duplicates}
    others = [ev for ev in events if ev.at_eid not in dup_ids]
    found = []
    candidate_props = sorted(set.intersection(*(set(_string_props(ev)) for ev in duplicates)))
    for prop in candidate_props:
        values = {_string_props(ev)[prop] for ev in duplicates}
        if len(values) != 1:
            continue
        value = next(iter(values))
        share = sum(1 for ev in others if _string_props(ev).get(prop) == value) / max(len(others), 1)
        if share < 0.5:
            dates = [day[ev.pos] for ev in duplicates]
            found.append(_finding("duplicate_events", prop, value, min(dates), max(dates)))
    return found


def _identity_break(frame: Frame, day: list[date], start: date, end: date) -> list[Cause]:
    broken = [
        ev
        for ev in frame.by_event.get("signed_up", [])
        if start <= day[ev.pos] <= end and ev.distinct_id not in frame.anon_ids_identified
    ]
    if len(broken) < BREAK_MIN:
        return []
    paths = {urlsplit(str(ev.props.get("$current_url", ""))).path for ev in broken}
    if len(paths) != 1:
        raise OracleError(f"identity breaks on several sign-up paths: {sorted(paths)}")
    dates = [day[ev.pos] for ev in broken]
    return [_finding("identity_break", "$current_url", next(iter(paths)), min(dates), max(dates))]


def _internal_traffic(events: list[Ev], day: list[date], days: list[date]) -> list[Cause]:
    counts: dict[str, dict[date, int]] = defaultdict(lambda: defaultdict(int))
    for ev in events:
        domain = ev.email.rsplit("@", 1)[-1].lower() if ev.email else "(none)"
        counts[domain][day[ev.pos]] += 1
    found = []
    for domain, daily in sorted(counts.items()):
        series = [daily.get(d, 0) for d in days]
        threshold = SPIKE_FACTOR * max(median(series), 1)
        spikes = [d for d, n in zip(days, series, strict=True) if n >= threshold]
        runs = _runs(spikes)
        if len(runs) == 1 and domain != "(none)":
            found.append(_finding("internal_traffic", "email", domain, *runs[0]))
    return found


def _property_value_change(events: list[Ev], day: list[date], days: list[date]) -> list[Cause]:
    seen: dict[str, dict[str, list[date]]] = defaultdict(lambda: defaultdict(list))
    for ev in events:
        for prop, value in _string_props(ev).items():
            seen[prop][value].append(day[ev.pos])
    found = []
    for prop, values in sorted(seen.items()):
        for new_value, new_days in sorted(values.items()):
            switch = min(new_days)
            if switch == days[0] or len(new_days) < CHANGE_MIN:
                continue
            replaced = [
                old
                for old, old_days in values.items()
                if old != new_value
                and sum(1 for d in old_days if d < switch) >= CHANGE_MIN
                and all(d < switch for d in old_days)
            ]
            if replaced:
                found.append(_finding("property_value_change", prop, new_value, switch, max(new_days)))
    return found


def detect_cause(metric: CustomMetric, frame: Frame, timezone: str) -> Cause:
    """Return the single anomaly behind the symptom on ``metric.event`` in its range, or ``none``.

    Raises :class:`OracleError` if more than one detector (or one detector more than once) fires.
    Complexity: O(n · p) for n events in range and p string properties per event.
    """
    if metric.function != "detect_cause":
        raise OracleError(f"{metric.function} is not a cause metric")
    day = frame.dates(timezone)
    days = [metric.date_from + timedelta(days=i) for i in range((metric.date_to - metric.date_from).days + 1)]
    events = [ev for ev in frame.by_event.get(metric.event, []) if metric.date_from <= day[ev.pos] <= metric.date_to]
    findings = (
        _tracking_outage(events, day, days)
        + _duplicate_events(events, day)
        + _identity_break(frame, day, metric.date_from, metric.date_to)
        + _internal_traffic(events, day, days)
        + _property_value_change(events, day, days)
    )
    if len(findings) > 1:
        raise OracleError(f"ambiguous planted cause for {metric.event}: {[f.model_dump() for f in findings]}")
    if not findings:
        return Cause(cause_type="none", property=None, value=None, start_date=None, end_date=None)
    return findings[0]
