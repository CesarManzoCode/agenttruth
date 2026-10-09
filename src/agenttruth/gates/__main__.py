"""``python -m agenttruth.gates K<n> [--out DIR]`` (also reached through ``agenttruth gate K<n>``).

Runs the independent checker of a sprint gate from the repository root and writes
``<out>/gate-K<n>.json`` with its evidence store. Exit 0 on verdict pass, 1 on fail, 2 on usage error.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from agenttruth import CONTRACT_VERSION
from agenttruth.gates import k1
from agenttruth.gates.framework import run_gate

_GATES = {"K1": k1}


def main(argv: list[str] | None = None) -> int:
    """Run the requested gate; returns the process exit code."""
    parser = argparse.ArgumentParser(prog="agenttruth gate")
    parser.add_argument("sprint")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    sprint = args.sprint.upper()
    gate = _GATES.get(sprint)
    if gate is None:
        print(f"gate {sprint}: no checker exists for this sprint yet", file=sys.stderr)
        return 2
    repo = Path.cwd()
    if not (repo / "docs" / "CONTRACT.md").exists() or not (repo / "datasets").is_dir():
        print("gate: run from the repository root", file=sys.stderr)
        return 2
    out = (args.out or repo / "build" / "gates" / sprint).resolve()
    # Delete the caches the reconstruction would otherwise read (compiled bytecode of the judged code).
    for cache in [*(repo / "src").rglob("__pycache__"), *(repo / "tests").rglob("__pycache__")]:
        shutil.rmtree(cache, ignore_errors=True)
    with tempfile.TemporaryDirectory(prefix=f"agenttruth-gate-{sprint}-") as scratch:
        report = run_gate(sprint, CONTRACT_VERSION, repo, out, gate.CRITERIA, gate.CONTROLS, gate.inputs, Path(scratch))
    for criterion in report.criteria:
        print(f"{criterion.id}: {criterion.result}")
    for control in report.negative_controls:
        print(
            f"negative control {control.criterion_id}: {control.result} (failing {control.observed_failing_criteria})"
        )
    print(f"gate {sprint}: verdict {report.verdict} -> {out / f'gate-{sprint}.json'}")
    return 0 if report.verdict == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
