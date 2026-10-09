"""Small builders for hand-made events and metrics used by known-answer tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from agenttruth.evidence.models import Event

TZ = "America/Mexico_City"
_counter = [0]


def utc_text(local: str, tz: str = TZ) -> str:
    """``YYYY-MM-DDTHH:MM:SS.mmm`` local time → emitted UTC timestamp text."""
    moment = datetime.fromisoformat(local).replace(tzinfo=ZoneInfo(tz)).astimezone(UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def ev(event: str, local: str, distinct_id: str, **props: Any) -> Event:
    """One event at a local time with a fresh ``at_eid``."""
    _counter[0] += 1
    at_eid = f"t-{_counter[0]:06d}"
    return Event.model_validate(
        {
            "schema": "agenttruth.event/v1",
            "event": event,
            "distinct_id": distinct_id,
            "timestamp": utc_text(local),
            "uuid": f"uuid-{at_eid}",
            "properties": {"at_eid": at_eid, "at_ds": "test", **props},
        }
    )


def identify(local: str, user: str, anon: str | None, email: str) -> Event:
    """An ``$identify`` merging ``anon`` into ``user`` and setting the email."""
    props: dict[str, Any] = {"$set": {"email": email, "name": user}}
    if anon is not None:
        props["$anon_distinct_id"] = anon
    return ev("$identify", local, user, **props)
