# ADR-0003 — Agent runtime: Anthropic Messages API + MCP connector; pinned arm configuration

- Status: Accepted (K0)
- Contract: §4.4, §9.4, K3, D-03

## Context
A real agent must drive the hosted MCP from a reproducible script, non-interactively, in CI-like conditions, with transcripts and cost accounting. Options were a Messages-API MCP connector, a local agent SDK (Claude Code / Agent SDK), PostHog's own sandbox harness, or Anthropic Managed Agents.

## Decision
Use the Anthropic Messages API with the MCP connector (beta `mcp-client-2026-09-15`, S18): the PostHog MCP URL carries `mode`, `readonly`, `project_id`, `tools` as query parameters (the connector documents no custom headers, F-16), authentication is a PostHog personal API key passed as `authorization_token` (accepted as `phx_`, F-13). The tool listing is captured once per run and pinned for all attempts (F-17), its hash recorded. Model `claude-sonnet-5-5`, `effort: high` (API default), adaptive thinking (default), `max_tokens 16000`, no sampling parameters (rejected by the API, F-18). Answers go through a strict client tool (ADR-0009).

## Alternatives rejected
- **Claude Code / Agent SDK locally.** Adds a local agent runtime, its own system prompt and tool-search behaviour, and version drift we do not control; harder to pin and to account for cost per attempt.
- **PostHog's `hogli evals` harness.** Requires Docker/Modal sandboxes, Temporal, a local PostHog test DB and Rust (S01a); it evaluates PostHog's own agent stack against a local server, not the hosted MCP.
- **Managed Agents.** More moving parts (hosted sessions, sandboxes) than needed for tool-calling evaluation.
- **Opus 5.5 as the subject.** About 2× cost per token (S19); budget would force N < 5. Model choice is a field of the arm, so another model can be added later as a new arm.
- **Multiple models in v1.** Doubles cost and scope without serving a vacancy requirement more strongly.

## Consequences
- Results speak about one pinned arm per mode; LIMITATIONS says so.
- The connector is not ZDR-eligible; only synthetic data flows through it.
- Undated model ids are recorded with the `model` echoed in each response; drift is visible, not prevented.
