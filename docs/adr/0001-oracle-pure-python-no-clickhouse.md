# ADR-0001 — Oracle is a pure-Python reference evaluator; no ClickHouse

- Status: Accepted (K0, 2026-10-08)
- Contract: §6, D-01

## Context
The oracle must compute the truth for every scenario independently of PostHog, so that a disagreement between AgentTruth and PostHog means something. PostHog computes insights as HogQL compiled to ClickHouse SQL (S01o, S01p). The dataset is small (60k–90k events, §5.2). The brief lists ClickHouse as optional, admitted only if a sprint justifies it with evidence.

## Decision
The oracle is plain Python operating on the parsed `events.jsonl`, implementing the semantic rules SEM-01…SEM-15 explicitly, with no SQL engine. A second, structurally different derivation — the generator's construction ledger computed from user journeys — is the cross-check (K1-C2).

## Alternatives rejected
- **ClickHouse (local) running the same queries.** Shares PostHog's execution model and function semantics (e.g. approximate quantiles, DateTime timezone conversion), so it would agree with PostHog for the wrong reasons; adds a server to CI; no requirement it serves at this data size. "Big data is a plus" does not justify it: 70k rows is not big data and claiming otherwise would be inflation (RK-14).
- **DuckDB as a second oracle.** A third derivation adds cost without adding independence beyond the ledger.
- **Use PostHog's answer as truth.** Circular; makes semantic and ingestion defects invisible.

## Consequences
- Oracle semantics are spelled out and reviewable; every rule cites a source and changes only through the divergence registry.
- Approximate functions (median/quantile) are excluded from scenarios because Python exact results and ClickHouse approximations would diverge for reasons unrelated to agents.
- If a future dataset grows beyond memory, this ADR is revisited; v1 does not need it.
