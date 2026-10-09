# AgentTruth — Limitations

This file states what AgentTruth does not show, cannot show, or has not yet shown. It starts at K0 with limitations known by design; each sprint appends what it learns (with a date and the sprint id). Entries are never deleted; a limitation that is lifted is marked **Lifted** with the evidence that lifted it.

## By design (K0)

### Scope of the claim

- **L-01 One model, two modes.** Results describe `claude-sonnet-5-5` at the pinned configuration driving PostHog's hosted MCP in `cli` and `tools` modes. They do not describe other models, other effort settings, other MCP clients (Cursor, Claude Desktop, ChatGPT), or PostHog AI inside the PostHog app.
- **L-02 Small samples.** The campaign uses N = 5 per scenario per arm (N = 1 in smoke runs). That is enough to find stable failures and rough rates, not to rank arms or detect small differences. No significance is claimed.
- **L-03 Narrow tool surface.** Only analytics queries (`query-trends`, `query-funnel`, `query-retention`, `execute-sql`, `read-data-schema`) and insight saving (`insight-create`, `insight-update`, `insight-get`) are tested — 8 of 1,091 tools in 2 of 72 feature categories at PostHog commit `e606d69`. Dashboards, flags, experiments, surveys, replay, error tracking and the rest are untested.
- **L-04 Synthetic data.** ≈ 60k–90k events for a fictional product with a Hedgebox-style taxonomy. Real projects have messier taxonomies, more events, custom properties, groups and data-warehouse tables. AgentTruth makes **no big-data claim**.
- **L-05 Simplified identity.** Users are identified at most once, person properties never change, no groups, no person-less events. Agent errors that only appear with complex identity graphs are out of reach.
- **L-06 Approximate functions excluded.** Medians and quantiles are not used in scenarios because PostHog's ClickHouse functions are approximate and the oracle is exact; errors specific to them are not measured.
- **L-07 One timezone, no DST.** The project timezone is `America/Mexico_City` (fixed UTC−06:00). DST-transition handling is not tested.

### Validity of the measurement

- **L-08 Truth models PostHog semantics as observed.** Where PostHog's behaviour differs from the oracle's first model, the oracle adopts PostHog's behaviour through a registered divergence (contract §6.4). The exam therefore measures "matches what PostHog computes", which is the user-relevant truth, not an abstract definition. Divergences classed as PostHog defects quarantine the scenario.
- **L-09 Hosted service drift.** PostHog's hosted MCP changes continuously and cannot be pinned. Each attempt records a catalog hash and runs pin the tool listing, so drift is visible, but results apply only to the recorded catalog hashes.
- **L-10 Model drift.** `claude-sonnet-5-5` is an undated model id. Each response's `model` is recorded; behaviour under the same id may still change over time.
- **L-11 No sampling control.** Temperature cannot be set on the model under test; variance is handled only by repetition.
- **L-12 Taxonomy coverage.** Wrong answers that match no precomputed signature are `E_UNCLASSIFIED`. The taxonomy explains only the mistakes it anticipates.
- **L-13 System prompt effect.** Results depend on AgentTruth's frozen exam system prompt and answer-tool descriptions; a different harness prompt could change pass rates.

### Operational

- **L-14 Data processors.** Prompts and PostHog tool results (synthetic) go to Anthropic under standard retention; the MCP connector is not ZDR-eligible. Synthetic events and allowlisted results go to PostHog Cloud US.
- **L-15 Self-exam needs PostHog access.** Agents taking the exam on themselves need a PostHog project with the dataset ingested and the documented project settings; AgentTruth does not provide access to its own projects.
- **L-16 Live gates need the owner's accounts.** K2–K5 and K7 evidence is produced with the owner's PostHog and Anthropic accounts. Anyone can re-verify recorded evidence offline; reproducing live runs requires one's own accounts and the setup in `docs/PREREQUISITES.md`.
- **L-17 Unverified at K0.** Docker base-image tags (resolved in K6), the comment thread of PostHog issue #108309, and model context/output limits for the 5.5 family were not verifiable during K0 (see `docs/RESEARCH.md`, S23, S32, S34).

## Sprint additions

<!-- K1…K7 append here: "### K<n> (YYYY-MM-DD)" followed by L-NN entries. -->
