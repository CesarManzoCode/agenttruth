# ADR-0013 — Content-addressed evidence store; SQLite index; Django

- Status: Accepted (K0)
- Contract: §13, D-13

## Context
Evidence must be immutable, hash-verifiable offline, committable, and browsable through the API and UI.

## Decision
Artifacts are content-addressed files with hashed manifests; gates read only these. The Django app uses SQLite as a rebuildable index over manifests. Large campaign stores ship as release assets with committed hashes.

## Alternatives rejected
- **PostgreSQL.** A server for a single-writer, read-mostly index; adds a compose service and CI service with no requirement served.
- **Database as source of truth.** Not hash-verifiable from git; harder to replay.

## Consequences
- `agenttruth index rebuild` must be deterministic; UI and API never hold data the evidence store lacks.
