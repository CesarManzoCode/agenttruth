# ADR-0017 — MIT license

- Status: Accepted (K0)
- Contract: D-17

## Decision
AgentTruth is MIT-licensed, matching PostHog's MIT core (S01u) and the owner's free-and-open intent. Vendored PostHog files keep their MIT notice and source commit under `third_party/posthog/`.

## Alternatives rejected
- **Apache-2.0.** Fine, but MIT matches PostHog and is simpler for upstream reuse.
- **AGPL.** Discourages the reuse the project exists to enable.
