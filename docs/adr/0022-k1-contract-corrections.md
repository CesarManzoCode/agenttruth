# ADR-0022 — K1 contract corrections (contract 1.0.1)

- Status: Accepted (owner decision on the K1 BLOCKED report, 2026-10-09)
- Contract: §2.5 F-23, §7.4, §14 K1 (allowed dependencies, K1-C3, K1-C4), §16; contract 1.0.0 → 1.0.1
- Evidence: commit `4b95625` (K1 BLOCKED report `reports/K1.yaml` and `evidence/K1/`), vendored files in `third_party/posthog/` (PostHog commit `e606d69fc4d9a7920ee4c2cbcd7cac62f915f58a`)

## Context

The first K1 run stopped with BLOCKED (contract §17, condition 2, related condition 4) before any code was written. Reading the pinned PostHog sources and the K1 gate side by side surfaced four problems in contract 1.0.0. The owner approved the four recommendations of that report and authorised this one amendment.

1. **RS value equal to its schema default.** §7.4 lists `retentionFilter.totalIntervals=8` among the round-trip values. §7.4 also requires every RS value to differ from its default in the vendored `posthog/schema.py`, and K1-C6 enforces that rule. At the pin, `posthog/schema.py` (git blob `6dd039d82772f0f47c09d92be565a669d18ac5f2`) declares `RetentionFilter.totalIntervals: int | None = 8` at line 29705. `AssistantRetentionFilter.totalIntervals` also defaults to 8, described as "8 (meaning 7 periods after initial cohort)" (lines 10651–10656). F-23 said the default was "7 total intervals". The 7 is `DEFAULT_TOTAL_INTERVALS` in `retention_query_runner.py` (line 71), which the runner uses only when the value is null or 0 (lines 385 and 387). An AST comparison of all 26 RS values against the snapshot found this the only collision (`evidence/K1/rs-defaults-check.json`, sha256 `8502959abaa4dd68790ee5638fb346b3f8995e39f0a35437c73199ed65b03075`, at commit `4b95625`).
2. **K1-C4 cannot hold as written.** K1-C4 required that disabling a fault change "no other EA truth". The 1.0.0 catalog makes that impossible:
   - F1 drops Android `uploaded_file` events on 2026-07-15..17. That window lies inside `ea-uploads-july-filtered` (uploads 2026-07-01..07-31, §7.2) and `ea-uploads-by-os-july`, so disabling F1 must change both truths.
   - F3 drops `$identify` for `/signup/mobile` sign-ups on 2026-06-22..28. Those users split from their later activity, which changes the June sign-up metrics (`ea-funnel-signup-upload-june`, `ea-funnel-signup-upload-1d`, `ea-sql-power-uploaders`). The resulting conversion drop is the symptom §5.2 plants on purpose.
3. **K1-C3's scope was ambiguous.** K1-C3 said "every scenario declares ≥ 3 signatures". §6.3 defines signature transforms only for exact-answer scenarios, and a planted-cause answer is a cause, not a number.
4. **The Node validator was not pinned.** §14 K1 validates the export with `npx tsx` against the vendored `schema.ts`, which imports `zod` and `yaml` when the module loads. §16 did not pin `zod`, `yaml` or `tsx`. PostHog's `pnpm-lock.yaml` at the pin resolves them for `services/mcp` to `zod` 4.3.6, `yaml` 2.9.0 and `tsx` 4.20.5 (S01v).

## Decision

1. The RS value becomes `retentionFilter.totalIntervals=10`. It differs from the schema default (8) and from the runner fallback (7). F-23 now says that 8 is the schema default at the pin and 7 is only the runner fallback.
2. Each exact-answer scenario declares in the catalog the planted faults its truth overlaps (`agenttruth.fault_overlaps`, a list of `F1`…`F5`, possibly empty). K1-C4 checks exactly that declaration, together with the fault's footprint and its planted-cause probe metrics. For each fault, rebuilding with the fault disabled must:
   - change events only inside the fault's declared window and segment, including the first and last day of the window;
   - change every probe metric of the fault's planted-cause scenario;
   - change every exact-answer truth declared as overlapping the fault, and no other.
3. K1-C3's minimum of three declared signatures applies to exact-answer scenarios only. Planted-cause scenarios declare none.
4. §16 pins `zod` 4.3.6, `yaml` 2.9.0 and `tsx` 4.20.5 for the Node validator of the PostHog export. They are pinned exactly in `third_party/posthog/`.

## Alternatives rejected

- **Remove `totalIntervals` from the RS list.** This loses a round-trip field for no gain.
- **Compare `totalIntervals` against the runner fallback (7).** This contradicts §7.4's stated default source. It also keeps a value that PostHog's schema fills in when the key is missing, so a stored 8 could not show whether the setting survived.
- **Move fault windows or exact-answer date ranges so that nothing overlaps.** This changes scenario ids and meanings fixed by §7.4 (for example "july"), or the faults of §5.2. It also removes the conversion-drop symptom F3 is meant to plant.
- **Infer the overlaps at gate time instead of declaring them.** An inferred set cannot be wrong, so the check could not fail. A declared set can, in both directions.

## Consequences

- No evidence is invalidated. Catalog v1, the datasets and the truths did not exist when this amendment was made.
- The catalog gains one field, `agenttruth.fault_overlaps`, on every exact-answer scenario. A change to a fault or a scenario that alters an overlap now fails K1-C4 until the declaration is updated.
- K4 tests `totalIntervals=10`, a value that cannot be confused with a default.
