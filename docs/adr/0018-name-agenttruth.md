# ADR-0018 — Name: AgentTruth

- Status: Accepted (K0)
- Contract: D-18

## Decision
The final name is **AgentTruth** (Python package and CLI `agenttruth`). No package with that name exists on PyPI or npm and a web search shows no project with that exact name (S35).

## Alternatives rejected
- **HogTruth** and other PostHog-derived names: implies affiliation with PostHog.
- **Deferring the name to K7:** every artifact, schema id and URL embeds the name; renaming late is churn.

## Consequences
K7 re-runs the collision check before release; a collision found then is BLOCKED for the owner to decide.
