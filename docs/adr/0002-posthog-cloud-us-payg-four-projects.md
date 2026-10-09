# ADR-0002 — PostHog Cloud US, pay-as-you-go with $0 limits, four projects

- Status: Accepted (K0)
- Contract: §4.2, §11, D-02

## Context
The subject is PostHog's *hosted* MCP (`mcp.posthog.com`), which proxies to PostHog Cloud (S01h). Event data cannot be deleted selectively (S07). The exam project must stay pristine while the round-trip project is written to, and results telemetry must not pollute either. The free plan allows one project; pay-as-you-go allows six, with per-product billing limits that can be $0 (S10).

## Decision
One PostHog Cloud **US** organization `AgentTruth` on pay-as-you-go, every usage-based product capped at $0, AI data processing disabled (ADR-0010). Four projects: `AT_DEV`, `AT_EXAM`, `AT_RT`, `AT_TEL` (§4.2). US because the hosted MCP and capture docs default to US hosts and the owner is in North America; region is recorded in `projects.yaml`.

## Alternatives rejected
- **Self-hosted PostHog.** The hosted MCP cannot target it; semantics and versions would differ from what PostHog users get; heavy to run.
- **Free plan, one project.** Exam and round-trip would share data; telemetry would land in the exam project; contamination unavoidable.
- **Several free organizations with one project each.** Works around plan limits in a way that could breach terms of service; rejected on principle.
- **EU region.** No technical reason to prefer it; US keeps defaults simple.

## Consequences
- The owner must add a payment method; expected cost is $0 because volumes (≈ 200k events total, historical import uncharged per S07) stay under free allowances and limits are $0. Owner verifies the billing page before K2 (PREREQUISITES).
- Two spare project slots remain for an `AT_EXAM` recreation if ever needed (§11 runbook).
