# AGENTS.md — standing instructions for coding agents in this repository

You are implementing AgentTruth, sprint by sprint, from `prompts/K<n>.md`. These rules apply to every sprint and every session. If a sprint prompt and this file disagree, stop and report BLOCKED.

## Source of truth

1. `docs/CONTRACT.md` is normative. Read the sections your sprint prompt names before writing code, and re-read the relevant section before every decision.
2. `docs/adr/` explains why. Do not re-litigate an ADR; if reality contradicts it, report BLOCKED.
3. `docs/RESEARCH.md` holds the facts and their sources. A FACT you find to be false in practice is a BLOCKED condition (contract §17.4).
4. You MUST NOT edit `docs/CONTRACT.md`, `docs/adr/*`, `docs/RESEARCH.md`, `docs/PREREQUISITES.md`, `prompts/*`, or this file. You MAY append to `docs/LIMITATIONS.md` under "Sprint additions".

## How a sprint ends

Exactly two ways:

- **DONE**: the sprint's gate (`make gate-K<n>`) passes including all negative controls, `make gates` passes, `reports/K<n>.yaml` (contract §18) and `evidence/K<n>/` are committed, CI is green.
- **BLOCKED**: one of the conditions in contract §17 occurred; you wrote the BLOCKED section of `reports/K<n>.yaml` with evidence, committed what is complete and correct, and stopped.

Never stop to ask whether to continue, to offer next steps, or to summarise mid-way. Never stop because the work is long.

## Never

- Relax, skip, `xfail`, or delete a test or gate criterion to get green. Never change a threshold, tolerance, lock hash, truth, catalog entry or negative control to make a check pass.
- Mock a live dependency in a check that the contract says is live. Without credentials, live commands fail closed.
- Hide a failure: no swallowed exceptions, no retries that turn a real error into success, no "best effort" fallbacks that are not pre-authorised in contract §17.
- Widen scope: no features, endpoints, tools, models, datasets or MCP categories beyond the contract. Good ideas go into the sprint report under `not_demonstrated` or as a suggestion, not into code.
- Write a secret anywhere: not in code, tests, fixtures, logs, artifacts, commit messages or reports. All run data goes through the evidence store's redacting writer.
- Use `random`, `numpy` randomness, `uuid4`, or the wall clock in dataset, oracle or grading paths.
- Let the gate checker import the code it judges (only `evidence` read APIs and the standard library).
- Touch PostHog `AT_EXAM` with any write, or use `AT_PH_ADMIN_KEY` or `AT_PH_WRITE_KEY` in an exam session.
- Perform an irreversible external action the sprint does not script (deleting a project, ingesting into a non-empty project, publishing an issue or release asset outside K7's scripted steps).

## Always

- Python: 3.14.6 via `uv`; `uv sync --frozen` in CI; Pydantic v2 models for every persisted structure, with JSON Schemas generated into `schemas/`; `ruff`, `ruff format`, `mypy --strict` clean; docstrings on public functions stating inputs, outputs and failure modes; explicit exceptions with actionable messages; complexity noted for anything over O(n log n) on event data.
- Tests first for logic with a known answer (oracle rules, grading precedence, comparators). Offline tests never open sockets.
- Every live command requires `AT_LIVE=1` and `--live`, records `target: live` and provider request ids.
- Evidence notes separate "the design says" from "the system did". Every report lists what was demonstrated and what was not.
- Keep commits small and conventional (`feat:`, `fix:`, `test:`, `docs:`, `chore:`). The last commit of a sprint adds its evidence and report.
- When something needs human action (credentials, billing, an irreversible step), state it as a precise checklist item in the report and stop with BLOCKED.

## Commands you can rely on (after K1)

- `make check` — lint, format check, types, offline tests.
- `make gate-K<n>` — independent checker for sprint n (offline, from evidence; K1 rebuilds).
- `make gates` — every gate whose evidence exists.
- `uv run agenttruth doctor` (after K2) — credential and project-settings diagnosis.

## Language

All repository content is in English.
