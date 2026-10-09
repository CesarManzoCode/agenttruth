# AgentTruth — developer and CI entry points (contract §14, §16).
UV ?= uv
RUN := $(UV) run --frozen
export PYTHONDONTWRITEBYTECODE := 1

.PHONY: check lint format-check types schemas-check rs-defaults-check test node-deps \
        export gate-K1 gates verify-evidence locks truths evidence-K1

## check: lint, format check, strict types, schema drift, defaults drift, offline tests
check: lint format-check types schemas-check rs-defaults-check test

lint:
	$(RUN) ruff check .

format-check:
	$(RUN) ruff format --check .

types:
	$(RUN) mypy --strict src

schemas-check:
	$(RUN) python -m agenttruth.schemagen --check

rs-defaults-check:
	$(RUN) python -m agenttruth.scenarios.rs_defaults --check

test:
	$(RUN) pytest -q -n auto

## node-deps: the pinned Node validator of the PostHog export (zod 4.3.6, yaml 2.9.0, tsx 4.20.5)
node-deps: third_party/posthog/node_modules/.bin/tsx

third_party/posthog/node_modules/.bin/tsx: third_party/posthog/package-lock.json
	cd third_party/posthog && npm ci --no-audit --no-fund

## export: PostHog tasks.yaml v2 export of the catalog, validated against the vendored schema.ts
export: node-deps
	$(RUN) agenttruth scenarios export --format posthog-tasks-v2 --out build/export/tasks.yaml
	cd third_party/posthog && npx --no-install tsx validate-export.ts ../../build/export/tasks.yaml

## gate-K1: the independent K1 checker; writes build/gates/K1/gate-K1.json (committed evidence is untouched)
gate-K1: node-deps
	$(RUN) agenttruth gate K1 --out build/gates/K1

## gates: every gate whose committed evidence exists, plus verification of that evidence
gates: node-deps
	@set -e; found=0; \
	for dir in evidence/K*; do \
	  n=$$(basename $$dir); [ -f "$$dir/gate-$$n.json" ] || continue; found=1; \
	  echo "== gate $$n"; $(MAKE) --no-print-directory gate-$$n; $(RUN) agenttruth evidence verify $$dir; \
	done; \
	if [ $$found = 0 ]; then echo "no gate evidence committed yet"; fi

## verify-evidence: re-hash every committed evidence directory
verify-evidence:
	@set -e; for dir in evidence/K*; do [ -d "$$dir" ] && $(RUN) agenttruth evidence verify $$dir; done

## locks: rebuild datasets/*.lock.json (a lock change must be explained in the sprint report)
locks:
	$(RUN) python -m agenttruth.dataset.lock --spec ds0
	$(RUN) python -m agenttruth.dataset.lock --spec ds1

## truths: recompute truths/ds1.v1.json with the oracle CLI (never edit it by hand)
truths:
	rm -rf build/truths-ds1
	$(RUN) agenttruth dataset build --spec ds1 --out build/truths-ds1
	$(RUN) agenttruth oracle compute --dataset build/truths-ds1 --catalog scenarios/catalog.v1.yaml --out truths/ds1.v1.json

## evidence-K1: run the K1 gate and write its report into evidence/K1 (sprint closing step)
evidence-K1: node-deps
	$(RUN) agenttruth gate K1 --out evidence/K1
