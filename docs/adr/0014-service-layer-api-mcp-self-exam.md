# ADR-0014 — One service layer behind REST and MCP; self-exam with the examinee's own PostHog access

- Status: Accepted (K0)
- Contract: K5, D-14

## Context
Requirement R1 asks for an API an agent can drive, an MCP server and machine documentation. The brief asked that any agent can take the exam on itself. AgentTruth's PostHog credentials must never be shared.

## Decision
A `service` layer owns logic; Django REST Framework (with drf-spectacular OpenAPI 3.1) and a Python `mcp`-SDK server are thin adapters with a parity test. `llms.txt` is generated from the same docs source. Self-exam: AgentTruth serves questions and grades answers; the examinee answers using PostHog access its operator provides — either a project where the operator ingested the published dataset with `agenttruth posthog ingest`, or (for the K5 gate only) AgentTruth's exam configuration.

## Alternatives rejected
- **AgentTruth proxies PostHog for examinees.** Shares credentials; turns AgentTruth into a data gateway; out of scope.
- **Separate logic per adapter.** Divergence between REST and MCP behaviour.
- **FastAPI instead of Django.** Django is a stated desirable (R5) and is PostHog's stack.

## Consequences
- Truths are never exposed before `finish`; the API surface is small and testable.
