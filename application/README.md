# SinceAI application - FastAPI + Vue

This folder contains the supported application. FastAPI serves a Vue 3 / Chart.js
page and a JSON API on port 8000. It uses MongoDB, Gemini and the deterministic
`backend/replenishment/` model. See the [project README](../README.md) for the product overview,
first-time Windows setup and a full startup block from any project directory.

Application settings live in the Git-ignored `.env` beside `.env.example`.
The shared Python environment is `../.venv/`.

## Start from this folder - Windows PowerShell

The first line selects the actual application folder, regardless of your current
terminal directory. Load settings before importing the backend:

```powershell
Set-Location -LiteralPath 'C:\Users\jan_k\Documents\SinceAI\application'
$sinceaiEnv = '.\.env'
Get-Content -LiteralPath $sinceaiEnv -ErrorAction Stop | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') {
        Set-Item -Path "env:$($matches[1])" -Value $matches[2].Trim()
    }
}
& '..\.venv\Scripts\python.exe' -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open http://localhost:8000. The process serves `/docs` and `/api/health` as well.
Stop it with **Ctrl+C**. Do not create another `.venv` here, run Python separately
from its `-m` arguments, or start another server on the occupied port.

The loader reads the single `.env` file using simple unquoted `KEY=value` lines. It
sets process environment variables in the current terminal; the backend itself
does not discover `.env` files. Restart Uvicorn when changing settings.

## macOS and Linux

From the repository root, create/install the shared environment if needed:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r application/requirements.txt
```

Export your configured variables through your shell or secret manager, then:

```bash
cd 'application'
../.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Exported `MONGODB_URI` and `GEMINI_API_KEY` are required for live database/AI use;
set the other variables below as needed. Avoid sourcing an untrusted environment
file as shell code. There is no npm or frontend build step.

## Configuration

These names are read by the current source. Defaults below describe the code,
not a guarantee that a remote model is available to your account.

| Variable | Code default | Purpose |
| --- | --- | --- |
| `MONGODB_URI` | Empty | MongoDB connection string; required for database-backed operations. |
| `MONGODB_DB` | `bayer_hackathon` | Source and application-state database. |
| `GEMINI_API_KEY` | Empty | Required for new Gemini generation and embeddings. |
| `GEMINI_MODEL` | `gemini-3.5-flash` | Generation model; configure an account-supported model. |
| `DEMO_PLANT` | `Plant-A` | Default plant for the three factory roles. |
| `TODAY` | System date | Optional ISO date for deterministic demo risk statuses; `.env.example` pins `2026-11-06`. |
| `REVIEW_DAYS` | `90` | Days until a newly registered chart's review date. |
| `RETIRE_IDLE_MINUTES` | `43200` | Inactivity threshold for retirement suggestions. |
| `N8N_WEBHOOK_URL` | Empty | Optional outbound approval-playbook webhook. |
| `WEBHOOK_SECRET` | Empty | If set, requires a matching `X-Webhook-Secret` on the decision endpoint. |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | Base URL sent in the optional playbook callback. |
| `GEMINI_EMBED_MODEL` | `gemini-embedding-001` | Embedding model used by the shared vector helper. |
| `EMBED_DIM` | `768` | Embedding/index dimension; changing it requires data/index updates. |
| `EMBED_RPM` | `90` | Process-local embedding pacing budget. |
| `DATA_PACK_XLSX` | Included workbook | Test fixture override; it does not select live application data. |

Check `backend/config.py` and `backend/vector_store.py` when adding configuration. Values such
as `APP_AUTH_MODE`, `KPI_BACKEND` or `N8N_KPI_WEBHOOK_URL` left in older local files
are not read by this implementation. Do not infer enabled authentication or an
alternate KPI backend from those entries.

When `WEBHOOK_SECRET` is set, the browser's built-in approval action currently
does not send that header. Use an authorized API/playbook caller for decisions;
do not place the secret in the frontend or disable it to expose the app publicly.

## Interface and roles

| Role ID | English label | Scope |
| --- | --- | --- |
| `tehtaan_johtaja` | Plant director | Factory context, default `DEMO_PLANT`. |
| `vuoropaallikko` | Shift supervisor | Factory context, default `DEMO_PLANT`. |
| `tuotantotyontekija` | Production worker | Factory context, default `DEMO_PLANT`. |
| `data_steward` | Data steward | Registry, proposals and audit view; no default plant filter. |

The header selects **English / Suomi** and **light / dark**. English and dark are
the defaults. Preferences are stored as `sinceai-language` and `sinceai-theme` in
browser storage. The selected language controls new model replies, clarifications,
chart titles, briefings, receipts and deterministic fallback text. Existing chat
messages are preserved; changing language does not call Gemini to translate history.

Language is not part of the chart fingerprint: changing language does not duplicate
a chart. Example English prompts include "Show monthly delivery reliability",
"Which products are at risk of running out?" and "What about Finland?".

## Operational tools

Run tools as modules from this directory so backend imports resolve consistently:

```powershell
& '..\.venv\Scripts\python.exe' -m tools.seed_mongo --help
& '..\.venv\Scripts\python.exe' -m tools.search --help
& '..\.venv\Scripts\python.exe' -m tools.check_vector_search --help
& '..\.venv\Scripts\python.exe' -m backend.replenishment.cli --help
```

Import/search tools live in `tools/`; shared runtime search code lives in
`backend/vector_store.py`. Configuration JSON files live in `config/`. Their
defaults are resolved relative to the installed source locations, not the shell's
working directory. Original data assets live in `../data/bayer/`.

## Governed metrics

The current allowlist includes Net Sales, Net Sales Growth, Units Shipped,
Inventory Coverage, On-Time In-Full, Forecast Variance, Market Access Coverage,
Demand Forecast Accuracy and Replenishment Reorder-By Date. `backend/metrics.py`
defines computation; `backend/replenishment/model.py` defines replenishment formulas and
`config/assumptions.json` supplies versioned assumptions. Source IDs and formulas stay
traceable when presentation language changes.

## API reference

Use `/docs` for the generated request/response schemas.

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/api/roles` | Role labels; optional `language=en` or `fi`. |
| GET | `/api/briefing/{role}` | Localized role briefing; optional `language`. |
| POST | `/api/ask` | Question, role, optional session ID and language. |
| GET | `/api/conversations/{session_id}` | Stored conversation. |
| GET | `/api/results/{result_id}/raw.csv` | Source rows for a computed result. |
| GET | `/api/meter` | Request and chart-reuse counts. |
| GET | `/api/registry` | Chart lifecycle, ownership, usage and suggestions. |
| GET | `/api/registry/{fingerprint}/preview` | Rendered preview of a live (non-retired) chart with receipt. |
| POST | `/api/registry/{fingerprint}/propose` | Create a `certify` or `retire` proposal. |
| POST | `/api/registry/decision` | Approve/reject a proposal; optional secret check as configured. |
| GET | `/api/proposals` | Proposal list. |
| GET | `/api/business-requests` | Data-pack business request intake, newest first. |
| GET | `/api/audit` | Recent audit events. |
| GET | `/api/health` | MongoDB access/counts and configured model; no Gemini probe. |

Example request (JSON body in `/docs` or your API client):

```json
{
  "role": "tehtaan_johtaja",
  "question": "Show monthly delivery reliability",
  "language": "en",
  "session_id": null
}
```

Reuse the returned `session_id` for follow-up questions. Language defaults to
English; unsupported values are rejected with HTTP 422. A valid role and a
non-blank question are required. Identifiers remain unchanged across languages.

## Development and verification

Run from this folder:

```powershell
& '..\.venv\Scripts\python.exe' -m pip install -r requirements-dev.txt
$env:N8N_WEBHOOK_URL = ''
& '..\.venv\Scripts\python.exe' -m pytest -q
node tests/frontend/preferences.test.cjs
node tests/frontend/chart_colors.test.cjs
& '..\.venv\Scripts\python.exe' -m pip check
```

Use a separate test terminal. Clearing `N8N_WEBHOOK_URL` there prevents an inherited
live webhook configuration from sending notifications during proposal tests.
`requirements.txt` contains runtime dependencies. `requirements-dev.txt` adds
pytest, HTTPX and mongomock. Root `pyproject.toml` configures test discovery/imports.
The backend tests use the included workbook and fake services; the Node checks
(preferences and chart-color tests) use simulated browser APIs.
Neither is a full visual browser test.
`tools/check_vector_search.py` is a separate live diagnostic, not part of the offline suite.

## Module map

| Path | Responsibility |
| --- | --- |
| `backend/main.py` | HTTP routes, input validation and static-file serving. |
| `backend/config.py`, `backend/db.py` | Environment settings and shared MongoDB access. |
| `backend/spec.py` | Structured Gemini specification, response text and language-aware caches. |
| `backend/engine.py` | Fingerprints, reuse decisions, persistence and approvals. |
| `backend/metrics.py`, `backend/replenishment/` | Governed calculations and replenishment exports. |
| `backend/briefing.py` | Role summaries and exception lists. |
| `backend/i18n.py`, `frontend/i18n.js` | Deterministic backend/frontend translations. |
| `frontend/index.html` | Vue interface, chart rendering and appearance controls. |
| `tools/seed_mongo.py`, `backend/vector_store.py` | Workbook import, enrichment, embeddings and search helpers. |
| `tools/search.py`, `tools/check_vector_search.py` | Live search CLI and integration diagnostics. |

See [data import and exports](../docs/data-import.md), [architecture](../docs/architecture.md)
and [n8n integration](../integrations/n8n/README.md). This prototype has no general authentication
or per-user authorization. Keep it bound to loopback.
