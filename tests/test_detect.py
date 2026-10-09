"""Planted-cause detectors on synthetic events (each fires on its own pattern only)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from _factories import TZ, ev, identify

from agenttruth.evidence.models import CustomMetric, Event
from agenttruth.oracle.detect import detect_cause
from agenttruth.oracle.frame import Frame, OracleError


def metric(event: str, start: str, end: str) -> CustomMetric:
    return CustomMetric.model_validate(
        {"type": "custom", "function": "detect_cause", "event": event, "date_from": start, "date_to": end}
    )


def days(start: date, n: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]


def test_tracking_outage() -> None:
    events = []
    for i, day in enumerate(days(date(2026, 7, 8), 10)):
        for os_name in ("Android", "iOS", "Windows"):
            if os_name == "Android" and 3 <= i <= 5:
                continue
            events += [ev("u", f"{day}T1{k}:00:00.000", f"{os_name}-{k}", **{"$os": os_name}) for k in range(4)]
    cause = detect_cause(metric("u", "2026-07-08", "2026-07-17"), Frame(events, TZ), TZ)
    assert (cause.cause_type, cause.property, cause.value) == ("tracking_outage", "$os", "Android")
    assert (cause.start_date, cause.end_date) == (date(2026, 7, 11), date(2026, 7, 13))


def test_duplicate_events() -> None:
    events = []
    for i, day in enumerate(days(date(2026, 8, 1), 6)):
        for browser in ("Firefox", "Chrome", "Safari"):
            for k in range(3):
                original = ev("s", f"{day}T1{k}:00:00.000", f"{browser}-{k}", **{"$browser": browser, "n": k})
                events.append(original)
                if browser == "Firefox" and 1 <= i <= 3:
                    events.append(ev("s", f"{day}T1{k}:00:00.200", f"{browser}-{k}", **{"$browser": browser, "n": k}))
    cause = detect_cause(metric("s", "2026-08-01", "2026-08-06"), Frame(events, TZ), TZ)
    assert (cause.cause_type, cause.property, cause.value) == ("duplicate_events", "$browser", "Firefox")
    assert (cause.start_date, cause.end_date) == (date(2026, 8, 2), date(2026, 8, 4))


def test_identity_break_and_none() -> None:
    events: list[Event] = []
    for i, day in enumerate(days(date(2026, 6, 20), 6)):
        for k, path in enumerate(("/signup/", "/signup/mobile/")):
            anon, user = f"anon-{i}-{k}", f"user-{i}-{k}"
            events.append(
                ev(
                    "signed_up",
                    f"{day}T10:00:00.000",
                    anon,
                    **{"$current_url": f"https://hedgebox.net{path}"},
                )
            )
            if not (path == "/signup/mobile/" and 1 <= i <= 4):
                events.append(identify(f"{day}T10:00:01.500", user, anon, f"{user}@example.com"))
    cause = detect_cause(metric("signed_up", "2026-06-20", "2026-06-25"), Frame(events, TZ), TZ)
    assert (cause.cause_type, cause.property, cause.value) == (
        "identity_break",
        "$current_url",
        "/signup/mobile/",
    )
    assert (cause.start_date, cause.end_date) == (date(2026, 6, 21), date(2026, 6, 24))
    quiet = detect_cause(metric("signed_up", "2026-06-20", "2026-06-20"), Frame(events, TZ), TZ)
    assert quiet.cause_type == "none" and quiet.value is None


def test_internal_traffic() -> None:
    events = [identify("2026-07-01T08:00:00.000", "staff", None, "staff@hedgebox-internal.example")]
    events += [identify("2026-07-01T08:00:00.000", "user", None, "user@example.com")]
    for i, day in enumerate(days(date(2026, 7, 1), 10)):
        events += [ev("$pageview", f"{day}T10:00:{k:02d}.000", "user") for k in range(5)]
        n = 60 if i in (6, 7) else 2
        events += [ev("$pageview", f"{day}T11:{k // 60:02d}:{k % 60:02d}.000", "staff") for k in range(n)]
    cause = detect_cause(metric("$pageview", "2026-07-01", "2026-07-10"), Frame(events, TZ), TZ)
    assert (cause.cause_type, cause.property, cause.value) == (
        "internal_traffic",
        "email",
        "hedgebox-internal.example",
    )
    assert (cause.start_date, cause.end_date) == (date(2026, 7, 7), date(2026, 7, 8))


def test_property_value_change_and_ambiguity() -> None:
    events = []
    for i, day in enumerate(days(date(2026, 8, 10), 10)):
        plan = "pro" if i >= 6 else "personal/pro"
        events += [ev("up", f"{day}T1{k}:00:00.000", f"u{i}{k}", new_plan=plan) for k in range(2)]
    cause = detect_cause(metric("up", "2026-08-10", "2026-08-19"), Frame(events, TZ), TZ)
    assert (cause.cause_type, cause.property, cause.value) == ("property_value_change", "new_plan", "pro")
    assert (cause.start_date, cause.end_date) == (date(2026, 8, 16), date(2026, 8, 19))
    both = events + [ev("up", f"2026-08-1{d}T09:00:00.000", f"v{d}", channel="b" if d >= 6 else "a") for d in range(10)]
    with pytest.raises(OracleError):
        detect_cause(metric("up", "2026-08-10", "2026-08-19"), Frame(both, TZ), TZ)
