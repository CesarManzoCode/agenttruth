# ADR-0011 — Isolation by project; contamination preflight; cleanup ledger plus sweep

- Status: Accepted (K0)
- Contract: §11, D-11

## Context
Events cannot be selectively deleted (S07). Insights can be soft-deleted (`PATCH {deleted:true}`, S01l). Agents may create objects the harness did not anticipate (duplicates, renamed insights).

## Decision
- Never re-ingest into a non-empty project; DEV-first ingestion order; delete-and-recreate runbook for a contaminated exam project (owner-executed).
- `AT_RT` baseline = non-deleted insight/dashboard ids after setup. Preflight rejects any deviation. Every run records a cleanup ledger from tool results and sweeps the project afterwards; cleanup soft-deletes the union and verifies baseline equality. One round-trip run at a time.

## Alternatives rejected
- **Name-prefix-only cleanup.** Misses objects an agent named differently.
- **Hard delete via API.** Not offered for insights; soft delete is the supported path.
- **Fresh project per run.** Exhausts the six-project cap and re-ingestion cost.

## Consequences
- Cleanup exactness is a gate criterion (K4-C3), not a best effort.
