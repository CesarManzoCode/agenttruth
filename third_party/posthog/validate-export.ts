// AgentTruth (MIT): validates a PostHog tasks.yaml v2 file against the vendored benchmark schema.
// Usage: npx --no-install tsx validate-export.ts <tasks.yaml>
// Exit 0 and a JSON summary when valid; exit 1 with the zod issues when not.
import { readFileSync } from 'node:fs'
import { parse as parseYaml } from 'yaml'

import { BenchmarkFileSchema } from './services/mcp/evals/benchmark/schema.ts'

const file = process.argv[2]
if (!file) {
    console.error('usage: validate-export.ts <tasks.yaml>')
    process.exit(2)
}
const result = BenchmarkFileSchema.safeParse(parseYaml(readFileSync(file, 'utf-8')))
if (!result.success) {
    console.error(JSON.stringify({ ok: false, issues: result.error.issues }))
    process.exit(1)
}
console.log(JSON.stringify({ ok: true, version: result.data.version, tasks: result.data.tasks.length }))
