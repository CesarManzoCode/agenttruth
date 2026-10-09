# Vendored PostHog files

These files are verbatim, unmodified copies from the PostHog repository. They are MIT-licensed
(PostHog's `LICENSE`, copied verbatim beside this file, applies to everything outside PostHog's
`ee/` directory; none of these files is under `ee/`). Copyright (c) 2020-2026 PostHog Inc.

- Upstream: https://github.com/PostHog/posthog
- Commit: `e606d69fc4d9a7920ee4c2cbcd7cac62f915f58a` (committed 2026-10-09T03:55:16Z)
- Fetched: 2026-10-09, sparse partial clone (`git clone --filter=blob:none --sparse`)

| Vendored path | Upstream path | Git blob | SHA-256 | Bytes |
|---|---|---|---|---|
| `services/mcp/evals/benchmark/schema.ts` | `services/mcp/evals/benchmark/schema.ts` | `b2d3a86bd3d18dc8fa433131e29d18a7d5f558e5` | `bb99a30faaf546030f7b2e043f8a3409a798eefd7bb583e0f181bb8c752bfc06` | 6180 |
| `posthog/schema.py` | `posthog/schema.py` | `6dd039d82772f0f47c09d92be565a669d18ac5f2` | `88c334b8de48332ec2eeed8510dfb595c6387516efd8287c72891cc5cc4b81c5` | 1446094 |
| `posthog/schema_enums.py` | `posthog/schema_enums.py` | `9c1ba21f597b984fa8b51c1823afe23696536646` | `b2c8b422e3fb119f173b51dcf019af17defc430a973d447da8c04e40f74c5d24` | 87370 |
| `LICENSE` | `LICENSE` | `847d9d3def03458035447bdae131e1981e2a63da` | `6d82d67dba42eb94ba10f1e986d2eec338c22fb7c5216c2c0ebdecd83d53a029` | 1563 |

`posthog/schema_enums.py` is vendored with `posthog/schema.py` because `schema.py` imports its enum
classes from it; the enum values are needed to read defaults such as
`TrendsFilter.display = ChartDisplayType.ACTIONS_LINE_GRAPH`.

## Re-fetch and verify

```bash
git clone --filter=blob:none --sparse --no-checkout https://github.com/PostHog/posthog.git posthog
cd posthog
git sparse-checkout set --no-cone /services/mcp/evals/benchmark/ /posthog/schema.py /posthog/schema_enums.py /LICENSE
git checkout e606d69fc4d9a7920ee4c2cbcd7cac62f915f58a
git ls-tree e606d69fc4d9a7920ee4c2cbcd7cac62f915f58a services/mcp/evals/benchmark/schema.ts posthog/schema.py posthog/schema_enums.py LICENSE
```

From this repository's root, `git hash-object third_party/posthog/<vendored path>` must print the
blob id in the table.
