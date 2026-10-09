# ADR-0009 — Structured answers through a strict client tool

- Status: Accepted (K0)
- Contract: §9.1, D-09

## Context
Grading needs machine-readable answers. Free-text parsing is brittle and invites grader bias.

## Decision
The runner defines client tools `submit_answer` and `submit_roundtrip_report` with `strict: true` (S21). The first call ends the attempt. Local JSON-Schema validation, including bounds strict mode cannot express, is normative. If the API rejects `strict` alongside an `mcp_toolset` (I-06), the runner drops `strict` and records it; local validation still decides `P_INVALID_ANSWER`.

## Alternatives rejected
- **JSON in the final text.** Parsing failures would be attributed to the agent unfairly or fixed by heuristics.
- **`output_config.format` JSON output.** Constrains the final message, but the agentic loop with MCP tools is easier to end deterministically with a tool call.

## Consequences
- Answer format errors are rare and attributable (`P_INVALID_ANSWER`).
- The answer tool's description is part of the frozen system surface and hashed.
