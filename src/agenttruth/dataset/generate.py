"""Journey generator for ``ds0``/``ds1`` (contract §5): random and planted journeys, planted faults.

A build is a pure function of ``(spec, seed, generator code)``. All randomness comes from
:class:`~agenttruth.dataset.rng.Stream` with one stream per journey and purpose, so journeys are
independent of one another and of the planted faults. Faults are applied after the base journeys
exist and ``at_eid`` values are assigned, which is what makes each fault switchable in isolation
(K1-C4): disabling one changes only the actions it touched.
"""

from __future__ import annotations

import copy
import math
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from itertools import pairwise
from typing import Any

from agenttruth.dataset.rng import Stream
from agenttruth.dataset.spec import DatasetSpec, FaultSpec, PlantedJourney
from agenttruth.dataset.timeutil import DAY_MS, Clock, format_ts

__all__ = [
    "GENERATOR_VERSION",
    "Action",
    "GenerationError",
    "Journey",
    "build_journeys",
]

GENERATOR_VERSION = "agenttruth-gen/1"
HOST = "hedgebox.net"
BASE_URL = "https://hedgebox.net"
INTERNAL_DOMAIN = "hedgebox-internal.example"

# (os, browser, weight). Android never pairs with Firefox, so F1 and F2 segments are disjoint.
DEVICES: tuple[tuple[str, str, float], ...] = (
    ("Windows", "Chrome", 24),
    ("Windows", "Microsoft Edge", 9),
    ("Windows", "Firefox", 7),
    ("Mac OS X", "Chrome", 12),
    ("Mac OS X", "Safari", 11),
    ("Mac OS X", "Firefox", 4),
    ("Linux", "Firefox", 3),
    ("Linux", "Chrome", 2),
    ("iOS", "Mobile Safari", 14),
    ("Android", "Chrome", 14),
)
MOBILE_OS = frozenset({"iOS", "Android"})

HOUR_WEIGHTS: tuple[float, ...] = (
    0.3, 0.2, 0.15, 0.1, 0.1, 0.2, 0.4, 0.8, 1.2, 1.5, 1.6, 1.6,
    1.4, 1.5, 1.6, 1.6, 1.5, 1.4, 1.3, 1.3, 1.2, 1.0, 0.8, 0.5,
)  # fmt: skip
WEEKDAY_WEIGHTS: tuple[float, ...] = (1.0, 1.05, 1.0, 0.95, 0.9, 0.6, 0.55)


@dataclass(frozen=True)
class Tier:
    """Behaviour parameters of an engagement tier."""

    weight: float
    p_active: float
    decays: bool
    p_login: float
    lam_upload: float
    lam_download: float
    p_upgrade: float


TIERS: dict[str, Tier] = {
    "casual": Tier(0.62, 0.05, True, 0.85, 0.9, 0.6, 0.06),
    "regular": Tier(0.32, 0.13, True, 0.85, 1.1, 0.8, 0.18),
    "power": Tier(0.06, 0.45, False, 0.97, 0.6, 0.5, 0.30),
}

# Monthly price per seat, in integer cents (money is generated in cents, §5.1).
PLAN_PRICES = {"personal/pro": 1200, "business/standard": 2500, "business/enterprise": 6000}
UPGRADE_PLANS: tuple[tuple[str, float], ...] = (
    ("personal/pro", 55),
    ("business/standard", 35),
    ("business/enterprise", 10),
)

FILE_TYPES = (
    "application/pdf",
    "image/jpeg",
    "image/png",
    "video/mp4",
    "text/plain",
    "application/zip",
    "audio/mpeg",
)
FILE_SIZES: dict[str, tuple[int, int]] = {
    "application/pdf": (40_000, 4_000_000),
    "image/jpeg": (80_000, 6_000_000),
    "image/png": (20_000, 3_000_000),
    "video/mp4": (2_000_000, 400_000_000),
    "text/plain": (200, 200_000),
    "application/zip": (500_000, 900_000_000),
    "audio/mpeg": (1_000_000, 20_000_000),
}
# Upload popularity shifts by month so monthly rankings differ; downloads and internal uploads differ too.
UPLOAD_WEIGHTS_BY_MONTH: dict[int, tuple[float, ...]] = {
    5: (30, 24, 16, 10, 10, 5, 5),
    6: (30, 24, 16, 10, 10, 5, 5),
    7: (22, 30, 18, 14, 8, 4, 4),
    8: (17, 24, 13, 30, 8, 4, 4),
}
DOWNLOAD_WEIGHTS: tuple[float, ...] = (34, 16, 18, 8, 12, 7, 5)
INTERNAL_UPLOAD_WEIGHTS: tuple[float, ...] = (3, 2, 3, 2, 3, 85, 2)

ANON_PAGES: tuple[tuple[str, float], ...] = (
    ("/", 35),
    ("/pricing/", 20),
    ("/features/", 15),
    ("/blog/sharing-large-files/", 7),
    ("/blog/team-folders/", 7),
    ("/blog/backup-checklist/", 6),
    ("/signup/", 10),
)
APP_PAGES: tuple[tuple[str, float], ...] = (
    ("/files/", 50),
    ("/files/shared/", 15),
    ("/account/", 10),
    ("/pricing/", 8),
    ("/account/billing/", 7),
    ("/help/", 10),
)
EVENT_URLS = {
    "logged_in": "/login/",
    "uploaded_file": "/files/",
    "downloaded_file": "/files/",
    "shared_file_link": "/files/",
    "deleted_file": "/files/",
    "upgraded_plan": "/account/billing/",
    "downgraded_plan": "/account/billing/",
    "invited_team_member": "/account/team/",
}
FIRST_NAMES = (
    "Ana", "Bruno", "Carla", "Diego", "Elena", "Fabio", "Gloria", "Hugo", "Irene", "Jorge",
    "Karla", "Luis", "Marta", "Nico", "Olga", "Pablo", "Rosa", "Sergio", "Tania", "Victor",
)  # fmt: skip
LAST_NAMES = (
    "Alvarez", "Benitez", "Castro", "Duarte", "Estrada", "Flores", "Garza", "Herrera", "Ibarra",
    "Juarez", "Lozano", "Mendez", "Navarro", "Ortega", "Paredes", "Quiroga", "Ramos", "Salinas",
)  # fmt: skip
USER_DOMAINS = ("example.com", "example.net", "example.org")


class GenerationError(RuntimeError):
    """The spec cannot be realised (e.g. a planted fault window would be empty)."""


@dataclass(slots=True)
class Action:
    """One intended step. ``url`` is ``$current_url`` for client-side events; None for server-side."""

    event: str
    ts: int
    distinct_id: str
    props: dict[str, Any]
    url: str | None
    at_eid: str = ""
    emitted: bool = True
    faults: list[str] = field(default_factory=list)


@dataclass
class Journey:
    """One person-to-be: identity, device, intended steps and the faults that touched them."""

    uid: str
    kind: str  # user | internal | visitor
    os: str
    browser: str
    anon_id: str | None
    user_id: str | None
    email: str | None
    name: str | None
    signup_url: str | None
    planted_label: str | None
    actions: list[Action] = field(default_factory=list)
    faults: set[str] = field(default_factory=set)

    @property
    def distinct_ids(self) -> list[str]:
        """Every distinct id the journey uses, anonymous first."""
        return [i for i in (self.anon_id, self.user_id) if i is not None]

    def identify_action(self) -> Action | None:
        """The ``$identify`` step, if the journey has one (emitted or not)."""
        return next((a for a in self.actions if a.event == "$identify"), None)

    @property
    def merged(self) -> bool:
        """Whether the anonymous id is merged into the identified one (its ``$identify`` is emitted)."""
        identify = self.identify_action()
        return self.kind == "user" and identify is not None and identify.emitted


# --------------------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------------------


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _time_of_day_ms(rng: Stream) -> int:
    hour = rng.weighted([(h, w) for h, w in enumerate(HOUR_WEIGHTS)])
    return ((hour * 60 + rng.randint(0, 59)) * 60 + rng.randint(0, 59)) * 1000 + rng.randint(0, 999)


def _file(rng: Stream, weights: tuple[float, ...]) -> dict[str, Any]:
    file_type = rng.weighted(list(zip(FILE_TYPES, weights, strict=True)))
    low, high = FILE_SIZES[file_type]
    return {"file_type": file_type, "file_size_b": rng.randint(low, high)}


def _person_name(rng: Stream) -> tuple[str, str]:
    return rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)


class _Builder:
    """Builds every journey of one spec; holds the clock and the data period."""

    def __init__(self, spec: DatasetSpec) -> None:
        self.spec = spec
        self.clock = Clock(spec.timezone)
        self.first_day = spec.warmup.date_from if spec.warmup else spec.window.date_from
        self.last_day = spec.window.date_to
        self.window_days = _days(spec.window.date_from, spec.window.date_to)
        self.warmup_days = _days(spec.warmup.date_from, spec.warmup.date_to) if spec.warmup else []
        self.all_days = self.warmup_days + self.window_days
        self.end_ms = self.clock.day_start_ms(self.last_day + timedelta(days=1))
        self.start_ms = self.clock.day_start_ms(self.first_day)

    def stream(self, uid: str, purpose: str) -> Stream:
        return Stream(self.spec.seed, f"{uid}/{purpose}")

    def day_weights(self, days: list[date]) -> list[tuple[date, float]]:
        return [(d, WEEKDAY_WEIGHTS[d.weekday()] * (1 + 0.004 * i)) for i, d in enumerate(days)]

    # ------------------------------------------------------------------ sessions

    def session(
        self, rng: Stream, day: date, items: list[tuple[str, str | None, dict[str, Any]]], distinct_id: str
    ) -> list[Action]:
        """Place ``items`` on ``day`` as one session, strictly increasing, ending before 23:59:00."""
        if not items:
            return []
        gaps = [0] + [rng.randint(5_000, 90_000) for _ in items[1:]]
        start = self.clock.day_start_ms(day) + _time_of_day_ms(rng)
        latest_end = self.clock.day_start_ms(day + timedelta(days=1)) - 60_000
        overflow = start + sum(gaps) - latest_end
        if overflow > 0:
            start = max(self.clock.day_start_ms(day) + 60_000, start - overflow)
        out = []
        ts = start
        for gap, (event, url, props) in zip(gaps, items, strict=True):
            ts += gap
            out.append(Action(event, ts, distinct_id, props, url))
        return out

    # ------------------------------------------------------------------ random users

    def random_user(self, index: int, warmup: bool) -> Journey:
        uid = f"u{index:05d}"
        rng = self.stream(uid, "profile")
        os_name, browser = rng.weighted([((o, b), w) for o, b, w in DEVICES])
        tier_name = rng.weighted([(name, tier.weight) for name, tier in TIERS.items()])
        tier = TIERS[tier_name]
        days = self.warmup_days if warmup else self.window_days
        signup_day = rng.weighted(self.day_weights(days))
        signup_ts = self.clock.day_start_ms(signup_day) + _time_of_day_ms(rng)
        # Keep the sign-up sequence and its first session inside the same local day.
        signup_ts = min(signup_ts, self.clock.day_start_ms(signup_day) + DAY_MS - 3_600_000)
        signup_ts = max(signup_ts, self.clock.day_start_ms(signup_day) + 2 * 3_600_000)
        mobile_signup = os_name in MOBILE_OS and rng.bernoulli(0.55)
        signup_url = "/signup/mobile/" if mobile_signup else "/signup/"
        first, last = _person_name(rng)
        email = f"{first.lower()}.{last.lower()}{index}@{rng.choice(USER_DOMAINS)}"
        journey = Journey(
            uid=uid,
            kind="user",
            os=os_name,
            browser=browser,
            anon_id=f"anon-{rng.hex(16)}",
            user_id=f"user-{index + 1000}",
            email=email,
            name=f"{first} {last}",
            signup_url=signup_url,
            planted_label=None,
        )
        self._pre_signup(journey, signup_day, signup_ts, rng.bernoulli(0.15))
        self._activity(journey, tier, signup_day, signup_ts)
        return journey

    def _pre_signup(self, journey: Journey, signup_day: date, signup_ts: int, from_invite: bool) -> None:
        assert journey.anon_id is not None
        assert journey.user_id is not None
        assert journey.signup_url
        rng = self.stream(journey.uid, "presignup")
        anon = journey.anon_id
        for _ in range(rng.weighted([(0, 60), (1, 30), (2, 10)])):
            day = signup_day - timedelta(days=rng.randint(1, 6))
            if day < self.first_day:
                continue
            pages: list[tuple[str, str | None, dict[str, Any]]] = [
                ("$pageview", rng.weighted(ANON_PAGES), {}) for _ in range(rng.randint(1, 3))
            ]
            journey.actions += self.session(rng, day, pages, anon)
        # Same-day sequence, built backwards from the sign-up so it is strictly ordered.
        signup_page_ts = signup_ts - rng.randint(30_000, 240_000)
        before = [("$pageview", journey.signup_url, signup_page_ts)]
        cursor = signup_page_ts
        if rng.bernoulli(0.45):
            cursor -= rng.randint(60_000, 5_400_000)
            before.append(("$pageview", "/pricing/", cursor))
        cursor -= rng.randint(60_000, 900_000)
        before.append(("$pageview", "/", cursor))
        journey.actions += [Action(e, ts, anon, {}, url) for e, url, ts in before if ts > self.start_ms]
        self._signup_sequence(journey, signup_ts, from_invite)

    def _signup_sequence(self, journey: Journey, signup_ts: int, from_invite: bool) -> None:
        assert journey.anon_id is not None
        assert journey.user_id is not None
        url = journey.signup_url
        journey.actions += [
            Action("signed_up", signup_ts, journey.anon_id, {"from_invite": from_invite}, url),
            Action(
                "$identify",
                signup_ts + 1_500,
                journey.user_id,
                {
                    "$anon_distinct_id": journey.anon_id,
                    "$set": {"email": journey.email, "name": journey.name},
                },
                url,
            ),
            Action("$pageview", signup_ts + 4_000, journey.user_id, {}, "/files/"),
        ]

    def _activity(self, journey: Journey, tier: Tier, signup_day: date, signup_ts: int) -> None:
        assert journey.user_id is not None
        rng = self.stream(journey.uid, "activity")
        plan_rng = self.stream(journey.uid, "plan")
        user = journey.user_id
        plan = "personal/free"
        seats = 1
        upgrade_target = (
            signup_day + timedelta(days=plan_rng.randint(1, 25)) if plan_rng.bernoulli(tier.p_upgrade) else None
        )
        downgrade_target: date | None = None
        bills_from: tuple[int, str, int] | None = None  # (first bill ts, plan, seats)
        bill_stop: int | None = None
        for day in _days(signup_day, self.last_day):
            age = (day - signup_day).days
            items: list[tuple[str, str | None, dict[str, Any]]] = []
            if age == 0:
                active = rng.bernoulli(0.5)
            else:
                p = tier.p_active * ((0.6 + 0.4 * math.exp(-age / 40)) if tier.decays else 1.0)
                active = rng.bernoulli(p)
                if active and rng.bernoulli(tier.p_login):
                    items.append(("logged_in", EVENT_URLS["logged_in"], {}))
                if active:
                    items.append(("$pageview", "/files/", {}))
            if not active:
                continue
            month_weights = UPLOAD_WEIGHTS_BY_MONTH[day.month]
            later: list[dict[str, Any]] = []
            downloads = [_file(rng, DOWNLOAD_WEIGHTS) for _ in range(rng.poisson(tier.lam_download))]
            if downloads and rng.bernoulli(0.3):
                items += [("downloaded_file", "/files/", f) for f in downloads]
                downloads = []
            for _ in range(rng.poisson(tier.lam_upload) + (1 if age == 0 and rng.bernoulli(0.6) else 0)):
                upload = _file(rng, month_weights)
                items.append(("uploaded_file", "/files/", upload))
                if rng.bernoulli(0.3):
                    items.append(("shared_file_link", "/files/", dict(upload)))
                elif rng.bernoulli(0.08):
                    later.append(dict(upload))
            items += [("downloaded_file", "/files/", f) for f in downloads]
            for shared in later:
                items += [("$pageview", "/files/shared/", {}), ("shared_file_link", "/files/", shared)]
            if rng.bernoulli(0.08):
                items.append(("deleted_file", "/files/", _file(rng, month_weights)))
            if plan.startswith("business/") and rng.bernoulli(0.15):
                items.append(("invited_team_member", EVENT_URLS["invited_team_member"], {}))
            if rng.bernoulli(0.2):
                items.append(("$pageview", rng.weighted(APP_PAGES), {}))
            if upgrade_target is not None and day >= upgrade_target and plan == "personal/free":
                new_plan = plan_rng.weighted(list(UPGRADE_PLANS))
                seats = plan_rng.randint(2, 12) if new_plan.startswith("business/") else 1
                items += [
                    ("$pageview", "/account/billing/", {}),
                    (
                        "upgraded_plan",
                        EVENT_URLS["upgraded_plan"],
                        {"previous_plan": plan, "new_plan": new_plan},
                    ),
                ]
                plan = new_plan
                if plan_rng.bernoulli(0.12):
                    downgrade_target = day + timedelta(days=plan_rng.randint(20, 50))
            elif downgrade_target is not None and day >= downgrade_target and plan != "personal/free":
                items.append(
                    (
                        "downgraded_plan",
                        EVENT_URLS["downgraded_plan"],
                        {"previous_plan": plan, "new_plan": "personal/free"},
                    )
                )
                plan = "personal/free"
                downgrade_target = None
            if age == 0:
                start = max(signup_ts + 9_000, max(a.ts for a in journey.actions) + 1_000)
                actions = self._continue(rng, start, items, user)
            else:
                actions = self.session(rng, day, items, user)
            journey.actions += actions
            for action in actions:
                if action.event == "upgraded_plan":
                    bills_from = (action.ts, action.props["new_plan"], seats)
                elif action.event == "downgraded_plan":
                    bill_stop = action.ts
        if bills_from is not None:
            journey.actions += self._bills(journey.uid, user, *bills_from, bill_stop)

    def _continue(
        self, rng: Stream, start: int, items: list[tuple[str, str | None, dict[str, Any]]], distinct_id: str
    ) -> list[Action]:
        """Continue the sign-up-day session after ``start``; drop what would not fit before 23:59:00."""
        day = self.clock.local_date(start)
        latest_end = self.clock.day_start_ms(day + timedelta(days=1)) - 60_000
        out = []
        ts = start
        for event, url, props in items:
            ts += rng.randint(5_000, 90_000)
            if ts >= latest_end:
                break
            out.append(Action(event, ts, distinct_id, props, url))
        return out

    def _bills(self, uid: str, user: str, upgrade_ts: int, plan: str, seats: int, stop: int | None) -> list[Action]:
        """Server-side ``paid_bill`` at upgrade and on the same day of each later month."""
        rng = self.stream(uid, "bills")
        amount = PLAN_PRICES[plan] * seats
        out = [self._bill(upgrade_ts + rng.randint(60_000, 600_000), user, plan, amount)]
        anchor = self.clock.local_date(upgrade_ts)
        for months in range(1, 6):
            year = anchor.year + (anchor.month - 1 + months) // 12
            month = (anchor.month - 1 + months) % 12 + 1
            last = (date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)).day
            day = date(year, month, min(anchor.day, last))
            ts = self.clock.day_start_ms(day) + rng.randint(3_600_000, 22 * 3_600_000)
            if ts >= self.end_ms or (stop is not None and ts > stop):
                break
            out.append(self._bill(ts, user, plan, amount))
        return out

    @staticmethod
    def _bill(ts: int, user: str, plan: str, amount_cents: int) -> Action:
        return Action("paid_bill", ts, user, {"amount_usd": amount_cents / 100, "plan": plan}, None)

    # ------------------------------------------------------------------ internal users and visitors

    def internal_user(self, index: int) -> Journey:
        uid = f"i{index:03d}"
        rng = self.stream(uid, "profile")
        os_name, browser = rng.weighted([((o, b), w) for o, b, w in DEVICES[:8]])
        first, last = _person_name(rng)
        user_id = f"user-{90000 + index}"
        journey = Journey(
            uid=uid,
            kind="internal",
            os=os_name,
            browser=browser,
            anon_id=None,
            user_id=user_id,
            email=f"{first.lower()}.{last.lower()}{index}@{INTERNAL_DOMAIN}",
            name=f"{first} {last}",
            signup_url=None,
            planted_label=None,
        )
        start = self.start_ms + 9 * 3_600_000 + index * 73_000
        journey.actions.append(self._internal_identify(journey, start))
        act = self.stream(uid, "activity")
        for day in self.all_days:
            if not act.bernoulli(0.7 if day.weekday() < 5 else 0.08):
                continue
            items: list[tuple[str, str | None, dict[str, Any]]] = [("logged_in", EVENT_URLS["logged_in"], {})]
            items += [("$pageview", act.weighted(APP_PAGES), {}) for _ in range(act.randint(1, 2))]
            for _ in range(act.poisson(1.7)):
                upload = _file(act, INTERNAL_UPLOAD_WEIGHTS)
                items.append(("uploaded_file", "/files/", upload))
                if act.bernoulli(0.3):
                    items.append(("shared_file_link", "/files/", dict(upload)))
            items += [("downloaded_file", "/files/", _file(act, DOWNLOAD_WEIGHTS)) for _ in range(act.poisson(0.7))]
            actions = self.session(act, day, items, user_id)
            journey.actions += [a for a in actions if a.ts > start]
        return journey

    @staticmethod
    def _internal_identify(journey: Journey, ts: int) -> Action:
        assert journey.user_id is not None
        return Action(
            "$identify",
            ts,
            journey.user_id,
            {"$set": {"email": journey.email, "name": journey.name}},
            "/login/",
        )

    def visitor(self, index: int) -> Journey:
        uid = f"v{index:05d}"
        rng = self.stream(uid, "profile")
        os_name, browser = rng.weighted([((o, b), w) for o, b, w in DEVICES])
        journey = Journey(
            uid=uid,
            kind="visitor",
            os=os_name,
            browser=browser,
            anon_id=f"anon-{rng.hex(16)}",
            user_id=None,
            email=None,
            name=None,
            signup_url=None,
            planted_label=None,
        )
        assert journey.anon_id is not None
        days = sorted(
            {rng.weighted(self.day_weights(self.all_days)) for _ in range(rng.weighted([(1, 70), (2, 22), (3, 8)]))}
        )
        for day in days:
            pages = [rng.weighted(ANON_PAGES) for _ in range(rng.randint(1, 3))]
            journey.actions += self.session(rng, day, [("$pageview", p, {}) for p in pages], journey.anon_id)
        return journey

    # ------------------------------------------------------------------ planted journeys

    def planted(self, index: int, plan: PlantedJourney) -> Journey:
        def ms(moment: datetime) -> int:
            return self.clock.local_ms(moment)

        if plan.kind == "internal":
            assert plan.start is not None
            uid = f"i{index:03d}"
            journey = Journey(
                uid=uid,
                kind="internal",
                os=plan.os,
                browser=plan.browser,
                anon_id=None,
                user_id=f"user-{90000 + index}",
                email=f"{plan.label}@{INTERNAL_DOMAIN}",
                name=plan.label.replace("-", " ").title(),
                signup_url=None,
                planted_label=plan.label,
            )
            journey.actions.append(self._internal_identify(journey, ms(plan.start)))
        else:
            assert plan.signup is not None
            uid = f"u{index:05d}"
            rng = self.stream(uid, "profile")
            journey = Journey(
                uid=uid,
                kind="user",
                os=plan.os,
                browser=plan.browser,
                anon_id=f"anon-{rng.hex(16)}",
                user_id=f"user-{index + 1000}",
                email=f"{plan.label}@example.com",
                name=plan.label.replace("-", " ").title(),
                signup_url=plan.signup.url,
                planted_label=plan.label,
            )
            assert journey.anon_id is not None
            signup_ts = ms(plan.signup.at)
            journey.actions += [Action("$pageview", ms(v.at), journey.anon_id, {}, v.url) for v in plan.pre_visits]
            journey.actions.append(Action("$pageview", signup_ts - 60_000, journey.anon_id, {}, plan.signup.url))
            self._signup_sequence(journey, signup_ts, plan.signup.from_invite)
        assert journey.user_id is not None
        for step in plan.actions:
            props = dict(step.props)
            if step.event == "paid_bill":
                url = None
                if "amount_usd_cents" in props:
                    cents = props.pop("amount_usd_cents")
                    if not isinstance(cents, int):
                        raise GenerationError(f"{plan.label}: amount_usd_cents must be an integer")
                    props["amount_usd"] = cents / 100
            else:
                url = step.url or EVENT_URLS.get(step.event, "/files/")
            journey.actions.append(Action(step.event, ms(step.at), journey.user_id, props, url))
        return journey


def _assign_ids(dataset_id: str, journey: Journey) -> None:
    journey.actions.sort(key=lambda a: a.ts)
    for previous, current in pairwise(journey.actions):
        if current.ts <= previous.ts:
            raise GenerationError(
                f"{journey.uid}: timestamps not strictly increasing ({previous.event}, {current.event})"
            )
    for seq, action in enumerate(journey.actions):
        action.at_eid = f"{dataset_id}-{journey.uid}-{seq:04d}"


# --------------------------------------------------------------------------------------------------
# Planted faults
# --------------------------------------------------------------------------------------------------


def _in_window(clock: Clock, ts: int, fault: FaultSpec) -> bool:
    return fault.date_from <= clock.local_date(ts) <= fault.date_to


def _apply_fault(fault: FaultSpec, journeys: list[Journey], clock: Clock, seed: str) -> None:
    for journey in journeys:
        touched = False
        if fault.id == "F1":
            if journey.os == fault.value:
                for action in journey.actions:
                    if action.event == fault.event and action.emitted and _in_window(clock, action.ts, fault):
                        action.emitted = False
                        action.faults.append("F1")
                        touched = True
        elif fault.id == "F2":
            assert fault.duplicate_delay_ms is not None
            if journey.browser == fault.value:
                low, high = fault.duplicate_delay_ms
                extra = []
                for action in journey.actions:
                    if action.event == fault.event and action.emitted and _in_window(clock, action.ts, fault):
                        delay = Stream(seed, f"F2/{action.at_eid}").randint(low, high)
                        if clock.local_date(action.ts + delay) != clock.local_date(action.ts):
                            raise GenerationError(f"F2 duplicate of {action.at_eid} would cross local midnight")
                        dup = Action(fault.event, action.ts + delay, action.distinct_id, dict(action.props), action.url)
                        dup.at_eid = f"{action.at_eid}-dup"
                        dup.faults.append("F2")
                        extra.append(dup)
                        touched = True
                journey.actions += extra
        elif fault.id == "F3":
            signup = next((a for a in journey.actions if a.event == "signed_up"), None)
            identify = journey.identify_action()
            if (
                journey.kind == "user"
                and signup is not None
                and identify is not None
                and fault.value.lower() in (signup.url or "").lower()
                and _in_window(clock, signup.ts, fault)
            ):
                identify.emitted = False
                identify.faults.append("F3")
                touched = True
        elif fault.id == "F4":
            assert fault.multiplier is not None
            if journey.email is not None and fault.value.lower() in journey.email.lower():
                extra = _internal_burst(fault, journey, clock)
                touched = bool(extra)
                journey.actions += extra
        elif fault.id == "F5":
            assert fault.replaces is not None
            for action in journey.actions:
                if (
                    action.event == fault.event
                    and action.props.get(fault.property) == fault.replaces
                    and _in_window(clock, action.ts, fault)
                ):
                    action.props = {**action.props, fault.property: fault.value}
                    action.faults.append("F5")
                    touched = True
        if touched:
            journey.faults.add(fault.id)
    _check_coverage(fault, journeys, clock)


def _internal_burst(fault: FaultSpec, journey: Journey, clock: Clock) -> list[Action]:
    """F4: ``multiplier - 1`` extra page views per original one, on one 3-second timeline per day.

    The extras of a day follow the person's last step of that day (or precede the first one if the
    day would overflow), so no two of them share a timestamp and none repeats another event within
    a second (which would also look like duplicated events).
    """
    assert fault.multiplier is not None
    by_day: dict[date, list[Action]] = {}
    for action in journey.actions:
        if action.event == fault.event and action.emitted and _in_window(clock, action.ts, fault):
            by_day.setdefault(clock.local_date(action.ts), []).append(action)
    extra: list[Action] = []
    for day, originals in sorted(by_day.items()):
        same_day = [a.ts for a in journey.actions if clock.local_date(a.ts) == day]
        count = len(originals) * (fault.multiplier - 1)
        step = 3_000
        start, direction = max(same_day) + step, 1
        if clock.local_date(start + count * step) != day:
            start, direction = min(same_day) - step, -1
        k = 0
        for original in originals:
            for i in range(1, fault.multiplier):
                copy_ = Action(fault.event, start + direction * k * step, original.distinct_id, {}, original.url)
                copy_.at_eid = f"{original.at_eid}-x{i:02d}"
                copy_.faults.append("F4")
                extra.append(copy_)
                k += 1
        if clock.local_date(start + direction * (k - 1) * step) != day:
            raise GenerationError(f"F4 burst for {journey.uid} does not fit in {day}")
    return extra


def _check_coverage(fault: FaultSpec, journeys: list[Journey], clock: Clock) -> None:
    """Every planted fault must touch its window's first and last day (K1-C4)."""
    days = {clock.local_date(a.ts) for j in journeys for a in j.actions if fault.id in a.faults}
    missing = [d for d in (fault.date_from, fault.date_to) if d not in days]
    if missing:
        raise GenerationError(f"{fault.id} touches no event on {', '.join(str(d) for d in missing)}")


# --------------------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------------------


def build_journeys(spec: DatasetSpec, disabled_faults: frozenset[str]) -> list[Journey]:
    """Build every journey of ``spec`` with all faults applied except ``disabled_faults``.

    Order: planted users, random users, planted internal, random internal, visitors. Raises
    :class:`GenerationError` when the spec cannot be realised. Complexity: O(events).
    """
    unknown = disabled_faults - {f.id for f in spec.faults}
    if unknown:
        raise GenerationError(f"cannot disable faults not in the spec: {sorted(unknown)}")
    builder = _Builder(spec)
    planted_users = [p for p in spec.planted if p.kind == "user"]
    planted_internal = [p for p in spec.planted if p.kind == "internal"]
    population = spec.population
    if len(planted_users) > population.users or len(planted_internal) > population.internal_users:
        raise GenerationError("more planted journeys than the population allows")
    journeys: list[Journey] = [builder.planted(i, p) for i, p in enumerate(planted_users)]
    random_users = population.users - len(planted_users)
    journeys += [
        builder.random_user(len(planted_users) + i, warmup=i < population.warmup_users) for i in range(random_users)
    ]
    journeys += [builder.planted(i, p) for i, p in enumerate(planted_internal)]
    journeys += [builder.internal_user(i) for i in range(len(planted_internal), population.internal_users)]
    journeys += [builder.visitor(i) for i in range(population.visitors)]
    for journey in journeys:
        journey.actions = [a for a in journey.actions if builder.start_ms <= a.ts < builder.end_ms]
        _assign_ids(spec.dataset_id, journey)
    for fault in sorted(spec.faults, key=lambda f: f.id):
        if fault.id not in disabled_faults:
            _apply_fault(fault, journeys, builder.clock, spec.seed)
    for journey in journeys:
        journey.actions.sort(key=lambda a: (a.ts, a.at_eid))
    return journeys


def clone(journeys: list[Journey]) -> list[Journey]:
    """Deep copy of journeys (used to evaluate mutations without touching the build)."""
    return copy.deepcopy(journeys)


AT_EID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/CesarManzoCode/agenttruth#at_eid")


def event_properties(journey: Journey, props: dict[str, Any], url: str | None) -> dict[str, Any]:
    """Event properties of a step as emitted, without ``at_eid``/``at_ds`` (§5.2).

    Client-side steps carry ``$current_url``, ``$host``, ``$browser``, ``$os`` and ``$lib = web``;
    server-side steps (``url is None``, i.e. ``paid_bill``) carry only ``$lib = posthog-python``.
    """
    if url is None:
        return {"$lib": "posthog-python", **props}
    return {
        "$current_url": BASE_URL + url,
        "$host": HOST,
        "$browser": journey.browser,
        "$os": journey.os,
        "$lib": "web",
        **props,
    }


def event_record(dataset_id: str, journey: Journey, action: Action) -> dict[str, Any]:
    """The ``events.jsonl`` record of an emitted step; ``uuid`` is UUIDv5 of ``at_eid``."""
    properties = event_properties(journey, action.props, action.url)
    properties["at_eid"] = action.at_eid
    properties["at_ds"] = dataset_id
    return {
        "schema": "agenttruth.event/v1",
        "event": action.event,
        "distinct_id": action.distinct_id,
        "timestamp": format_ts(action.ts),
        "uuid": str(uuid.uuid5(AT_EID_NAMESPACE, action.at_eid)),
        "properties": properties,
    }


__all__ += ["AT_EID_NAMESPACE", "clone", "event_properties", "event_record"]
