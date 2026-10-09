"""Evidence: canonical encoding, redaction, content-addressed store and verification (§12, §13)."""

from __future__ import annotations

import gzip
import hashlib
from pathlib import Path

import pytest

from agenttruth.evidence.canonical import (
    canonical_dumps,
    canonical_file_bytes,
    canonical_jsonl_bytes,
    sha256_json,
)
from agenttruth.evidence.read import artifact_relpath, referenced_hashes, verify_store
from agenttruth.evidence.redact import Redactor, secret_env_names
from agenttruth.evidence.store import EvidenceStore, ImmutableArtifactError


def test_canonical_encoding_is_sorted_compact_and_utf8() -> None:
    obj = {"b": 1, "a": [1.5, "é", None], "c": {"z": True, "y": 19.99}}
    assert canonical_dumps(obj) == '{"a":[1.5,"é",null],"b":1,"c":{"y":19.99,"z":true}}'
    assert canonical_file_bytes(obj).endswith(b"\n")
    assert canonical_jsonl_bytes([{"b": 1}, {"a": 2}]) == b'{"b":1}\n{"a":2}\n'
    assert sha256_json({"a": 1, "b": 2}) == sha256_json({"b": 2, "a": 1})
    with pytest.raises(ValueError, match="not JSON compliant"):
        canonical_dumps({"x": float("nan")})


def test_redaction_of_env_values_and_patterns() -> None:
    env = {
        "ANTHROPIC_API_KEY": "sk-ant-api03-CANARYsecretvalue",
        "AT_PH_READ_KEY": "phx_canaryReadKey1234",
        "HOME": "/root",
    }
    assert secret_env_names(env) == ["ANTHROPIC_API_KEY", "AT_PH_READ_KEY"]
    redactor = Redactor.from_environment(env)
    text = (
        "key sk-ant-api03-CANARYsecretvalue and phx_canaryReadKey1234; other pha_abcdefghijkl, phs_zyxwvutsrq; "
        '{"authorization_token": "tok-123456789"} Authorization: Bearer abc.def.ghi '
        "https://mcp.posthog.com/mcp?mode=cli&token=s3cr3tvalue&x=1"
    )
    result = redactor.redact(text)
    for secret in ("CANARYsecretvalue", "phx_canaryReadKey1234", "pha_abcdefghijkl", "phs_zyxwvutsrq",
                   "tok-123456789", "abc.def.ghi", "s3cr3tvalue"):  # fmt: skip
        assert secret not in result.text
    marker = hashlib.sha256(b"phx_canaryReadKey1234").hexdigest()[:8]
    assert f"[REDACTED:env:AT_PH_READ_KEY:{marker}]" in result.text
    assert result.count >= 7
    assert Redactor({"SHORT": "abc"}).redact("abc").text == "abc"  # values under 8 chars are ignored


def test_store_is_content_addressed_redacted_immutable_and_verifiable(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "ev", Redactor({"AT_PH_ADMIN_KEY": "phx_adminCANARY0001"}))
    digest = store.put_text("transcript with phx_adminCANARY0001 inside", "txt")
    path = tmp_path / "ev" / artifact_relpath(digest, "txt")
    assert path.exists() and "phx_adminCANARY0001" not in path.read_text()
    assert store.put_text("transcript with phx_adminCANARY0001 inside", "txt") == digest
    zipped = store.put_text("hello", "json", compress=True)
    zipped_path = tmp_path / "ev" / artifact_relpath(zipped, "json.gz")
    assert gzip.decompress(zipped_path.read_bytes()) == b"hello"
    assert store.put_text("hello", "json", compress=True) == zipped  # mtime=0: deterministic bytes
    manifest = tmp_path / "ev" / "gate-KX.json"
    manifest.write_text(canonical_dumps({"criteria": [{"evidence": [digest, zipped]}]}))
    assert referenced_hashes({"criteria": [{"evidence": [digest]}]}) == {digest}
    assert verify_store(tmp_path / "ev").ok
    path.write_text("tampered")
    with pytest.raises(ImmutableArtifactError):
        store.put_text("transcript with phx_adminCANARY0001 inside", "txt")
    result = verify_store(tmp_path / "ev")
    assert not result.ok and any("does not match" in p for p in result.problems)
    path.unlink()
    assert any("missing artifact" in p for p in verify_store(tmp_path / "ev").problems)
