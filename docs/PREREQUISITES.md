# AgentTruth — Prerequisites

Everything below must exist before running the sprint marked in the "Needed by" column. Costs were checked on 2026-10-08 against the sources cited (IDs from `docs/RESEARCH.md`). Nothing here is optional: a missing item makes the sprint stop with BLOCKED (contract §17, condition 3).

## Summary

| # | Item | Needed by | Cost | Source |
|---|---|---|---|---|
| 1 | GitHub account and an empty **public** repository `agenttruth` | K1 | $0 — Actions are free for public repos on standard runners | S26 |
| 2 | Local machine (Fedora) with git, make, Docker Engine + Compose v2, uv 0.12.24, Node 24.21.0, pnpm 10.34.6 | K1 (Docker: K6) | $0 | S27–S30 |
| 3 | Claude Code (to run the prompts) | K1 | your existing plan; not part of the project budget | — |
| 4 | PostHog Cloud **US** organization `AgentTruth` on **pay-as-you-go**, all billing limits $0, AI data processing **off** | K2 | $0 expected; a payment method is required to unlock > 1 project | S10, S07 |
| 5 | Four PostHog projects `AT_DEV`, `AT_EXAM`, `AT_RT`, `AT_TEL` | K2 | $0 (pay-as-you-go allows 6) | S10 |
| 6 | Three PostHog personal API keys (read, write, admin) with exact scopes and project limits | K2 | $0 | S01i, S01j, S04 |
| 7 | Anthropic Console Workspace `agenttruth` with a **$150/month** spend limit, **$150** of credits, and an API key in that Workspace | K3 | $150 maximum (planned ≤ $145: K3 $25, K4 $10, K5 $10, K7 $100) | S19, S22 |
| 8 | `.env.local` filled in (git-ignored) | K2 | $0 | — |

**Total cash out:** at most $150 (Anthropic). PostHog: $0 with the limits set as below. No domain, hosting or paid CI is needed: AgentTruth runs locally and in GitHub Actions; reviewers run it with Docker Compose.

## 1. GitHub

- Create an empty public repository (no README, no license, no .gitignore — K1 commits them).
- Local clone with push access over SSH or `gh auth login`.
- After K1: in repository settings, keep Actions enabled; no secrets are added to GitHub (live gates run locally, contract §14).

## 2. Local toolchain

- `git`, `make`, `curl`.
- Docker Engine with the Compose v2 plugin (`docker compose version` works). Podman is not supported.
- `uv` 0.12.24: `curl -LsSf https://astral.sh/uv/0.12.24/install.sh | sh`. K1 installs Python 3.14.6 through uv.
- Node 24.21.0 (any version manager) and pnpm 10.34.6 (`corepack enable && corepack prepare pnpm@10.34.6 --activate`).
- About 5 GB free disk (Python, Node modules, Playwright browsers, Docker images).

## 3. PostHog Cloud

### 3.1 Organization and plan
1. Sign up at `https://us.posthog.com` (US region). Name the organization `AgentTruth`.
2. Billing → subscribe to pay-as-you-go (add a card). This is what allows more than one project (free plan: 1; pay-as-you-go: 6 — S10).
3. Billing → set a **$0 billing limit on every usage-based product** listed (at least Product analytics, PostHog AI, Session replay, Feature flags, Surveys, Data warehouse, Error tracking, Logs, LLM analytics). Expected usage: ≈ 200k events total, far below the 1M/month free allowance (S10); historical imports are not charged ingestion fees (S07).
4. Organization settings → **AI data processing: disabled.** This hides every MCP tool that could bill PostHog AI (S04; contract ADR-0010).
5. Screenshot the billing page showing $0 projected and the limits; keep it for the K2 report.

### 3.2 Projects
Create four projects in that organization, named exactly:

| Name | Alias in AgentTruth |
|---|---|
| `AgentTruth DEV` | `AT_DEV` |
| `AgentTruth EXAM` | `AT_EXAM` |
| `AgentTruth RT` | `AT_RT` |
| `AgentTruth TEL` | `AT_TEL` |

For each: do **not** install any snippet, do **not** change settings (K2's `agenttruth posthog setup` applies timezone, week start and test-account filters and reads them back), do **not** create insights or dashboards. Record the numeric project id and the project token (`phc_…`, Project settings → General).

### 3.3 Personal API keys
Account settings → Personal API keys → create three keys. Use the scope list exactly; restrict each to the listed projects (the key creation dialog allows choosing projects). Copy each key once into `.env.local`.

| Key | Scopes | Projects |
|---|---|---|
| `AT_PH_READ_KEY` | `query:read`, `insight:read`, `event_definition:read`, `property_definition:read`, `action:read`, `project:read` | DEV, EXAM, RT |
| `AT_PH_WRITE_KEY` | the six above + `insight:write` | RT only |
| `AT_PH_ADMIN_KEY` | `project:read`, `project:write`, `query:read`, `insight:read`, `insight:write`, `dashboard:read`, `dashboard:write` | DEV, EXAM, RT, TEL |

The read key must not have any `:write` scope — K2 proves it by expecting a 403.

## 4. Anthropic

1. Anthropic Console → create a Workspace named `agenttruth` (spend limits cannot be set on the default Workspace — S22).
2. Workspace → Limits → monthly spend limit **$150**.
3. Billing → purchase **$150** of credits.
4. Create an API key inside the `agenttruth` Workspace → `ANTHROPIC_API_KEY`.

Why $150: model `claude-sonnet-5-5` costs $2 / $10 per million input / output tokens, $0.10 per million cached input (S19). K0 estimates $0.10–$0.40 per attempt (contract I-07); ≈ 400 planned attempts across K3–K7 plus the K5 cold-start sessions. Each sprint has a hard cap enforced by the runner (contract §14); K7 uses costs measured in K3/K4 and reduces N by a fixed rule if needed (ADR-0021).

## 5. `.env.local`

Create in the repository root after K1 (K1 adds `.env.local` to `.gitignore` and ships `.env.example`):

```dotenv
AT_LIVE=0                      # set to 1 only when running live commands
ANTHROPIC_API_KEY=
AT_PH_REGION=us
AT_PH_PROJECT_ID_DEV=
AT_PH_PROJECT_ID_EXAM=
AT_PH_PROJECT_ID_RT=
AT_PH_PROJECT_ID_TEL=
AT_PH_TOKEN_DEV=
AT_PH_TOKEN_EXAM=
AT_PH_TOKEN_RT=
AT_PH_TOKEN_TEL=
AT_PH_READ_KEY=
AT_PH_WRITE_KEY=
AT_PH_ADMIN_KEY=
```

## 6. Before each sprint

| Before | Check |
|---|---|
| K1 | Items 1–3. |
| K2 | Items 4–6 and 8; billing page shows $0 limits; AI data processing off. After K2 ships `doctor`, run `uv run agenttruth doctor` before every later sprint. |
| K3 | Item 7; Workspace spend so far ≤ $0 or known. |
| K4–K7 | `doctor` green; Anthropic spend to date + next sprint cap ≤ $150. |
