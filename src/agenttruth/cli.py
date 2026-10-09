"""``agenttruth`` command line (interfaces fixed by contract §14 K1).

- ``agenttruth dataset build --spec <ds> --out <dir> [--disable-fault F<n>]``
- ``agenttruth oracle compute --dataset <dir> --catalog <file> --out <file>``
- ``agenttruth scenarios lint [--catalog <file>] [--truths <file>] [--json-out <file>]``
- ``agenttruth scenarios export --format posthog-tasks-v2 --out <file> [--catalog <file>]``
- ``agenttruth evidence verify <path>``
- ``agenttruth gate K<n> [--out <dir>]``

Exit codes: 0 success, 1 a check failed, 2 invalid input or usage.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from pydantic import ValidationError

from agenttruth.dataset.build import BuildError, build_dataset, resolve_spec
from agenttruth.evidence.canonical import canonical_dumps
from agenttruth.evidence.models import dump
from agenttruth.evidence.read import verify_store
from agenttruth.oracle.compute import compute_truths, write_truths
from agenttruth.oracle.frame import OracleError
from agenttruth.scenarios.export import FORMATS, export_posthog_tasks_v2
from agenttruth.scenarios.lint import lint_catalog

__all__ = ["main"]

DEFAULT_CATALOG = Path("scenarios/catalog.v1.yaml")
DEFAULT_TRUTHS = Path("truths/ds1.v1.json")
DEFAULT_RS_DEFAULTS = Path("third_party/posthog/rs_defaults.json")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agenttruth", description="AgentTruth command line (contract §14).")
    sub = parser.add_subparsers(dest="group", required=True)

    dataset = sub.add_parser("dataset", help="build datasets").add_subparsers(dest="command", required=True)
    build = dataset.add_parser("build", help="build a dataset from its spec into an empty directory")
    build.add_argument("--spec", required=True, help="dataset id (e.g. ds1) or path to a spec YAML")
    build.add_argument("--out", required=True, type=Path)
    build.add_argument("--disable-fault", action="append", default=[], choices=["F1", "F2", "F3", "F4", "F5"])

    oracle = sub.add_parser("oracle", help="compute truths").add_subparsers(dest="command", required=True)
    compute = oracle.add_parser("compute", help="compute truths and signatures from a dataset's events")
    compute.add_argument("--dataset", required=True, type=Path)
    compute.add_argument("--catalog", required=True, type=Path)
    compute.add_argument("--out", required=True, type=Path)

    scenarios = sub.add_parser("scenarios", help="lint and export the catalog").add_subparsers(
        dest="command", required=True
    )
    lint = scenarios.add_parser("lint", help="lint the scenario catalog")
    lint.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    lint.add_argument("--truths", type=Path, default=None, help=f"default: {DEFAULT_TRUTHS} if it exists")
    lint.add_argument("--rs-defaults", type=Path, default=DEFAULT_RS_DEFAULTS)
    lint.add_argument("--json-out", type=Path, default=None)
    export = scenarios.add_parser("export", help="export the catalog to another format")
    export.add_argument("--format", required=True, choices=FORMATS)
    export.add_argument("--out", required=True, type=Path)
    export.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)

    evidence = sub.add_parser("evidence", help="evidence store").add_subparsers(dest="command", required=True)
    verify = evidence.add_parser("verify", help="re-hash an evidence directory and check references")
    verify.add_argument("path", type=Path)

    gate = sub.add_parser("gate", help="run the independent gate checker of a sprint")
    gate.add_argument("sprint", help="K1 … K7")
    gate.add_argument("--out", type=Path, default=None, help="directory for the gate report and its evidence")
    return parser


def _dataset_build(args: argparse.Namespace) -> int:
    root = Path.cwd()
    manifest = build_dataset(resolve_spec(args.spec, root), args.out, frozenset(args.disable_fault), root)
    print(canonical_dumps({"dataset_id": manifest.dataset_id, "counts": dump(manifest.counts), "out": str(args.out)}))
    return 0


def _oracle_compute(args: argparse.Namespace) -> int:
    truths = compute_truths(args.dataset, args.catalog)
    digest = write_truths(truths, args.out)
    print(canonical_dumps({"truths": len(truths.truths), "out": str(args.out), "sha256": digest}))
    return 0


def _scenarios_lint(args: argparse.Namespace) -> int:
    truths = args.truths if args.truths is not None else (DEFAULT_TRUTHS if DEFAULT_TRUTHS.exists() else None)
    report = lint_catalog(args.catalog, truths, args.rs_defaults)
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(canonical_dumps(dump(report)) + "\n", encoding="utf-8")
    for issue in report.issues:
        print(f"{issue.scenario_id or '-'}: [{issue.rule}] {issue.message}", file=sys.stderr)
    print(canonical_dumps({"ok": report.ok, "scenarios": report.scenarios, "issues": len(report.issues)}))
    return 0 if report.ok else 1


def _scenarios_export(args: argparse.Namespace) -> int:
    count = export_posthog_tasks_v2(args.catalog, args.out)
    print(canonical_dumps({"format": args.format, "tasks": count, "out": str(args.out)}))
    return 0


def _evidence_verify(args: argparse.Namespace) -> int:
    result = verify_store(args.path)
    for problem in result.problems:
        print(problem, file=sys.stderr)
    print(canonical_dumps({"ok": result.ok, "artifacts": result.artifacts, "manifests": result.manifests}))
    return 0 if result.ok else 1


def _gate(args: argparse.Namespace) -> int:
    # The gate checker runs in its own interpreter: nothing imports ``agenttruth.gates`` (§4.1).
    argv = [sys.executable, "-m", "agenttruth.gates", args.sprint]
    if args.out is not None:
        argv += ["--out", str(args.out)]
    sys.stdout.flush()
    os.execv(sys.executable, argv)  # replaces this process; returns only on failure


_HANDLERS = {
    ("dataset", "build"): _dataset_build,
    ("oracle", "compute"): _oracle_compute,
    ("scenarios", "lint"): _scenarios_lint,
    ("scenarios", "export"): _scenarios_export,
    ("evidence", "verify"): _evidence_verify,
}


def main(argv: list[str] | None = None) -> int:
    """Run the CLI; returns the process exit code."""
    args = _parser().parse_args(argv)
    if args.group == "gate":
        return _gate(args)
    handler = _HANDLERS[(args.group, args.command)]
    try:
        return handler(args)
    except (BuildError, OracleError, ValidationError, ValueError, FileExistsError, FileNotFoundError) as exc:
        print(f"agenttruth {args.group} {args.command}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
