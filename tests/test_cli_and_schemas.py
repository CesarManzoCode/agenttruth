"""CLI exit codes and outputs; JSON Schemas generated from the models are current and valid."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from agenttruth import schemagen
from agenttruth.cli import main
from agenttruth.evidence.models import Event, TrendsMetric, ValueMatch
from agenttruth.evidence.read import load_json, load_yaml


def test_cli_lint_export_build_verify(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["scenarios", "lint"]) == 0
    assert main(["scenarios", "export", "--format", "posthog-tasks-v2", "--out", str(tmp_path / "t.yaml")]) == 0
    assert main(["dataset", "build", "--spec", "ds0", "--out", str(tmp_path / "ds0")]) == 0
    assert main(["dataset", "build", "--spec", "ds0", "--out", str(tmp_path / "ds0")]) == 2  # not empty
    assert main(["evidence", "verify", str(tmp_path / "ds0")]) == 0
    assert main(["oracle", "compute", "--dataset", str(tmp_path / "ds0"), "--catalog", "scenarios/catalog.v1.yaml",
                 "--out", str(tmp_path / "t.json")]) == 2  # fmt: skip
    assert "catalog targets ds1" in capsys.readouterr().err


def test_schemas_are_current() -> None:
    assert schemagen.check(Path("schemas")) == []


def _json(obj: object) -> object:
    return json.loads(json.dumps(obj, default=str))


def test_committed_files_validate_against_their_schemas() -> None:
    pairs = [
        ("truths.v1.json", load_json(Path("truths/ds1.v1.json"))),
        ("catalog.v1.json", _json(load_yaml(Path("scenarios/catalog.v1.yaml")))),
        ("dataset-spec.v1.json", _json(load_yaml(Path("datasets/ds1.spec.yaml")))),
        ("rs-defaults.v1.json", load_json(Path("third_party/posthog/rs_defaults.json"))),
        ("dataset-lock.v1.json", load_json(Path("datasets/ds1.lock.json"))),
    ]
    for name, document in pairs:
        schema = load_json(Path("schemas") / name)
        jsonschema.validate(document, schema)


def test_models_are_strict() -> None:
    base = {"type": "trends", "event": "e", "math": "total", "date_from": "2026-07-01", "date_to": "2026-07-01",
            "filter_test_accounts": False}  # fmt: skip
    TrendsMetric.model_validate(base)
    with pytest.raises(ValidationError, match="extra"):
        TrendsMetric.model_validate({**base, "unexpected": 1})
    with pytest.raises(ValidationError, match="boolean"):
        TrendsMetric.model_validate({**base, "filter_test_accounts": "false"})
    with pytest.raises(ValidationError, match="math_property"):
        TrendsMetric.model_validate({**base, "math": "sum"})
    with pytest.raises(ValidationError, match="substring"):
        ValueMatch.model_validate({"rule": "contains"})
    with pytest.raises(ValidationError, match="timestamp"):
        Event.model_validate({"schema": "agenttruth.event/v1", "event": "e", "distinct_id": "d",
                              "timestamp": "2026-07-01T00:00:00Z", "uuid": "u", "properties": {}})  # fmt: skip
