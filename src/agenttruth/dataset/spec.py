"""Dataset spec model (``datasets/<id>.spec.yaml``), importable by the oracle (contract §4.1).

The spec fixes everything a build depends on besides generator code: seed, window, warm-up,
population sizes, the five planted faults with their windows and segments, the planted edge-case
journeys, and the oracle-sensitivity mutations of K1-C5.
"""

from __future__ import annotations

from datetime import date, datetime
from itertools import pairwise
from typing import Literal

from pydantic import Field, JsonValue, StrictBool, StrictInt, StrictStr, model_validator

from agenttruth.evidence.models import DateWindow, FaultId, Model, TestAccountFilter

__all__ = [
    "DatasetSpec",
    "FaultSpec",
    "PlantedAction",
    "PlantedJourney",
    "PlantedSignup",
    "PlantedVisit",
    "PopulationSpec",
    "SensitivityTarget",
]

MutationKind = Literal[
    "drop_in_range_uploaded_file",
    "move_boundary_event_across_local_midnight",
    "change_internal_user_email_domain",
    "duplicate_signed_up",
    "remove_identify",
]


class FaultSpec(Model):
    """One planted fault (contract §5.2): what it does, to which segment, in which local window.

    ``property``/``operator``/``value`` identify the affected segment as an analyst would name it
    (the planted-cause truth). Fault-specific parameters: ``duplicate_delay_ms`` (F2),
    ``multiplier`` (F4) and ``replaces`` (F5, the value the fault rewrites into ``value``).
    """

    id: FaultId
    cause_type: Literal[
        "tracking_outage", "duplicate_events", "identity_break", "internal_traffic", "property_value_change"
    ]
    event: StrictStr
    date_from: date
    date_to: date
    property: StrictStr
    property_type: Literal["event", "person"]
    operator: Literal["exact", "icontains"]
    value: StrictStr
    duplicate_delay_ms: tuple[StrictInt, StrictInt] | None = None
    multiplier: StrictInt | None = None
    replaces: StrictStr | None = None

    @model_validator(mode="after")
    def _params(self) -> FaultSpec:
        if self.date_from > self.date_to:
            raise ValueError(f"{self.id}: date_from after date_to")
        expected = {"F2": "duplicate_delay_ms", "F4": "multiplier", "F5": "replaces"}
        for name in ("duplicate_delay_ms", "multiplier", "replaces"):
            present = getattr(self, name) is not None
            if present != (expected.get(self.id) == name):
                raise ValueError(f"{self.id}: parameter {name} is {'unexpected' if present else 'required'}")
        return self


class PlantedVisit(Model):
    """An anonymous pageview before sign-up, at a local time."""

    at: datetime
    url: StrictStr


class PlantedSignup(Model):
    """A sign-up at an exact local time through a given sign-up page."""

    at: datetime
    url: StrictStr
    from_invite: StrictBool = False


class PlantedAction(Model):
    """A post-sign-up (or internal) action at an exact local time with explicit properties."""

    at: datetime
    event: StrictStr
    url: StrictStr | None = None
    props: dict[str, JsonValue] = Field(default_factory=dict)


class PlantedJourney(Model):
    """A scripted journey that plants an edge case (§5.2). It has no random activity.

    Users get the standard sign-up sequence automatically: sign-up page view 60 s before
    ``signup.at``, ``signed_up`` at ``signup.at``, ``$identify`` 1.5 s later and a ``/files/`` page
    view 4 s later. Internal journeys start with ``$identify`` at ``start``.
    """

    label: StrictStr = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    kind: Literal["user", "internal"]
    os: StrictStr
    browser: StrictStr
    signup: PlantedSignup | None = None
    start: datetime | None = None
    pre_visits: list[PlantedVisit] = Field(default_factory=list)
    actions: list[PlantedAction] = Field(default_factory=list)

    @model_validator(mode="after")
    def _kind(self) -> PlantedJourney:
        if self.kind == "user" and (self.signup is None or self.start is not None):
            raise ValueError(f"{self.label}: a planted user needs signup and no start")
        if self.kind == "internal" and (self.start is None or self.signup is not None or self.pre_visits):
            raise ValueError(f"{self.label}: a planted internal user needs start and no signup or visits")
        return self


class SensitivityTarget(Model):
    """Where an oracle-sensitivity mutation (K1-C5) applies, by planted label and local time."""

    id: StrictStr = Field(pattern=r"^M[0-9]+$")
    kind: MutationKind
    label: StrictStr
    event: StrictStr
    at: datetime | None = None
    delta_ms: StrictInt | None = None
    new_email: StrictStr | None = None


class PopulationSpec(Model):
    """Population sizes; planted journeys count towards ``users`` and ``internal_users``."""

    users: StrictInt = Field(gt=0)
    warmup_users: StrictInt = Field(ge=0)
    internal_users: StrictInt = Field(ge=0)
    visitors: StrictInt = Field(ge=0)


class DatasetSpec(Model):
    """``datasets/<id>.spec.yaml``."""

    schema_id: Literal["agenttruth.dataset-spec/v1"] = Field(alias="schema")
    dataset_id: StrictStr = Field(pattern=r"^ds[0-9]+$")
    seed: StrictStr
    timezone: StrictStr
    week_start_day: Literal[1]
    test_account_filters: list[TestAccountFilter]
    window: DateWindow
    warmup: DateWindow | None
    population: PopulationSpec
    catalog: StrictStr | None
    faults: list[FaultSpec]
    planted: list[PlantedJourney]
    sensitivity: list[SensitivityTarget]

    @model_validator(mode="after")
    def _consistency(self) -> DatasetSpec:
        ids = [fault.id for fault in self.faults]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate fault id")
        labels = [journey.label for journey in self.planted]
        if len(labels) != len(set(labels)):
            raise ValueError("duplicate planted label")
        if self.warmup is not None and self.warmup.date_to >= self.window.date_from:
            raise ValueError("warm-up must end before the window starts")
        windows = sorted((f.date_from, f.date_to, f.id) for f in self.faults)
        for (_, end_a, id_a), (start_b, _, id_b) in pairwise(windows):
            if start_b <= end_a:
                raise ValueError(f"fault windows {id_a} and {id_b} overlap")
        return self
