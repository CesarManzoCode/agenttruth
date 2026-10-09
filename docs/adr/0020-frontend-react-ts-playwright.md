# ADR-0020 — React 19 + TypeScript 6 + Vite, served by Django; Playwright (TS) on Docker Compose

- Status: Accepted (K0)
- Contract: K6, §16, D-20

## Context
R2/R5 require React with TypeScript; R6 requires basic UX. PostHog pins TypeScript 6.0.3 and Playwright TS (S01u).

## Decision
React 19.3 + TypeScript 6.0.3 (strict) + Vite 8, TanStack Query, React Router; built assets served by Django via WhiteNoise (one origin, no CORS). E2E with `@playwright/test` against `docker compose up --wait` with no API mocks; accessibility smoke with axe.

## Alternatives rejected
- **TypeScript 7 (native compiler).** Newest major; typescript-eslint supports `<6.1.0`; PostHog stays on 6.0.3.
- **React 18 (PostHog's pin).** No reason to start a new app on the previous major.
- **Separate frontend server in production.** Extra service, CORS, no benefit.
- **Python Playwright.** Fine technically, but TS keeps frontend tests with frontend code, as PostHog does.
