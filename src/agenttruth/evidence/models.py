"""Pydantic v2 models for every structure AgentTruth persists (contract §5–§7, §13).

Every top-level document carries ``schema: agenttruth.<kind>/v1`` (field ``schema_id`` in Python,
alias ``schema`` on disk). Models are strict about unknown keys (``extra="forbid"``) and about
numbers and booleans (``StrictInt``/``StrictBool``), so a typo or a stringly-typed value in a catalog,
spec or recorded artifact fails validation with the offending path instead of being coerced.

These models are pure definitions (no I/O) and belong to the read side of ``evidence``.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)

__all__ = [
    "Catalog",
    "Cause",
    "CriterionResult",
    "CustomMetric",
    "DatasetCounts",
    "DatasetLock",
    "EASpec",
    "EditOp",
    "Event",
    "FaultId",
    "FileEntry",
    "FunnelMetric",
    "FunnelStep",
    "FunnelWindow",
    "GateReport",
    "Ledger",
    "LedgerAction",
    "LedgerJourney",
    "LintIssue",
    "LintReport",
    "Manifest",
    "Metric",
    "Model",
    "Mutation",
    "NegativeControl",
    "PCSpec",
    "PlantedFault",
    "Probe",
    "ProbeMetric",
    "ProjectConfig",
    "PropertyFilter",
    "RASetting",
    "RASpec",
    "RSSpec",
    "RetentionMetric",
    "RsDefaults",
    "Scenario",
    "SchemaFieldRef",
    "TestAccountFilter",
    "TrendsMetric",
    "TruthRecord",
    "TruthValue",
    "Truths",
    "ValueMatch",
    "dump",
]

FaultId = Literal["F1", "F2", "F3", "F4", "F5"]
CauseType = Literal[
    "tracking_outage",
    "duplicate_events",
    "identity_break",
    "internal_traffic",
    "property_value_change",
    "none",
]
SemId = Annotated[str, Field(pattern=r"^SEM-(0[1-9]|1[0-5])$")]
SigId = Annotated[str, Field(pattern=r"^SIG_[A-Z0-9_]+$|^SIG_EVENT_[a-z_$][a-z0-9_]*$")]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
IsoTimestamp = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")]


class Model(BaseModel):
    """Base model: unknown keys rejected, instances immutable, fields populated by name or alias."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


def dump(model: BaseModel) -> dict[str, Any]:
    """Return the JSON-compatible dict of ``model`` with on-disk aliases (``schema``) and nulls kept."""
    return model.model_dump(mode="json", by_alias=True)


# --------------------------------------------------------------------------------------------------
# Metric specs (contract §7.3)
# --------------------------------------------------------------------------------------------------


class PropertyFilter(Model):
    """A property filter on an event or on the person (``type: person``) at event time."""

    key: StrictStr
    type: Literal["event", "person"] = "event"
    operator: Literal["exact", "icontains"]
    value: StrictStr


class TrendsMetric(Model):
    """Aggregate of one event over an inclusive local date range (SEM-01, SEM-03, SEM-05, SEM-12).

    ``math``: ``total`` counts events, ``dau`` counts distinct persons over the whole range, ``sum``
    adds ``math_property`` in integer cents (SEM-14). With ``breakdown`` the value is a mapping keyed
    by the event property value; with ``interval: day`` it is keyed by local date (``YYYY-MM-DD`` or
    ``YYYY-MM-DD|<breakdown value>``), zero-filled over every day of the range.
    """

    type: Literal["trends"]
    event: StrictStr
    math: Literal["total", "dau", "sum"]
    math_property: StrictStr | None = None
    date_from: date
    date_to: date
    properties: list[PropertyFilter] = Field(default_factory=list)
    breakdown: StrictStr | None = None
    interval: Literal["day"] | None = None
    filter_test_accounts: StrictBool

    @model_validator(mode="after")
    def _math_property(self) -> TrendsMetric:
        if (self.math == "sum") != (self.math_property is not None):
            raise ValueError("math_property is required for math=sum and forbidden otherwise")
        return self


class FunnelStep(Model):
    """One funnel step: an event name and optional property filters."""

    event: StrictStr
    properties: list[PropertyFilter] = Field(default_factory=list)


class FunnelWindow(Model):
    """Conversion window measured from the step-1 event (SEM-07)."""

    n: StrictInt = Field(gt=0)
    unit: Literal["second", "minute", "hour", "day", "week"]


class FunnelMetric(Model):
    """Funnel over an inclusive local date range; every step event must lie in the range (SEM-06..09).

    The value is a mapping ``{"entered", "step_2", ..., "converted"}`` of person counts: ``entered``
    for step 1, ``step_<k>`` for intermediate steps and ``converted`` for the last step.
    """

    type: Literal["funnel"]
    steps: list[FunnelStep] = Field(min_length=2)
    window: FunnelWindow
    order: Literal["ordered", "strict"]
    date_from: date
    date_to: date
    filter_test_accounts: StrictBool


class RetentionMetric(Model):
    """One retention cell (SEM-10, SEM-11): ``{"cohort_size", "retained"}``.

    Cohort periods partition the inclusive cohort range ``[date_from, date_to]`` into local buckets of
    ``period``; ``cohort_index`` selects one. ``retained`` counts cohort persons with a return event in
    bucket ``cohort + period_index`` or, with ``cumulative``, in any bucket from there up to
    ``total_intervals - 1``.
    """

    type: Literal["retention"]
    start_event: StrictStr
    return_event: StrictStr
    period: Literal["Day", "Week", "Month"]
    retention_type: Literal["retention_first_time", "retention_recurring"]
    cumulative: StrictBool
    total_intervals: StrictInt = Field(gt=1)
    date_from: date
    date_to: date
    cohort_index: StrictInt = Field(ge=0)
    period_index: StrictInt = Field(ge=1)
    filter_test_accounts: StrictBool

    @model_validator(mode="after")
    def _period_in_range(self) -> RetentionMetric:
        if self.period_index >= self.total_intervals:
            raise ValueError("period_index must be smaller than total_intervals")
        return self


CustomFunction = Literal[
    "power_uploaders",
    "top_values",
    "distinct_days_users",
    "first_ever_in_range",
    "detect_cause",
]

_CUSTOM_PARAMS: dict[str, set[str]] = {
    "power_uploaders": {"anchor_event", "min_count", "within_days"},
    "top_values": {"property", "top_n"},
    "distinct_days_users": {"min_days_exclusive"},
    "first_ever_in_range": set(),
    "detect_cause": set(),
}


class CustomMetric(Model):
    """A named oracle function with typed parameters; its HogQL lives in the scenario (§7.3).

    - ``power_uploaders``: persons whose earliest ``anchor_event`` in range is followed by at least
      ``min_count`` ``event`` events within ``within_days`` days (inclusive).
    - ``top_values``: the ``top_n`` values of event ``property`` by count, descending (a ranking).
    - ``distinct_days_users``: persons with ``event`` on more than ``min_days_exclusive`` distinct days.
    - ``first_ever_in_range``: persons whose first-ever ``event`` (whole dataset, SEM-15) is in range.
    - ``detect_cause``: the planted cause behind a symptom on ``event`` within the range.
    """

    type: Literal["custom"]
    function: CustomFunction
    event: StrictStr
    date_from: date
    date_to: date
    filter_test_accounts: StrictBool = False
    anchor_event: StrictStr | None = None
    min_count: StrictInt | None = None
    within_days: StrictInt | None = None
    property: StrictStr | None = None
    top_n: StrictInt | None = None
    min_days_exclusive: StrictInt | None = None

    @model_validator(mode="after")
    def _params(self) -> CustomMetric:
        optional = {"anchor_event", "min_count", "within_days", "property", "top_n", "min_days_exclusive"}
        required = _CUSTOM_PARAMS[self.function]
        for name in sorted(optional):
            present = getattr(self, name) is not None
            if name in required and not present:
                raise ValueError(f"custom function {self.function} requires {name}")
            if name not in required and present:
                raise ValueError(f"custom function {self.function} does not take {name}")
        return self


Metric = Annotated[TrendsMetric | FunnelMetric | RetentionMetric | CustomMetric, Field(discriminator="type")]
ProbeMetric = Annotated[TrendsMetric | FunnelMetric, Field(discriminator="type")]


# --------------------------------------------------------------------------------------------------
# Answers and truths
# --------------------------------------------------------------------------------------------------


class Cause(Model):
    """A planted-cause answer or truth (§9.1 ``cause``); all fields null except type for ``none``."""

    cause_type: CauseType
    property: StrictStr | None
    value: StrictStr | None
    start_date: date | None
    end_date: date | None


TruthValue = StrictInt | StrictFloat | dict[str, StrictInt] | list[StrictStr] | Cause


class ValueMatch(Model):
    """How a planted-cause answer's ``value`` is compared (§9.2): exact, or contains ``substring``."""

    rule: Literal["exact", "contains"]
    substring: StrictStr | None = None

    @model_validator(mode="after")
    def _substring(self) -> ValueMatch:
        if (self.rule == "contains") != (self.substring is not None):
            raise ValueError("substring is required for rule=contains and forbidden for rule=exact")
        return self


# --------------------------------------------------------------------------------------------------
# Scenario catalog (contract §7.2, §7.4)
# --------------------------------------------------------------------------------------------------


class EASpec(Model):
    """AgentTruth fields of an exact-answer scenario."""

    kind: Literal["exact_answer"]
    answer_kind: Literal["count", "amount", "mapping", "ranking"]
    metric: Metric
    signatures: list[SigId]
    semantics: list[SemId]
    fault_overlaps: list[FaultId]
    posthog_query: StrictStr = Field(description='"auto" for non-custom metrics; reviewed HogQL for custom')


class Probe(Model):
    """A numeric probe metric of a planted-cause scenario (triangulated in K2, checked by K1-C4)."""

    id: StrictStr
    metric: ProbeMetric
    posthog_query: Literal["auto"]


class PCSpec(Model):
    """AgentTruth fields of a planted-cause scenario."""

    kind: Literal["planted_cause"]
    answer_kind: Literal["cause"]
    fault: FaultId
    metric: CustomMetric
    probes: list[Probe] = Field(min_length=1)
    value_match: ValueMatch
    semantics: list[SemId]

    @model_validator(mode="after")
    def _detect(self) -> PCSpec:
        if self.metric.function != "detect_cause":
            raise ValueError("planted-cause metrics use function detect_cause")
        return self


class SchemaFieldRef(Model):
    """A field of a class in the vendored ``posthog/schema.py`` (whose default the RS value must differ from)."""

    schema_class: StrictStr
    schema_field: StrictStr


class RSSpec(Model):
    """AgentTruth fields of a round-trip-scripted case: one setting through the MCP save path (§7.4).

    ``path`` is the dotted path of the setting inside the insight's query object (``source`` for
    insight-viz queries is implied by ``insight``). Update cases name the settings present before the
    update in ``initial`` and how the update is sent in ``operation``.
    """

    kind: Literal["roundtrip_scripted"]
    insight: Literal["sql", "trends", "funnels", "retention"]
    path: StrictStr
    value: JsonValue
    schema_default: SchemaFieldRef
    operation: Literal["create", "update_full_query", "update_partial_chart_settings"]
    initial: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def _initial(self) -> RSSpec:
        if (self.operation == "create") != (self.initial is None):
            raise ValueError("initial settings are required for update operations and forbidden for create")
        return self


class RASetting(Model):
    """A setting the round-trip agent prompt asks for, with the label the agent reports it under."""

    label: StrictStr
    path: StrictStr
    value: JsonValue


class RASpec(Model):
    """AgentTruth fields of a round-trip-agent scenario (prompts may stay draft until K4)."""

    kind: Literal["roundtrip_agent"]
    answer_kind: Literal["roundtrip_report"]
    draft: StrictBool
    insight: Literal["sql", "trends", "funnels", "retention"]
    operation: Literal["create", "update"]
    settings: list[RASetting] = Field(min_length=1)
    keep: list[RASetting] = Field(default_factory=list)


AgentTruthSpec = Annotated[EASpec | PCSpec | RSSpec | RASpec, Field(discriminator="kind")]


class Scenario(Model):
    """One catalog entry: PostHog ``tasks.yaml`` v2 task fields plus ``agenttruth`` (ADR-0007)."""

    id: StrictStr
    category: StrictStr
    intent: StrictStr
    expected_tools: list[StrictStr]
    acceptable_tools: list[StrictStr]
    success_criteria: StrictStr
    agenttruth: AgentTruthSpec


class Catalog(Model):
    """Scenario catalog file ``scenarios/catalog.v<N>.yaml``.

    Id uniqueness, kebab-case and category membership are checked by ``scenarios lint`` (K1-C6), not
    here, so that a malformed catalog still loads and every problem is reported at once.
    """

    schema_id: Literal["agenttruth.catalog/v1"] = Field(alias="schema")
    version: Literal[1]
    dataset: StrictStr
    scenarios: list[Scenario]


# --------------------------------------------------------------------------------------------------
# Dataset artifacts (contract §5)
# --------------------------------------------------------------------------------------------------


class Event(Model):
    """One line of ``events.jsonl``: a capture-ready event plus the schema tag."""

    schema_id: Literal["agenttruth.event/v1"] = Field(alias="schema")
    event: StrictStr
    distinct_id: StrictStr = Field(max_length=200)
    timestamp: IsoTimestamp
    uuid: StrictStr
    properties: dict[str, JsonValue]


class TestAccountFilter(Model):
    """The project test-account filter of contract §4.2."""

    __test__ = False  # not a pytest test class

    key: StrictStr
    type: Literal["person"]
    value: StrictStr
    operator: Literal["not_icontains"]


class ProjectConfig(Model):
    """Project configuration the oracle evaluates against (§6.1)."""

    timezone: StrictStr
    week_start_day: Literal[0, 1]
    test_account_filters: list[TestAccountFilter]


class FileEntry(Model):
    """Hash and size of one dataset file."""

    sha256: Sha256
    bytes: StrictInt
    lines: StrictInt | None = None


class DatasetCounts(Model):
    """Population and event counts of a dataset build."""

    events: StrictInt
    users: StrictInt
    internal_users: StrictInt
    visitors: StrictInt
    planted_journeys: StrictInt
    distinct_ids: StrictInt


class DateWindow(Model):
    """An inclusive local date range."""

    date_from: date
    date_to: date


class Manifest(Model):
    """``manifest.json`` of a dataset build (§5.1)."""

    schema_id: Literal["agenttruth.manifest/v1"] = Field(alias="schema")
    dataset_id: StrictStr
    generator_version: StrictStr
    spec_sha256: Sha256
    catalog_sha256: Sha256 | None
    seed: StrictStr
    window: DateWindow
    warmup: DateWindow | None
    faults_enabled: list[FaultId]
    faults_disabled: list[FaultId]
    project_config: ProjectConfig
    counts: DatasetCounts
    files: dict[str, FileEntry]


class DatasetLock(Model):
    """``datasets/<id>.lock.json``: expected SHA-256 of each built file (K1-C1)."""

    schema_id: Literal["agenttruth.dataset-lock/v1"] = Field(alias="schema")
    dataset_id: StrictStr
    files: dict[Literal["events.jsonl", "ledger.json", "manifest.json"], Sha256]


class LedgerAction(Model):
    """One intended step of a journey, emitted or suppressed by a fault."""

    at_eid: StrictStr
    event: StrictStr
    timestamp: IsoTimestamp
    distinct_id: StrictStr
    emitted: StrictBool
    faults: list[FaultId]


class LedgerJourney(Model):
    """One journey: who (identity, internal or not), what (steps), and which faults touched it."""

    uid: StrictStr
    kind: Literal["user", "internal", "visitor"]
    distinct_ids: list[StrictStr]
    merged: StrictBool
    email: StrictStr | None
    os: StrictStr
    browser: StrictStr
    signup_url: StrictStr | None
    planted_label: StrictStr | None
    faults: list[FaultId]
    actions: list[LedgerAction]


class PlantedFault(Model):
    """A planted fault as constructed: the cause it implies and how much it touched."""

    id: FaultId
    enabled: StrictBool
    cause: Cause
    touched_events: StrictInt
    touched_journeys: StrictInt


class EditOp(Model):
    """One mechanical edit of ``events.jsonl`` used by an oracle-sensitivity mutation (K1-C5)."""

    op: Literal["remove", "insert", "set_timestamp", "set_property"]
    at_eid: StrictStr
    timestamp: IsoTimestamp | None = None
    path: list[StrictStr] | None = None
    value: JsonValue = None
    event: Event | None = None


class Mutation(Model):
    """An event-file mutation and the scenario values the construction predicts after it (K1-C5)."""

    id: StrictStr
    kind: Literal[
        "drop_in_range_uploaded_file",
        "move_boundary_event_across_local_midnight",
        "change_internal_user_email_domain",
        "duplicate_signed_up",
        "remove_identify",
    ]
    description: StrictStr
    edits: list[EditOp] = Field(min_length=1)
    predicted_changes: dict[str, TruthValue]


class Ledger(Model):
    """``ledger.json``: the construction ledger (§5.4), computed from journey structures."""

    schema_id: Literal["agenttruth.ledger/v1"] = Field(alias="schema")
    dataset_id: StrictStr
    generator_version: StrictStr
    spec_sha256: Sha256
    catalog_sha256: Sha256 | None
    faults_disabled: list[FaultId]
    counts: DatasetCounts
    planted_faults: list[PlantedFault]
    scenario_values: dict[str, TruthValue]
    sensitivity: list[Mutation]
    journeys: list[LedgerJourney]


# --------------------------------------------------------------------------------------------------
# Truths (oracle output)
# --------------------------------------------------------------------------------------------------


class TruthRecord(Model):
    """Truth of one EA/PC scenario with its signature values (EA) or probe values (PC)."""

    scenario_id: StrictStr
    kind: Literal["exact_answer", "planted_cause"]
    answer_kind: Literal["count", "amount", "mapping", "ranking", "cause"]
    value: TruthValue
    signatures: dict[str, TruthValue]
    probes: dict[str, TruthValue]
    fault_overlaps: list[FaultId]
    fault: FaultId | None
    value_match: ValueMatch | None
    test_accounts_flipped: TruthValue | None
    semantics: list[SemId]
    metric_sha256: Sha256


class Truths(Model):
    """``truths/<dataset>.v<catalog version>.json``, written only by ``agenttruth oracle compute``."""

    schema_id: Literal["agenttruth.truths/v1"] = Field(alias="schema")
    contract_version: StrictStr
    dataset_id: StrictStr
    events_sha256: Sha256
    manifest_sha256: Sha256
    catalog_sha256: Sha256
    catalog_version: StrictInt
    project_config: ProjectConfig
    truths: list[TruthRecord]


# --------------------------------------------------------------------------------------------------
# Lint, RS defaults, gate report
# --------------------------------------------------------------------------------------------------


class LintIssue(Model):
    """One ``scenarios lint`` finding."""

    scenario_id: StrictStr | None
    rule: StrictStr
    message: StrictStr


class LintReport(Model):
    """Output of ``agenttruth scenarios lint --json-out``."""

    schema_id: Literal["agenttruth.lint-report/v1"] = Field(alias="schema")
    catalog_sha256: Sha256
    truths_sha256: Sha256 | None
    ok: StrictBool
    scenarios: StrictInt
    by_kind: dict[str, StrictInt]
    signatures: StrictInt
    issues: list[LintIssue]


class RsDefaults(Model):
    """Defaults extracted from the vendored ``posthog/schema.py`` for the classes RS lint needs."""

    schema_id: Literal["agenttruth.rs-defaults/v1"] = Field(alias="schema")
    posthog_commit: StrictStr
    sources: dict[str, StrictStr]
    classes: dict[str, dict[str, JsonValue]]


class CriterionResult(Model):
    """One gate criterion's outcome (§13.3)."""

    id: StrictStr
    statement: StrictStr
    result: Literal["pass", "fail"]
    observed: JsonValue
    expected: JsonValue
    evidence: list[Sha256]


class NegativeControl(Model):
    """One negative control's outcome (§13.3)."""

    criterion_id: StrictStr
    sabotage: StrictStr
    expected_fail: list[StrictStr]
    observed_failing_criteria: list[StrictStr]
    result: Literal["pass", "fail"]


class GateReport(Model):
    """``evidence/K<n>/gate-K<n>.json``, written only by ``agenttruth gate K<n>``."""

    schema_id: Literal["agenttruth.gate-report/v1"] = Field(alias="schema")
    gate: StrictStr
    contract_version: StrictStr
    git_sha: StrictStr
    git_dirty: StrictBool
    environment: dict[str, StrictStr]
    inputs: dict[str, StrictStr]
    criteria: list[CriterionResult]
    negative_controls: list[NegativeControl]
    verdict: Literal["pass", "fail"]
