"""``agenttruth dataset build``: spec → ``events.jsonl``, ``ledger.json``, ``manifest.json`` (§5.1).

The build is a pure function of the spec, its seed, the catalog it names (the ledger records one
value per scenario) and generator code. Output files are canonical (sorted keys, LF, events
ordered by ``(timestamp, at_eid)``), so two builds of the same inputs are byte-identical (K1-C1).
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from agenttruth.dataset.generate import (
    GENERATOR_VERSION,
    Action,
    GenerationError,
    Journey,
    build_journeys,
    event_record,
)
from agenttruth.dataset.ledger_eval import evaluate, persons_of, planted_cause
from agenttruth.dataset.spec import DatasetSpec, SensitivityTarget
from agenttruth.dataset.timeutil import Clock, format_ts
from agenttruth.evidence.canonical import (
    canonical_file_bytes,
    canonical_jsonl_bytes,
    sha256_bytes,
    sha256_json,
)
from agenttruth.evidence.models import (
    Catalog,
    DatasetCounts,
    EASpec,
    Ledger,
    Manifest,
    PCSpec,
    TruthValue,
    dump,
)
from agenttruth.evidence.read import load_yaml

__all__ = ["BuildError", "build_dataset", "load_spec", "resolve_spec"]


class BuildError(RuntimeError):
    """The dataset cannot be built from these inputs."""


def resolve_spec(spec: str, root: Path) -> Path:
    """Resolve ``--spec``: a dataset id such as ``ds1`` (→ ``datasets/ds1.spec.yaml``) or a path."""
    path = Path(spec)
    if path.suffix in {".yaml", ".yml"}:
        return path if path.is_absolute() else root / path
    return root / "datasets" / f"{spec}.spec.yaml"


def load_spec(path: Path) -> DatasetSpec:
    """Load and validate a dataset spec. Raises ``FileNotFoundError`` or ``ValueError``."""
    return DatasetSpec.model_validate(load_yaml(path))


def _load_catalog(spec: DatasetSpec, root: Path) -> tuple[Catalog | None, str | None]:
    if spec.catalog is None:
        return None, None
    path = root / spec.catalog
    data = path.read_bytes()
    catalog = Catalog.model_validate(load_yaml(path))
    if catalog.dataset != spec.dataset_id:
        raise BuildError(f"catalog {path} is for dataset {catalog.dataset}, not {spec.dataset_id}")
    return catalog, sha256_bytes(data)


def _scenario_values(
    catalog: Catalog | None, spec: DatasetSpec, journeys: list[Journey], clock: Clock
) -> dict[str, TruthValue]:
    if catalog is None:
        return {}
    internal = spec.test_account_filters[0].value
    persons = persons_of(journeys)
    faults = {fault.id: fault for fault in spec.faults}
    values: dict[str, TruthValue] = {}
    for scenario in catalog.scenarios:
        info = scenario.agenttruth
        if isinstance(info, EASpec):
            values[scenario.id] = evaluate(info.metric, persons, clock, internal)
        elif isinstance(info, PCSpec):
            values[scenario.id] = planted_cause(faults[info.fault], journeys, clock)
    return values


def _find(journeys: list[Journey], target: SensitivityTarget, clock: Clock) -> tuple[int, Action]:
    for index, journey in enumerate(journeys):
        if journey.planted_label != target.label:
            continue
        for action in journey.actions:
            if action.event != target.event or not action.emitted:
                continue
            if target.at is None or action.ts == clock.local_ms(target.at):
                return index, action
    raise BuildError(f"sensitivity target {target.id}: no {target.event} step for {target.label} at {target.at}")


def _mutation(
    target: SensitivityTarget,
    spec: DatasetSpec,
    journeys: list[Journey],
    clock: Clock,
) -> tuple[dict[str, Any], list[Journey]]:
    """Return the mutation's edit operations and the journeys with the same change applied."""
    index, action = _find(journeys, target, clock)
    mutated = list(journeys)
    journey = copy.deepcopy(journeys[index])
    mutated[index] = journey
    step = next(a for a in journey.actions if a.at_eid == action.at_eid)
    edits: list[dict[str, Any]]
    if target.kind in {"drop_in_range_uploaded_file", "remove_identify"}:
        step.emitted = False
        edits = [{"op": "remove", "at_eid": step.at_eid}]
        description = f"remove {step.event} {step.at_eid} ({target.label})"
    elif target.kind == "move_boundary_event_across_local_midnight":
        if target.delta_ms is None:
            raise BuildError(f"{target.id}: delta_ms is required")
        before = clock.local_date(step.ts)
        step.ts += target.delta_ms
        if clock.local_date(step.ts) == before:
            raise BuildError(f"{target.id}: moving by {target.delta_ms} ms does not cross local midnight")
        edits = [{"op": "set_timestamp", "at_eid": step.at_eid, "timestamp": format_ts(step.ts)}]
        description = f"move {step.event} {step.at_eid} by {target.delta_ms} ms across local midnight"
    elif target.kind == "change_internal_user_email_domain":
        if target.new_email is None or step.event != "$identify":
            raise BuildError(f"{target.id}: needs new_email and an $identify step")
        step.props = {**step.props, "$set": {**step.props["$set"], "email": target.new_email}}
        edits = [
            {
                "op": "set_property",
                "at_eid": step.at_eid,
                "path": ["properties", "$set", "email"],
                "value": target.new_email,
            }
        ]
        description = f"change the email of internal user {target.label} to {target.new_email}"
    else:  # duplicate_signed_up
        dup = Action(step.event, step.ts, step.distinct_id, dict(step.props), step.url)
        dup.at_eid = f"{step.at_eid}-m4dup"
        journey.actions.append(dup)
        journey.actions.sort(key=lambda a: (a.ts, a.at_eid))
        edits = [{"op": "insert", "at_eid": dup.at_eid, "event": event_record(spec.dataset_id, journey, dup)}]
        description = f"duplicate {step.event} {step.at_eid} as {dup.at_eid}"
    return {"id": target.id, "kind": target.kind, "description": description, "edits": edits}, mutated


def build_dataset(spec_path: Path, out: Path, disabled: frozenset[str], root: Path) -> Manifest:
    """Build the dataset of ``spec_path`` into the empty-or-new directory ``out``.

    ``root`` resolves the spec's catalog path. Returns the manifest. Raises :class:`BuildError` or
    :class:`GenerationError` if the spec cannot be realised and ``FileExistsError`` if ``out``
    already contains files. Complexity: O(events · scenarios) for the ledger.
    """
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"output directory is not empty: {out}")
    spec = load_spec(spec_path)
    catalog, catalog_sha = _load_catalog(spec, root)
    clock = Clock(spec.timezone)
    try:
        journeys = build_journeys(spec, disabled)
        values = _scenario_values(catalog, spec, journeys, clock)
    except GenerationError as exc:
        raise BuildError(str(exc)) from exc
    sensitivity = []
    if catalog is not None:
        for target in spec.sensitivity:
            mutation, mutated = _mutation(target, spec, journeys, clock)
            after = _scenario_values(catalog, spec, mutated, clock)
            changes = {sid: after[sid] for sid in sorted(after) if after[sid] != values[sid]}
            if not changes:
                raise BuildError(f"sensitivity target {target.id} changes no scenario value")
            mutation["predicted_changes"] = changes
            sensitivity.append(mutation)

    events = [event_record(spec.dataset_id, j, a) for j in journeys for a in j.actions if a.emitted]
    events.sort(key=lambda e: (e["timestamp"], e["properties"]["at_eid"]))
    counts = DatasetCounts(
        events=len(events),
        users=sum(1 for j in journeys if j.kind == "user"),
        internal_users=sum(1 for j in journeys if j.kind == "internal"),
        visitors=sum(1 for j in journeys if j.kind == "visitor"),
        planted_journeys=sum(1 for j in journeys if j.planted_label is not None),
        distinct_ids=len({e["distinct_id"] for e in events}),
    )
    spec_sha = sha256_json(dump(spec))
    faults = {fault.id: fault for fault in spec.faults}
    ledger = Ledger.model_validate(
        {
            "schema": "agenttruth.ledger/v1",
            "dataset_id": spec.dataset_id,
            "generator_version": GENERATOR_VERSION,
            "spec_sha256": spec_sha,
            "catalog_sha256": catalog_sha,
            "faults_disabled": sorted(disabled),
            "counts": dump(counts),
            "planted_faults": [
                {
                    "id": fid,
                    "enabled": fid not in disabled,
                    "cause": dump(planted_cause(faults[fid], journeys, clock)),
                    "touched_events": sum(1 for j in journeys for a in j.actions if fid in a.faults),
                    "touched_journeys": sum(1 for j in journeys if fid in j.faults),
                }
                for fid in sorted(faults)
            ],
            "scenario_values": values,
            "sensitivity": sensitivity,
            "journeys": [
                {
                    "uid": j.uid,
                    "kind": j.kind,
                    "distinct_ids": j.distinct_ids,
                    "merged": j.merged,
                    "email": j.email,
                    "os": j.os,
                    "browser": j.browser,
                    "signup_url": j.signup_url,
                    "planted_label": j.planted_label,
                    "faults": sorted(j.faults),
                    "actions": [
                        {
                            "at_eid": a.at_eid,
                            "event": a.event,
                            "timestamp": format_ts(a.ts),
                            "distinct_id": a.distinct_id,
                            "emitted": a.emitted,
                            "faults": sorted(a.faults),
                        }
                        for a in j.actions
                    ],
                }
                for j in journeys
            ],
        }
    )
    events_bytes = canonical_jsonl_bytes(events)
    ledger_bytes = canonical_file_bytes(dump(ledger))
    manifest = Manifest.model_validate(
        {
            "schema": "agenttruth.manifest/v1",
            "dataset_id": spec.dataset_id,
            "generator_version": GENERATOR_VERSION,
            "spec_sha256": spec_sha,
            "catalog_sha256": catalog_sha,
            "seed": spec.seed,
            "window": dump(spec.window),
            "warmup": dump(spec.warmup) if spec.warmup else None,
            "faults_enabled": sorted(set(faults) - disabled),
            "faults_disabled": sorted(disabled),
            "project_config": {
                "timezone": spec.timezone,
                "week_start_day": spec.week_start_day,
                "test_account_filters": [dump(f) for f in spec.test_account_filters],
            },
            "counts": dump(counts),
            "files": {
                "events.jsonl": {
                    "sha256": sha256_bytes(events_bytes),
                    "bytes": len(events_bytes),
                    "lines": len(events),
                },
                "ledger.json": {"sha256": sha256_bytes(ledger_bytes), "bytes": len(ledger_bytes)},
            },
        }
    )
    out.mkdir(parents=True, exist_ok=True)
    (out / "events.jsonl").write_bytes(events_bytes)
    (out / "ledger.json").write_bytes(ledger_bytes)
    (out / "manifest.json").write_bytes(canonical_file_bytes(dump(manifest)))
    return manifest
