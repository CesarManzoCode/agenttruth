# AgentTruth

AgentTruth measures how often an AI agent driving PostHog's hosted MCP gives the exact right answer to analytics questions whose truth is known by construction, why it is wrong when it is wrong (a closed error taxonomy), and whether insight settings saved through the MCP survive the round trip. Every claim is meant to be re-checkable with a command against committed, hash-verified evidence. This is a work in progress built sprint by sprint; the normative specification is [`docs/CONTRACT.md`](docs/CONTRACT.md), and the public README arrives with release v1.0.0.
