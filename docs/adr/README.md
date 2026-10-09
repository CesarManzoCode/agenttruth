# Architecture Decision Records

Each ADR records one decision, the alternatives rejected and why. ADRs are immutable once accepted; a changed decision is a new ADR that supersedes the old one and amends `docs/CONTRACT.md` (§20).

| ADR | Decision |
|---|---|
| [0001](0001-oracle-pure-python-no-clickhouse.md) | Oracle in pure Python; no ClickHouse |
| [0002](0002-posthog-cloud-us-payg-four-projects.md) | PostHog Cloud US, pay-as-you-go with $0 limits, four projects |
| [0003](0003-agent-runtime-anthropic-mcp-connector.md) | Anthropic Messages API + MCP connector; pinned arm |
| [0004](0004-two-mcp-mode-arms.md) | Two arms: `cli` (headline) and `tools` |
| [0005](0005-attribution-ladder-scripted-mcp.md) | Attribution ladder with a scripted MCP layer |
| [0006](0006-dataset-design.md) | Dataset design |
| [0007](0007-scenario-format-tasks-yaml-superset.md) | Catalog as a superset of PostHog `tasks.yaml` v2 |
| [0008](0008-closed-taxonomy-signatures.md) | Closed taxonomy via signatures |
| [0009](0009-structured-answers-strict-client-tool.md) | Strict client tool for answers |
| [0010](0010-read-only-boundary-defense-in-depth.md) | Four-layer read-only boundary; AI processing off |
| [0011](0011-isolation-cleanup-contamination.md) | Isolation, cleanup, contamination |
| [0012](0012-secrets-and-redaction.md) | Redaction at the capture boundary |
| [0013](0013-evidence-store-sqlite-django.md) | Content-addressed evidence; SQLite index |
| [0014](0014-service-layer-api-mcp-self-exam.md) | One service layer; self-exam model |
| [0015](0015-telemetry-to-posthog.md) | Telemetry to a dedicated project |
| [0016](0016-no-braintrust-score-shaped-output.md) | No Braintrust; Score-shaped output |
| [0017](0017-license-mit.md) | MIT |
| [0018](0018-name-agenttruth.md) | Name |
| [0019](0019-english.md) | English |
| [0020](0020-frontend-react-ts-playwright.md) | React + TS + Playwright |
| [0021](0021-repetition-statistics-budget.md) | Repetition, statistics, budget |
| [0022](0022-k1-contract-corrections.md) | K1 contract corrections (contract 1.0.1) |
