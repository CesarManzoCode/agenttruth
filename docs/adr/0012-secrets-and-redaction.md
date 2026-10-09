# ADR-0012 — Redaction at the capture boundary

- Status: Accepted (K0)
- Contract: §12, D-12

## Context
Transcripts and tool payloads are needed for grading and are published as evidence in a public repo. They pass through code that also holds API keys.

## Decision
The evidence store's write API is the only disk path for run data and redacts before writing (exact secret values from the environment + token regexes). Headers and environment are never recorded. `audit secrets` scans store, repo and release assets; canary tests prove redaction and detection. Telemetry is an allowlist.

## Alternatives rejected
- **Redact at publication time.** Secrets would exist on disk and in local backups; a missed step leaks.
- **Do not keep transcripts.** Grading of trace-based classes and reductions would be impossible.

## Consequences
- Some debugging information (headers) is unavailable by design.
