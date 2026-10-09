# ADR-0016 — No Braintrust; Score-shaped output

- Status: Accepted (K0)
- Contract: §9.5, D-16

## Context
PostHog's harness uses Braintrust as its engine and requires a Braintrust key (S01a); its scorer contract is a thin shim over Braintrust's `Score` (S01e).

## Decision
AgentTruth does not depend on Braintrust. Every grade record carries a `{name, score, metadata}` projection matching PostHog's scorer contract so results can be imported into Braintrust or wrapped as PostHog scorers later.

## Alternatives rejected
- **Braintrust as engine.** Third-party account and key for a public project; offline replay would depend on a hosted service.

## Consequences
- Upstreaming a numeric-truth scorer to PostHog remains possible without changing AgentTruth's data.
