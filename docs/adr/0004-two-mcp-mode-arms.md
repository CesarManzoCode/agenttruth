# ADR-0004 — Two arms: `cli` (headline) and `tools`

- Status: Accepted (K0)
- Contract: §4.5, K3, K7, D-04

## Context
PostHog's MCP serves either one `exec` tool wrapping all tools (`cli`) or one MCP tool per PostHog tool (`tools`). `cli` "is the default for all clients"; Cursor is auto-switched to `tools` (S01h). The two modes present different schemas and discovery flows to the model, so accuracy and failure modes can differ.

## Decision
Every agent-facing suite runs on both arms. `cli` is the headline arm because it is what most clients get by default. Tool calls are normalised to `(tool, input)` across modes (`exec` `call <tool> <json>` parsed per S01n) so grading is mode-agnostic.

## Alternatives rejected
- **Only `tools` mode.** Easiest to parse but not what users get; a reviewer would discount results.
- **Only `cli` mode.** Loses the comparison that tells PostHog whether a failure is mode-specific.

## Consequences
- Campaign cost doubles relative to one arm; mitigated by N=5 and ADR-0021's reduction rule.
- Mode differences are reported descriptively, never as significant.
