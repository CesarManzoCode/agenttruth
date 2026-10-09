# ADR-0007 — Scenario catalog: YAML superset of PostHog `tasks.yaml` v2

- Status: Accepted (K0)
- Contract: §7, D-07

## Context
PostHog's MCP benchmark (`tasks.yaml` v2, S01g) already has a task vocabulary — `id`, `category`, `intent`, `expected_tools`, `acceptable_tools`, `success_criteria` — but nothing scores intent or success. Compatibility makes AgentTruth's work directly reusable by PostHog.

## Decision
`scenarios/catalog.v1.yaml` keeps PostHog's six fields with their meaning and puts AgentTruth-specific fields under `agenttruth:` (kind, answer kind, metric spec, signatures, semantics). `agenttruth scenarios export --format posthog-tasks-v2` emits a file validated against PostHog's vendored `schema.ts` (MIT, pinned commit).

## Alternatives rejected
- **Own format only.** Loses the bridge to PostHog's benchmark.
- **Writing into PostHog's file directly.** Their schema forbids extra fields and their categories differ in scope.

## Consequences
- AgentTruth scenarios can be proposed upstream as benchmark tasks with a numeric success check.
- The vendored schema is a snapshot; drift is a K7 re-check item.
