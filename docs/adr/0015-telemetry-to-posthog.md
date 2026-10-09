# ADR-0015 — Results as allowlisted events in a dedicated PostHog project; dashboards as code

- Status: Accepted (K0)
- Contract: §12, K5, D-15

## Context
The brief asks for results to flow back into PostHog and be viewed in its dashboards. Results must not pollute the exam data and must not leak transcripts or secrets.

## Decision
`AT_TEL` receives `agenttruth attempt graded` and `agenttruth run completed` events with an allowlist of properties, person processing disabled. A dashboard spec in the repo is applied idempotently through REST with the admin key.

## Alternatives rejected
- **Send results to `AT_EXAM`.** Changes the exam dataset.
- **Send full transcripts.** Leak surface; unnecessary for dashboards.

## Consequences
- Dashboards are reproducible from code; the K5 gate checks idempotency.
