"""``agenttruth oracle compute``: truths, signature values and probe values for a catalog (§6).

Inputs are a built dataset directory (``events.jsonl`` and ``manifest.json``; never ``ledger.json``)
and a catalog file. Output is ``truths/<dataset>.v<version>.json`` as canonical JSON.
"""

from __future__ import annotations

from pathlib import Path

from agenttruth import CONTRACT_VERSION
from agenttruth.dataset.reader import DatasetFiles, read_events, read_manifest
from agenttruth.evidence.canonical import canonical_file_bytes, sha256_bytes, sha256_file, sha256_json
from agenttruth.evidence.models import Catalog, EASpec, PCSpec, Truths, dump
from agenttruth.evidence.read import load_yaml
from agenttruth.oracle.detect import detect_cause
from agenttruth.oracle.frame import Frame, OracleError
from agenttruth.oracle.metrics import evaluate
from agenttruth.oracle.signatures import transform

__all__ = ["compute_truths", "write_truths"]


def compute_truths(dataset_dir: Path, catalog_path: Path) -> Truths:
    """Compute every EA/PC truth of ``catalog_path`` from the events in ``dataset_dir``.

    Raises :class:`OracleError` when a truth or declared signature is undefined, ``ValueError`` for
    invalid inputs, and ``FileNotFoundError`` for missing files. Complexity: O(n · m) for n events
    and m metric evaluations (truths, signatures, probes).
    """
    files = DatasetFiles(dataset_dir)
    manifest, manifest_sha = read_manifest(dataset_dir)
    catalog_bytes = catalog_path.read_bytes()
    catalog = Catalog.model_validate(load_yaml(catalog_path))
    if catalog.dataset != manifest.dataset_id:
        raise OracleError(f"catalog targets {catalog.dataset}, dataset is {manifest.dataset_id}")
    ids = [scenario.id for scenario in catalog.scenarios]
    if len(ids) != len(set(ids)):
        raise OracleError("catalog has duplicate scenario ids")
    timezone = manifest.project_config.timezone
    frame = Frame(read_events(files.events), timezone)
    records = []
    for scenario in catalog.scenarios:
        info = scenario.agenttruth
        if isinstance(info, EASpec):
            metric = info.metric
            value = evaluate(metric, frame, timezone)
            signatures = {}
            for signature in info.signatures:
                mistaken, zone = transform(metric, signature, timezone)
                signatures[signature] = evaluate(mistaken, frame, zone)
            flipped, zone = transform(metric, "SIG_TEST_ACCOUNTS", timezone)
            records.append(
                {
                    "scenario_id": scenario.id,
                    "kind": "exact_answer",
                    "answer_kind": info.answer_kind,
                    "value": value,
                    "signatures": signatures,
                    "probes": {},
                    "fault_overlaps": sorted(info.fault_overlaps),
                    "fault": None,
                    "value_match": None,
                    "test_accounts_flipped": evaluate(flipped, frame, zone),
                    "semantics": info.semantics,
                    "metric_sha256": sha256_json(dump(metric)),
                }
            )
        elif isinstance(info, PCSpec):
            cause = detect_cause(info.metric, frame, timezone)
            records.append(
                {
                    "scenario_id": scenario.id,
                    "kind": "planted_cause",
                    "answer_kind": "cause",
                    "value": dump(cause),
                    "signatures": {},
                    "probes": {probe.id: evaluate(probe.metric, frame, timezone) for probe in info.probes},
                    "fault_overlaps": [],
                    "fault": info.fault,
                    "value_match": dump(info.value_match),
                    "test_accounts_flipped": None,
                    "semantics": info.semantics,
                    "metric_sha256": sha256_json(dump(info.metric)),
                }
            )
    return Truths.model_validate(
        {
            "schema": "agenttruth.truths/v1",
            "contract_version": CONTRACT_VERSION,
            "dataset_id": manifest.dataset_id,
            "events_sha256": sha256_file(files.events),
            "manifest_sha256": manifest_sha,
            "catalog_sha256": sha256_bytes(catalog_bytes),
            "catalog_version": catalog.version,
            "project_config": dump(manifest.project_config),
            "truths": records,
        }
    )


def write_truths(truths: Truths, out: Path) -> str:
    """Write ``truths`` as a canonical JSON file and return its SHA-256."""
    data = canonical_file_bytes(dump(truths))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return sha256_bytes(data)
