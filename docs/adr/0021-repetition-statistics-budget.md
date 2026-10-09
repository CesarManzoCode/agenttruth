# ADR-0021 — Repetition, statistics and budget policy

- Status: Accepted (K0)
- Contract: K3, K7, D-21

## Context
Sampling cannot be fixed on the model under test (F-18), so variance is controlled only by repetition. The budget is limited; claims must not exceed what the sample supports.

## Decision
- Smoke (K3, K4): N=1 per scenario per arm. Campaign (K7): N=5 per scenario per arm.
- Report per scenario/arm: pass count, Wilson 95% interval; class counts; `stable_fail` (same non-PASS class ≥ 4/5), `flaky` (1–3 non-PASS of 5). Arm comparisons are descriptive; no significance claims.
- Budget: K7 cap $100 (total plan $145 across K3–K7). Projection = K3/K4 measured mean cost per attempt × planned attempts. If projection > cap: first reduce `tools` arm to N=3; if still above, reduce `cli` arm to N=3; if still above, BLOCKED. N never below 3.
- Infra classes are excluded from denominators and reported separately.

## Alternatives rejected
- **N=10+.** Doubles cost; not needed to find stable failures.
- **Bootstrap or significance tests between arms.** Misleading at N=5.

## Consequences
- The results report says exactly what N supports: stable failures and rough rates, not rankings.
