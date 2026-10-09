"""Event frame: emitted events with identity resolved and person email known at event time.

Built from ``events.jsonl`` alone (contract §6.1). Identity follows SEM-04: an ``$identify`` merges
``$anon_distinct_id`` into the identified id for all of its events, past and future; a merge whose
anonymous id is already identified is refused (F-24). Person email follows SEM-05: the value set by
``$set.email`` on the person's events, as known at each event's time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from agenttruth.evidence.models import Event

__all__ = ["Ev", "Frame", "OracleError", "parse_timestamp"]

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class OracleError(RuntimeError):
    """A truth is undefined or the input violates an oracle assumption (with the reason)."""


def parse_timestamp(text: str) -> int:
    """UTC epoch milliseconds of an ``events.jsonl`` timestamp (``YYYY-MM-DDTHH:MM:SS.mmmZ``)."""
    moment = datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    return (moment - _EPOCH) // timedelta(milliseconds=1)


@dataclass(frozen=True, slots=True)
class Ev:
    """One event with its resolved person and the person's email at that moment."""

    pos: int
    ts: int
    at_eid: str
    event: str
    distinct_id: str
    props: dict[str, object]
    person: int
    email: str | None


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, item: str) -> str:
        self.parent.setdefault(item, item)
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[item] != root:
            self.parent[item], item = root, self.parent[item]
        return root

    def union_into(self, child: str, parent: str) -> None:
        self.parent[self.find(child)] = self.find(parent)


class Frame:
    """All events of a dataset, ordered by ``(timestamp, at_eid)``, with per-timezone local dates.

    Complexity: O(n log n) to build (sort), O(n) per timezone for local dates.
    """

    def __init__(self, events: list[Event], timezone: str) -> None:
        raw = []
        for event in events:
            at_eid = event.properties.get("at_eid")
            if not isinstance(at_eid, str):
                raise OracleError(f"event {event.uuid} has no string at_eid")
            raw.append((parse_timestamp(event.timestamp), at_eid, event))
        raw.sort(key=lambda item: (item[0], item[1]))

        identities = _UnionFind()
        identified: set[str] = set()
        for _, _, event in raw:
            identities.find(event.distinct_id)
            if event.event != "$identify":
                continue
            anon = event.properties.get("$anon_distinct_id")
            if isinstance(anon, str) and anon != event.distinct_id:
                already = anon in identified or identities.find(anon) != anon
                if not already:
                    identities.union_into(anon, event.distinct_id)
            identified.add(event.distinct_id)

        person_ids: dict[str, int] = {}
        emails: dict[int, str] = {}
        self.events: list[Ev] = []
        for pos, (ts, at_eid, event) in enumerate(raw):
            root = identities.find(event.distinct_id)
            person = person_ids.setdefault(root, len(person_ids))
            set_props = event.properties.get("$set")
            if isinstance(set_props, dict) and isinstance(set_props.get("email"), str):
                emails[person] = str(set_props["email"])
            self.events.append(
                Ev(
                    pos,
                    ts,
                    at_eid,
                    event.event,
                    event.distinct_id,
                    dict(event.properties),
                    person,
                    emails.get(person),
                )
            )
        self.persons = len(person_ids)
        self.timezone = timezone
        self.by_event: dict[str, list[Ev]] = {}
        self.by_person: dict[int, list[Ev]] = {}
        for ev in self.events:
            self.by_event.setdefault(ev.event, []).append(ev)
            self.by_person.setdefault(ev.person, []).append(ev)
        self.anon_ids_identified = {
            str(ev.props["$anon_distinct_id"])
            for ev in self.by_event.get("$identify", [])
            if isinstance(ev.props.get("$anon_distinct_id"), str)
        }
        self._dates: dict[str, list[date]] = {}

    def dates(self, timezone: str) -> list[date]:
        """Local calendar date of every event (indexed by ``Ev.pos``) in ``timezone``."""
        cached = self._dates.get(timezone)
        if cached is None:
            zone = ZoneInfo(timezone)
            cached = [(_EPOCH + timedelta(milliseconds=ev.ts)).astimezone(zone).date() for ev in self.events]
            self._dates[timezone] = cached
        return cached
