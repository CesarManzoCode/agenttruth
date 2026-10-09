"""Gate K1 (contract 1.0.1 §14 K1): the independent checker. Standard library + evidence read side.

The checker never imports the code it judges. It reconstructs everything it reads in fresh
subprocesses (``python -m agenttruth …``) inside an empty scratch directory, with caches disabled
(``PYTHONDONTWRITEBYTECODE``, ``ruff --no-cache``, a new mypy cache, ``pytest -p no:cacheprovider``),
then judges the outputs. Contract facts it checks against (fault table §5.2, window, timezone,
mutation kinds of K1-C5) are restated here as constants.
"""

from __future__ import annotations

import json
import re
import shutil
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from agenttruth.evidence.canonical import canonical_dumps, sha256_bytes, sha256_file
from agenttruth.evidence.read import load_json, load_yaml
from agenttruth.gates.framework import Control, Criterion, Ctx, GateStepError, Outcome
from agenttruth.gates.import_rules import check_tree

__all__ = ["CONTROLS", "CRITERIA", "inputs"]

TZ = ZoneInfo("America/Mexico_City")
WINDOW = (date(2026, 6, 1), date(2026, 8, 31))
INTERNAL = "hedgebox-internal.example"
DATASETS = ("ds0", "ds1")
LOCKED_FILES = ("events.jsonl", "ledger.json", "manifest.json")
CATALOG = "scenarios/catalog.v1.yaml"
TRUTHS = "truths/ds1.v1.json"
# Contract §5.2, planted faults (ids, windows and segments are normative).
FAULTS: dict[str, dict[str, str]] = {
    "F1": {"cause_type": "tracking_outage", "event": "uploaded_file", "date_from": "2026-07-15",
           "date_to": "2026-07-17", "property": "$os", "value": "Android"},
    "F2": {"cause_type": "duplicate_events", "event": "shared_file_link", "date_from": "2026-08-03",
           "date_to": "2026-08-09", "property": "$browser", "value": "Firefox"},
    "F3": {"cause_type": "identity_break", "event": "$identify", "date_from": "2026-06-22",
           "date_to": "2026-06-28", "property": "$current_url", "value": "/signup/mobile"},
    "F4": {"cause_type": "internal_traffic", "event": "$pageview", "date_from": "2026-07-27",
           "date_to": "2026-07-29", "property": "email", "value": INTERNAL},
    "F5": {"cause_type": "property_value_change", "event": "upgraded_plan", "date_from": "2026-08-17",
           "date_to": "2026-08-31", "property": "new_plan", "value": "pro"},
}  # fmt: skip
MUTATION_KINDS = (
    "drop_in_range_uploaded_file",
    "move_boundary_event_across_local_midnight",
    "change_internal_user_email_domain",
    "duplicate_signed_up",
    "remove_identify",
)
_AT_EID = re.compile(r'"at_eid":"([^"]+)"')


# --------------------------------------------------------------------------------------------------
# Reconstruction helpers (memoized by input digest)
# --------------------------------------------------------------------------------------------------


def _agenttruth(ctx: Ctx, *args: str, env: dict[str, str] | None = None) -> str:
    result = ctx.run([ctx.python, "-m", "agenttruth", *args], env=env)
    if result.returncode != 0:
        raise GateStepError(
            f"agenttruth {' '.join(args[:2])} exited {result.returncode}: {result.stderr.strip()[-600:]}"
        )
    return result.stdout


def _build(ctx: Ctx, spec: Path, disabled: tuple[str, ...] = (), *, fresh: str | None = None) -> Path:
    """Build ``spec`` with ``disabled`` faults into an empty directory (memoized unless ``fresh``)."""

    def go(hashseed: str = "0") -> Path:
        out = ctx.fresh_dir(f"build-{spec.stem}-{'-'.join(disabled) or 'all'}") / "dataset"
        args = ["dataset", "build", "--spec", str(spec), "--out", str(out)]
        for fault in disabled:
            args += ["--disable-fault", fault]
        _agenttruth(ctx, *args, env=ctx.env(PYTHONHASHSEED=hashseed))
        return out

    if fresh is not None:
        return go(fresh)
    key = f"build:{sha256_file(spec)}:{sha256_file(ctx.repo / CATALOG)}:{','.join(disabled)}"
    return ctx.cached(key, go)


def _oracle(ctx: Ctx, dataset: Path, catalog: Path) -> Path:
    """Run ``oracle compute`` on ``dataset`` with ``catalog`` (memoized by input digests)."""
    digests = [sha256_file(dataset / "events.jsonl"), sha256_file(dataset / "manifest.json"), sha256_file(catalog)]
    key = "oracle:" + ":".join(digests)

    def go() -> Path:
        out = ctx.fresh_dir("truths") / "truths.json"
        _agenttruth(ctx, "oracle", "compute", "--dataset", str(dataset), "--catalog", str(catalog), "--out", str(out))
        return out

    return ctx.cached(key, go)


def _copy_text(ctx: Ctx, source: Path, old: str, new: str, name: str) -> Path:
    """Copy ``source`` into a fresh directory with ``old`` replaced once by ``new``."""
    text = source.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise GateStepError(f"sabotage anchor not found exactly once in {source.name}: {old!r}")
    out = ctx.fresh_dir(name) / source.name
    out.write_text(text.replace(old, new), encoding="utf-8")
    return out


def _source_copy(ctx: Ctx, name: str) -> Path:
    """Copy the files git knows about (tracked and untracked-not-ignored) into a fresh directory."""
    listed = ctx.run(["git", "ls-files", "-co", "--exclude-standard", "-z"])
    if listed.returncode != 0:
        raise GateStepError(f"git ls-files failed: {listed.stderr.strip()}")
    root = ctx.fresh_dir(name) / "repo"
    for rel in sorted(filter(None, listed.stdout.split("\0"))):
        if rel.startswith(("evidence/", "build/")):
            continue
        source = ctx.repo / rel
        if source.is_file():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    return root


def _tail(text: str, lines: int = 40) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def _local_day(timestamp: str) -> date:
    moment = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    return moment.astimezone(TZ).date()


def _truth_map(path: Path) -> dict[str, dict[str, object]]:
    data = load_json(path)
    assert isinstance(data, dict)
    return {str(r["scenario_id"]): r for r in data["truths"]}


def _same_value(a: object, b: object, kind: object) -> bool:
    if kind == "amount" and isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return round(a * 100) == round(b * 100)
    return a == b


# --------------------------------------------------------------------------------------------------
# K1-C1 reproducible
# --------------------------------------------------------------------------------------------------


def c1(ctx: Ctx, sabotage: str | None) -> Outcome:
    builds = ctx.cached(
        "c1-builds",
        lambda: {
            ds: (
                _build(ctx, ctx.repo / "datasets" / f"{ds}.spec.yaml", fresh="1"),
                _build(ctx, ctx.repo / "datasets" / f"{ds}.spec.yaml", fresh="2"),
            )
            for ds in DATASETS
        },
    )
    builds = dict(builds)
    if sabotage is not None:
        corrupted = ctx.fresh_dir("nc-c1") / "dataset"
        shutil.copytree(builds["ds1"][1], corrupted)
        with (corrupted / "events.jsonl").open("ab") as handle:
            handle.write(b"\n")
        builds["ds1"] = (builds["ds1"][0], corrupted)
    observed: dict[str, object] = {}
    expected: dict[str, object] = {}
    evidence = []
    passed = True
    for ds, (a, b) in builds.items():
        lock = load_json(ctx.repo / "datasets" / f"{ds}.lock.json")
        assert isinstance(lock, dict)
        hashes_a = {f: sha256_file(a / f) for f in LOCKED_FILES}
        hashes_b = {f: sha256_file(b / f) for f in LOCKED_FILES}
        manifest = load_json(a / "manifest.json")
        assert isinstance(manifest, dict)
        consistent = all(manifest["files"][f]["sha256"] == hashes_a[f] for f in ("events.jsonl", "ledger.json"))
        passed &= hashes_a == hashes_b == lock["files"] and consistent
        observed[ds] = {
            "build_a_hashseed_1": hashes_a,
            "build_b_hashseed_2": hashes_b,
            "manifest_consistent": consistent,
        }
        expected[ds] = lock["files"]
        evidence.append(ctx.artifact((a / "manifest.json").read_bytes(), "json"))
        evidence.append(ctx.artifact((ctx.repo / "datasets" / f"{ds}.lock.json").read_bytes(), "json"))
    return Outcome(passed, observed, {"identical_builds_equal_to_lock": expected}, evidence)


# --------------------------------------------------------------------------------------------------
# K1-C2 ledger ≡ oracle
# --------------------------------------------------------------------------------------------------


def c2(ctx: Ctx, sabotage: str | None) -> Outcome:
    dataset = _build(ctx, ctx.repo / "datasets" / "ds1.spec.yaml")
    truths_path = _oracle(ctx, dataset, ctx.repo / CATALOG)
    ledger_path = dataset / "ledger.json"
    if sabotage is not None:
        ledger = load_json(ledger_path)
        assert isinstance(ledger, dict)
        ledger["scenario_values"]["ea-uploads-july-filtered"] += 1
        ledger_path = ctx.fresh_dir("nc-c2") / "ledger.json"
        ledger_path.write_text(canonical_dumps(ledger) + "\n", encoding="utf-8")
    ledger_values = load_json(ledger_path)
    assert isinstance(ledger_values, dict)
    ledger_map = ledger_values["scenario_values"]
    oracle_map = _truth_map(truths_path)
    rows = []
    for sid in sorted(set(ledger_map) | set(oracle_map)):
        record = oracle_map.get(sid, {})
        equal = (
            sid in ledger_map
            and sid in oracle_map
            and _same_value(ledger_map[sid], record["value"], record["answer_kind"])
        )
        rows.append({"scenario_id": sid, "ledger": ledger_map.get(sid), "oracle": record.get("value"), "equal": equal})
    committed = (ctx.repo / TRUTHS).read_bytes()
    reproduced = committed == truths_path.read_bytes()
    passed = bool(rows) and all(r["equal"] for r in rows) and reproduced
    evidence = [ctx.json_artifact(rows), ctx.artifact(truths_path.read_bytes(), "json")]
    observed = {
        "scenarios": len(rows),
        "equal": sum(1 for r in rows if r["equal"]),
        "different": [r["scenario_id"] for r in rows if not r["equal"]],
        "committed_truths_reproduced": reproduced,
        "truths_sha256": sha256_bytes(truths_path.read_bytes()),
    }
    expected = {
        "different": [],
        "committed_truths_reproduced": True,
        "truths_sha256": sha256_bytes(committed),
    }
    return Outcome(passed, observed, expected, evidence)


# --------------------------------------------------------------------------------------------------
# K1-C3 signatures distinct
# --------------------------------------------------------------------------------------------------


def _distinguishable(a: object, b: object, kind: object) -> bool:
    if kind == "amount":
        return isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(a - b) > 0.005
    if kind == "mapping" and isinstance(a, dict) and isinstance(b, dict):
        return set(a) != set(b) or any(a[k] != b[k] for k in a)
    return a != b


def c3(ctx: Ctx, sabotage: str | None) -> Outcome:
    catalog = ctx.repo / CATALOG
    if sabotage is not None:
        catalog = _copy_text(
            ctx,
            catalog,
            "signatures: [SIG_PERIOD_PREV, SIG_PERIOD_NEXT, SIG_PERIOD_EXTRA_DAY, SIG_TZ_UTC]",
            "signatures: [SIG_PERIOD_PREV, SIG_PERIOD_NEXT, SIG_PERIOD_EXTRA_DAY, SIG_TZ_UTC, SIG_TEST_ACCOUNTS]",
            "nc-c3",
        )
    dataset = _build(ctx, ctx.repo / "datasets" / "ds1.spec.yaml")
    truths = _truth_map(_oracle(ctx, dataset, catalog))
    declared_doc = load_yaml(catalog)
    assert isinstance(declared_doc, dict)
    declared = {
        s["id"]: list(s["agenttruth"]["signatures"])
        for s in declared_doc["scenarios"]
        if s["agenttruth"]["kind"] == "exact_answer"
    }
    problems = []
    summary = {}
    for sid, sigs in sorted(declared.items()):
        record = truths.get(sid)
        if record is None:
            problems.append(f"{sid}: no truth record")
            continue
        values = record["signatures"]
        assert isinstance(values, dict)
        if sorted(values) != sorted(sigs):
            problems.append(f"{sid}: computed signatures {sorted(values)} differ from declared {sorted(sigs)}")
        if len(sigs) < 3:
            problems.append(f"{sid}: declares {len(sigs)} signatures (minimum 3)")
        named = [("truth", record["value"]), *values.items()]
        for i, (name_a, va) in enumerate(named):
            for name_b, vb in named[i + 1 :]:
                if not _distinguishable(va, vb, record["answer_kind"]):
                    problems.append(f"{sid}: {name_a} and {name_b} are not distinguishable")
        summary[sid] = {"signatures": len(sigs), "answer_kind": record["answer_kind"]}
    evidence = [ctx.json_artifact({"scenarios": summary, "problems": problems})]
    observed = {
        "ea_scenarios": len(declared),
        "signatures": sum(len(s) for s in declared.values()),
        "problems": problems,
    }
    return Outcome(not problems and bool(declared), observed, {"problems": [], "min_signatures": 3}, evidence)


# --------------------------------------------------------------------------------------------------
# K1-C4 faults isolated
# --------------------------------------------------------------------------------------------------


def _index(path: Path) -> dict[str, str]:
    lines: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            match = _AT_EID.search(line)
            if match is None:
                raise GateStepError(f"{path}: line without at_eid")
            lines[match.group(1)] = line
    return lines


def _footprint(fault: str, with_fault: dict[str, str], without: dict[str, str]) -> tuple[list[str], list[date]]:
    """Problems with the event diff of disabling ``fault``, and the local dates the diff touches."""
    spec = FAULTS[fault]
    start, end = date.fromisoformat(spec["date_from"]), date.fromisoformat(spec["date_to"])
    added = [json.loads(with_fault[k]) for k in sorted(set(with_fault) - set(without))]
    removed = [json.loads(without[k]) for k in sorted(set(without) - set(with_fault))]
    changed = [
        (json.loads(with_fault[k]), json.loads(without[k]))
        for k in sorted(set(with_fault) & set(without))
        if with_fault[k] != without[k]
    ]
    problems: list[str] = []
    diff = added + removed + [a for a, _ in changed]
    days = [_local_day(e["timestamp"]) for e in diff]
    outside = sorted({d.isoformat() for d in days if not start <= d <= end})
    if outside:
        problems.append(f"diff touches days outside {start}..{end}: {outside}")
    if not diff or min(days) != start or max(days) != end:
        problems.append(f"diff does not span the whole window {start}..{end}")
    expect = {"F1": "removed", "F2": "added", "F3": "removed", "F4": "added", "F5": "changed"}[fault]
    sizes = {"added": len(added), "removed": len(removed), "changed": len(changed)}
    if any(n for kind, n in sizes.items() if kind != expect) or not sizes[expect]:
        problems.append(f"expected only {expect} events, got {sizes}")
    if fault == "F1":
        bad = [e for e in removed if e["event"] != spec["event"] or e["properties"].get("$os") != spec["value"]]
    elif fault == "F2":
        originals: dict[tuple[str, str], list[tuple[int, str]]] = {}
        for line in without.values():
            if f'"event":"{spec["event"]}"' in line:
                e = json.loads(line)
                props = {k: v for k, v in e["properties"].items() if k != "at_eid"}
                originals.setdefault((e["distinct_id"], canonical_dumps(props)), []).append(
                    (_ms(e["timestamp"]), e["timestamp"])
                )
        bad = []
        for e in added:
            props = {k: v for k, v in e["properties"].items() if k != "at_eid"}
            twins = originals.get((e["distinct_id"], canonical_dumps(props)), [])
            if (
                e["event"] != spec["event"]
                or props.get("$browser") != spec["value"]
                or not any(50 <= _ms(e["timestamp"]) - ts <= 400 for ts, _ in twins)
            ):
                bad.append(e)
    elif fault == "F3":
        bad = [
            e
            for e in removed
            if e["event"] != spec["event"] or spec["value"] not in str(e["properties"].get("$current_url", "")).lower()
        ]
    elif fault == "F4":
        internal_ids = {
            json.loads(line)["distinct_id"]
            for line in with_fault.values()
            if '"event":"$identify"' in line and INTERNAL in line
        }
        bad = [e for e in added if e["event"] != spec["event"] or e["distinct_id"] not in internal_ids]
        base: dict[tuple[str, date], int] = {}
        for line in without.values():
            if '"event":"$pageview"' in line:
                e = json.loads(line)
                day = _local_day(e["timestamp"])
                if e["distinct_id"] in internal_ids and start <= day <= end:
                    base[(e["distinct_id"], day)] = base.get((e["distinct_id"], day), 0) + 1
        extra: dict[tuple[str, date], int] = {}
        for e in added:
            key = (e["distinct_id"], _local_day(e["timestamp"]))
            extra[key] = extra.get(key, 0) + 1
        if any(extra.get(k, 0) != 29 * n for k, n in base.items()) or set(extra) - set(base):
            problems.append("F4 extras are not 29 per original internal page view (30x)")
    else:
        bad = []
        for a, b in changed:
            rest_a = {**a, "properties": {k: v for k, v in a["properties"].items() if k != "new_plan"}}
            rest_b = {**b, "properties": {k: v for k, v in b["properties"].items() if k != "new_plan"}}
            if (
                a["event"] != spec["event"]
                or a["properties"].get("new_plan") != spec["value"]
                or b["properties"].get("new_plan") != "personal/pro"
                or rest_a != rest_b
            ):
                bad.append(a)
    if bad:
        problems.append(
            f"{len(bad)} diff events outside the {fault} segment, e.g. {bad[0].get('properties', {}).get('at_eid')}"
        )
    return problems, days


def _ms(timestamp: str) -> int:
    moment = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    return (moment - datetime(1970, 1, 1, tzinfo=UTC)) // timedelta(milliseconds=1)


def c4(ctx: Ctx, sabotage: str | None) -> Outcome:
    spec = ctx.repo / "datasets" / "ds1.spec.yaml"
    if sabotage is not None:
        spec = _copy_text(
            ctx,
            spec,
            "date_from: 2026-07-15, date_to: 2026-07-17,",
            "date_from: 2026-07-15, date_to: 2026-07-18,",
            "nc-c4",
        )
    problems: list[str] = []
    spec_doc = load_yaml(spec)
    assert isinstance(spec_doc, dict)
    declared_faults = {f["id"]: f for f in spec_doc["faults"]}
    if sorted(declared_faults) != sorted(FAULTS):
        problems.append(f"spec faults {sorted(declared_faults)} differ from contract F1-F5")
    for fid, contract in FAULTS.items():
        declared = declared_faults.get(fid, {})
        mismatched = [k for k, v in contract.items() if str(declared.get(k)) != v]
        if mismatched:
            problems.append(f"{fid}: spec {mismatched} differ from contract §5.2")
    catalog = ctx.repo / CATALOG
    base = _build(ctx, spec)
    base_truths = _truth_map(_oracle(ctx, base, catalog))
    base_index = ctx.cached(f"index:{sha256_file(base / 'events.jsonl')}", lambda: _index(base / "events.jsonl"))
    per_fault: dict[str, object] = {}
    for fid in sorted(FAULTS):
        disabled = _build(ctx, spec, (fid,))
        truths = _truth_map(_oracle(ctx, disabled, catalog))
        key = f"footprint:{fid}:{sha256_file(base / 'events.jsonl')}:{sha256_file(disabled / 'events.jsonl')}"

        def footprint(fid: str = fid, disabled: Path = disabled) -> tuple[list[str], list[date]]:
            return _footprint(fid, base_index, _index(disabled / "events.jsonl"))

        fp_problems, days = ctx.cached(key, footprint)
        problems += [f"{fid}: {p}" for p in fp_problems]
        pc = [r for r in base_truths.values() if r["fault"] == fid]
        probe_changes: dict[str, object] = {}
        window = (date.fromisoformat(FAULTS[fid]["date_from"]), date.fromisoformat(FAULTS[fid]["date_to"]))
        for record in pc:
            probes = record["probes"]
            after_probes = truths[str(record["scenario_id"])]["probes"]
            assert isinstance(probes, dict)
            assert isinstance(after_probes, dict)
            for probe, value in probes.items():
                after = after_probes[probe]
                if value == after:
                    problems.append(f"{fid}: probe {probe} does not change")
                    continue
                if isinstance(value, dict) and isinstance(after, dict):
                    # A breakdown value absent from a result has a count of zero.
                    keys = sorted(k for k in set(value) | set(after) if value.get(k, 0) != after.get(k, 0))
                    dated = [date.fromisoformat(k[:10]) for k in keys if re.match(r"^\d{4}-\d{2}-\d{2}", k)]
                    if any(not window[0] <= d <= window[1] for d in dated):
                        problems.append(f"{fid}: probe {probe} changes outside the window")
                    probe_changes[probe] = keys
        if len(pc) != 1:
            problems.append(f"{fid}: expected exactly one planted-cause scenario, found {len(pc)}")
        changed = sorted(
            sid
            for sid, r in base_truths.items()
            if r["kind"] == "exact_answer" and not _same_value(r["value"], truths[sid]["value"], r["answer_kind"])
        )
        declared_overlaps = sorted(
            sid
            for sid, r in base_truths.items()
            if r["kind"] == "exact_answer" and fid in r["fault_overlaps"]  # type: ignore[operator]
        )
        if changed != declared_overlaps:
            problems.append(f"{fid}: EA truths changed {changed} but declared overlaps are {declared_overlaps}")
        per_fault[fid] = {
            "diff_days": sorted({d.isoformat() for d in days}),
            "diff_events": len(days),
            "probe_changes": probe_changes,
            "ea_changed": changed,
            "ea_declared": declared_overlaps,
        }
    evidence = [ctx.json_artifact(per_fault)]
    return Outcome(not problems, {"faults": per_fault, "problems": problems}, {"problems": []}, evidence)


# --------------------------------------------------------------------------------------------------
# K1-C5 oracle sensitivity
# --------------------------------------------------------------------------------------------------


def _apply_edits(source: Path, edits: list[dict[str, object]], target: Path) -> list[str]:
    """Apply mutation edits to ``source/events.jsonl`` into ``target``; return claim violations."""
    by_eid = {str(e["at_eid"]): e for e in edits}
    problems: list[str] = []
    seen: dict[str, dict[str, object]] = {}
    target.mkdir(parents=True)
    shutil.copy2(source / "manifest.json", target / "manifest.json")
    with (
        (source / "events.jsonl").open("r", encoding="utf-8") as src,
        (target / "events.jsonl").open("w", encoding="utf-8") as dst,
    ):
        for line in src:
            match = _AT_EID.search(line)
            edit = by_eid.get(match.group(1)) if match else None
            if edit is None:
                dst.write(line)
                continue
            event = json.loads(line)
            seen[str(edit["at_eid"])] = event
            if edit["op"] == "remove":
                continue
            if edit["op"] == "set_timestamp":
                event["timestamp"] = edit["timestamp"]
            elif edit["op"] == "set_property":
                node = event
                path = edit["path"]
                assert isinstance(path, list)
                for key in path[:-1]:
                    node = node[key]
                node[path[-1]] = edit["value"]
            dst.write(canonical_dumps(event) + "\n")
        for edit in edits:
            if edit["op"] == "insert":
                dst.write(canonical_dumps(edit["event"]) + "\n")
    for edit in edits:
        if edit["op"] != "insert" and str(edit["at_eid"]) not in seen:
            problems.append(f"edit target {edit['at_eid']} not found")
    return problems


def _check_claim(
    kind: str, edits: list[dict[str, object]], targets: dict[str, dict[str, object]], events: Path
) -> list[str]:
    """Verify that a mutation is what its kind claims (K1-C5 lists the five kinds)."""
    if len(edits) != 1:
        return [f"{kind}: expected one edit, got {len(edits)}"]
    edit = edits[0]
    target = targets.get(str(edit["at_eid"]))
    if kind == "duplicate_signed_up":
        event = edit["event"]
        assert isinstance(event, dict)
        twins = [
            json.loads(line)
            for line in events.open(encoding="utf-8")
            if '"event":"signed_up"' in line and f'"distinct_id":"{event["distinct_id"]}"' in line
        ]
        same = [
            t
            for t in twins
            if t["timestamp"] == event["timestamp"]
            and {k: v for k, v in t["properties"].items() if k != "at_eid"}
            == {k: v for k, v in event["properties"].items() if k != "at_eid"}
        ]
        ok = edit["op"] == "insert" and event["event"] == "signed_up" and len(same) == 1
        return [] if ok else [f"{kind}: inserted event does not duplicate exactly one signed_up"]
    if target is None:
        return [f"{kind}: target not found"]
    if kind == "drop_in_range_uploaded_file":
        ok = (
            edit["op"] == "remove"
            and target["event"] == "uploaded_file"
            and WINDOW[0] <= _local_day(str(target["timestamp"])) <= WINDOW[1]
        )
    elif kind == "move_boundary_event_across_local_midnight":
        ok = (
            edit["op"] == "set_timestamp"
            and abs(_ms(str(edit["timestamp"])) - _ms(str(target["timestamp"]))) == 1
            and _local_day(str(edit["timestamp"])) != _local_day(str(target["timestamp"]))
        )
    elif kind == "change_internal_user_email_domain":
        props = target["properties"]
        person = props.get("$set", {}) if isinstance(props, dict) else {}
        old = str(person.get("email", "")) if isinstance(person, dict) else ""
        ok = (
            edit["op"] == "set_property"
            and target["event"] == "$identify"
            and INTERNAL in old
            and INTERNAL not in str(edit["value"])
        )
    else:  # remove_identify
        ok = edit["op"] == "remove" and target["event"] == "$identify"
    return [] if ok else [f"{kind}: the edit is not what the kind claims"]


def c5(ctx: Ctx, sabotage: str | None) -> Outcome:
    dataset = _build(ctx, ctx.repo / "datasets" / "ds1.spec.yaml")
    catalog = ctx.repo / CATALOG
    base = _truth_map(_oracle(ctx, dataset, catalog))
    ledger = load_json(dataset / "ledger.json")
    assert isinstance(ledger, dict)
    mutations = ledger["sensitivity"]
    problems: list[str] = []
    kinds = sorted(str(m["kind"]) for m in mutations)
    if kinds != sorted(MUTATION_KINDS):
        problems.append(f"mutation kinds {kinds} differ from the K1-C5 list")
    summary = []
    for index, mutation in enumerate(mutations):
        edits = list(mutation["edits"])

        def mutate(edits: list[dict[str, object]] = edits, mid: str = str(mutation["id"])) -> tuple[Path, list[str]]:
            target = ctx.fresh_dir(f"c5-{mid}") / "dataset"
            claim = _apply_edits(dataset, edits, target)
            return target, claim

        mutated, apply_problems = ctx.cached(f"c5-mutate:{dataset}:{mutation['id']}", mutate)
        targets = {
            str(e["at_eid"]): json.loads(line)
            for e in edits
            for line in _grep(dataset / "events.jsonl", str(e["at_eid"]))
        }
        problems += apply_problems + _check_claim(str(mutation["kind"]), edits, targets, dataset / "events.jsonl")
        after_path = _oracle(ctx, mutated, catalog)
        after = _truth_map(after_path)
        if sabotage is not None and index == 0:
            after = {sid: {**r, "value": base[sid]["value"]} for sid, r in after.items()}  # oracle "ignores" it
        observed_changes = {
            sid: r["value"]
            for sid, r in sorted(after.items())
            if not _same_value(r["value"], base[sid]["value"], r["answer_kind"])
        }
        predicted = mutation["predicted_changes"]
        match = sorted(observed_changes) == sorted(predicted) and all(
            _same_value(observed_changes[s], predicted[s], base[s]["answer_kind"]) for s in predicted
        )
        if not predicted:
            problems.append(f"{mutation['id']}: predicts no change")
        if not match:
            problems.append(
                f"{mutation['id']}: observed changes {sorted(observed_changes)} "
                f"differ from predicted {sorted(predicted)}"
            )
        summary.append(
            {
                "id": mutation["id"],
                "kind": mutation["kind"],
                "description": mutation["description"],
                "predicted": predicted,
                "observed": observed_changes,
                "match": match,
            }
        )
    evidence = [ctx.json_artifact(summary)]
    return Outcome(not problems, {"mutations": summary, "problems": problems}, {"problems": []}, evidence)


def _grep(path: Path, at_eid: str) -> list[str]:
    needle = f'"at_eid":"{at_eid}"'
    with path.open("r", encoding="utf-8") as handle:
        return [line for line in handle if needle in line]


# --------------------------------------------------------------------------------------------------
# K1-C6 catalog
# --------------------------------------------------------------------------------------------------


def c6(ctx: Ctx, sabotage: str | None) -> Outcome:
    catalog = ctx.repo / CATALOG
    if sabotage is not None:
        catalog = _copy_text(ctx, catalog, "- id: ea-signups-day-0714\n", "- id: ea-uploads-july-filtered\n", "nc-c6")
    work = ctx.fresh_dir("c6")
    lint_json = work / "lint.json"
    lint = ctx.run(
        [ctx.python, "-m", "agenttruth", "scenarios", "lint", "--catalog", str(catalog), "--truths",
         str(ctx.repo / TRUTHS), "--json-out", str(lint_json)]
    )  # fmt: skip
    rs = ctx.run([ctx.python, "-m", "agenttruth.scenarios.rs_defaults", "--check"])
    tasks = work / "tasks.yaml"
    export = ctx.run(
        [ctx.python, "-m", "agenttruth", "scenarios", "export", "--format", "posthog-tasks-v2", "--catalog",
         str(catalog), "--out", str(tasks)]
    )  # fmt: skip
    validator_dir = ctx.repo / "third_party" / "posthog"
    if not (validator_dir / "node_modules" / ".bin" / "tsx").exists():
        raise GateStepError("third_party/posthog/node_modules is missing: run `make node-deps`")
    validate = ctx.run(["npx", "--no-install", "tsx", "validate-export.ts", str(tasks)], cwd=validator_dir)
    doc = load_yaml(catalog)
    assert isinstance(doc, dict)
    agent_tasks = sum(1 for s in doc["scenarios"] if s["agenttruth"]["kind"] != "roundtrip_scripted")
    try:
        validation = json.loads(validate.stdout.strip().splitlines()[-1]) if validate.returncode == 0 else {}
    except json.JSONDecodeError, IndexError:
        validation = {}
    lint_report = load_json(lint_json) if lint_json.exists() else {"ok": False, "issues": ["no report"]}
    assert isinstance(lint_report, dict)
    passed = (
        lint.returncode == 0
        and lint_report.get("ok") is True
        and rs.returncode == 0
        and export.returncode == 0
        and validate.returncode == 0
        and validation.get("ok") is True
        and validation.get("tasks") == agent_tasks
    )
    evidence = [ctx.json_artifact(lint_report)]
    if tasks.exists():
        evidence.append(ctx.artifact(tasks.read_bytes(), "yaml"))
    evidence.append(ctx.artifact((validate.stdout + validate.stderr).encode("utf-8"), "txt"))
    observed = {
        "lint_exit": lint.returncode,
        "lint_ok": lint_report.get("ok"),
        "lint_issues": lint_report.get("issues"),
        "scenarios": lint_report.get("scenarios"),
        "by_kind": lint_report.get("by_kind"),
        "rs_defaults_current": rs.returncode == 0,
        "export_exit": export.returncode,
        "schema_ts_validation": validation or _tail(validate.stderr, 10),
    }
    expected = {
        "lint_ok": True,
        "rs_defaults_current": True,
        "schema_ts_validation": {"ok": True, "tasks": agent_tasks},
    }
    return Outcome(passed, observed, expected, evidence)


# --------------------------------------------------------------------------------------------------
# K1-C7 quality and K1-C8 import rules
# --------------------------------------------------------------------------------------------------

_TYPE_ERROR = '\n\n_NEGATIVE_CONTROL_TYPE_ERROR: int = "not an int"\n'
_FORBIDDEN_IMPORT = 'from agenttruth.dataset.generate import GENERATOR_VERSION\n\n__all__ = ["GENERATOR_VERSION"]\n'


def _quality(ctx: Ctx, copy: Path) -> dict[str, object]:
    env = ctx.env(PYTHONPATH=str(copy / "src"))
    cache = ctx.fresh_dir("mypy-cache")
    junit = ctx.fresh_dir("junit") / "junit.xml"
    steps = {
        "ruff_check": [ctx.python, "-m", "ruff", "check", "--no-cache", "."],
        "ruff_format": [ctx.python, "-m", "ruff", "format", "--check", "--no-cache", "."],
        "mypy_strict": [ctx.python, "-m", "mypy", "--strict", "--cache-dir", str(cache), "src"],
        "pytest": [
            ctx.python,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-n",
            "4",
            f"--junitxml={junit}",
        ],
    }
    results: dict[str, object] = {}
    logs = []
    for name, argv in steps.items():
        run = ctx.run(argv, cwd=copy, env=env)
        results[name] = run.returncode
        logs.append(f"$ {' '.join(argv[2:])}\nexit {run.returncode}\n{_tail(run.stdout + run.stderr)}\n")
    tests = {"tests": 0, "failures": -1, "errors": -1, "skipped": -1, "socket_guard_passed": False}
    if junit.exists():
        suite = ET.parse(junit).getroot()
        suite = suite if suite.tag == "testsuite" else suite.find("testsuite")  # type: ignore[assignment]
        assert suite is not None
        tests = {k: int(suite.get(k, "0")) for k in ("tests", "failures", "errors", "skipped")}
        guard = [
            case
            for case in suite.iter("testcase")
            if case.get("name") == "test_offline_tests_cannot_open_sockets" and len(case) == 0
        ]
        tests["socket_guard_passed"] = len(guard) == 1
    results["pytest_summary"] = tests
    results["log"] = "\n".join(logs)
    return results


def c7(ctx: Ctx, sabotage: str | None) -> Outcome:
    def run(sabotaged: bool) -> dict[str, object]:
        copy = _source_copy(ctx, "c7-nc" if sabotaged else "c7")
        if sabotaged:
            with (copy / "src" / "agenttruth" / "evidence" / "canonical.py").open("a", encoding="utf-8") as handle:
                handle.write(_TYPE_ERROR)
        return _quality(ctx, copy)

    results = run(True) if sabotage is not None else ctx.cached("c7-clean", lambda: run(False))
    summary = results["pytest_summary"]
    assert isinstance(summary, dict)
    passed = (
        all(results[k] == 0 for k in ("ruff_check", "ruff_format", "mypy_strict", "pytest"))
        and summary["tests"] > 0
        and summary["failures"] == 0
        and summary["errors"] == 0
        and summary["skipped"] == 0
        and summary["socket_guard_passed"] is True
    )
    evidence = [ctx.artifact(str(results["log"]).encode("utf-8"), "txt")]
    observed = {k: v for k, v in results.items() if k != "log"}
    expected = {
        "ruff_check": 0,
        "ruff_format": 0,
        "mypy_strict": 0,
        "pytest": 0,
        "pytest_summary": {"failures": 0, "errors": 0, "skipped": 0, "socket_guard_passed": True},
    }
    return Outcome(passed, observed, expected, evidence)


def c8(ctx: Ctx, sabotage: str | None) -> Outcome:
    def run(sabotaged: bool) -> dict[str, object]:
        copy = _source_copy(ctx, "c8-nc" if sabotaged else "c8")
        if sabotaged:
            (copy / "src" / "agenttruth" / "oracle" / "_negative_control.py").write_text(_FORBIDDEN_IMPORT)
        violations = [f"{v.module}:{v.line} [{v.rule}] {v.detail}" for v in check_tree(copy / "src")]
        test = ctx.run(
            [ctx.python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_import_rules.py"],
            cwd=copy,
            env=ctx.env(PYTHONPATH=str(copy / "src")),
        )
        modules = sum(1 for _ in (copy / "src").rglob("*.py"))
        return {"modules": modules, "gate_ast_violations": violations, "pytest_import_rules": test.returncode,
                "log": _tail(test.stdout + test.stderr)}  # fmt: skip

    results = run(True) if sabotage is not None else ctx.cached("c8-clean", lambda: run(False))
    passed = not results["gate_ast_violations"] and results["pytest_import_rules"] == 0
    observed = {k: v for k, v in results.items() if k != "log"}
    evidence = [ctx.json_artifact(observed)]
    return Outcome(passed, observed, {"gate_ast_violations": [], "pytest_import_rules": 0}, evidence)


# --------------------------------------------------------------------------------------------------
# Definitions
# --------------------------------------------------------------------------------------------------

CRITERIA = [
    Criterion(
        "K1-C1",
        "ds0 and ds1 built twice in two fresh processes into two empty directories yield identical events.jsonl, "
        "ledger.json, manifest.json SHA-256, equal to datasets/*.lock.json.",
        c1,
    ),
    Criterion(
        "K1-C2",
        "For every EA/PC scenario, ledger value == oracle value (exact for counts/mappings/rankings; amounts in "
        "integer cents); the committed truths file is the oracle's output.",
        c2,
    ),
    Criterion(
        "K1-C3",
        "For every EA scenario, truth and declared signature values are pairwise distinguishable under §9.2 "
        "tolerance; every EA scenario declares >= 3 signatures.",
        c3,
    ),
    Criterion(
        "K1-C4",
        "Every EA scenario declares the planted faults its truth overlaps. For each F1-F5, rebuilding with that "
        "fault disabled changes events only inside the fault's declared window and segment (§5.2), including its "
        "first and last day; changes every probe metric of the fault's PC scenario; and changes exactly the EA "
        "truths declared as overlapping that fault.",
        c4,
    ),
    Criterion(
        "K1-C5",
        "Each event-file mutation (drop one in-range uploaded_file; move one boundary event by 1 ms across local "
        "midnight; change one internal user's email domain; duplicate one signed_up; remove one $identify) changes "
        "exactly the predicted scenario truths by the predicted delta.",
        c5,
    ),
    Criterion(
        "K1-C6",
        "scenarios lint passes (ids unique, kebab-case, categories valid, every SEM/SIG id exists, RS values differ "
        "from defaults); export validates against the vendored PostHog schema.ts.",
        c6,
    ),
    Criterion(
        "K1-C7",
        "ruff check, ruff format --check, mypy --strict on src/, pytest -q all pass; no network used by offline tests.",
        c7,
    ),
    Criterion("K1-C8", "AST test proves the §4.1 import rules.", c8),
]

CONTROLS = [
    Control("K1-C1", "append a byte to one built file (ds1 build B events.jsonl)", ("K1-C1",)),
    Control("K1-C2", "perturb one ledger value (ea-uploads-july-filtered + 1) in a ledger copy", ("K1-C2",)),
    Control(
        "K1-C3",
        "add a colliding signature (SIG_TEST_ACCOUNTS on ea-signups-day-0714) in a catalog copy",
        ("K1-C3",),
    ),
    Control("K1-C4", "enlarge the F1 window by a day (date_to 2026-07-18) in a spec copy", ("K1-C4",)),
    Control("K1-C5", "make the oracle ignore mutation M1 by patching a copy of its truths", ("K1-C5",)),
    Control("K1-C6", "duplicate a scenario id (ea-uploads-july-filtered) in a catalog copy", ("K1-C6",)),
    Control(
        "K1-C7",
        "introduce a type error into a temporary copy of evidence/canonical.py and run the C7 toolchain on that copy",
        ("K1-C7",),
    ),
    Control(
        "K1-C8",
        "insert a forbidden import (oracle -> dataset.generate) in a temporary module of a source copy",
        ("K1-C8",),
    ),
]


def inputs(ctx: Ctx) -> dict[str, str]:
    """SHA-256 of every committed input the gate read, plus the dataset manifests it rebuilt."""
    files = [
        "datasets/ds0.spec.yaml",
        "datasets/ds1.spec.yaml",
        "datasets/ds0.lock.json",
        "datasets/ds1.lock.json",
        CATALOG,
        TRUTHS,
        "third_party/posthog/rs_defaults.json",
        "third_party/posthog/services/mcp/evals/benchmark/schema.ts",
        "third_party/posthog/package-lock.json",
    ]
    out = {name: sha256_file(ctx.repo / name) for name in files}
    builds = ctx.memo.get("c1-builds")
    if isinstance(builds, dict):
        for ds, (a, _) in sorted(builds.items()):
            out[f"rebuilt {ds} manifest.json"] = sha256_file(a / "manifest.json")
    return out
