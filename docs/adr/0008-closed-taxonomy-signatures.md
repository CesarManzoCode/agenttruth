# ADR-0008 — Closed error taxonomy; classification by oracle-computed signatures

- Status: Accepted (K0)
- Contract: §6.3, §8, D-08

## Context
A taxonomy is only useful if every wrong answer gets exactly one class, deterministically, without an LLM judge. LLM judges are what PostHog uses for filters and time ranges today (S01c); they are not reproducible.

## Decision
For each exact-answer scenario the oracle precomputes the value each specific mistake would produce ("signatures": previous period, exclusive end date, UTC instead of project time, unfiltered test accounts, total vs unique, default funnel window, funnel order, retention type/cumulative, confusable event, dropped filter). A wrong answer equal to a signature (within tolerance) gets that class; scenarios must keep signatures pairwise distinguishable (K1-C3). Trace-based classes (`E_EVENT_INVENTED`, `E_MISREPORTED_RESULT`, `T_TOOL_FAILURE`, `P_*`) and a fixed precedence (§8.3) make the set closed; `E_UNCLASSIFIED` and `I_HARNESS_ERROR` are the explicit catch-alls.

## Alternatives rejected
- **LLM judge for error types.** Non-deterministic; violates offline replay with identical hashes.
- **Classify from tool-call arguments only.** An agent can query correctly and still misreport, or query wrongly and get lucky; the answer value is what the user sees.

## Consequences
- Classification is exact and replayable; the fake-agent gate can prove it.
- Some real errors will be `E_UNCLASSIFIED`; their rate is reported and, if > 20% in K7, flagged in LIMITATIONS rather than patched mid-campaign.
