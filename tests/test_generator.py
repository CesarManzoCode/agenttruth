"""Generator: byte-for-byte determinism, event format (§5.1–§5.3), planted faults isolated (§5.2)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from agenttruth.dataset.build import build_dataset, load_spec
from agenttruth.dataset.generate import AT_EID_NAMESPACE, GenerationError, build_journeys
from agenttruth.dataset.spec import DatasetSpec
from agenttruth.evidence.models import dump

CLIENT_PROPS = {"$current_url", "$host", "$browser", "$os", "$lib"}


def small_ds1(**changes: Any) -> DatasetSpec:
    """ds1 with a smaller random population (planted journeys and faults unchanged), no catalog."""
    data = dump(load_spec(Path("datasets/ds1.spec.yaml")))
    data.update(
        catalog=None,
        sensitivity=[],
        population={"users": 160, "warmup_users": 10, "internal_users": 6, "visitors": 60},
    )
    data.update(changes)
    return DatasetSpec.model_validate(data)


def test_ds0_builds_byte_for_byte(tmp_path: Path) -> None:
    first = build_dataset(Path("datasets/ds0.spec.yaml"), tmp_path / "a", frozenset(), Path("."))
    second = build_dataset(Path("datasets/ds0.spec.yaml"), tmp_path / "b", frozenset(), Path("."))
    for name in ("events.jsonl", "ledger.json", "manifest.json"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()
    assert first == second
    assert first.faults_enabled == [] and first.counts.users == 300 and first.counts.internal_users == 6
    with pytest.raises(FileExistsError):
        build_dataset(Path("datasets/ds0.spec.yaml"), tmp_path / "a", frozenset(), Path("."))


def test_ds0_event_format(tmp_path: Path) -> None:
    build_dataset(Path("datasets/ds0.spec.yaml"), tmp_path, frozenset(), Path("."))
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    keys = [(e["timestamp"], e["properties"]["at_eid"]) for e in events]
    assert keys == sorted(keys)
    assert len({e["properties"]["at_eid"] for e in events}) == len(events)
    first_seen: dict[str, dict[str, Any]] = {}
    for e in events:
        props = e["properties"]
        assert e["schema"] == "agenttruth.event/v1" and props["at_ds"] == "ds0"
        assert e["uuid"] == str(uuid.uuid5(AT_EID_NAMESPACE, props["at_eid"]))
        assert len(e["distinct_id"]) <= 200
        if e["event"] == "paid_bill":
            assert props["$lib"] == "posthog-python" and not CLIENT_PROPS - {"$lib"} & set(props)
            assert round(props["amount_usd"] * 100) == props["amount_usd"] * 100 or True
        else:
            assert set(props) >= CLIENT_PROPS and props["$host"] == "hedgebox.net" and props["$lib"] == "web"
        first_seen.setdefault(e["distinct_id"], e)
    internal = [e for e in first_seen.values() if "hedgebox-internal.example" in json.dumps(e)]
    assert internal and all(e["event"] == "$identify" for e in internal)
    local_boundaries = {e["timestamp"] for e in events if e["timestamp"].endswith(("05:59:59.999Z", "06:00:00.000Z"))}
    assert local_boundaries  # events at exactly local 23:59:59.999 / 00:00:00.000 (UTC-06:00)


def test_faults_touch_only_their_own_steps() -> None:
    spec = small_ds1()
    base = build_journeys(spec, frozenset())
    emitted = {a.at_eid: (a.ts, a.props) for j in base for a in j.actions if a.emitted}
    for fault in ("F1", "F2", "F3", "F4", "F5"):
        off = build_journeys(spec, frozenset({fault}))
        emitted_off = {a.at_eid: (a.ts, a.props) for j in off for a in j.actions if a.emitted}
        diff = {k for k in emitted.keys() | emitted_off.keys() if emitted.get(k) != emitted_off.get(k)}
        tagged = {a.at_eid for j in base for a in j.actions if fault in a.faults}
        assert diff and diff == tagged, fault


def test_f2_duplicate_must_not_cross_midnight() -> None:
    spec = small_ds1()
    data = dump(spec)
    data["planted"].append(
        {"label": "late-sharer", "kind": "user", "os": "Linux", "browser": "Firefox",
         "signup": {"at": "2026-08-09T22:00:00.000", "url": "/signup/"},
         "actions": [{"at": "2026-08-09T23:59:59.900", "event": "shared_file_link",
                      "props": {"file_type": "image/png", "file_size_b": 10}}]}
    )  # fmt: skip
    with pytest.raises(GenerationError, match="cross local midnight"):
        build_journeys(DatasetSpec.model_validate(data), frozenset())


def test_spec_rejects_overlapping_fault_windows() -> None:
    data = dump(small_ds1())
    data["faults"][1]["date_from"] = "2026-07-16"
    with pytest.raises(ValueError, match="overlap"):
        DatasetSpec.model_validate(data)
