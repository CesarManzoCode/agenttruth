# ADR-0006 — Dataset `ds1`: Hedgebox-compatible taxonomy, hash RNG, absolute window, fixed non-UTC timezone

- Status: Accepted (K0)
- Contract: §5, D-06

## Context
Truth must be known by construction, stable forever, and the dataset must exercise the semantics agents get wrong (periods, timezones, unique vs total, test accounts, funnel windows, retention types, identity). PostHog's own Hedgebox data is reproducible only per simulation version and its docs advise against absolute counts (S01b).

## Decision
- Taxonomy: Hedgebox event and property names (S01b, S01t) so PostHog engineers recognise it and scenario intents port to their harness; generation logic is AgentTruth's own.
- Randomness: counter-based BLAKE2b streams only; no `random`/`numpy`/clock; canonical JSONL; build is a pure function (§5.1).
- Time: absolute window 2026-06-01..2026-08-31 plus a warm-up 2026-05-18..2026-05-31, all in the past at ingestion (≥ 48 h, S07). Scenarios use absolute dates only.
- Project timezone `America/Mexico_City` (UTC−06:00, no DST since 2022) and `week_start_day = Monday`, applied explicitly (new projects default to UTC, S01s).
- Identity kept to the documented case (anonymous → identify once; properties set once) so point-in-time and current person properties coincide (S14, S15).
- Five planted faults in disjoint segments/windows (§5.2).
- Volume 60k–90k events.

## Alternatives rejected
- **Relative dates ("last 30 days").** Truth would change daily.
- **UTC project timezone.** Timezone mistakes would be invisible.
- **Timezone with DST.** Adds ambiguous local hours whose PostHog handling is not documented; the non-UTC offset already makes timezone errors observable.
- **Python `random` with a seed.** Only `random()` is guaranteed stable across versions; helper methods are not.
- **Larger datasets.** No requirement served; costs read budget; risks quotas.

## Consequences
- Every truth is a fixed number per dataset version; datasets are never edited in place.
- Free-plan retention (1 year) is irrelevant on pay-as-you-go (7 years, S10).
