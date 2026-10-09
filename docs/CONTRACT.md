# AgentTruth — Contract

| | |
|---|---|
| Contract version | 1.0.0 (K0) |
| Status | Normative. Binding on every sprint K1–K7. |
| Owner | César Manzo (`CesarManzoCode`) |
| Implementer | Claude Code, one prompt per sprint (`prompts/K1.md` … `prompts/K7.md`) |
| Source register | `docs/RESEARCH.md` (IDs `S01a`…`S36`) |
| Decisions | `docs/adr/` (ADR-0001 … ADR-0021) |

The key words MUST, MUST NOT, SHOULD, SHOULD NOT and MAY are used as in RFC 2119. "The implementer" is Claude Code executing a sprint prompt. "The owner" is César.

This document fixes everything that matters for architecture and evidence. It deliberately does not fix internal module layout, file names inside packages, or helper structure; those belong to the implementer. Anything the implementer would need to decide that is *not* internal layout and is *not* answered here is a BLOCKED condition (§17), never a judgement call.

---

## 1. Technical verdict

**Build it, with five corrections to the brief.**

The gap is real and is confirmed at a pinned commit. PostHog's own agent evals judge the *shape* of the query an agent sends (`InsightShape`: tool, display, compare, breakdown, events) and delegate filters, math and date ranges to LLM judges; nothing compares an agent's answer to a number known to be true, and Hedgebox's own documentation tells eval authors not to rely on absolute counts (S01b, S01c). Saved-state scorers exist for feature flags and dashboards but not for insight settings, and the analytics evals forbid saving at all (S01c, S01d, S01f). The MCP benchmark's `success_criteria` are unscored (S01g). Meanwhile issue #108309, opened 2026-09-29, lists silent loss of chart settings on save as "confirmed, high impact" by code reading only (S02), and at the pinned commit ten MCP chart-setting keys are still outside a Zod schema that strips unknown keys by default (S01l, S01m, S25). So the two things AgentTruth measures — **numeric truth known by construction** and **saved-settings round trip** — are exactly the two things nobody measures today.

Corrections to the brief, each with an ADR:

1. **Attribution ladder, not one exam.** A wrong agent answer can come from the generator, the oracle, PostHog's semantics, ingestion, the MCP layer, or the model. The brief separated the first four (K2). This contract adds a deterministic **scripted MCP client** layer (no LLM) between PostHog's REST API and the agent, for queries (K2) and for round trips (K4). Only when generator ≡ oracle ≡ REST ≡ scripted MCP does a failure count against the agent. The same layer reproduces #108309 without spending a token. (ADR-0005)
2. **What is under test is "a pinned model driving PostHog's hosted MCP", not "PostHog's assistant".** PostHog AI's in-product assistant is not reachable through the MCP tools in scope; the MCP is a tool surface that any agent drives. Results are stated per *arm* = (model, model config, MCP mode, tool allowlist), and the default arm uses PostHog's default `cli` mode because that is what clients get unless they opt out (S01h). (ADR-0003, ADR-0004)
3. **Absolute time, fixed timezone, Hedgebox-compatible taxonomy.** Relative ranges ("last 30 days") depend on "now" and would make truth drift; every scenario uses absolute dates inside a window that is in the past at ingestion (≥ 48 h, S07). The project timezone is fixed to a non-UTC zone so timezone mistakes are observable. Event names and properties reuse PostHog's Hedgebox taxonomy (S01b, S01t) so PostHog engineers recognise it and scenarios port to their harness. (ADR-0006)
4. **Event data cannot be deleted selectively (S07), so isolation is by project, not by cleanup.** Four dedicated PostHog Cloud projects (exam, round-trip, dev, telemetry), which requires the pay-as-you-go plan (free plan allows one project, S10) with $0 billing limits. (ADR-0002, ADR-0011)
5. **Self-exam requires the examinee's own PostHog access.** "Any agent can take the exam on itself" is delivered as: AgentTruth publishes the dataset and questions and grades answers; the examinee answers through whatever PostHog access its operator provides (a project with the same dataset ingested via `agenttruth posthog ingest`). AgentTruth never hands out its own PostHog credentials. (ADR-0014)

Smaller corrections: the MCP has 72 feature categories and 1,091 tools at the pin, not 74 categories (S01k); ClickHouse is not used (ADR-0001); Braintrust is not used, but scores are emitted in PostHog's scorer shape (ADR-0016).

**What a finished AgentTruth will demonstrate:** for a fixed synthetic dataset with known answers, how often a pinned agent configuration produces the exact right number through PostHog's hosted MCP, why it is wrong when it is wrong (closed taxonomy), whether saved insight settings survive the MCP path, and where in the ladder each failure lives — every claim re-checkable with a command.

**What it will not demonstrate:** model-general accuracy (one model, two modes), statistically fine-grained comparisons (N = 5 per scenario per arm), anything about the 70 MCP feature categories outside analytics and insights, PostHog AI in-product, big-data scale, or behaviour of future PostHog versions beyond the recorded catalog hash.

---

## 2. Research findings

Each line is tagged **FACT** (stated by a cited primary source), **INFERENCE** (reasoned from facts, not directly stated; carries the check that will confirm it) or **DESIGN DECISION** (a choice; cites its ADR). IDs are stable and referenced elsewhere.

### 2.1 PostHog's existing evaluation surface

- **F-01 FACT** PostHog's harness runs a real agent in a sandbox against a seeded Hedgebox team per case, uses Braintrust as its only engine, pins `--agent-model`, supports `--trials N`, and is run with `hogli evals`; it needs Docker or Modal, Temporal, a test DB and the Rust toolchain. (S01a)
- **F-02 FACT** Product-analytics scorers grade query shape deterministically (`InsightShape`) and use LLM judges for schema alignment and time range; no scorer checks a numeric result. (S01c)
- **F-03 FACT** Hedgebox is byte-reproducible under a fixed seed, but its docs say absolute counts "can drift if the simulation code changes" and recommend relative ranges and shape assertions. (S01b)
- **F-04 FACT** Analytics evals forbid insight writes (`NoToolCall(forbidden=INSIGHT_WRITE_TOOLS)`); saved-state scorers exist for flags and dashboards only. (S01c, S01d, S01f)
- **F-05 FACT** `services/mcp/evals/benchmark/tasks.yaml` is version 2 with 44 tasks; `intent` and `success_criteria` are not scored by any script; probes must be read-only; a fixture flag exists to catch configuration lost on edit. (S01g)
- **F-06 FACT** The scorer contract surface is `eval_async(output, expected, **kwargs) → Score(name, score, metadata)`. (S01e)
- **I-01 INFERENCE** No public PostHog artifact measures exact numeric correctness of agent answers or persistence of insight settings through the MCP. *Check:* K7 re-scans the pinned trees and the latest master for scorers comparing to numeric truth or insight settings before publishing any claim of novelty; the claim is otherwise worded as "at commit e606d69".

### 2.2 Issue #108309

- **F-07 FACT** Issue #108309 is open (opened 2026-09-29), lists ten MCP problems validated by reading code, not by live reproduction; item 2 says chart settings are silently dropped because the assistant chart-settings schema is a strict subset of `ChartSettings`. (S02)
- **F-08 FACT** At the pin, the MCP `AssistantDataVisualizationChartSettings` is a plain `z.object` lacking `chartStyle`, `heatmap`, `resultCustomizations`, `scatter`, `showAnnotations`, `showPieTotal`, `showXAxisBorder`, `showXAxisTicks`, `showYAxisBorder`, `yAxisAtZero`; `legendPosition` and `pie` are present (added since the issue was filed). `TableSettings.conditionalFormatting` is also absent. (S01l, S01m)
- **F-09 FACT** Zod 4 `z.object` strips unknown keys without error. The MCP uses `zod ^4.3.6`. (S25, S01u)
- **F-10 FACT** `insight-update` sends `query` whole in a `PATCH`; there is no merge of nested settings in the MCP handler. (S01l)
- **I-02 INFERENCE** Creating or updating a SQL insight through `insight-create`/`insight-update` with any key from F-08 returns success while the stored insight lacks that key. *Check:* K4 scripted round trip (L2 layer, §4.3) in both MCP modes, recorded with REST readback. Until K4 records it, it is a hypothesis everywhere.
- **I-03 INFERENCE** `InsightVizNode.source` is typed as an open record in the MCP, so trends/funnel/retention settings are not stripped by the MCP layer; any loss there would come from the backend. *Check:* K4 scripted cases for trends/funnels/retention fields.
- **U-01 NOT VERIFIED** The issue's comment thread and any fix PRs after 2026-10-08 (S02, S34). K7 re-reads the issue before drafting any upstream text.

### 2.3 Hosted MCP configuration

- **F-11 FACT** Hosted endpoint `https://mcp.posthog.com/mcp`; region routing is automatic; modes `cli` (single `exec` tool, the default for all clients except an allow-list that includes Cursor) and `tools` (one MCP tool per PostHog tool), selectable with `?mode=` or `x-posthog-mcp-mode`. (S01h, S03, S04)
- **F-12 FACT** Read-only: `?readonly=true` or header `x-posthog-read-only`; filters the catalog to tools whose `readOnlyHint` is true. Project pinning: `?project_id=` or `x-posthog-project-id`, which also removes switch tools. Allowlists: `?features=` and `?tools=` combine as a union; `always_available` tools bypass the allowlist but not the read-only filter. (S01i, S01j, S04)
- **F-13 FACT** Accepted bearer tokens: personal API keys (`phx_`) and OAuth access tokens (`pha_`). A personal key therefore authenticates non-interactively in CI. Project-scoped tokens hide organization-level tools. (S01i, S01j, S01h)
- **F-14 FACT** In-scope tools and annotations at the pin: read-only `read-data-schema`, `query-trends`, `query-funnel`, `query-retention`, `execute-sql`, `insight-get`, `insights-list`, `insight-query`; read-write `insight-create`, `insight-update`, `insight-delete`. None requires AI consent. Tools that do (18) are hidden when the organization's AI data processing is off. (S01k, S01j, S04)
- **F-15 FACT** MCP tool annotations are hints and "should be considered untrusted" per the MCP specification (version 2026-07-28). (S24)
- **I-04 INFERENCE** None of the in-scope tools consumes PostHog AI credits (they are not `requires_ai_consent`, and PostHog says only tools that call LLMs internally bill AI spend). *Check:* with AI data processing **disabled** for the organization (DESIGN, ADR-0010) such tools cannot even be listed; K3 additionally asserts no listed tool name is in the pinned AI-consent list. Owner reads the AI usage line on the billing page after K7 and records it in the K7 report.
- **I-05 INFERENCE** In `cli` mode the `exec` dispatcher only executes tools from the filtered catalog, so `readonly` is enforced there too. *Check:* K2 read-only probe calls `exec` with `call insight-create {...}` under the read-only configuration and expects failure; K2 gate criterion K2-C5.

### 2.4 Running an agent against the hosted MCP

- **F-16 FACT** Anthropic's Messages API MCP connector takes `mcp_servers[{type:"url", url, name, authorization_token}]` plus an `mcp_toolset` per server; only HTTPS Streamable HTTP/SSE servers; only tool calls; responses contain `mcp_tool_use`/`mcp_tool_result` blocks; not ZDR-eligible. No custom headers are documented, so every PostHog option must be passed in the URL query string. (S18)
- **F-17 FACT** Beta `mcp-client-2026-09-15` adds tool-list pinning (a `tools` array of `{name, description, input_schema}` on the toolset, after which the API does not query the server for its tools) and the `mcp_tool_listing` response block. (S18, S31)
- **F-18 FACT** On Sonnet 5.5 non-default `temperature`/`top_p`/`top_k` are rejected; effort defaults to `high`; adaptive thinking is the default. Sampling is therefore not controllable; repetition is the only variance control. (S20)
- **F-19 FACT** Prices per million tokens: `claude-sonnet-5-5` $2 input, $10 output, $2.50 cache write (5 min), $0.10 cache hit; `claude-opus-5-5` $4/$20/$5/$0.20. Tool definitions and tool blocks are billed as tokens. (S19)
- **F-20 FACT** `strict: true` client tools guarantee schema-valid inputs on Sonnet 5.5 and Opus 5.5, with schema restrictions (no numeric/string bounds, `additionalProperties:false`). (S21)
- **I-06 INFERENCE** `strict: true` client tools can be combined with an `mcp_toolset` in one request. *Check:* first K3 live call; if rejected, the runner drops `strict` and keeps local schema validation, which is normative either way (§9.1). This is a pre-authorised fallback, not a BLOCKED condition.
- **I-07 INFERENCE** Cost per attempt for the default arm is about $0.10–$0.40 (≈ 25–40k tokens of tool definitions written to cache once, 6–10 model iterations, 3–6k output tokens). *Check:* K3 computes mean and p95 cost per attempt from recorded `usage`; K7 projects the campaign from K3/K4 actuals, not from this estimate.

### 2.5 Semantics the oracle must match

- **F-21 FACT** Query date ranges are resolved in the project timezone; for day-or-coarser intervals `date_to` extends to 23:59:59.999999 local; weekly buckets align to the team's `week_start_day`; HogQL DateTime fields are converted to the project timezone. (S01o)
- **F-22 FACT** Funnel defaults: order `ordered` (sequential), conversion window 14 days, breakdown attribution first touch. All step events must fall inside the query date range, not only step 1. Repeated events in two steps need two occurrences; strict order forbids intervening events. (S01p, S01q, S12)
- **F-23 FACT** Retention: start event defines cohort; Period 0 is always 100%; "recurring" vs "first time" (first occurrence within range) vs "first ever"; "on" (default) vs cumulative "on or after"; default period Day and 7 total intervals. (S13, S01q, S01r)
- **F-24 FACT** Identify merges the anonymous person into the identified one and earlier events then count under the surviving person; merging two already-identified persons is refused. Person properties are stored on events at event time in the default ("persons on events") mode. (S14, S15)
- **F-25 FACT** New projects default to timezone UTC and to a test-account filter that excludes an auto-created internal-users cohort. (S01s)
- **F-26 FACT** Capture: `/batch/` with project token; body < 20 MB; `historical_migration: true` for imports; with `sent_at` the server rewrites `timestamp`, without it uses `timestamp` directly; timestamps > now + 23 h are replaced; historical events are not charged ingestion fees; events cannot be selectively deleted; capture is not request-rate-limited; over-quota capture still returns 200 with `quota_limited`. (S05, S06, S07, S09)
- **F-27 FACT** Query API: `POST /api/projects/:id/query/`, `force_blocking` refresh, 100 rows default, 10 s execution cap, 240/min, 2400/h, 3 concurrent, an hourly read budget returning 429; `OFFSET` rejected for personal keys. (S08)
- **I-08 INFERENCE** Ingestion is complete when a forced-blocking HogQL count over the dataset window equals the generator's event count and the distinct-person count equals the oracle's, twice in a row ≥ 60 s apart. *Check:* K2-C2.

### 2.6 Plan, regions, toolchain

- **F-28 FACT** PostHog free plan: 1 project, 1M events/month, 1-year retention. Pay-as-you-go: 6 projects, 7-year retention, per-product billing limits that can be set to $0. (S10)
- **F-29 FACT** GitHub Actions is free for public repositories on standard runners. (S26)
- **F-30 FACT** Versions in §16 were read from PyPI/npm/uv/git on 2026-10-08 (S27–S30). Docker base-image tags could not be checked (S32).

### 2.7 Design decisions (index)

| ID | Decision | ADR |
|---|---|---|
| D-01 | Oracle is a pure-Python reference evaluator over the generated event file; no ClickHouse, no SQL engine | 0001 |
| D-02 | PostHog Cloud US, pay-as-you-go with $0 limits, four projects | 0002 |
| D-03 | Agent = Anthropic Messages API + MCP connector; model `claude-sonnet-5-5`, effort `high`, adaptive thinking, pinned tool listing | 0003 |
| D-04 | Two arms: `cli` (headline, PostHog default) and `tools` | 0004 |
| D-05 | Attribution ladder L0–L3 with a scripted MCP client layer | 0005 |
| D-06 | Dataset `ds1`: Hedgebox-compatible taxonomy, counter-based hash RNG, absolute window 2026-06-01..2026-08-31, project timezone `America/Mexico_City`, week starts Monday | 0006 |
| D-07 | Scenario catalog in YAML that is a superset of PostHog `tasks.yaml` v2 and exports to it | 0007 |
| D-08 | Closed error taxonomy; wrong numeric answers classified by oracle-computed error signatures | 0008 |
| D-09 | Structured answers through a `strict` client tool; local validation is normative | 0009 |
| D-10 | Read-only boundary in four independent layers | 0010 |
| D-11 | Isolation by project; contamination preflight; cleanup ledger plus sweep | 0011 |
| D-12 | Redaction at the capture boundary; nothing secret is ever written | 0012 |
| D-13 | Content-addressed evidence store; SQLite index; Django | 0013 |
| D-14 | One service layer behind REST (DRF + drf-spectacular) and an MCP server (Python `mcp` SDK); self-exam with the examinee's own PostHog access | 0014 |
| D-15 | Results as allowlisted events into a dedicated telemetry project; dashboards as code | 0015 |
| D-16 | No Braintrust; Score-shaped output | 0016 |
| D-17 | MIT license | 0017 |
| D-18 | Name: AgentTruth | 0018 |
| D-19 | English for code, docs, contract | 0019 |
| D-20 | React 19 + TypeScript 6 + Vite, served by Django; Playwright (TS) e2e on Docker Compose | 0020 |
| D-21 | Repetition, statistics and budget policy | 0021 |

---

## 3. Vacancy requirement → evidence matrix

Every row names the artifact a PostHog reviewer can check and the command that checks it. "Gate" = the sprint gate that first produces the evidence. Nothing in this table may be claimed in public docs before its gate is green (§13.4).

| Req | Requirement (brief) | Evidence in AgentTruth | Verify with | Gate |
|---|---|---|---|---|
| R1 | Built something agents use: agent-operable API, MCP server, evals, machine docs | (a) An eval suite for agents driving PostHog's MCP, with closed taxonomy and deterministic grading. (b) AgentTruth's own MCP server and OpenAPI-described REST API. (c) `llms.txt`. (d) A cold-start external agent completes a self-exam using only those. | `make gate-K3`, `make gate-K5`; `agenttruth evidence verify evidence/K5` | K3, K5 |
| R2 | Full-stack: Python + React; big data a plus | Python/Django service + React/TypeScript UI, e2e-tested on the real stack. Big data: **not claimed** (≈70k events; LIMITATIONS). | `make gate-K6` | K6 |
| R3 | A 0→1 project | Public repo whose history starts at this contract and ends at v1.0.0, every sprint closed by a gate report. | `git log --first-parent`; `agenttruth evidence verify evidence/` | K1–K7 |
| R4 | Strong writing, public docs | Contract, ADRs, research log, LIMITATIONS, public results report with a claims ledger in which every claim resolves to evidence or is worded as a hypothesis. | `make gate-K7` (claims lint) | K7 |
| R5 | Desirable: Django, React+TS, AI-native | Django 5.2 LTS, React 19 + TS 6; the product exists to measure AI agents. | `make gate-K5`, `make gate-K6` | K5, K6 |
| R6 | Product ownership: basic UX, docs for own work, support | UI with run/attempt/diff/compare views and accessibility smoke; `agenttruth doctor`; SUPPORT.md, issue templates (bug, truth dispute), triage policy; results dashboards in PostHog. | `make gate-K6`, `make gate-K7` | K5–K7 |

Hard rule (from the brief): a feature that serves no row of this table is out of scope even if it is a good idea. The implementer MUST NOT add one; if a sprint seems to need one, that is BLOCKED.

---

## 4. Architecture and boundaries

### 4.1 Components

AgentTruth is one Python distribution (`agenttruth`, CLI `agenttruth`) plus a React app. Logical components and their allowed dependencies (arrows = "may import"):

```
                ┌──────────────┐
                │  evidence    │  artifact store, manifests, hashing, redaction, schemas
                └──────▲───────┘
   ┌──────────┬────────┼─────────┬───────────┬─────────────┬──────────┐
dataset    oracle   scenarios  posthog     mcpclient     agent     grading
(generator, (truth,  (catalog,  (capture,   (scripted     (Anthropic (offline
 ledger,    signa-   lint,      REST query, PostHog MCP   runner,    classifier)
 faults)    tures)   export)    setup,      client)       fake
                                readback,                 agents)
                                cleanup)
   └──────────┴────────┴─────────┴───────────┴─────────────┴──────────┘
                │                                   │
            service  (exam sessions, runs, scenarios — the only API for adapters)
          ┌─────┴──────┐
       web (Django,   mcpserver (Python mcp SDK,
       DRF, OpenAPI,  streamable HTTP + stdio)
       SPA host)
          │
       frontend (React + TS)

gates  ── reads evidence only (independent checker)
telemetry ── reads evidence, writes to PostHog AT_TEL
```

Import rules (enforced by an AST-based test from K1 onward):

- `oracle` MUST NOT import `dataset` except the event-file reader and the dataset spec model; it MUST NOT read the ledger. The oracle derives truth from emitted events only.
- `grading` MUST be pure: inputs are recorded artifacts, outputs are classification records. No network, no clock, no randomness.
- `gates` MUST import only `evidence` (read-side) and the standard library. A gate never calls the code it judges; it reads what that code recorded.
- `web` and `mcpserver` MUST call only `service`. Neither adapter contains business logic.
- Nothing imports `gates`.

### 4.2 External systems and projects

All PostHog resources live in one PostHog Cloud **US** organization named `AgentTruth`, on the pay-as-you-go plan with every usage-based product capped at $0 and **AI data processing disabled** (ADR-0002, ADR-0010).

| Alias | Purpose | Data | Writes allowed | Who writes |
|---|---|---|---|---|
| `AT_DEV` | Iterate on ingestion and triangulation before touching canonical projects | `ds0` (smoke dataset) | events (capture) | `agenttruth posthog ingest` |
| `AT_EXAM` | Read-only exam target (exact answer, planted cause, K5 self-exam) | `ds1` | events once at setup; project settings once at setup; **nothing after** | setup commands only |
| `AT_RT` | Round-trip target | `ds1` | insights (created and deleted per run) | MCP under test, cleanup |
| `AT_TEL` | AgentTruth results as events + dashboards | results events | events, dashboards, insights | `agenttruth telemetry …` |

Project settings applied by `agenttruth posthog setup` to `AT_DEV`, `AT_EXAM`, `AT_RT` and read back (K2-C1): `timezone = America/Mexico_City`; `week_start_day = 1` (Monday); `test_account_filters = [{"key":"email","type":"person","value":"@hedgebox-internal.example","operator":"not_icontains"}]`; `test_account_filters_default_checked = true`.

Credentials (environment variables; never in files committed to git; loaded from a git-ignored `.env.local`):

| Variable | Kind | Scope | Used by |
|---|---|---|---|
| `AT_PH_TOKEN_DEV`, `AT_PH_TOKEN_EXAM`, `AT_PH_TOKEN_RT`, `AT_PH_TOKEN_TEL` | project capture tokens (`phc_…`, public) | one project each | ingestion, telemetry capture |
| `AT_PH_READ_KEY` | personal API key | scopes `query:read`, `insight:read`, `event_definition:read`, `property_definition:read`, `action:read`, `project:read`; projects `AT_DEV`, `AT_EXAM`, `AT_RT` | REST triangulation, readback, exam MCP sessions |
| `AT_PH_WRITE_KEY` | personal API key | READ scopes + `insight:write`; project `AT_RT` only | round-trip MCP sessions, cleanup |
| `AT_PH_ADMIN_KEY` | personal API key | `project:read`, `project:write`, `query:read`, `insight:read`, `insight:write`, `dashboard:read`, `dashboard:write`; projects all four | `posthog setup`, `telemetry dashboards apply`, K4 contamination/loss controls. Never given to an agent. |
| `AT_PH_PROJECT_ID_DEV/EXAM/RT/TEL` | numeric ids | — | all |
| `ANTHROPIC_API_KEY` | Anthropic key in a dedicated Workspace with a spend limit | — | agent runner |

### 4.3 Attribution ladder

```
L0  generator ledger  ── K1 ──  oracle(events)            "truth by construction" ≡ "truth by computation"
L1  oracle            ── K2 ──  PostHog REST /query        semantics + ingestion
L2  PostHog REST      ── K2/K4 ── scripted MCP client      MCP layer (no LLM): queries, saves
L3  scripted MCP      ── K3/K4/K7 ── agent (LLM)           the agent
```

- A scenario is **gradable** for agents only if L0 and L1 agree, or the L1 difference is a registered, unexpired divergence of class `posthog_semantics` whose decision is "oracle adopts PostHog behaviour" (then the oracle is changed and L1 agrees). Scenarios with an open divergence of class `posthog_defect`, `ingestion` or `unknown` are **quarantined**: excluded from agent scoring and listed in the run report.
- A query scenario is **MCP-clean** if L2 agrees for both modes. A failure on a non-MCP-clean scenario is attributed to the MCP layer, never to the agent.
- Round-trip fields are tested at L2 (scripted) and L3 (agent). An L3 field failure whose L2 counterpart also fails is attributed to the tool (`R_SILENT_DROP` at L2 implies the agent cannot succeed by sending the field).

### 4.4 Runtime data flow (exam attempt)

```
scenario + truth ─► agent runner ─► Anthropic Messages API (beta mcp-client-2026-09-15)
                                    │  mcp_servers: https://mcp.posthog.com/mcp?mode=<arm>&readonly=true
                                    │               &project_id=<AT_EXAM>&tools=<allowlist>
                                    │  authorization_token: AT_PH_READ_KEY
                                    │  tools: [mcp_toolset(pinned listing), submit_answer(strict)]
                                    ▼
                         response blocks (mcp_tool_use / mcp_tool_result / text / tool_use)
                                    │  redaction at capture boundary (§12)
                                    ▼
                         evidence store: attempt record + transcript (content-addressed)
                                    ▼
                    grading (offline, pure) ─► classification record ─► run report
                                    ▼
                    gates (read-only checker) ─► gate report      telemetry ─► AT_TEL
```

### 4.5 Fixed external interfaces

- PostHog MCP URL query parameters (the only channel the Anthropic connector offers, F-16): `mode`, `readonly`, `project_id`, `tools`. `features` is not used (the explicit `tools` allowlist is narrower).
- Exam allowlist (both arms, `AT_EXAM`, read key, `readonly=true`): `read-data-schema,query-trends,query-funnel,query-retention,execute-sql`.
- Round-trip allowlist (`AT_RT`, write key, no `readonly`): `read-data-schema,query-trends,query-funnel,query-retention,execute-sql,insight-create,insight-update,insight-get`.
- `always_available` tools that appear despite the allowlist are tolerated only if they are read-only in the pinned catalog snapshot; any read-write tool in an exam listing aborts the run (fail closed).
- Every attempt's tool listing is captured (`mcp_tool_listing` block) or, when pinned, copied from the run's pinned listing; its SHA-256 over canonical JSON is the **catalog hash** recorded per attempt.

---

## 5. Dataset (`ds0`, `ds1`)

### 5.1 Determinism

- Randomness comes only from a counter-based generator: `u64 = int.from_bytes(blake2b(seed ‖ stream_name ‖ counter, digest_size=8))`, with helpers for uniform floats, integers, choices and Poisson/exponential draws built on it. Python's `random`, `numpy`, `uuid4`, the clock, and dict/set iteration order of non-sorted containers MUST NOT influence output.
- Output files are canonical: UTF-8, LF, JSON Lines with sorted keys and `separators=(",", ":")`, events sorted by `(timestamp_utc, at_eid)`. Floats are emitted with `repr` of values that are exactly representable decimals (money is generated in integer cents and emitted as `cents/100`).
- A dataset build emits: `events.jsonl` (capture-ready events), `ledger.json` (construction ledger), `manifest.json` (spec hash, seed, counts, file hashes, generator version). Build is a pure function of `(spec, seed, generator code)`.

### 5.2 `ds1` specification

| Item | Value |
|---|---|
| Fictional product | Hedgebox (taxonomy borrowed from PostHog's demo, S01b/S01t, MIT). Data generation is AgentTruth's own; no PostHog code is reused. |
| Window | 2026-06-01T00:00:00 to 2026-08-31T23:59:59.999 in `America/Mexico_City` (fixed UTC−06:00 throughout; Mexico has had no DST since 2022). All timestamps are emitted in UTC ISO-8601 with milliseconds and `Z`. |
| Population | ~2,400 identified users (sign-up dates spread across the window with weekday seasonality), 40 internal users (emails `@hedgebox-internal.example`), ~3,000 never-identified visitors. Exact counts are in the ledger. |
| Identity | Each user starts with an anonymous `distinct_id`; at sign-up emits `signed_up` then `$identify` with `$anon_distinct_id` merging into `user-<n>` (`distinct_id` ≤ 200 chars). Person properties (`email`, `name`) are set once at identify and never changed, so point-in-time and current person properties coincide (F-24). Internal users have no anonymous activity: their first event is `$identify` with `$set {email, name}`, so their email is present on every event they emit whichever person-properties mode PostHog uses. No group analytics. No `$process_person_profile: false`. |
| Events | All client-side events carry `$current_url`, `$host = hedgebox.net`, `$browser`, `$os`, `$lib = web`. `paid_bill` is server-side (`$lib = posthog-python`, no browser properties), as in Hedgebox. Events: `$pageview`, `signed_up` (`from_invite`), `logged_in`, `uploaded_file`/`downloaded_file`/`shared_file_link`/`deleted_file` (`file_type`, `file_size_b`), `upgraded_plan`/`downgraded_plan` (`previous_plan`, `new_plan` ∈ `personal/free`, `personal/pro`, `business/standard`, `business/enterprise`), `invited_team_member`, `paid_bill` (`amount_usd`, `plan`). Every event carries `at_eid` (dataset-unique id) and `at_ds = "ds1"`; top-level `uuid` is a UUIDv5 of `at_eid`. |
| Size | 60k–90k events (ledger fixes the exact number). |
| Edge cases (planted on purpose) | events within ±30 min of local midnight and at exact local `00:00:00.000` and `23:59:59.999`; funnel completions at exactly the conversion window and window ± 1 s; out-of-order step sequences; repeated steps; internal users mirroring normal behaviour; users whose first `uploaded_file` precedes the window start (`ds1` includes a 14-day pre-window warm-up segment `2026-05-18..2026-05-31` so "first ever" differs from "first in range"). |
| Planted faults | F1–F5 below, each confined to a declared segment and window that do not overlap one another. |

Planted faults (injectable; each can be switched off for negative controls):

| ID | Fault | Construction | Observable symptom | Cause the agent must find |
|---|---|---|---|---|
| F1 | Tracking outage | `uploaded_file` from `$os = Android` not emitted 2026-07-15..2026-07-17 | Upload dip | `cause_type=tracking_outage`, dimension `$os=Android` |
| F2 | Duplicate events | `shared_file_link` from `$browser = Firefox` emitted twice (+50–400 ms) 2026-08-03..2026-08-09 | Share spike with flat unique sharers | `duplicate_events`, `$browser=Firefox` |
| F3 | Identity break | Users signing up via `$current_url` containing `/signup/mobile` 2026-06-22..2026-06-28 never emit `$identify` (activity under a second, unmerged distinct id) | New-user spike, conversion drop | `identity_break`, property `$current_url`, value containing `/signup/mobile` |
| F4 | Internal traffic | Internal users emit 30× normal `$pageview` 2026-07-27..2026-07-29 | Pageview spike only without test-account filter | `internal_traffic`, property `email`, value containing `hedgebox-internal.example` |
| F5 | Property value change | `upgraded_plan.new_plan` emitted as `pro` instead of `personal/pro` from 2026-08-17 | `personal/pro` upgrades collapse in breakdown | `property_value_change`, `new_plan=pro` |

### 5.3 `ds0`

Same generator, separate seed, 1 week window 2026-05-04..2026-05-10, ~300 users, all edge-case kinds present, no faults. Used only in `AT_DEV` and in unit tests.

### 5.4 Construction ledger

The ledger records, per user, the intended journey (which steps, when, under which distinct ids, internal or not, which faults touched it) and, per scenario metric, the value implied by those journeys computed from the journey structures (not from `events.jsonl`). K1-C2 compares ledger values to oracle values for every scenario.

---

## 6. Oracle

### 6.1 Contract

`oracle.evaluate(metric_spec, events, project_config) → value` where `metric_spec` is the declarative metric in the scenario (§7.3), `events` is the parsed `events.jsonl`, and `project_config` is `{timezone, week_start_day, test_account_filters}`. Same inputs, same output; no I/O beyond reading the event file.

### 6.2 Semantic rules (normative)

The oracle implements exactly these rules. Each rule cites its source; a rule changed after K2 triangulation cites the divergence id that changed it.

| ID | Rule | Source |
|---|---|---|
| SEM-01 | Explicit `date_from`/`date_to` (calendar dates) are interpreted in the project timezone; `date_to` is inclusive to 23:59:59.999999 local. | S01o |
| SEM-02 | Day buckets are local calendar days; week buckets start Monday 00:00 local; month buckets are local calendar months. | S01o |
| SEM-03 | `math=total` counts events; `math=dau` ("unique users") counts distinct persons after identity resolution. | S15 |
| SEM-04 | Identity resolution: a distinct id merged by `$identify` (`$anon_distinct_id` → identified id) belongs to the identified person for all its events, past and future. An id never identified is its own person. | S14, S15 |
| SEM-05 | Test-account filter excludes events whose person `email` (as known at event time; always set for internal users by construction, §5.2) contains `@hedgebox-internal.example`; applied only when the metric says `filter_test_accounts: true`. | S01s, §4.2 |
| SEM-06 | Funnel order `ordered`: step *k+1* is the first matching event after the step-*k* event used; other events may intervene. `strict`: no other event of the person may occur between consecutive steps. | S12, S01q |
| SEM-07 | Funnel conversion window is measured from the step-1 event; default 14 days; a step at exactly `step1 + window` counts as converted (boundary semantics confirmed or corrected in K2). | S01p, S01q |
| SEM-08 | Every funnel step event must lie inside `[date_from, date_to]` (local, per SEM-01). | S01p |
| SEM-09 | A person enters the funnel once (first qualifying step-1 event in range that leads to the furthest step reached; exact tie-breaking confirmed in K2). | S12 |
| SEM-10 | Retention `retention_first_time`: cohort period = period of the person's first start event within the date range; `recurring`: every period with a start event; return in period *k* = any return event in that period; Period 0 = cohort size. | S13, S01r |
| SEM-11 | Retention period boundaries follow SEM-02. | S01o |
| SEM-12 | Property breakdown uses the event property value at event time; funnel breakdowns use first-touch attribution unless specified. | S01q, S12 |
| SEM-13 | HogQL `toDate(timestamp)`/`toStartOfDay` operate in project time. | S01o |
| SEM-14 | Sums of `amount_usd` are computed in integer cents and compared with tolerance (§9.2). | design |
| SEM-15 | The pre-window warm-up segment is outside every scenario's range unless the metric says `first_ever`. | §5.2 |

Rules marked "confirmed in K2" are expected to be the first triangulation targets; the oracle is changed only through the divergence registry (§6.4).

### 6.3 Error signatures

For every exact-answer scenario the oracle also evaluates **signature transforms** of its metric. A signature is the value an agent would report if it made one specific mistake. Transforms (each applies only where meaningful):

| Signature | Transform of the metric spec |
|---|---|
| `SIG_PERIOD_PREV`, `SIG_PERIOD_NEXT` | shift the range by its own length backwards/forwards |
| `SIG_PERIOD_EXCL_END` | `date_to` exclusive (drop the last local day) |
| `SIG_PERIOD_EXTRA_DAY` | extend `date_to` by one day |
| `SIG_TZ_UTC` | evaluate with timezone UTC |
| `SIG_TEST_ACCOUNTS` | flip `filter_test_accounts` |
| `SIG_AGG_TOTAL`, `SIG_AGG_UNIQUE` | switch `math` between total and unique persons |
| `SIG_FUNNEL_WINDOW_DEFAULT` | replace the stated window with the default 14 days (or vice versa) |
| `SIG_FUNNEL_ORDER` | swap `ordered` ↔ `strict` |
| `SIG_RETENTION_TYPE` | swap `retention_first_time` ↔ `retention_recurring` |
| `SIG_RETENTION_CUMULATIVE` | flip `cumulative` |
| `SIG_EVENT_<name>` | replace the event with a declared confusable event (e.g. `downloaded_file` for `uploaded_file`) |
| `SIG_FILTER_DROPPED` | drop the scenario's property filter |

A scenario is **valid** only if its truth and all its declared signature values are pairwise distinguishable under the grading tolerance (K1-C3). Signatures that collide MUST be removed from that scenario's declared list (not silently merged).

### 6.4 Divergence registry

`divergences.yaml` (committed). Entry fields: `id` (`DIV-NNN`), `scenario_ids`, `layer` (`L1` | `L2`), `class` (`generator` | `oracle` | `posthog_semantics` | `posthog_defect` | `ingestion` | `mcp_layer` | `unknown`), `oracle_value`, `posthog_value`, `evidence` (artifact hashes of both sides), `analysis` (one paragraph, citing source ids), `decision` (`oracle_adopts_posthog` | `fix_generator` | `fix_oracle` | `quarantine`), `recorded` (date), `expires` (date, ≤ 30 days after `recorded`), `posthog_catalog_hash`, `status` (`open` | `resolved`). `generator`/`oracle` divergences are resolved by fixing code and do not remain open. `unknown` is never acceptable at a gate. An expired entry counts as missing.

---

## 7. Scenario model

### 7.1 Kinds

| Kind | Purpose | Target | Answer |
|---|---|---|---|
| `exact_answer` (EA) | numeric truth for trends, funnels, retention, SQL | `AT_EXAM`, read-only | `submit_answer` |
| `planted_cause` (PC) | find the planted fault behind a symptom | `AT_EXAM`, read-only | `submit_answer` with `cause` |
| `roundtrip_scripted` (RS) | one settings field through the MCP save path, no LLM | `AT_RT` | — (scripted) |
| `roundtrip_agent` (RA) | agent saves/updates an insight with stated settings | `AT_RT` | `submit_roundtrip_report` |

### 7.2 File format

One catalog file per version: `scenarios/catalog.v1.yaml`. It is a superset of PostHog's `tasks.yaml` v2 task (S01g): the fields `id` (kebab-case, unique), `category` (a PostHog `TASK_CATEGORIES` value: `product-analytics`, `sql` or `insights`), `intent`, `expected_tools`, `acceptable_tools`, `success_criteria` keep PostHog's meaning, so `agenttruth scenarios export --format posthog-tasks-v2` can emit a file that validates against PostHog's `schema.ts` (vendored under `third_party/posthog/` with its MIT notice and source commit). AgentTruth fields live under `agenttruth:`.

```yaml
version: 1
dataset: ds1
scenarios:
  - id: ea-uploads-july-filtered
    category: product-analytics
    intent: "How many files were uploaded in July 2026, excluding internal and test users?"
    expected_tools: [query-trends]
    acceptable_tools: [execute-sql, read-data-schema]
    success_criteria: "Reports the number of uploaded_file events from 2026-07-01 to 2026-07-31 in project time with test accounts filtered."
    agenttruth:
      kind: exact_answer
      answer_kind: count            # count | rate | amount | mapping | ranking | cause | roundtrip_report
      metric:                       # §7.3
        type: trends
        event: uploaded_file
        math: total
        date_from: 2026-07-01
        date_to: 2026-07-31
        filter_test_accounts: true
      signatures: [SIG_PERIOD_PREV, SIG_PERIOD_EXCL_END, SIG_TZ_UTC, SIG_TEST_ACCOUNTS, SIG_AGG_UNIQUE, SIG_EVENT_downloaded_file]
      semantics: [SEM-01, SEM-03, SEM-05]
      posthog_query: auto           # compile metric → TrendsQuery JSON for L1/L2; or an explicit HogQL string for type: custom
```

### 7.3 Metric spec

`type` ∈ `trends` (event, math, date range, optional `properties`, optional `breakdown`, `filter_test_accounts`), `funnel` (steps, `window {n, unit}`, `order`, date range, filters), `retention` (start event, return event, `period`, `retention_type`, `cumulative`, cohort date range, `cohort_index`, `period_index`), `custom` (a named oracle function plus the reviewed HogQL used for L1/L2). Each non-custom metric compiles deterministically to a PostHog query object (`TrendsQuery`, `FunnelsQuery`, `RetentionQuery`) used by L1 (REST) and L2 (scripted MCP); `custom` metrics carry their HogQL verbatim.

### 7.4 Catalog v1 (normative list; prompts are final text written in K1 and frozen by hash)

Exact answer (16):

| id | Tests |
|---|---|
| `ea-uploads-july-filtered` | total count, month range, test-account filter |
| `ea-signups-day-0714` | single local day (timezone trap: events near midnight) |
| `ea-active-week-0706` | unique persons with `logged_in` in the Monday week of 2026-07-06 |
| `ea-revenue-august` | sum of `amount_usd`, August |
| `ea-uploads-by-os-july` | breakdown mapping by `$os` |
| `ea-funnel-signup-upload-june` | 2-step funnel, window stated as 14 days (PostHog's default), entered and converted counts |
| `ea-funnel-signup-upload-1d` | same with an explicit 1-day window |
| `ea-funnel-activation-july` | 3-step funnel `signed_up → uploaded_file → upgraded_plan`, 30-day window |
| `ea-funnel-pricing-signup-1h` | `$pageview` with `$current_url` containing `/pricing/` → `signed_up`, 1-hour window |
| `ea-funnel-strict-upload-share` | strict order `uploaded_file → shared_file_link` |
| `ea-retention-firsttime-w1` | weekly first-time retention `signed_up → uploaded_file`, cohort week of 2026-06-08, week 1 retained count and cohort size |
| `ea-retention-recurring-d1` | daily recurring `logged_in → logged_in`, cohort 2026-07-01, day 1 |
| `ea-sql-power-uploaders` | users who signed up in June and uploaded ≥ 3 files within 7 days of sign-up |
| `ea-sql-top-filetypes-aug` | top 3 `file_type` by uploads in August (ties impossible by construction) |
| `ea-sql-distinct-login-days` | identified users who logged in on > 10 distinct local days in July |
| `ea-sql-first-ever-upload-june` | persons whose first-ever `uploaded_file` (including warm-up) is in June |

Planted cause (5): `pc-f1-upload-dip`, `pc-f2-share-spike`, `pc-f3-newuser-spike`, `pc-f4-pageview-spike`, `pc-f5-pro-upgrades-drop`. Each prompt states only the symptom and the date range to look at.

Round-trip scripted (RS): every key below, created via `insight-create` and, for update cases, changed via `insight-update`, in both modes:

- SQL (`DataVisualizationNode`): `display=ActionsBar`, `chartSettings.showLegend=true`, `chartSettings.legendPosition=bottom`, `chartSettings.showValuesOnSeries=true`, `chartSettings.stackBars100=true`, `chartSettings.showAnnotations=true`, `chartSettings.showXAxisTicks=false`, `chartSettings.showYAxisBorder=false`, `chartSettings.yAxisAtZero=false`, `chartSettings.chartStyle` (a valid non-default value from `posthog/schema.py`), `tableSettings.pinnedColumns`, `tableSettings.conditionalFormatting` (minimal valid rule).
- Trends: `trendsFilter.display=ActionsBar`, `trendsFilter.showValuesOnSeries=true`, `compareFilter.compare=true`, `breakdownFilter.breakdown=$os`, `interval=week`.
- Funnels: `funnelsFilter.funnelWindowInterval=7`, `funnelsFilter.funnelOrderType=strict`, `funnelsFilter.funnelVizType=trends`, `funnelsFilter.breakdownAttributionType=last_touch`.
- Retention: `retentionFilter.period=Week`, `retentionFilter.totalIntervals=8`, `retentionFilter.retentionType=retention_first_time`, `retentionFilter.cumulative=true`.
- Update semantics: create SQL insight with `legendPosition=bottom` and `showValuesOnSeries=true`, then update only `legendPosition=top` (a) sending the full query with both settings, (b) sending a query with the same `source` and `display` whose `chartSettings` contains only `legendPosition: top`; record what survives in each case (F-10 predicts (b) loses `showValuesOnSeries`; whether that is a defect or documented replace-semantics is stated in `findings/108309.md`, not assumed).

Every RS value MUST differ from the schema default for that key (lint against defaults extracted from the vendored `posthog/schema.py` snapshot).

Round-trip agent (6): `ra-trends-bar-compare-breakdown`, `ra-funnel-7d-strict-trends`, `ra-retention-week-8-firsttime-cumulative`, `ra-sql-bar-legend-annotations` (one in-schema and one out-of-schema setting), `ra-sql-update-legend-only` (update must keep other settings), `ra-sql-axis-settings` (`showXAxisTicks=false`, `yAxisAtZero=false`). Each prompt names the insight `at-rt-<run_id>-<scenario>` and lists the settings in plain language.

Prompt rules (enforced by `scenarios lint` where mechanical): a prompt states the question as a user would, with absolute dates; it is unambiguous about everything the truth depends on — the event or behaviour, the date range, unique people vs event counts when that changes the number, the conversion window (always stated for funnels), strict step order when required, and whether internal/test users are included whenever flipping that changes the truth (lint: if `SIG_TEST_ACCOUNTS` ≠ truth, the intent must contain one of the fixed phrases "excluding internal and test users" or "including internal and test users"). It never hints at a pitfall (no mention of timezones, of how PostHog computes things, or of which tool to use).

The catalog is versioned. Changing a prompt, metric or signature list after K3 creates `catalog.v2` and invalidates comparisons with earlier runs.

---

## 8. Error taxonomy (closed)

Every attempt receives exactly one **attempt class**. Round-trip attempts additionally receive one **field class** per requested field. The sets below are closed; adding a member is a contract change (ADR + new catalog version).

### 8.1 Attempt classes

| Class | Group | Definition |
|---|---|---|
| `I_TIMEOUT` | infra | attempt wall clock exceeded (§9.4) |
| `I_BUDGET` | infra | stopped by budget guard before completion |
| `I_PROVIDER_ERROR` | infra | Anthropic API error after retries (5xx, overloaded) |
| `I_MCP_UNREACHABLE` | infra | MCP connector could not reach/initialise PostHog MCP |
| `I_RATE_LIMITED` | infra | PostHog 429 (query budget/rate) on every query attempt |
| `I_HARNESS_ERROR` | infra | AgentTruth bug; attempt invalid (also catch-all for infra) |
| `T_TOOL_FAILURE` | tool | every query tool call in the attempt returned a server-side error (not a validation error caused by bad input), and no PASS |
| `P_WRITE_ATTEMPT` | protocol | any attempt (call or `exec call`) of a write tool in a read-only scenario |
| `P_NO_ANSWER` | protocol | conversation ended without `submit_answer`/`submit_roundtrip_report` |
| `P_INVALID_ANSWER` | protocol | submitted payload fails local schema validation |
| `P_ABSTAIN` | protocol | `status = cannot_answer` |
| `PASS` | pass | answer correct (§9.2) / all fields OK and report consistent (§9.3) |
| `E_EVENT_INVENTED` | answer | wrong answer and a query used an event name not in the dataset taxonomy or PostHog built-ins |
| `E_WRONG_EVENT` | answer | matches a `SIG_EVENT_*` |
| `E_PERIOD` | answer | matches a `SIG_PERIOD_*` |
| `E_TIMEZONE` | answer | matches `SIG_TZ_UTC` |
| `E_TEST_ACCOUNTS` | answer | matches `SIG_TEST_ACCOUNTS` |
| `E_AGGREGATION` | answer | matches `SIG_AGG_*` |
| `E_FILTER` | answer | matches `SIG_FILTER_DROPPED` |
| `E_FUNNEL_WINDOW` | answer | matches `SIG_FUNNEL_WINDOW_DEFAULT` |
| `E_FUNNEL_ORDER` | answer | matches `SIG_FUNNEL_ORDER` |
| `E_RETENTION_SEMANTICS` | answer | matches `SIG_RETENTION_TYPE` or `SIG_RETENTION_CUMULATIVE` |
| `E_MISREPORTED_RESULT` | answer | no signature matches, but the truth value appears in a successful MCP tool result of the attempt |
| `E_UNCLASSIFIED` | answer | wrong; none of the above |
| `C_NO_ANOMALY` | cause | reports no anomaly |
| `C_WRONG_CAUSE_TYPE` | cause | `cause_type` differs |
| `C_WRONG_DIMENSION` | cause | type right, dimension (property or value) wrong |
| `C_WRONG_WINDOW` | cause | type and dimension right, window outside tolerance |
| `R_SILENT_DROP` | round trip | at least one field `R_SILENT_DROP` |
| `R_SILENT_ALTER` | round trip | at least one field `R_SILENT_ALTER` (and none worse) |
| `R_EXTRA_MUTATION` | round trip | an unrequested field changed (update scenarios) |
| `R_AGENT_OMITTED` | round trip | at least one field `R_AGENT_OMITTED` |
| `R_REPORTED_ERROR` | round trip | failures exist but each was surfaced (tool error or agent report) |

### 8.2 Field classes (round trip)

| Field class | Definition |
|---|---|
| `OK` | stored value equals requested value (after §9.3 normalisation) |
| `R_AGENT_OMITTED` | (agent only) no successful write call in the attempt contained the field with the requested value |
| `R_SILENT_DROP` | the write call that contained the field succeeded, the stored insight lacks the field, and no tool error mentioned it |
| `R_SILENT_ALTER` | stored value present but different, write call succeeded |
| `R_REPORTED_ERROR` | the write call failed, or the agent's report lists the field as not applied |

Attempt-level `claim_mismatch` (boolean, recorded beside the class): the agent's report claims a field applied whose field class is not `OK`. This is the agent-visible symptom of a silent failure.

### 8.3 Precedence (deterministic)

Attempt class is the first match in this order:
`I_*` (in table order) → `T_TOOL_FAILURE` → `P_WRITE_ATTEMPT` → `P_NO_ANSWER` → `P_INVALID_ANSWER` → `P_ABSTAIN` → `PASS` → for EA: `E_EVENT_INVENTED` → `E_WRONG_EVENT` → `E_PERIOD` → `E_TIMEZONE` → `E_TEST_ACCOUNTS` → `E_AGGREGATION` → `E_FILTER` → `E_FUNNEL_WINDOW` → `E_FUNNEL_ORDER` → `E_RETENTION_SEMANTICS` → `E_MISREPORTED_RESULT` → `E_UNCLASSIFIED`; for PC: `C_NO_ANOMALY` → `C_WRONG_CAUSE_TYPE` → `C_WRONG_DIMENSION` → `C_WRONG_WINDOW`; for RA: `R_SILENT_DROP` → `R_SILENT_ALTER` → `R_EXTRA_MUTATION` → `R_AGENT_OMITTED` → `R_REPORTED_ERROR`.

Mapping answers (breakdowns) are classified on the first wrong key in sorted key order. Ranking answers are classified as one value (the list).

---

## 9. Grading rules

### 9.1 Structured answers

The agent answers by calling a client tool (not an MCP tool) defined by the runner with `strict: true` (F-20; fallback per I-06):

- `submit_answer`: `{scenario_id, status: "answered"|"cannot_answer", value: number|null, unit: "count"|"fraction"|"percent"|"usd"|null, mapping: [{key, value}]|null, ranking: [string]|null, cause: {cause_type: "tracking_outage"|"duplicate_events"|"identity_break"|"internal_traffic"|"property_value_change"|"none", property: string|null, value: string|null, start_date: string|null, end_date: string|null}|null, explanation: string}`
- `submit_roundtrip_report`: `{scenario_id, insight_short_id: string|null, applied: [string], not_applied: [string], explanation: string}` where entries are the setting labels given in the prompt.

The first call to the answer tool ends the attempt; later text is ignored. Local JSON-Schema validation (with the bounds strict mode cannot express, e.g. `fraction ∈ [0,1]`) is normative.

### 9.2 Exact answer and planted cause

| answer_kind | Correct when |
|---|---|
| `count` | `value` is an integer equal to truth (`unit` `count`) |
| `rate` | `fraction` within ±0.0005 of truth, or `percent` within ±0.05 |
| `amount` | `usd` within ±0.005 |
| `mapping` | same key set; every value correct by its kind |
| `ranking` | identical ordered list |
| `cause` | `cause_type` equal; `property` equal; `value` equal (for F3 and F4: the answer's `value` contains the planted substring `/signup/mobile` or `hedgebox-internal.example` respectively); `start_date`/`end_date` each within ±1 day of the planted window |

Signature matching uses the same tolerance as correctness. Funnel scenarios ask for counts (`entered`, `converted`, and for 3-step funnels `step_2`), retention scenarios for counts (`cohort_size`, `retained`), as mappings — never rates; `rate` is defined for future catalogs. Mapping keys are compared exactly as the values are stored in the data (e.g. `$os` values), and the prompt says so ("use the values exactly as recorded").

### 9.3 Round trip

- Requested fields are JSON paths in the stored insight's `query` (REST `GET /api/projects/:id/insights/:id/`, read with `AT_PH_READ_KEY` — never through the MCP).
- Normalisation before comparison: `InsightVizNode` wrapper vs bare source equivalence; enum strings compared case-sensitively; numeric `7` equals `7.0`; nothing else.
- For update scenarios, every field present before the update and not requested to change MUST be unchanged (`R_EXTRA_MUTATION` otherwise).
- Agent-sent values come from the recorded `mcp_tool_use` inputs (tools mode) or the parsed `exec` `call` JSON (cli mode).

### 9.4 Attempt limits

Per attempt: wall clock 300 s; ≤ 30 server-side tool iterations (continuation on `pause_turn` counts); `max_tokens` 16,000 per request; cost cap $1.50 (computed from `usage` and S19 prices). Crossing a limit ends the attempt with the matching `I_*` class.

### 9.5 Determinism of grading

Grading is a pure function of `(attempt record, scenario, truth file, catalog snapshot, contract version)`. `agenttruth grade --run <id>` run three times in fresh processes MUST produce byte-identical `grades.jsonl` and report hash. Every grade record also carries a Score-shaped projection `{name, score, metadata}` (`score` = 1.0 for `PASS`, 0.0 for answer/protocol/tool classes, `null` for infra) compatible with PostHog's scorer contract (F-06).

---

## 10. Read-only / write boundary

Exact-answer, planted-cause and K5 self-exam sessions against `AT_EXAM` are read-only through four independent layers; each is verified separately (K2-C5, K3-C6):

1. **Credential:** `AT_PH_READ_KEY` has no write scope (a REST write with it returns 403).
2. **Server mode:** `readonly=true` in the MCP URL.
3. **Allowlist:** `tools=` contains only read-only tools; the runner aborts if the received or pinned listing contains any tool that is read-write in the pinned catalog snapshot.
4. **Target:** `project_id` pins `AT_EXAM`; the project's state (event count, insight and dashboard id sets) is snapshotted at K2 and re-checked before and after every run.

Round-trip sessions use `AT_PH_WRITE_KEY`, which is limited to `AT_RT`, and the round-trip allowlist. No credential with write access to `AT_EXAM` is ever given to an MCP session.

---

## 11. Isolation, cleanup and contamination

- Events are never deleted; projects are never reused across dataset versions. Re-ingesting into a project that already has events is refused (`ingest` checks a zero event count first and requires `--confirm-irreversible`).
- Ingestion order is fixed: `ds0 → AT_DEV`, full verification and triangulation there, then `ds1 → AT_EXAM` and `ds1 → AT_RT`.
- If `AT_EXAM` is ever contaminated (failed or duplicated ingestion), the only remedy is: delete the project, create a new one, re-run setup and ingestion, bump `exam_epoch` in `projects.yaml`, and re-run the K2 gate. This is a runbook, not an implementer decision; the implementer stops with BLOCKED and the owner executes it.
- `AT_RT` **baseline** = the set of non-deleted insight ids (and dashboards) recorded right after setup. Before every round-trip run, preflight lists non-deleted insights; any id outside the baseline rejects the run (`contaminated: <ids>`).
- During a run, every created insight is recorded in the run's **cleanup ledger** from tool results; after the run a **sweep** lists non-deleted insights and diffs against the baseline. Cleanup soft-deletes (`PATCH {deleted:true}`, S01l) the union of ledger ids and sweep extras, then verifies the project equals the baseline. Sweep extras not in the ledger are reported (`agent_extra_objects`).
- `agenttruth cleanup --run <id>` is idempotent; `agenttruth cleanup --orphans` deletes every non-baseline insight in `AT_RT` and reports them. Both use `AT_PH_WRITE_KEY`.
- One round-trip run at a time: a local lock file plus the baseline preflight.

---

## 12. Security and redaction

Never leaves the process unredacted, never written to disk, never committed, never sent to telemetry:

- every value of `ANTHROPIC_API_KEY`, `AT_PH_*_KEY`, and any `phx_…`, `pha_…`, `phs_…`, `sk-ant-…` token, `Authorization`/`authorization_token` values, and `token=` URL parameters;
- HTTP request/response headers (never recorded at all);
- environment dumps.

Mechanism: the evidence store's write API is the only path to disk for run data; it applies redaction (exact secret values loaded at startup with length ≥ 8, plus the regexes above) and replaces each hit with `[REDACTED:<kind>:<first 8 hex of sha256>]`. `agenttruth audit secrets` scans the evidence store, the git tree, and (in K7) release assets for the same patterns and the literal values available in the environment; any hit fails the scan.

Transcripts: kept (redacted) for every attempt because grading needs tool inputs and results. Thinking blocks are stored as `{type: thinking, redacted: true}` without signatures. Transcripts are committed only for gate evidence and published in the campaign tarball; they contain synthetic data only.

Telemetry (§K5) is an allowlist: `run_id, attempt_id, scenario_id, scenario_kind, arm, model, effort, mcp_mode, class, passed, claim_mismatch, dataset_id, catalog_version, contract_version, git_sha, cost_usd, input_tokens, output_tokens, tool_calls, duration_ms`. `distinct_id` is `agenttruth-runner` with `$process_person_profile: false`. Nothing else is sent.

Data sent to third parties by design: prompts and PostHog tool results (synthetic data) to Anthropic under standard retention (MCP connector is not ZDR-eligible, F-16); synthetic events and allowlisted results to PostHog. Declared in LIMITATIONS.

---

## 13. Evidence

### 13.1 Store

- Content-addressed: every artifact is stored as `sha256/<hh>/<hash>.<ext>` (gzip with `mtime=0` for transcripts), immutable once written.
- Manifests (`run.json`, `gate-K<n>.json`, `dataset manifest`, `release.json`) list artifact hashes and are themselves hashed.
- A SQLite index (Django-managed) is a cache rebuilt from manifests (`agenttruth index rebuild`); it is never the source of truth.
- Run manifest fields: `run_id`, `kind`, `contract_version`, `catalog_version` + hash, `dataset_id` + manifest hash, `truths_hash`, `git_sha`, `git_dirty` (gates reject `true`), `arm` {`model`, `effort`, `thinking`, `max_tokens`, `beta`, `mcp_url_without_secrets`, `allowlist`, `pinned_listing_hash`}, `posthog_project_alias` + id, `started_at`, `finished_at`, `attempts[]` (ids, hashes, class), `cost_usd`, `anthropic_request_ids`, `response_models` (the `model` string returned per response).

### 13.2 Committed evidence

`evidence/K<n>/` contains each gate's report, manifests, and the artifacts the gate cites (redacted). The full K7 campaign store is published as a release asset whose SHA-256 is committed. `agenttruth evidence verify <path>` re-hashes everything and fails on any mismatch or missing artifact.

### 13.3 Gate reports

Written only by `agenttruth gate K<n>` (the independent checker). Fields: `gate`, `contract_version`, `git_sha`, `inputs` (manifest hashes read), `criteria[]` {`id`, `statement`, `result` pass|fail, `observed`, `expected`, `evidence` hashes}, `negative_controls[]` {`criterion_id`, `sabotage`, `expected_fail`, `observed_failing_criteria`, `result`}, `verdict`. The verdict is pass only if every criterion passes **and** every negative control produces exactly its declared `expected_fail` set — normally its single target criterion; a control declared with `expected_fail: none` (a canonicalisation check) must leave every criterion passing. A gate with a criterion that cannot be evaluated (missing credentials, missing artifact) fails; it never skips.

### 13.4 Evidence rule

A claim is publishable only with the full chain: **claim → contract section → real target → command → immutable artifact → hash → result → known limitations.** If any element is missing the sentence is rewritten as a hypothesis ("we expect…", "not yet verified"). Evidence notes always separate **"the design says"** from **"the system did"**, and every sprint report ends with **what it demonstrated** and **what it did not**.

---

## 14. Sprint specifications

Common rules for every sprint:

- A sprint is exactly one K, executed end to end from its prompt. It ends only in **DONE** (gate verdict pass, closing report written, committed) or **BLOCKED** (§17).
- Commands that touch PostHog or Anthropic require `AT_LIVE=1` and `--live`. Without credentials they exit non-zero with `missing credential: <name>`; they never fall back to mocks. Offline tests never touch the network (enforced by a pytest plugin that fails on socket use outside tests marked `live`).
- Gates run offline from evidence and can be re-run by anyone with the repo: `make gate-K<n>`. CI runs `make check` and every gate whose evidence exists.
- Every sprint keeps all earlier gates green at its final commit (`make gates`).
- Anthropic spend caps per sprint (enforced by the runner's budget guard, not by good intentions): K3 $25, K4 $10, K5 $10, K7 $100.
- The implementer commits in small, meaningful commits on `main` with conventional messages; the sprint's last commit adds `evidence/K<n>/` and `reports/K<n>.yaml`.

### K1 — Repository, generator, oracle

**Objective.** A reproducible repository in which `ds0`/`ds1` build byte-for-byte, the oracle computes every scenario truth and signature from events alone, the ledger agrees with it, planted faults are injectable, and an independent checker proves all of that with negative controls.

**Requirement dimension.** R3 (0→1 foundation), R1 (eval core), R4 (contract as the first commit).

**Deliverables.**
- First commit: exactly the K0 files from the zip (contract, ADRs, research, limitations, prerequisites, AGENTS.md, prompts), message `docs: K0 foundation contract`.
- Python project managed by `uv` (`pyproject.toml`, `uv.lock`), Python 3.14.6 pinned in `.python-version`; `Makefile` with `check`, `gate-K1`, `gates`.
- Packages per §4.1 that K1 needs: `evidence`, `dataset`, `oracle`, `scenarios`, `gates`.
- Pydantic v2 models for: dataset spec, event, ledger, manifest, metric spec, scenario, truth record, gate report; JSON Schemas generated from them under `schemas/` (committed, drift-checked).
- `scenarios/catalog.v1.yaml` with all EA and PC scenarios of §7.4 (final prompt text), RS field list, RA scenarios (prompts may be refined in K4 only if K1 marks them `draft: true`).
- `datasets/ds0.lock.json`, `datasets/ds1.lock.json`: expected manifest hashes.
- `truths/ds1.v1.json`: truths and signature values for every EA/PC scenario.
- `third_party/posthog/`: vendored `services/mcp/evals/benchmark/schema.ts` and the defaults table needed for RS lint, with LICENSE excerpt and source commit `e606d69…`.
- CI workflow (GitHub Actions, `ubuntu-24.04`): `uv sync --frozen`, `make check`, `make gate-K1`.

**Interfaces fixed by K1.** CLI: `agenttruth dataset build --spec <ds> --out <dir> [--disable-fault F<n>]`, `agenttruth oracle compute --dataset <dir> --catalog <file> --out <file>`, `agenttruth scenarios lint`, `agenttruth scenarios export --format posthog-tasks-v2 --out <file>`, `agenttruth evidence verify <path>`, `agenttruth gate K<n>`. File formats: `events.jsonl`, `ledger.json`, `manifest.json`, catalog YAML, truths JSON, gate report JSON — all with `schema: agenttruth.<kind>/v1`.

**Allowed dependencies.** Runtime: `pydantic`, `pyyaml`, `jsonschema`. Dev: `pytest`, `pytest-xdist`, `hypothesis`, `ruff`, `mypy`. Node only for validating the PostHog export (`npx tsx` against the vendored `schema.ts` with `zod` pinned to the version in `third_party/posthog/`).

**Gate K1** (`make gate-K1`). The checker forces reconstruction: it deletes every build output and cache it reads, rebuilds in fresh subprocesses, then judges.

| Criterion | Pass condition |
|---|---|
| K1-C1 reproducible | `ds0` and `ds1` built twice in two fresh processes into two empty directories yield identical `events.jsonl`, `ledger.json`, `manifest.json` SHA-256, equal to `datasets/*.lock.json`. |
| K1-C2 ledger ≡ oracle | For every EA/PC scenario, ledger value == oracle value (exact for counts/mappings/rankings; amounts in integer cents). |
| K1-C3 signatures distinct | For every EA scenario, truth and declared signature values are pairwise distinguishable under §9.2 tolerance; every scenario declares ≥ 3 signatures. |
| K1-C4 faults isolated | For each F1–F5: rebuilding with that fault disabled changes the oracle value of the fault's probe metrics inside its declared window and segment, and changes no other EA truth. |
| K1-C5 oracle sensitivity | Each of these event-file mutations changes exactly the predicted scenario truths by the predicted delta: drop one in-range `uploaded_file`; move one boundary event by 1 ms across local midnight; change one internal user's email domain; duplicate one `signed_up`; remove one `$identify`. |
| K1-C6 catalog | `scenarios lint` passes (ids unique, kebab-case, categories valid, every SEM/SIG id exists, RS values differ from defaults); export validates against the vendored PostHog `schema.ts`. |
| K1-C7 quality | `ruff check`, `ruff format --check`, `mypy --strict` on `src/`, `pytest -q` all pass; no network used by offline tests. |
| K1-C8 import rules | AST test proves the §4.1 import rules. |

Negative controls (each must fail exactly its criterion): append a byte to one built file (C1); perturb one ledger value (C2); add a colliding signature (C3); enlarge a fault window by a day in the spec copy (C4); make the oracle ignore one mutation by patching a copy of the truths (C5); duplicate a scenario id in a catalog copy (C6); insert a forbidden import in a temp module copy (C8); introduce a type error into a temporary copy of one source module and run the C7 toolchain on that copy (C7).

**Rejection conditions.** Any use of `random`, `numpy`, wall clock or `uuid4` in data paths; oracle reading the ledger; truths edited by hand; a criterion skipped; lock hashes regenerated to make C1 pass without explaining why in the report.

**Do not change.** This contract, ADRs, RESEARCH.md (append-only corrections go to the closing report and to LIMITATIONS).

**DONE.** Gate K1 verdict pass with all negative controls; `evidence/K1/` and `reports/K1.yaml` committed; CI green on the final commit.

### K2 — PostHog setup, ingestion, triangulation

**Objective.** Real PostHog projects configured and loaded; every scenario's truth agrees with PostHog's REST answer (L1) and with the scripted MCP answer in both modes (L2), or carries a registered divergence; read-only boundary verified.

**Requirement dimension.** R1 (eval validity), R3.

**Deliverables.**
- `posthog` package: capture client (raw `/batch/` POSTs, no `sent_at`, `historical_migration: true`, ≤ 1,000 events or ≤ 5 MB per request, sequential, retry with backoff on 5xx/429, fail on any `quota_limited`), REST query client (`refresh: force_blocking`, keyset pagination, 429 budget handling), project setup and settings readback, state snapshot.
- `mcpclient` package: scripted client for `https://mcp.posthog.com/mcp` over Streamable HTTP (Python `mcp` SDK) supporting both modes; in `cli` mode it issues `exec` commands (`call <tool> <json>`).
- `projects.yaml` (aliases, ids, region, `exam_epoch`; no secrets).
- `divergences.yaml` per §6.4.
- Commands: `agenttruth doctor` (credentials present, key scopes probed, project settings drift), `agenttruth posthog setup --project <alias> --live`, `agenttruth posthog ingest --dataset <dir> --project <alias> --confirm-irreversible --live`, `agenttruth posthog verify-ingest --project <alias> --live`, `agenttruth triangulate --project <alias> --layers L1,L2 --modes cli,tools --live`, `agenttruth boundary-probe --live`.

**Required order.** setup (DEV, EXAM, RT, TEL) → ingest `ds0` into DEV → verify → triangulate DEV → only if DEV triangulation has no `unknown` divergences: ingest `ds1` into EXAM and RT → verify both → triangulate EXAM → boundary probe → snapshot EXAM and RT baselines.

**Interfaces fixed by K2.** Divergence entry schema; project state snapshot schema; triangulation record `{scenario_id, layer, mode, posthog_query_hash, value, oracle_value, agree, divergence_id}`; scripted MCP call record `{mode, tool, input, is_error, result_hash, latency_ms}`.

**Gate K2** (`make gate-K2`).

| Criterion | Pass condition |
|---|---|
| K2-C1 settings | Read-back settings of DEV/EXAM/RT equal §4.2 values. |
| K2-C2 ingestion | For EXAM and RT: event count over the window == manifest; distinct `at_eid` == count; min/max timestamps == manifest; every boundary-flagged event (≤ 200, by `at_eid`) has the exact emitted timestamp; distinct persons == oracle; zero `quota_limited`; two stable polls ≥ 60 s apart. |
| K2-C3 L1 | For every EA/PC truth and every PC probe metric: REST value == oracle value, or an `open` unexpired divergence with class ≠ `unknown` covers it; scenarios with `posthog_defect`/`ingestion` classes are listed as quarantined. |
| K2-C4 L2 | For every non-quarantined EA scenario and both modes: scripted MCP value == REST value, or a divergence with class `mcp_layer` covers it. |
| K2-C5 read-only | With the exam configuration, the listing has no tool that is read-write in the pinned catalog snapshot; `insight-create` (tools mode) and `exec call insight-create …` (cli mode) both fail; REST `POST …/insights/` with `AT_PH_READ_KEY` returns 403. |
| K2-C6 catalog | Exam listing ⊆ allowlist ∪ read-only `always_available`; no listed tool appears in the pinned AI-consent list; catalog hash recorded per mode. |
| K2-C7 baselines | EXAM snapshot (event count, insight ids, dashboard ids) and RT baseline recorded with hashes. |
| K2-C8 provenance | Every artifact above has `target: live`, PostHog request ids or MCP session ids, and a clean `git_sha`. |

Negative controls: alter one REST value in an evidence copy (C3); delete one divergence entry (C3); set one divergence `expires` in the past (C3); alter one scripted MCP value (C4); add `insight-create` to a recorded exam listing (C5/C6 — the control declares which one it targets: the RW check is C5, the allowlist check is C6, and two separate sabotages are used); change one boundary timestamp by 1 ms (C2); flip `target` to `mock` (C8).

**Rejection conditions.** Ingesting `ds1` before DEV passed; any `unknown` divergence; editing the oracle to match PostHog without a divergence entry; using the MCP for readback; using `AT_PH_ADMIN_KEY` in any MCP session.

**Do not change.** The `events.jsonl` lock hashes (a generator change after ingestion requires a new dataset id and fresh projects — that is BLOCKED, owner decides) and catalog v1 prompts. The `ledger.json` lock hash may change only together with an `oracle_adopts_posthog` divergence, with `events.jsonl` unchanged, citing the divergence id in the commit and report.

**DONE.** Gate K2 pass; registry has no `unknown`; quarantine list (possibly empty) published in `reports/K2.yaml`.

### K3 — Agent runner, exact-answer and planted-cause exams

**Objective.** A reproducible agent runner against the hosted MCP with pinned configuration, budget control and redacted transcripts; deterministic grading into the closed taxonomy, proven exact on a fake agent with known errors; a live smoke run on both arms.

**Requirement dimension.** R1 (evals, agent-facing), R5 (AI-native).

**Deliverables.**
- `agent` package: `AgentDriver` interface `run(scenario, arm, budget) → AttemptRecord`; `AnthropicMCPDriver` (beta `mcp-client-2026-09-15`, `mcp_servers` URL per §4.5, `mcp_toolset` with the run's pinned listing, `cache_control` on the toolset, `submit_answer` strict client tool, `pause_turn` continuation, limits §9.4); `FakeDriver` that replays scripted transcripts in the exact recorded format.
- Listing pinning: a run starts with one unpinned call that captures `mcp_tool_listing`; that listing is validated (§4.5), hashed and pinned for every attempt of the run.
- `grading` package per §8–§9 with Score projection.
- Fake profile `fake:catalog`: for every EA/PC scenario, a set of fake attempts each committing one designed error (one per signature declared, plus `E_EVENT_INVENTED`, `E_MISREPORTED_RESULT`, `E_UNCLASSIFIED`, each `P_*`, `T_TOOL_FAILURE`, each `C_*`, and a `PASS`), with an `injected.json` manifest written by the fake profile generator, not by the grader.
- Budget guard: pre-request projection from current usage; refuses a request that could exceed the cap; marks `I_BUDGET`.
- Commands: `agenttruth exam run --suite ea|pc|all --arm cli|tools --reps N --budget-usd X --live`, `agenttruth exam run --driver fake:catalog`, `agenttruth grade --run <id>`, `agenttruth report --run <id>`.

**Arms (fixed).** `cli`: `mode=cli`; `tools`: `mode=tools`. Both: model `claude-sonnet-5-5`, `output_config.effort = "high"`, `thinking = {"type":"adaptive"}`, `max_tokens = 16000`, no sampling params, system prompt `harness_prompts/exam.v1.txt` (written in K3, hashed; states only: the role (an analyst answering questions about a product's data), that the connected PostHog project is the data source, and that the final answer goes through `submit_answer` — it MUST NOT hint at any pitfall, including timezones, test accounts, unique vs total, or funnel windows).

**Interfaces fixed by K3.** Attempt record schema (blocks, tool calls normalised across modes, usage, cost, timings, listing hash, response model ids); grade record schema; run report schema.

**Gate K3** (`make gate-K3`).

| Criterion | Pass condition |
|---|---|
| K3-C1 classification exact | For `fake:catalog`, grader class == `injected.json` class for 100% of fake attempts, and every class in §8.1 applicable to EA/PC appears at least once. |
| K3-C2 offline determinism | `grade` run 3× in fresh processes on the live smoke run yields identical `grades.jsonl` and report hash. |
| K3-C3 live smoke | Every EA/PC scenario × both arms × N=1 has an attempt record with a class; ≤ 10% `I_*`; manifest complete (§13.1). |
| K3-C4 budget | A live run with `--budget-usd 0.05` stops with `I_BUDGET` and recorded spend ≤ cap + one request's max cost; the smoke run's spend ≤ its cap. |
| K3-C5 redaction | `audit secrets` on K3 evidence: 0 hits; a canary secret injected into a fake transcript before capture is redacted in the stored artifact. |
| K3-C6 read-only in practice | Every attempt's listing hash equals the run's pinned hash and contains no RW tool; zero successful write calls. |
| K3-C7 config pinning | All attempts in a run share one arm hash; every response `model` equals the configured model. |

Negative controls: change one grade class in a copy (C1); reorder JSON keys in one grade record copy without changing semantics (C2 must still pass — this control asserts canonicalisation, recorded as `expected_fail: none`); change one byte in a graded file (C2); remove one attempt record (C3); raise recorded spend above cap (C4); put an unredacted canary into an artifact copy (C5); add a RW tool to one attempt's listing (C6); change one response `model` (C7).

**Rejection conditions.** Grading that calls an LLM; signatures computed at grading time instead of read from truths; changing prompts to make the fake catalog pass; storing unredacted transcripts even temporarily; any temperature/top_p parameter.

**Do not change.** Catalog v1, truths, oracle (unless via a K2-style divergence with evidence, which is BLOCKED in K3).

**DONE.** Gate K3 pass; smoke results summarised in `reports/K3.yaml` with measured mean/p95 cost per attempt per arm.

### K4 — Round trip

**Objective.** Measure whether insight settings survive the MCP save path: scripted (L2) for every RS field in both modes and agent-level (L3) for RA scenarios, with exact cleanup and contamination rejection.

**Requirement dimension.** R1, R6 (owning correctness of a product surface).

**Deliverables.**
- RS runner on the scripted MCP client; readback through REST with `AT_PH_READ_KEY`; field comparator per §9.3.
- RA support in the agent runner (`submit_roundtrip_report`) using the round-trip allowlist and `AT_PH_WRITE_KEY`.
- Preflight, cleanup ledger, sweep, cleanup and orphan commands per §11.
- `findings/108309.md`: for each issue-#108309-related key, "the design (static code) says" vs "the system did" with evidence hashes; marks I-02/I-03 as confirmed or refuted.
- Commands: `agenttruth roundtrip run --level scripted|agent --modes cli,tools [--reps N] --live`, `agenttruth roundtrip preflight --live`, `agenttruth cleanup --run <id> | --orphans --live`.

**Gate K4** (`make gate-K4`).

| Criterion | Pass condition |
|---|---|
| K4-C1 simulated loss detected | Live: after an RS create succeeds, the harness removes one requested field via REST with `AT_PH_ADMIN_KEY` before readback; the comparator reports exactly that field as lost. Offline: removing one field from a recorded readback copy flips exactly that field's class. |
| K4-C2 contamination rejected | Live: a stray insight created via REST in RT makes preflight refuse with its id; after `cleanup --orphans`, preflight accepts. |
| K4-C3 cleanup exact | After every K4 run, RT non-deleted insights == baseline; ledger ids ∪ sweep extras == ids soft-deleted. |
| K4-C4 RS complete | Every RS field × both modes × (create, and update where defined) has a field class; `findings/108309.md` references each record. |
| K4-C5 RA smoke | Every RA scenario × both arms × N=1 graded; field classes and `claim_mismatch` recorded. |
| K4-C6 exam untouched | EXAM snapshot equals the K2 baseline. |

Negative controls: delete one RS record (C4); add a non-baseline id to a post-run state copy (C3); make preflight evidence show acceptance despite a stray id (C2); mark the loss-injection readback as OK (C1); change EXAM event count in a snapshot copy (C6); drop one RA grade (C5).

**Rejection conditions.** Reading back through the MCP; deleting anything outside `AT_RT`; RS values equal to defaults; treating `R_REPORTED_ERROR` as pass.

**Do not change.** Exam suites, truths, arms.

**DONE.** Gate K4 pass; `findings/108309.md` states reproduced / not reproduced per key, with "design says / system did".

### K5 — AgentTruth for agents

**Objective.** AgentTruth itself is usable by agents: an OpenAPI-described REST API and an MCP server over the same service layer, `llms.txt`, results flowing into PostHog as events with dashboards, a `doctor` command, and proof that a cold-start agent completes a self-exam using only that surface.

**Requirement dimension.** R1 (API/MCP/machine docs), R5 (Django), R6 (support tooling, dashboards).

**Deliverables.**
- `service` layer: scenarios (list/get, public fields only — never truths), datasets (manifest, download of `events.jsonl` for operators who ingest into their own project), exam sessions (`start(suite, examinee_label) → session`, `next_question`, `submit(answer)`, `finish → report`), runs and grades (read-only views of the evidence index).
- Django 5.2 project with DRF and drf-spectacular; OpenAPI 3.1 at `/api/schema/`, committed as `openapi.yaml` and drift-checked; every operation has a summary, description and example.
- MCP server (Python `mcp` SDK, Streamable HTTP at `/mcp` on its own process, plus stdio) with tools `list_scenarios`, `get_scenario`, `start_exam`, `next_question`, `submit_answer`, `finish_exam`, `get_report`, `read_docs`; tool annotations accurate (`readOnlyHint` true for reads).
- `/llms.txt` and `/llms-full.txt` (llmstxt.org format) generated from the same source as the docs.
- Telemetry: `agenttruth telemetry publish --run <id> --live` (events `agenttruth attempt graded`, `agenttruth run completed`; allowlist §12), `agenttruth telemetry dashboards apply --live` (dashboard "AgentTruth results" with pass rate by arm, class distribution, cost per run, round-trip field outcomes; defined as code; idempotent).
- Self-exam suite `self-exam-smoke` = 5 EA scenarios (`ea-uploads-july-filtered`, `ea-signups-day-0714`, `ea-funnel-signup-upload-june`, `ea-retention-firsttime-w1`, `ea-sql-top-filetypes-aug`).
- Cold-start harness: a host loop that gives a pinned model (same arm settings as K3 `cli`) either (a) AgentTruth MCP tools as client tools, or (b) a single `http_request` client tool restricted to the AgentTruth base URL; plus PostHog MCP via the connector with the exam configuration. Fixed instruction text: *"You are an autonomous agent. A service called AgentTruth is available through your tools. Take its exam named `self-exam-smoke` as the examinee: start a session, answer every question it gives you using your PostHog tools, finish the session, and reply with the report id. No human will answer questions."* For arm (b) the instruction also gives the base URL and nothing else.

**Interfaces fixed by K5.** REST paths (`/api/v1/scenarios`, `/api/v1/datasets/{id}`, `/api/v1/exams`, `/api/v1/exams/{id}/next`, `/api/v1/exams/{id}/answers`, `/api/v1/exams/{id}/finish`, `/api/v1/reports/{id}`, `/api/v1/runs`, `/api/v1/runs/{id}`, `/api/v1/attempts/{id}`, `/api/v1/compare`), MCP tool names above, telemetry event names and properties.

**Gate K5** (`make gate-K5`).

| Criterion | Pass condition |
|---|---|
| K5-C1 OpenAPI | `manage.py spectacular --validate --fail-on-warn` output == committed `openapi.yaml`; every operation has summary, description, at least one example. |
| K5-C2 parity | A recorded session script executed through REST and through MCP yields byte-identical canonical JSON results. |
| K5-C3 cold start | Both cold-start arms finish a `self-exam-smoke` session with a report id, schema-valid answers to all 5 questions, zero human turns after the instruction; transcripts recorded and redacted. Answer correctness is reported, not required. |
| K5-C4 telemetry | After publishing a K3 run, a REST HogQL query on `AT_TEL` returns exactly one `agenttruth attempt graded` event per attempt and the union of property keys ⊆ allowlist (plus PostHog `$` properties); captured payload log passes `audit secrets`. |
| K5-C5 dashboards | `dashboards apply` twice creates nothing the second time; readback matches the spec. |
| K5-C6 doctor | `doctor` reports each missing credential by name when run with an empty environment and exits non-zero; reports OK with the real environment. |

Negative controls: add an undocumented endpoint to a schema copy (C1); alter one MCP result (C2); remove `finish` from a cold-start transcript copy (C3); add a disallowed property to a payload copy (C4); add an extra insight to a dashboard readback copy (C5); make doctor evidence show exit 0 with an empty environment (C6).

**Rejection conditions.** Business logic in views or MCP handlers; exposing truths or signatures through any public endpoint before `finish`; sending transcripts to telemetry; giving the cold-start agent any AgentTruth documentation beyond what its tools return.

**Do not change.** Grading, taxonomy, catalog.

**DONE.** Gate K5 pass.

### K6 — Web product

**Objective.** A usable web UI over the same service layer, shipped with Docker Compose and verified end to end with Playwright on the real stack.

**Requirement dimension.** R2, R5, R6 (basic UX).

**Deliverables.**
- `frontend/`: React 19 + TypeScript 6 (strict) + Vite 8, TanStack Query, React Router; built assets served by Django (WhiteNoise).
- Routes: `/runs` (list with arm, catalog, pass rate, cost), `/runs/:runId` (per-scenario results, class distribution, config, quarantined scenarios), `/runs/:runId/attempts/:attemptId` (prompt, redacted transcript with tool calls, submitted answer vs truth or field-by-field diff for round trips, class and why), `/scenarios`, `/scenarios/:id` (intent, semantics, signatures — truth hidden until the user clicks "reveal", which is a UI affordance only), `/compare?a=&b=` (per-scenario pass rate side by side, deltas, class shifts), `/docs` (links to OpenAPI, llms.txt, contract).
- `docker-compose.yml`: `web` (gunicorn Django + built SPA), `mcp` (AgentTruth MCP server); SQLite on a named volume; evidence directory mounted read-only; healthchecks; images based on `python:3.14.6-slim-bookworm` and `node:24.21.0-bookworm-slim` (build stage), pinned by digest (§16).
- Seed: `agenttruth index rebuild` over committed evidence (K3/K4 runs) at container start.
- Playwright (TypeScript) suite run against `docker compose up --wait`; no route interception, no API mocks.

**Gate K6** (`make gate-K6`).

| Criterion | Pass condition |
|---|---|
| K6-C1 build | `docker compose build --no-cache` and `up --wait` succeed from a clean clone; healthchecks green. |
| K6-C2 e2e | Playwright: runs list → run → failing attempt shows the class and, for an RS/RA record with `R_SILENT_DROP`, the dropped field highlighted with values matching the evidence record; compare page deltas equal `/api/v1/compare`; attempt page DOM contains no secret pattern; deep links load directly; zero console errors; zero skipped tests. |
| K6-C3 front-end quality | `tsc --noEmit` strict, ESLint with 0 warnings, Vitest unit tests pass. |
| K6-C4 accessibility smoke | `@axe-core/playwright` on every route: 0 violations of impact `serious` or `critical`. |

Negative controls: mark one Playwright test skipped in a report copy (C2); inject one console error entry (C2); add one serious axe violation entry (C4); change a recorded image digest (C1).

**Rejection conditions.** Mocking the API in e2e; a second data path that bypasses the service layer; storing state only in the browser.

**Do not change.** API contracts from K5 (additive changes allowed, recorded in OpenAPI and parity tests).

**DONE.** Gate K6 pass.

### K7 — Campaign, reduction, release

**Objective.** Run the full exam against the real hosted MCP with repetitions, analyse with honest statistics, reduce every stable failure to a minimal reproduction with attribution, prepare (not publish) an upstream evidence package, publish public docs with a claims ledger, and release v1.0.0.

**Requirement dimension.** R1, R3, R4, R6.

**Deliverables.**
- Pre-campaign: re-run K2 triangulation and boundary probe (refreshing divergences); record current catalog hashes; if in-scope tool schemas changed since K3, re-pin and note it.
- Campaign: EA + PC + RA scenarios × arms `cli` and `tools` × N=5, under the $100 cap, applying ADR-0021's reduction rule if K3/K4 actual costs project above the cap.
- Statistics (ADR-0021): per scenario and arm pass rate with Wilson 95% interval; class distribution; `stable_fail` (same non-PASS class in ≥ 4/5), `flaky` (1–3 non-PASS of 5); arm comparison descriptive only.
- Reduction for every `stable_fail` and every RS/RA silent failure: replay the agent's final query/write through scripted MCP and REST; attribute (`agent` | `mcp_layer` | `posthog`); delta-minimise the tool input while the failure persists; a reduction counts only if it reproduces 3/3 runs; otherwise `not_reproducible`.
- `upstream/` package (not published): issue drafts with minimal repro script, expected vs actual, environment (catalog hash, commit if known), evidence hashes; a comment draft for #108309 if K4 reproduced anything.
- Public docs: `README.md` (what it is, what it proves and does not, quickstart), `docs/HOW_IT_WORKS.md`, `docs/SCENARIOS.md`, `docs/TAXONOMY.md`, `docs/RESULTS.md` (campaign report), `docs/SELF_EXAM.md`, `SUPPORT.md` (channels, triage within 7 days, truth-dispute process), `.github/ISSUE_TEMPLATE/` (bug, truth dispute, scenario proposal), `SECURITY.md`, `CONTRIBUTING.md`, final `docs/LIMITATIONS.md`.
- Claims ledger `docs/CLAIMS.yaml`: every sentence in README/RESULTS that asserts a result carries a claim id `[C-nn]` resolving to the §13.4 chain.
- Release: tag `v1.0.0`; `release.json` (all gate report hashes, campaign store hash); campaign store tarball as GitHub release asset.

**Gate K7** (`make gate-K7`).

| Criterion | Pass condition |
|---|---|
| K7-C1 campaign complete | attempts == plan (after any recorded reduction) and each graded; offline regrade 3× byte-identical. |
| K7-C2 statistics reproducible | `agenttruth report --campaign` regenerates `docs/RESULTS.md` data tables byte-identical to the committed ones. |
| K7-C3 reductions | Every `stable_fail` and silent round-trip failure has a reduction record with attribution and 3/3 repro or `not_reproducible`; upstream drafts cite only reproduced ones. |
| K7-C4 claims | Claims lint: every `[C-nn]` resolves to a full chain; no result-asserting sentence lacks an id unless phrased as a hypothesis (lint word list + manual list of exceptions in `CLAIMS.yaml`). |
| K7-C5 gates | `make gates` passes at the release commit (all K1–K7 gates, offline from evidence). |
| K7-C6 secrets | `audit secrets` over the repo, evidence and the release tarball: 0 hits. |
| K7-C7 ownership | SUPPORT.md, issue templates, doctor, dashboards link present and referenced from README. |

Negative controls: remove one attempt (C1); edit one table cell in RESULTS.md (C2); delete one reduction record (C3); add an unsupported superlative claim (C4); corrupt one older gate report (C5); plant a canary in the tarball copy (C6); delete SUPPORT.md in a copy (C7).

**Rejection conditions.** Publishing the upstream package (owner decides); claiming significance between arms; dropping scenarios after seeing results; changing the catalog during the campaign; hiding quarantined scenarios.

**Do not change.** Everything frozen by earlier gates except documentation and the corrections the claims lint forces.

**DONE.** Gate K7 pass, tag pushed, release created; `reports/K7.yaml` lists what v1.0.0 demonstrated and did not.

---

## 15. Final acceptance matrix (GATE / EVIDENCE)

v1.0.0 is accepted only when every row is green at the release commit.

| Gate | Criterion ids | Evidence (committed) | Re-check command | Proves | Does not prove |
|---|---|---|---|---|---|
| K1 | C1–C8 | `evidence/K1/gate-K1.json`, `datasets/*.lock.json`, `truths/ds1.v1.json` | `make gate-K1` | Data and truths are reproducible and independently derived | Anything about PostHog |
| K2 | C1–C8 | `evidence/K2/`, `divergences.yaml`, `projects.yaml` | `make gate-K2` | PostHog (REST and scripted MCP) agrees with truths or the difference is explained; read-only boundary holds | Agent behaviour |
| K3 | C1–C7 | `evidence/K3/` (fake run, smoke runs, grades) | `make gate-K3` | Grading is exact and deterministic; runner is pinned, budgeted, redacted | Agent accuracy at scale (N=1) |
| K4 | C1–C6 | `evidence/K4/`, `findings/108309.md` | `make gate-K4` | Which settings survive the MCP save path (scripted), cleanup exactness | Agent round-trip rates at scale |
| K5 | C1–C6 | `evidence/K5/`, `openapi.yaml`, `llms.txt` | `make gate-K5` | An agent can use AgentTruth cold; results land in PostHog | Usability for humans |
| K6 | C1–C4 | `evidence/K6/` (Playwright JSON, axe report, image digests) | `make gate-K6` | The web product works on the real stack | Load or multi-user behaviour |
| K7 | C1–C7 | `evidence/K7/`, `release.json`, `docs/RESULTS.md`, `docs/CLAIMS.yaml`, `upstream/` | `make gate-K7` | Campaign results, reductions and every public claim are traceable | Results for other models, modes, datasets, or later PostHog versions |

---

## 16. Toolchain (versions verified 2026-10-08)

Pinned exactly. Upgrades are allowed only for security fixes and are recorded in the sprint report with the reason.

| Tool | Version | Verified by | Note |
|---|---|---|---|
| Python | 3.14.6 | S29 (`uv python list`) | PostHog pins 3.14.7, which uv 0.12.24 cannot install yet |
| uv | 0.12.24 | S27 | |
| Django | 5.2.18 | S27 | LTS; matches PostHog's `~=5.2.0` (S01u). 6.x rejected: drf-spectacular 0.30.0 and pytest-django 4.14.0 do not classify 6.1 |
| djangorestframework | 3.18.3 | S27 | classifies Django 5.2–6.1 |
| drf-spectacular | 0.30.0 | S27 | |
| django-stubs | 5.2.9 | S27 | matches Django 5.2 |
| whitenoise | 6.12.0 | S27 | |
| gunicorn | 26.2.0 | S27 | |
| pydantic | 2.14.0 | S27 | |
| pyyaml | 6.0.3 | S27 | |
| jsonschema | 4.26.0 | S27 | |
| httpx | 0.28.1 | S27 | |
| mcp (Python SDK) | 2.3.0 | S27, wheel inspected (streamable HTTP client and server present) | |
| anthropic (Python SDK) | 1.12.1 | S27, S31 | has `mcp_tool_listing` beta types |
| posthog (Python SDK) | 7.66.0 | S27 | telemetry capture only (ingestion uses raw `/batch/`) |
| pytest | 9.1.1 | S27 | |
| pytest-django | 4.14.0 | S27 | |
| pytest-xdist | 3.8.0 | S27 | |
| hypothesis | 6.168.5 | S27 | |
| ruff | 0.16.10 | S27 | |
| mypy | 2.4.0 | S27 | |
| Node.js | 24.21.0 | S30 | PostHog requires `>=24 <25` |
| pnpm | 10.34.6 | S28 | PostHog major 10 |
| TypeScript | 6.0.3 | S28 | PostHog's pin; typescript-eslint 8.71.1 supports `<6.1.0` |
| React / React DOM | 19.3.0 | S28 | |
| @types/react, @types/react-dom | 19.3.0 | S28 | |
| Vite | 8.3.4 | S28 | |
| @vitejs/plugin-react | 6.1.2 | S28 | |
| Vitest | 5.0.3 | S28 | |
| @tanstack/react-query | 5.104.1 | S28 | |
| react-router | 8.4.0 | S28 | |
| @playwright/test | 1.64.0 | S28 | browsers installed by the same version |
| @axe-core/playwright | 4.13.0 | S28 | |
| ESLint / typescript-eslint | 10.12.0 / 8.71.1 | S28 | |
| Docker base images | `python:3.14.6-slim-bookworm`, `node:24.21.0-bookworm-slim` | **NOT VERIFIED** (S32) | K6 MUST resolve each tag, pin `@sha256:` digests, and record them; if a tag does not exist, use the newest existing patch of the same minor and record the deviation (pre-authorised, not BLOCKED) |
| GitHub Actions runner | `ubuntu-24.04` | — | free for public repos (S26) |
| PostHog MCP | hosted, catalog hash recorded per run | S01k | not pinnable; drift is recorded, not prevented |
| Anthropic model | `claude-sonnet-5-5` | S19, S20 | undated id; `response.model` recorded per response |

If `uv sync` cannot resolve this set (a version yanked, an incompatibility), the implementer stops with BLOCKED and the resolver output; the implementer MUST NOT pick substitutes.

---

## 17. BLOCKED protocol

The implementer stops and reports BLOCKED — instead of deciding — when any of these happens:

1. A decision is needed that this contract does not make and that is not internal layout.
2. A gate criterion cannot pass without changing the contract, a test's threshold, a frozen artifact (lock hashes, catalog, truths) or a negative control.
3. A credential, project, budget or external service is missing, misconfigured or behaves differently from §2 FACTs.
4. Live evidence contradicts a FACT in §2 (record it; do not "work around" it).
5. An irreversible external action not explicitly scripted by the sprint is needed (deleting a PostHog project, ingesting into a non-empty project, publishing anything).
6. A spend cap would be exceeded.
7. The toolchain set in §16 does not resolve.

Not BLOCKED (pre-authorised, record in the report): I-06 strict-tool fallback; Docker tag patch fallback (§16); oracle and ledger-derivation changes justified by a divergence entry with evidence during K2 (with the `ledger.json` lock rule of K2); adding fake attempts to cover a taxonomy class.

A BLOCKED report contains: the condition number above, what was attempted, the exact command and output (redacted), the artifacts and hashes collected, the options visible with their consequences, and what the implementer recommends — then stops. Forbidden while blocked: relaxing a test, skipping a criterion, editing frozen artifacts, mocking a live dependency, widening scope, or continuing with later deliverables "in the meantime".

---

## 18. Closing report format (`reports/K<n>.yaml`)

```yaml
sprint: K3
contract_version: 1.0.0
status: done            # done | blocked
git:
  start_sha: <sha>
  end_sha: <sha>
  dirty: false
gate:
  command: make gate-K3
  report: evidence/K3/gate-K3.json
  report_sha256: <hash>
  verdict: pass
  criteria: {K3-C1: pass, K3-C2: pass, ...}
  negative_controls: {total: 8, behaved_as_expected: 8}
deliverables:
  - id: agent-runner
    status: done
    evidence: [<artifact hashes>]
spend:
  anthropic_usd: 12.84
  cap_usd: 25
  posthog_usd: 0
measurements:            # numbers the next sprints depend on
  cost_per_attempt_usd: {cli: {mean: 0.21, p95: 0.44}, tools: {mean: 0.27, p95: 0.51}}
design_said_vs_system_did:
  - design: "I-06 strict client tools combine with mcp_toolset"
    system: "accepted (request id req_…)"
deviations:              # pre-authorised fallbacks and why
  - none
divergences_opened: []
limitations_added: [<LIMITATIONS.md anchors>]
demonstrated:
  - "Grader classifies 100% of 212 injected errors exactly (gate K3-C1)"
not_demonstrated:
  - "Agent accuracy with N>1"
blocked: null           # or {condition: 3, summary: ..., evidence: [...], options: [...], recommendation: ...}
next_sprint_inputs:
  - "pinned listing hashes: cli=<…>, tools=<…>"
```

---

## 19. Risk register

| ID | Risk | Where it bites | Detected by / declared as |
|---|---|---|---|
| RK-01 | Oracle encodes a semantic different from PostHog's (funnel boundaries, retention ranges, identity) | Agent blamed for PostHog semantics | K2-C3 with divergence registry; quarantine |
| RK-02 | Ingestion alters timestamps (skew correction) or loses/duplicates events | Truth mismatch everywhere | No `sent_at`; K2-C2 exact boundary check and uuid/`at_eid` counts |
| RK-03 | Ingestion into `AT_EXAM` goes wrong and cannot be undone | Permanent contamination | DEV-first order; non-empty refusal; delete-and-recreate runbook (§11) |
| RK-04 | Hosted MCP catalog or tool descriptions change during the project | Non-comparable runs | Catalog hash per attempt; listing pinned per run; K7 re-pins; LIMITATIONS |
| RK-05 | Read-only flag not enforced in `cli` `exec` path | Exam writes to `AT_EXAM` | Four-layer boundary; K2-C5 probe; read key has no write scope |
| RK-06 | Model nondeterminism makes N=5 too small to compare arms | Overclaiming | Wilson intervals; descriptive comparison only (D-21); claims lint |
| RK-07 | Anthropic cost higher than estimate | Campaign truncated | K3 measured costs; budget guard; ADR-0021 reduction rule; BLOCKED at cap |
| RK-08 | PostHog query read budget (429) during triangulation/campaign | Infra noise | Backoff; `I_RATE_LIMITED` excluded from scores; spread runs |
| RK-09 | Grader bug misclassifies | Wrong conclusions | K3-C1 fake catalog with independent injected manifest; offline determinism |
| RK-10 | Checker that never fails | False confidence | Negative controls required in every gate verdict |
| RK-11 | Secrets leak into transcripts or telemetry | Credential exposure in a public repo | Redaction at write boundary; canary tests; `audit secrets` in K3/K5/K7 |
| RK-12 | Agent-created objects leak between round-trip runs | Contaminated results | Baseline preflight, ledger + sweep, K4-C2/C3 |
| RK-13 | Issue #108309 fixed before K4 | Round-trip finds nothing | Still valuable as a regression test; reported honestly as "not reproduced at <catalog hash>" |
| RK-14 | Inflation: presenting a 70k-event synthetic set as "big data", N=5 as "benchmark", one model as "agents" | Reviewer distrust | LIMITATIONS; claims lint; §1 "does not demonstrate" |
| RK-15 | Inflation: implying PostHog AI (in-product) was tested | Misrepresentation | §1 correction 2; README wording reviewed by claims lint |
| RK-16 | Signature collisions make classification ambiguous | Wrong class | K1-C3 distinguishability |
| RK-17 | Prompt leaks pitfalls (teaching to the test) | Inflated pass rates | Frozen system prompt reviewed against "no pitfall hints" rule; prompt hash in manifests |
| RK-18 | Scope creep (other MCP categories, more models) | Sprints never close | R-table rule (§3); BLOCKED on scope |
| RK-19 | PostHog plan/limits change (projects, retention) | Setup fails | `doctor`; PREREQUISITES re-checked by owner before K2 |
| RK-20 | Docker image tags/versions unavailable | K6 build fails | Pre-authorised patch fallback with digest pinning |

---

## 20. Change control

- This contract changes only by an ADR that amends it, approved by the owner, bumping the contract version (minor for additive, major for anything that invalidates evidence).
- The implementer never edits `docs/CONTRACT.md`, `docs/adr/*`, `docs/RESEARCH.md`, or `prompts/*`. Discoveries go into the sprint report and, where they limit claims, into `docs/LIMITATIONS.md` (which the implementer may append to).
- Catalog, dataset and truths are versioned artifacts; a change creates a new version and new projects as needed, never an in-place edit.

### Changelog

- 1.0.0 (2026-10-08) — K0 contract.
