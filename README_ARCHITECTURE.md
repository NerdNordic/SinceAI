# SinceAI architecture

## Request path

1. The Vue interface in `fastapi+vue/app/static/` calls the same FastAPI process.
2. `app/main.py` validates API input, including the `en`/`fi` language allowlist.
3. `app/spec.py` asks Gemini for a validated `ChartSpec`, sanitizes filters against
   catalog data and caches responses by model, prompt version, context and language.
   Selected response language is also passed as a Gemini system instruction.
4. `app/engine.py` identifies charts by metric, dimensions and filter keys. The
   fingerprint is independent of language and filter values. It chooses REUSE,
   EXTEND, ANSWER, BUILD or CLARIFY. Chat-only turns do not count as chart requests.
5. `app/metrics.py` computes governed numbers from MongoDB data. `reorder/` computes
   inventory coverage, runout dates, replenishment deadlines and risk status.
6. Gemini words a short response from computed results; deterministic localized
   fallbacks handle unavailable answer generation. Results include definitions,
   source rows, filters and warnings, with raw CSV downloads.

## Data and state

The workbook is imported directly into MongoDB by `seed_mongo.py`. Source
provenance is retained in `_source`. Canonical KPI aliases and asset enrichment
support vector search in `kpi_catalog`, `analytics_assets` and `chart_registry`.
`vector_store.py` is the single implementation used by the importer, application
and search diagnostics. Numeric computation uses ordinary queries, not embeddings.

The application writes `chart_registry`, `request_log`, `results`, `conversations`,
`proposals`, `audit_log` and `llm_cache`. Registry entries retain chart ownership,
usage, lifecycle status and localized titles. Reusing a chart does not create a
second chart when the language or selected filter values change.

`assumptions.json` defines replenishment assumptions and their version/fingerprint.
The included workbook is also the offline regression fixture. Source workbook and
challenge documents remain in the data-pack directory.

## Presentation

Vue 3 and Chart.js are loaded from pinned CDN URLs; there is no Node build step.
CSS variables control appearance. Plain JavaScript dictionaries translate UI
labels, statuses, examples and chart labels. Browser storage remembers language
and theme, with safe defaults if storage is unavailable. Existing conversation
messages are preserved in the language in which they were written.

Backend presentation translations live in `app/i18n.py`. They do not change metric
identifiers, source queries, fingerprints or computed values. API language defaults
to English, and unsupported language values are rejected before calling Gemini.

## Governance integration

The optional `n8n/build-less-governance-scan.json` scans the same MongoDB registry,
proposes certification/retirement and records audit entries. The backend can also
notify an optional approval webhook. Data-steward decisions update proposal and
chart lifecycle state. See `n8n/N8N.md` for configuration.

## Runtime and verification boundaries

Runtime packages are in `fastapi+vue/requirements.txt`. Test-only packages are in
`requirements-dev.txt`. Root `pyproject.toml` scopes pytest to the supported suite
and makes the application modules importable from the repository root.

The backend regression suite loads synthetic workbook data into mongomock and
replaces Gemini. The Node checks exercise language/theme-facing frontend logic
without npm dependencies. Live search diagnostics are separate because they call
Gemini/Atlas and their chart test temporarily writes to the registry.

This remains a local prototype: role selection is not authentication, and the
callback secret does not protect every API route. Source queries, calculations,
current retry behavior and database sessions were preserved during the cleanup.
Do not expose the server to a shared network without a separate security review.
