# SinceAI architecture

This document describes the implemented FastAPI + Vue prototype. See the
[project README](../README.md) for setup and the [application guide](../application/README.md)
for configuration and API routes. The original challenge asks for broader BI-estate
governance; not every challenge workflow is implemented by this application.

## Components

```text
Browser (Vue 3 + Chart.js)
  -> FastAPI routes and language/input validation
     -> Gemini: validated ChartSpec / conversational reply
     -> Decision engine: fingerprint and registry lookup
        -> Python metrics + replenishment model: computed values and evidence
        -> MongoDB: source data, registry, conversations, results and audit state
     -> Gemini: short answer using computed values, or deterministic fallback
  <- Localized answer, chart/table, calculation receipt and CSV link

Optional n8n schedule -> same MongoDB -> proposals and audit entries
Human decision -> FastAPI -> proposal and chart lifecycle update
```

Gemini is an external service, not a computation engine. Vector search suggests
KPI/report/chart candidates; it does not replace canonical metric calculations or
the deterministic chart fingerprint.

## Question-to-result path

1. `backend/main.py` checks the role and non-blank question. Pydantic restricts the
   selected language to `en` or `fi` before calling the model.
2. `backend/spec.py` uses history and optional KPI hints to request a structured
   `ChartSpec`. It validates the response and sanitizes product/market/plant filters
   against catalog lookups. Canonical metric IDs and schema enums remain unchanged.
3. Chat-only replies are saved as conversation turns without incrementing the
   analytics request meter. Ambiguous/unsupported specifications return CLARIFY.
4. `backend/engine.py` fingerprints metric, sorted dimensions and non-empty filter keys.
   The fingerprint excludes language, title and filter values. An active/certified
   matching chart is REUSE for the same filters or EXTEND for changed values. Without
   a match, a one-off request is ANSWER; a recurring request registers a BUILD.
5. `backend/metrics.py` queries source collections and computes governed results.
   `backend/replenishment/` computes demand, inventory cover, effective lead time, safety stock,
   runout dates, order deadlines and risk statuses using `config/assumptions.json`.
6. The response includes a definition, KPI ID, selected filters, source provenance,
   warnings and a raw-data download. Gemini may word the result; if this answer
   generation fails, a deterministic fallback uses the computed values.

CSV downloads retrieve source rows according to the saved result source/query;
they are not immutable historical snapshots of a changing live database.

## Source data and persistent state

[The importer](data-import.md) reads 21 data sheets from the synthetic
workbook into MongoDB collections, preserving numeric types and `_source` details.
It enriches KPI aliases and report descriptions and defines three vector indexes:
`kpi_vector`, `asset_vector`, `chart_vector`. Source collection refreshes replace
contents; application state is not the source import's purpose.

| Collection | Application state |
| --- | --- |
| `chart_registry` | Fingerprint, canonical spec, filters, ownership, use count, role use, lifecycle and localized titles. |
| `conversations` | Ordered question/answer turns and follow-up context. |
| `request_log` | Analytics requests, decisions and fingerprints for the meter. |
| `results` | Source/query metadata used for raw CSV retrieval. |
| `proposals` | Pending/approved/rejected certification and retirement proposals. |
| `audit_log` | Chart registration, proposal and decision events. |
| `llm_cache` | Specification and answer caches keyed by prompt version, model, inputs and language. |

`backend/db.py` maintains a process-local shared MongoDB database handle and cached
small catalog lookups. `backend/metrics.py` caches replenishment results by database
identity and evaluation date. These caches are not distributed invalidation systems;
restart the app after replacing source data to refresh process-local lookups/results.

## Presentation and localization

`frontend/index.html` contains the Vue interface and Chart.js rendering. Both
libraries load from pinned CDN URLs, so there is no frontend package manager or
build step. CSS variables control dark/light mode. `frontend/i18n.js` translates
labels, status values, examples and chart presentation; `backend/i18n.py` translates
backend briefings, definitions, warnings and fallback text.

English/dark are defaults. Browser storage saves the choice and safely falls back
when storage is blocked. Requests carry the selected language; Gemini receives it
in prompts and system instructions. Caches are separated by language. Switching
language preserves conversation history and chart identity and does not translate
previous model replies through additional LLM calls. Source identifiers stay intact.

The Data Steward's governance view also lists the imported business requests
(`GET /api/business-requests`): filterable by urgency, status, product and
market, ordered urgency first, with an action that sends a request's text into
the conversation for the reuse-before-build flow. The conversation is shared by
all roles; factory roles keep their dashboard view.

## n8n and approvals

The bundled [governance scan](../integrations/n8n/README.md) reads MongoDB directly every five minutes,
proposes chart certification or retirement, and writes audit entries. It does not
need inbound access to the local backend. People decide proposals in the app/API.
A separately configured `N8N_WEBHOOK_URL` can notify an approval playbook and
include a `PUBLIC_BASE_URL` callback; that is distinct from the bundled scan.

If `WEBHOOK_SECRET` is set, the decision endpoint requires `X-Webhook-Secret`.
The current frontend does not send that secret; use an authorized API/playbook
caller for that configuration. The secret is not general authentication.

## Failure and security boundaries

- Optional KPI hints and similar-chart/report searches can fail without aborting
  the deterministic registry/computation path.
- A new specification still needs Gemini. Provider failures may fail the request
  after retries; there is no offline specification stub in the supported app.
- Structured specifications are validated; generated prose remains model output
  and should be reviewed. The prototype is not a production governance guarantee.
- Role/plant selection is user-supplied context, not an authenticated permission
  boundary. Conversation/result IDs do not establish per-user access control.
- Most routes have no authentication. Keep Uvicorn bound to `127.0.0.1` and
  credentials out of the browser, logs and Git.
- All included data is synthetic; no patient/HCP data is represented.

## Verification boundaries

Runtime requirements live in `application/requirements.txt`; development requirements
add pytest/HTTPX/mongomock. Root `pyproject.toml` configures supported test discovery.
The backend suite loads the workbook into mongomock and replaces Gemini. The Node
checks simulate browser APIs. They verify behavior without external writes or a
visual browser session. Live Atlas/Gemini diagnostics are separate commands.
