# AgentTruth — Research Log (K0)

This file is the source register for `docs/CONTRACT.md`. Every FACT in the contract cites one or more source IDs from this file. A source marked **NOT VERIFIED** could not be loaded or did not contain the claimed information; anything that depends on it is written as INFERENCE or as an open runtime check, never as FACT.

- Consulted: 2026-10-08 (America/Mexico_City), which is 2026-10-09 UTC for the repository checkout.
- Researcher: K0 planning session (Claude, on behalf of César Manzo).
- Repository pin for every `S01*` source: `PostHog/posthog` @ `e606d69fc4d9a7920ee4c2cbcd7cac62f915f58a` (master, committed 2026-10-09T03:55:16Z). Where a file's git blob id is given, it is the first 12 hex chars of `git hash-object` at that commit.

## How to re-verify

```bash
git clone --filter=blob:none --sparse https://github.com/PostHog/posthog.git
cd posthog && git checkout e606d69fc4d9a7920ee4c2cbcd7cac62f915f58a
git sparse-checkout set --no-cone products/posthog_ai services/mcp products/product_analytics \
  products/demo/backend/logic/products/hedgebox posthog/hogql_queries/utils '/posthog/schema.py'
git hash-object services/mcp/src/tools/generated/product_analytics.ts   # expect 79544054c4f1...
```

---

## S01 — PostHog repository (pinned commit above)

| ID | Path (blob) | What it demonstrates |
|---|---|---|
| S01a | `products/posthog_ai/eval_harness/README.md` (`abda86f174ef`) | PostHog's harness runs the real coding agent in a sandbox against a seeded Hedgebox project, one isolated org/team per case; run with `hogli evals`; Braintrust is the default and only engine and needs `BRAINTRUST_API_KEY`; flags `--agent-model`, `--agent-runtime {claude,codex}`, `--trials N`, `--fail-under`; `EXPORT_EVAL_RESULTS=1` writes `eval_results.jsonl`; suites declared as `eval_*` coroutines; experiment metadata records `agent_model`, `trials`, `git_sha`. Requires Rust toolchain, Docker or Modal sandboxes, Temporal, test DB. |
| S01b | `products/posthog_ai/evals/AGENTS.md` (`66e28fa9df3e`) | Hedgebox dataset reference: `HedgeboxMatrix(seed="b1ef3c66-…", days_past=120, days_future=30, n_clusters=500)`; "byte-for-byte reproducible" but "do not hard-code absolute counts; they can drift if the simulation code changes"; recommends relative date ranges and shape assertions; event taxonomy (`signed_up`, `uploaded_file`, `paid_bill`, …), plans strings, `filterTestAccounts=True` on seeded insights. |
| S01c | `products/posthog_ai/evals/product_analytics/scorers.py` (`e19b3615f64c`) | `INSIGHT_WRITE_TOOLS = {insight-create, insight-update, insight-partial-update, insight-destroy}`; `InsightShape` is deterministic and checks only `tool`, `display`, `compare`, `funnel_viz`, `breakdown`, `events`, `event_sequence`; "Filters, math, and date ranges are left to the schema-alignment judges"; judged scorers (`TrendsSchemaAlignment`, `*TimeRangeRelevancy`) are LLM classifiers. No scorer compares an answer to a known numeric truth. |
| S01d | `products/posthog_ai/evals/product_analytics/eval_trends.py` line 306 | `NoToolCall(forbidden=INSIGHT_WRITE_TOOLS, name="no_persistent_insight_save")` — analytics evals forbid saving. |
| S01e | `products/posthog_ai/eval_harness/scorers/contract.py` | Scorer contract surface: `eval_async(output, expected, **kwargs)`, `Score(name, score, metadata)`; currently a shim over Braintrust's `Score`/`Scorer`. |
| S01f | `products/posthog_ai/eval_harness/test/test_saved_object_scorers.py` | Saved-state scorers exist for flags (`products/feature_flags/evals/creation_scorers.py::CreatedFlagConfiguration`) and dashboards (`products/dashboards/evals/scorers.py::SavedDashboardContents`). None found for insight chart settings. |
| S01g | `services/mcp/evals/README.md` (`954ca5a622ef`), `benchmark/tasks.yaml` (`f822d33af8d4`), `benchmark/schema.ts` | `tasks.yaml` `version: 2`, 44 tasks; fields `id`, `category` (enum `TASK_CATEGORIES`), `intent`, `expected_tools`, `acceptable_tools`, `success_criteria`, optional `probe {tool,args,max_ms}`; "No script here scores `intent` or `success_criteria`"; probe runner refuses non-read-only probe tools; fixture flag `mcp-eval-retarget-me` built so a targeting edit "has unrelated configuration it can drop"; seeding goes through REST, "so the tools under test do not build their own starting state". |
| S01h | `services/mcp/README.md` | Hosted endpoint `https://mcp.posthog.com/mcp`; personal API key as `Authorization: Bearer phx_…`; `features=` and `tools=` URL filters (union); server modes `tools` and `cli` ("cli is the default for all clients"; Cursor auto-selects tools); pin via `?mode=` or `x-posthog-mcp-mode`; MCP server proxies to the PostHog instance and does not store analytics data. |
| S01i | `services/mcp/src/index.ts` (`373aa6014a77`) lines 162, 170–174, 234–253 | Accepted token prefixes `phx_` (personal API key) and `pha_` (OAuth access token); org/project pinning from `x-posthog-organization-id`/`organization_id` and `x-posthog-project-id`/`project_id` ("pin the MCP session … and remove the switch tools"); read-only from `x-posthog-read-only` or `?readonly=` (`true`/`1`); `?features`, `?tools`, `?region`, `?mode`. |
| S01j | `services/mcp/src/tools/toolDefinitions.ts` (`e0335ff038c5`) lines 284–341 | Catalog filter order: allowlist (features ∪ tools, `always_available` bypasses), read-only keeps only `readOnlyHint === true`, tools with `requires_ai_consent` hidden without AI consent, feature-flag gate, entitlement gate, org-scoped tools hidden for project-scoped tokens. |
| S01k | `services/mcp/schema/tool-definitions-all.json` | 1,091 tool definitions across 72 `feature` values (the vacancy brief's "74 categories" does not match this commit). In-scope tools, scopes and annotations: `query-trends`, `query-funnel`, `query-retention` (feature `insights`, RO, `query:read`); `execute-sql` (`sql`, RO, `query:read`); `read-data-schema` (`data_schema`, RO, `action:read`,`event_definition:read`,`property_definition:read`); `insight-get`, `insights-list` (RO, `insight:read`); `insight-query` (RO, `query:read`); `insight-create`, `insight-update`, `insight-delete` (RW, `insight:write`). None of these has `requires_ai_consent`. The 18 tools that do are LLM-analytics, replay-vision, notebook-widget and web-analytics suggestion tools. `insight-partial-update` (listed in S01c) does not exist in this catalog. |
| S01l | `services/mcp/src/tools/generated/product_analytics.ts` (`79544054c4f1`) | `insight-create` = `POST /api/projects/{id}/insights/`; `insight-update` = `PATCH …/insights/{id}/` sending `query` whole when present; `insight-delete` = `PATCH {deleted: true}`. `InsightQuery = z.union([AssistantInsightVizNode (source: record passthrough), AssistantDataVisualizationNode, AssistantBareInsightQuery (catchall), AssistantBareHogQLQuery (catchall)])`. `AssistantDataVisualizationChartSettings` is a plain `z.object` with 16 keys. |
| S01m | `services/mcp/src/api/generated.ts` `interface ChartSettings` | Full backend `ChartSettings` has 26 keys. Keys absent from the MCP schema (S01l): `chartStyle`, `heatmap`, `resultCustomizations`, `scatter`, `showAnnotations`, `showPieTotal`, `showXAxisBorder`, `showXAxisTicks`, `showYAxisBorder`, `yAxisAtZero`. `TableSettings.conditionalFormatting` is likewise absent from the MCP table schema. |
| S01n | `services/mcp/schema/exec-command-reference.md` | cli-mode syntax: `exec` tool with commands `help`, `learn`, `tools`, `search`, `info`, `schema`, `call [--json] [--confirm] <tool> [json]`; one command per request. |
| S01o | `posthog/hogql_queries/utils/query_date_range.py` (`99434a145d78`) | Dates resolved in the team timezone (`now_with_timezone`, `relative_date_parse(…, self._timezone_info)`); for intervals > hour (or calendar-day `date_to`), `date_to` is extended to `23:59:59.999999`; relative `date_from` truncated to start of day; buckets aligned with `team.week_start_day`; HogQL DateTime fields are wrapped in `toTimeZone(…, project tz)` so day boundaries follow the project timezone (comment at ~line 334). |
| S01p | `products/product_analytics/backend/hogql_queries/funnels/funnel_query_context.py` lines 115–120; `funnel_event_query.py` `_date_range_expr` | Funnel conversion window default `14` `day`; every step event is filtered to `date_from ≤ timestamp ≤ date_to` (not only the first step). |
| S01q | `posthog/schema.py` | `FunnelsFilter`: `funnelOrderType = ordered`, `funnelWindowInterval = 14`, `funnelWindowIntervalUnit = day`, `breakdownAttributionType = first_touch`. `RetentionFilter`: `period = Day`, `retentionType` default `None`, `cumulative = None`. |
| S01r | `products/product_analytics/backend/hogql_queries/retention/retention_query_runner.py` | `DEFAULT_TOTAL_INTERVALS = 7`; retention types `retention_first_time` (first occurrence matching filters) and `retention_first_ever_occurrence`; cumulative mode wraps the base query. |
| S01s | `posthog/models/team/team.py` | New teams get `test_account_filters = [{key:id, type:cohort, value:<internal test users cohort>, operator:not_in}]`; `timezone` default `"UTC"`; `week_start_day` nullable; `test_account_filters_default_checked` nullable; documented filter entry shapes (person, event, cohort). |
| S01t | `products/demo/backend/logic/products/hedgebox/taxonomy.py` | Exact Hedgebox event constants (`signed_up`, `logged_in`, `uploaded_file`, `downloaded_file`, `deleted_file`, `shared_file_link`, `upgraded_plan`, `downgraded_plan`, `invited_team_member`, `paid_bill`, …) and group type `account`. |
| S01u | `LICENSE`, `pyproject.toml`, `package.json`, `pnpm-workspace.yaml`, `frontend/package.json` | Repo is MIT Expat outside `ee/`; `services/mcp/package.json` declares MIT and `zod ^4.3.6`. PostHog's own pins: Python `==3.14.7`, `django~=5.2.0`, `pydantic~=2.12.0`, `pytest~=9.1.1`, `mcp~=1.26.0`, `anthropic==0.80.0`, `posthoganalytics==7.66.0`, Node `>=24 <25`, `pnpm@10.29.3`, TypeScript `6.0.3`, Vite `^8.1.0`, `@playwright/test 1.60.0`, React `^18.3.1`. |

## S02 — GitHub issue PostHog/posthog#108309

- URL: https://github.com/PostHog/posthog/issues/108309 — loaded as a public web page on 2026-10-08.
- Title "MCP: validated product analytics agent feedback (dashboards, insights, SQL)"; state **Open**; opened 2026-09-29 by `sampennington`; labels `MCP`, `feature/mcp`; no linked PRs shown.
- Content: a ranked backlog of agent-reported problems from the MCP agent-feedback channel, "checked by reading the code, not by reproducing it live". Item 2, "Chart settings are silently dropped on update (confirmed, high impact)": the assistant chart-settings schema is a strict subset of `ChartSettings`, so Zod strips `legendPosition`, `pie`, `heatmap`, `showAnnotations` without error; suggested fix: pass unknown keys or widen the schema, merge settings on PATCH, add a read-modify-write test. Item 9 (annotations on SQL insights) depends on item 2. Other items cover OAuth scopes in Cursor, tile colors, annotation targets, `execute-sql` placeholder IndexError, tooltip key collisions, headless rendering, minute-interval memory errors, heatmap cards.
- **Comments: NOT VERIFIED.** The public page showed none; the GitHub REST API was not reachable from this session (HTTP 403 from the session proxy).
- Cross-check against S01l/S01m at the pinned commit (10 days after the issue): `legendPosition` and `pie` are now in the MCP schema; `heatmap` and `showAnnotations` (plus eight other keys) are still absent. Combined with S25, the remaining silent-strip path is a static-code INFERENCE until K4 reproduces it at runtime.

## S03–S17 — PostHog documentation (posthog.com, consulted 2026-10-08)

| ID | URL | What it demonstrates | Gaps |
|---|---|---|---|
| S03 | https://posthog.com/docs/model-context-protocol | Server URL `https://mcp.posthog.com/mcp`; connecting and calling tools is free; some tools call LLMs internally and may be billed as PostHog AI spend; those require AI data processing enabled. | Does not list read-only/pinning params. |
| S04 | https://posthog.com/docs/model-context-protocol/faq.md | `x-posthog-read-only` or `readonly` (`true`/`1`, header wins); pinning headers/params `x-posthog-organization-id`/`organization_id`, `x-posthog-project-id`/`project_id` (removes switch tools); `x-posthog-mcp-mode`/`mode` (`cli`/`tools`); AI tools hidden when AI data processing is off; MCP Server API-key preset "scopes access to a specific project". | Individual preset scopes not listed. |
| S05 | https://posthog.com/docs/api/capture | `/i/v0/e/` and `/batch/` (POST, public, project token `api_key`); hosts `https://us.i.posthog.com`, `https://eu.i.posthog.com`; batch body < 20 MB; `historical_migration: true` for migrations; `distinct_id` ≤ 200 chars; invalid events still get `200`. | No rate limits, no latency figures, no handling of old timestamps. |
| S06 | https://posthog.com/docs/data/timestamps.md | Timestamp priority: with `sent_at` the server applies `timestamp = now + timestamp − sent_at`; `timestamp` without `sent_at` is used directly; computed timestamps > now + 23 h are replaced by capture time. | No past-age cutoff stated. |
| S07 | https://posthog.com/docs/migrate.md | Historical events "aren't charged standard ingestion fees"; timestamps should be ≥ 48 h before import; "no way to selectively delete event data"; doc says a paid plan "unlocks the necessary features"; test on a test project first. | No ordering rules, throughput, or time-to-queryable. |
| S08 | https://posthog.com/docs/api/queries | `POST /api/projects/:project_id/query/` with personal API key (Query Read); refresh modes incl. `force_blocking`; default 100 rows, ≤ 50k with explicit `LIMIT`; 10 s max execution; 2400/h, 240/min, 3 concurrent; per-project hourly read budget → HTTP 429 `api_queries_budget_exceeded`; `OFFSET` rejected for personal keys. | Budget size not stated. |
| S09 | https://posthog.com/docs/api | Private endpoint limits: analytics 240/min & 1200/h; CRUD 480/min & 4800/h; capture endpoints have no request-level rate limits; ~5,000 events/min per distinct ID loses strict ordering; over-quota capture returns `200` with `quota_limited`. | Personal-key scope/project restriction not documented here (see S01j, S04). |
| S10 | https://posthog.com/pricing | Free: 1M analytics events/month, no card, **1 project**, 1-year retention, 500 AI credits ($5)/month. Pay-as-you-go: **6 projects**, 7-year retention, per-product billing limits (FAQ suggests setting a $0 limit). | Per-event price beyond 1M not on this page. |
| S11 | https://posthog.com/docs/posthog-ai/pricing.md | Credits consumed "whenever PostHog performs intelligent work"; 100 credits = $1; 500 free/month; features pause when exhausted. | MCP not mentioned. |
| S12 | https://posthog.com/docs/product-analytics/funnels | Sequential/strict/any order definitions; repeated event in two steps requires two occurrences; first-ever vs first-matching occurrence; exclusion steps exclude the person; breakdown attribution first/last/all/specific step. | Conversion-window default not stated (see S01p/S01q). |
| S13 | https://posthog.com/docs/product-analytics/retention | Recurring vs first time (within range) vs first ever; Period 0 always 100%; "On" default vs "On or after" (cumulative); breakdown requires same value at start and return. | Edge cases of range/period boundaries not stated. |
| S14 | https://posthog.com/docs/data/persons | Identify merges prior anonymous events; merging two already-identified profiles is refused with an ingestion warning. | Override mechanics not described. |
| S15 | https://posthog.com/docs/how-posthog-works/queries | Person properties are copied onto events (values at event time); after a merge, earlier events show the surviving `person_id` and unique-person counts drop accordingly. | Mechanism not described. |
| S16 | https://posthog.com/docs/product-analytics/trends/filters | Test-account filtering lives in project settings. | **Insufficient**: defaults and aggregation definitions not stated; S01s used instead. |
| S17 | https://posthog.com/careers/ai-product-engineer | Hiring process ends in a paid "SuperDay" ("we'll pay you $1,000"); teams include "Context & MCP". | Vacancy requirements as quoted in the brief were not on this page; the brief is the source for R1–R6. |

## S18–S23 — Anthropic documentation (consulted 2026-10-08)

| ID | URL | What it demonstrates | Gaps |
|---|---|---|---|
| S18 | https://platform.claude.com/docs/en/agents-and-tools/mcp-connector | Beta `mcp-client-2025-11-20`; newer `mcp-client-2026-09-15` adds tool-list pinning (`tools` on `mcp_toolset`) and an `mcp_tool_listing` response block with `name`/`description`/`input_schema`; `mcp_servers[{type:"url", url (https only), name, authorization_token}]`; per-tool `enabled`/`defer_loading` via `default_config`/`configs`; only tool calls supported; Streamable HTTP and SSE; not ZDR-eligible; usable in Message Batches; blocks `mcp_tool_use`/`mcp_tool_result`. | No custom headers documented (→ PostHog options must go in the URL query string). Divergence between a pinned list and the live server is not specified. |
| S19 | https://platform.claude.com/docs/en/about-claude/pricing | Per-MTok: `claude-sonnet-5-5` $2 in / $10 out / $2.50 5-min cache write / $0.10 cache hit; `claude-opus-5-5` $4 / $20 / $5 / $0.20; `claude-haiku-5-5` (≤100K prompt) $0.10 / $0.50; Batch API −50%; tool definitions and tool blocks billed as tokens; no separate MCP-connector fee listed. | — |
| S20 | https://platform.claude.com/docs/en/models/sonnet-5/migration-guide | On Sonnet 5.5, non-default `temperature`/`top_p`/`top_k` return HTTP 400; effort `low|medium|high|xhigh|max`, default `high`, via `output_config.effort`; adaptive thinking default; `thinking.type` ∈ {`adaptive`, `between_tools`}; model id `claude-sonnet-5-5` has no date suffix. | Snapshot semantics of undated IDs not described. |
| S21 | https://platform.claude.com/docs/en/build-with-claude/structured-outputs | `strict: true` on tool definitions guarantees schema-valid tool inputs; supported on Sonnet 5.5 and Opus 5.5; schema limits (no min/max, `additionalProperties:false` required, ≤ 20 strict tools). | Combination with `mcp_toolset` not documented. |
| S22 | https://platform.claude.com/docs/en/api/rate-limits | Spend caps by tier (Start $500/month …); per-Workspace spend and rate limits (not on the default Workspace); Sonnet 5.5 Start tier 1,000 RPM, 2M ITPM, 400K OTPM; cached input does not count toward ITPM for most models. | — |
| S23 | https://platform.claude.com/docs/en/about-claude/models/overview | **NOT VERIFIED** — the fetched page rendered only 4.x models. Context window and max-output for 5.5 models are therefore not stated as FACT anywhere. | — |

## S24–S36 — Other sources

| ID | Source | What it demonstrates |
|---|---|---|
| S24 | https://modelcontextprotocol.io/specification/latest | Current spec version **2026-07-28**; JSON-RPC; tools/resources/prompts; "descriptions of tool behavior such as annotations should be considered untrusted, unless obtained from a trusted server". |
| S25 | https://zod.dev/api (objects) | Zod 4: "By default, unrecognized keys are stripped from the parsed result"; `z.strictObject` throws; `z.looseObject` passes through. |
| S26 | https://docs.github.com/en/billing/concepts/product-billing/github-actions | "GitHub Actions usage is free for … public repositories that use standard GitHub-hosted runners." |
| S27 | PyPI (`pip index versions`, `https://pypi.org/pypi/<pkg>/<ver>/json`), 2026-10-08 | Latest versions and classifiers used in CONTRACT §16 (Django 6.1.2 latest but DRF 3.18.3 classifies 5.2–6.1 while drf-spectacular 0.30.0 and pytest-django 4.14.0 classify only up to 6.0; Django 5.2.18 latest LTS patch). |
| S28 | npm registry (`npm view`), 2026-10-08 | React 19.3.0, TypeScript 7.0.2 latest (6.0.3 latest 6.x), Vite 8.3.4, `@vitejs/plugin-react` 6.1.2, `@playwright/test` 1.64.0, pnpm 12.10.1 latest (10.34.6 latest 10.x), `@modelcontextprotocol/sdk` 1.32.1. |
| S29 | `uv python list --all-versions` (uv 0.12.24) | CPython 3.14.6 is the newest 3.14 build uv 0.12.24 can install; 3.14.7 (PostHog's pin) is not in its catalog. |
| S30 | `git ls-remote --tags https://github.com/nodejs/node.git` | Latest Node 24 tag `v24.21.0`. |
| S31 | `anthropic` 1.12.1 wheel (PyPI) | Ships `BetaMCPToolListingBlock`, `BetaMCPToolUseBlock`, `BetaRequestMCPServerURLDefinitionParam{name,type,url,authorization_token,tool_configuration}`. |
| S32 | Docker Hub tag API | **NOT VERIFIED** — unreachable from this session. Base-image tags are resolved and digest-pinned in K6. |
| S33 | python.org, nodejs.org, endoflife.date | **NOT VERIFIED** — blocked by the session proxy; S29/S30 used instead. |
| S34 | GitHub REST API for issue #108309 | **NOT VERIFIED** — HTTP 403 in this session; comment thread unknown. |
| S35 | PyPI/npm/web search for "agenttruth" | No package named `agenttruth`/`agent-truth` on PyPI or npm; web search shows no project with this exact name (nearest: "agenttrust"). |
| S36 | Brief from César (`attachment.txt`) | Vacancy requirements R1–R6, method references (Thalyx-Kernel, SupaKernel, SupaDiff), prior repo findings. Treated as requirements, not as facts about PostHog. |

## Confirmation status of the brief's prior findings

| Prior finding | Status | Source |
|---|---|---|
| `eval_harness` with real agent, sandbox, seeders, scorers, Braintrust, `hogli evals` | CONFIRMED | S01a |
| Analytics/SQL scorers judge query shape; `InsightShape` deterministic; LLM judges for schema and time range; no numeric truth | CONFIRMED | S01c |
| Hedgebox seeded, byte-reproducible, advises against absolute counts | CONFIRMED | S01b |
| Insight evals forbid saving via `NoToolCall(forbidden=INSIGHT_WRITE_TOOLS)` | CONFIRMED | S01c, S01d |
| `SavedDashboardContents`, `CreatedFlagConfiguration`; no insight-settings scorer | CONFIRMED (none found in the checked-out eval trees) | S01f |
| `tasks.yaml` v2 with 44 tasks; intent/success_criteria unscored; `mcp-eval-retarget-me` | CONFIRMED | S01g |
| Issue #108309 documents silent chart-settings drops confirmed by code reading, not reproduced | CONFIRMED (and partially fixed at the pin: `legendPosition`, `pie` added; `heatmap`, `showAnnotations` still absent) | S02, S01l, S01m |
| "74 categories" in the MCP | CORRECTED: 72 `feature` values, 1,091 tools at the pin | S01k |
