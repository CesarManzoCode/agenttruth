# ADR-0010 — Read-only boundary in four independent layers; AI processing off

- Status: Accepted (K0)
- Contract: §10, D-10

## Context
MCP annotations are untrusted hints by spec (S24). PostHog's read-only mode filters by `readOnlyHint` (S01j), and the `cli` path's enforcement is inferred, not documented (I-05). An exam that writes to `AT_EXAM` would corrupt every later run.

## Decision
Four layers, each verified on its own: (1) a personal key without write scopes, (2) `readonly=true`, (3) a read-only tool allowlist plus runner-side abort on any RW tool in the listing, (4) project pinning to `AT_EXAM` with a state snapshot checked before and after runs. Additionally, the organization's AI data processing is disabled so tools that bill PostHog AI cannot be listed (S04).

## Alternatives rejected
- **Trust `readonly=true` alone.** Single point of failure resting on an annotation.
- **Rely on the round-trip project being separate.** Does not protect the exam project from an exam session.

## Consequences
- The read key must be created with exactly the listed scopes; `doctor` and K2-C5 probe it.
- If PostHog ever needs AI processing for an in-scope tool, K2-C6 fails and the owner decides.
