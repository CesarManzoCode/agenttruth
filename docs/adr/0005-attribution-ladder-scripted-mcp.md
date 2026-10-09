# ADR-0005 — Attribution ladder with a scripted MCP client layer

- Status: Accepted (K0)
- Contract: §4.3, K2, K4, K7, D-05

## Context
The brief's K2 separated generator, oracle, PostHog semantics and ingestion. That still leaves two causes conflated whenever an agent is wrong: the MCP layer (schemas, stripping, serialisation) and the model. Issue #108309 is precisely an MCP-layer problem that has only been "confirmed by reading code" (S02).

## Decision
Insert a deterministic layer between PostHog REST and the agent: a scripted MCP client (Python `mcp` SDK, Streamable HTTP, both modes) that issues the same queries and saves the agent would, without an LLM. Ladder: L0 ledger↔oracle (K1), L1 oracle↔REST (K2), L2 REST↔scripted MCP (K2 queries, K4 saves), L3 scripted MCP↔agent (K3/K4/K7). A failure is attributed to the agent only when L0–L2 agree for that scenario.

## Alternatives rejected
- **Agent-only round trip.** Cannot distinguish "the agent did not send the field" from "the tool dropped it".
- **Unit-testing PostHog's Zod schemas from source.** Tests PostHog's code at a commit, not the hosted service users hit.

## Consequences
- #108309 item 2 can be reproduced (or refuted) at zero LLM cost, with exact field-level evidence.
- K7 reductions replay agent tool calls through L2 to attribute failures.
