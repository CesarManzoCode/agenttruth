"""Gate checker framework (contract §13.3). Standard library plus the read side of ``evidence``.

A gate evaluates every criterion on reconstructed inputs, then runs each negative control: the
control's sabotage is applied to a copy of an input its target criterion reads, and *every*
criterion is evaluated again. Non-target criteria read their unmodified inputs; expensive
reconstruction steps (dataset builds, oracle runs, toolchain runs) are memoized by the digest of
their inputs within one gate run, so they are re-judged on the same observations. A control
behaves as expected when the set of failing criteria equals its declared ``expected_fail``.
The verdict is pass only if every criterion passes and every control behaves as expected.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from agenttruth.evidence.canonical import canonical_file_bytes, sha256_bytes
from agenttruth.evidence.models import GateReport
from agenttruth.evidence.read import artifact_relpath

__all__ = [
    "Control",
    "Criterion",
    "Ctx",
    "GateStepError",
    "Outcome",
    "run_gate",
]

JsonValue = object
_SECRET_ENV = ("ANTHROPIC_API_KEY",)


class GateStepError(RuntimeError):
    """A reconstruction step failed; the criterion that needed it fails with this message."""


@dataclass
class Outcome:
    """Result of evaluating one criterion once."""

    passed: bool
    observed: JsonValue
    expected: JsonValue
    evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Criterion:
    """A gate criterion: ``evaluate(ctx, sabotage)`` with ``sabotage=None`` for the real inputs."""

    id: str
    statement: str
    evaluate: Callable[[Ctx, str | None], Outcome]


@dataclass(frozen=True)
class Control:
    """A negative control: a sabotage of one criterion's input and the failures it must cause."""

    criterion_id: str
    sabotage: str
    expected_fail: tuple[str, ...]


class Ctx:
    """Shared state of one gate run: repository, scratch directory, memo, artifacts, environment."""

    def __init__(self, repo: Path, scratch: Path) -> None:
        self.repo = repo
        self.scratch = scratch
        self.python = sys.executable
        self.memo: dict[str, object] = {}
        self.artifacts: dict[str, tuple[bytes, str]] = {}
        self.collect_artifacts = True
        self._counter = 0

    def fresh_dir(self, name: str) -> Path:
        """Return a new, empty directory under the scratch directory."""
        self._counter += 1
        path = self.scratch / f"{self._counter:03d}-{name}"
        path.mkdir(parents=True)
        return path

    def env(self, **extra: str) -> dict[str, str]:
        """Subprocess environment: inherited, minus secrets, never writing bytecode."""
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in _SECRET_ENV and not (k.startswith("AT_PH_") and k.endswith("_KEY"))
        }
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env.update(extra)
        return env

    def run(
        self,
        argv: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout: int = 1800,
    ) -> subprocess.CompletedProcess[str]:
        """Run a fresh subprocess and capture its output (never raises on a non-zero exit)."""
        return subprocess.run(
            argv,
            cwd=cwd or self.repo,
            env=env or self.env(),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def cached[T](self, key: str, compute: Callable[[], T]) -> T:
        """Memoize ``compute`` under ``key`` for this gate run."""
        if key not in self.memo:
            self.memo[key] = compute()
        return self.memo[key]  # type: ignore[return-value]

    def artifact(self, data: bytes, ext: str) -> str:
        """Record ``data`` as an evidence artifact of the main run and return its SHA-256."""
        digest = sha256_bytes(data)
        if self.collect_artifacts:
            self.artifacts.setdefault(digest, (data, ext))
        return digest

    def json_artifact(self, obj: object) -> str:
        """Record ``obj`` as a canonical JSON artifact and return its SHA-256."""
        return self.artifact(canonical_file_bytes(obj), "json")


def _safe(criterion: Criterion, ctx: Ctx, sabotage: str | None) -> Outcome:
    try:
        return criterion.evaluate(ctx, sabotage)
    except Exception as exc:  # a criterion that cannot be evaluated fails; it never skips (§13.3)
        return Outcome(False, {"error": f"{type(exc).__name__}: {exc}"}, "criterion evaluable and satisfied")


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def _dirty(repo: Path, out: Path) -> bool:
    """True if the work tree differs from HEAD, ignoring the gate's own output directory."""
    try:
        out_rel = out.resolve().relative_to(repo.resolve()).as_posix().rstrip("/") + "/"
    except ValueError:
        out_rel = None
    lines = [line[3:] for line in _git(repo, "status", "--porcelain", "--untracked-files=all").splitlines()]
    return any(out_rel is None or not path.startswith(out_rel) for path in lines if path)


def _tool_version(argv: list[str], cwd: Path) -> str:
    try:
        result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False, timeout=60)
    except OSError:
        return "unavailable"
    return (result.stdout or result.stderr).strip().splitlines()[0] if result.returncode == 0 else "unavailable"


def run_gate(
    gate: str,
    contract_version: str,
    repo: Path,
    out: Path,
    criteria: list[Criterion],
    controls: list[Control],
    inputs: Callable[[Ctx], dict[str, str]],
    scratch: Path,
) -> GateReport:
    """Evaluate ``criteria`` and ``controls``, write ``out/gate-<gate>.json`` plus artifacts, return it.

    ``out`` must be absent or hold only a previous gate report and its ``sha256/`` store, which are
    replaced. Raises ``FileExistsError`` if ``out`` holds anything else.
    """
    ctx = Ctx(repo, scratch)
    results = []
    for criterion in criteria:
        print(f"[{gate}] {criterion.id} …", file=sys.stderr, flush=True)
        outcome = _safe(criterion, ctx, None)
        print(f"[{gate}] {criterion.id}: {'pass' if outcome.passed else 'FAIL'}", file=sys.stderr, flush=True)
        results.append(
            {
                "id": criterion.id,
                "statement": criterion.statement,
                "result": "pass" if outcome.passed else "fail",
                "observed": outcome.observed,
                "expected": outcome.expected,
                "evidence": sorted(set(outcome.evidence)),
            }
        )
    ctx.collect_artifacts = False
    control_results = []
    for control in controls:
        print(
            f"[{gate}] negative control on {control.criterion_id}: {control.sabotage}",
            file=sys.stderr,
            flush=True,
        )
        failing = []
        for criterion in criteria:
            sabotage = control.sabotage if criterion.id == control.criterion_id else None
            if not _safe(criterion, ctx, sabotage).passed:
                failing.append(criterion.id)
        behaved = failing == sorted(control.expected_fail)
        print(
            f"[{gate}]   failing {failing}: {'as expected' if behaved else 'UNEXPECTED'}",
            file=sys.stderr,
            flush=True,
        )
        control_results.append(
            {
                "criterion_id": control.criterion_id,
                "sabotage": control.sabotage,
                "expected_fail": sorted(control.expected_fail),
                "observed_failing_criteria": failing,
                "result": "pass" if behaved else "fail",
            }
        )
    verdict = all(r["result"] == "pass" for r in results) and all(c["result"] == "pass" for c in control_results)
    report = GateReport.model_validate(
        {
            "schema": "agenttruth.gate-report/v1",
            "gate": gate,
            "contract_version": contract_version,
            "git_sha": _git(repo, "rev-parse", "HEAD") or "unknown",
            "git_dirty": _dirty(repo, out),
            "environment": {
                "python": platform.python_version(),
                "platform": f"{platform.system()} {platform.machine()}",
                "node": _tool_version(["node", "--version"], repo),
                "uv": _tool_version(["uv", "--version"], repo),
            },
            "inputs": inputs(ctx),
            "criteria": results,
            "negative_controls": control_results,
            "verdict": "pass" if verdict else "fail",
        }
    )
    _write(out, gate, report, ctx.artifacts)
    return report


def _write(out: Path, gate: str, report: GateReport, artifacts: dict[str, tuple[bytes, str]]) -> None:
    if out.exists():
        unexpected = [p for p in out.iterdir() if p.name not in {f"gate-{gate}.json", "sha256"}]
        if unexpected:
            raise FileExistsError(f"{out} holds files other than a gate report: {unexpected}")
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for digest, (data, ext) in sorted(artifacts.items()):
        path = out / artifact_relpath(digest, ext)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    document = report.model_dump(mode="json", by_alias=True)
    (out / f"gate-{gate}.json").write_bytes(canonical_file_bytes(document))
