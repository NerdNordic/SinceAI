# SinceAI and n8n integration

The Streamlit dashboard makes server-side HTTP calls to FastAPI. The browser connects to Streamlit on port 8501; FastAPI remains on port 8000 for application and n8n APIs. With `KPI_BACKEND=n8n`, FastAPI validates requests, adds the effective role, actor and plant scope, authenticates to n8n, and validates the response. n8n owns chat interpretation, routing, registry writes and approvals. Python retains morning briefings and deterministic replenishment calculations.

The local implementation is ready for the contracts below. The actual n8n workflow export is not in this repository: updating and publishing those workflows and live end-to-end verification remain deployment steps. No migration or live workflow execution was performed while implementing this integration.

## Values to configure

Merge values from `n8n.env.example` into your **existing** `application/.env`. The application does not automatically load `.env`; load it in the launching shell as described below. Existing secrets were not read, overwritten or generated into source files.

| Setting | Value / purpose |
| --- | --- |
| `KPI_BACKEND` | `n8n` after updating the workflows; default is `local`. There is no automatic fallback. |
| `N8N_KPI_WEBHOOK_URL` | `https://nerdnordic.app.n8n.cloud/webhook/kpi-chat` from the supplied brief. Confirm against the published Webhook node. |
| `N8N_GOVERNANCE_WEBHOOK_URL` | Proposed new workflow URL: `https://nerdnordic.app.n8n.cloud/webhook/kpi-governance`. Create/publish this workflow first. |
| `N8N_KPI_WEBHOOK_SECRET` | Generate a random secret and use the same value in both n8n Webhook Header Auth credentials, header name `X-KPI-Webhook-Secret`. |
| `N8N_KPI_TIMEOUT_SECONDS` | `90`; allowed range 1–120. HTTPX read/write inactivity timeout; connect/pool timeouts are 5 seconds. Configure the workflow to finish below this budget. |
| `N8N_REPLENISHMENT_SECRET` | A **different** random secret. In n8n's replenishment HTTP Request node, use Header Auth named `X-Replenishment-Secret` with this value. |
| `MONGODB_URI` | Atlas connection URI for the same database used by n8n. In integrated mode the app reads dashboard records and calculation source data; n8n needs write permissions for its workflow. |
| `MONGODB_DB` | `bayer_hackathon`, unless your actual shared database has another name. |
| `DEMO_PLANT` | `Plant-A`, or the factory plant used by the three factory roles. Match n8n's role/scope configuration. |
| `APP_AUTH_MODE` | `local` for loopback-only demo access, or `proxy` for an authenticated deployment. |
| `APP_PROXY_SECRET` | Separate random secret required only for `proxy` mode. Configure it in the trusted reverse proxy and both Python processes; never expose it to the browser. |
| `SINCEAI_API_URL` | Server-side API origin used by Streamlit, default `http://127.0.0.1:8000`. Remote origins must use HTTPS. |

Generate each secret separately in a local terminal, then store it in `.env` and the appropriate credential store:

```powershell
..\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
```

`N8N_WEBHOOK_URL`, `WEBHOOK_SECRET` and `PUBLIC_BASE_URL` retain their original meanings for the legacy approval playbook/callback. Do not point `N8N_WEBHOOK_URL` at `/kpi-chat`. The legacy decision callback now fails closed when its secret is absent. Local UI approval decisions require the authenticated legacy callback; its shared secret is not exposed to the browser.

Gemini credentials are configured in n8n for integrated chat. FastAPI does not need a Gemini key for chat, briefing or the internal replenishment endpoint in n8n mode.

## URLs and authentication directions

| Caller → destination | URL | Authentication |
| --- | --- | --- |
| Browser → local app | `http://localhost:8000/` | Loopback demo; role selector is not login. |
| Browser → hosted app | `https://<your-sinceai-host>/` | Your authenticated reverse proxy. |
| FastAPI → n8n chat | Production KPI URL above | `X-KPI-Webhook-Secret` |
| FastAPI → n8n governance | New governance URL above | `X-KPI-Webhook-Secret` |
| n8n → Python calculation | `https://<your-sinceai-host>/api/internal/replenishment` | `X-Replenishment-Secret` |
| Health probe → app | `/api/health` | Public minimal database health; does not test n8n readiness. |

For testing, replace `/webhook/` with `/webhook-test/` in the relevant configured URL and enable **Listen for test event** in n8n. Production URLs require published workflows. FastAPI requires HTTPS for n8n destinations, does not follow redirects, ignores environment HTTP proxies and does not retry POST requests.

The calculation URL is configured in the n8n HTTP Request node, not in FastAPI's webhook settings. n8n Cloud cannot reach your laptop's `localhost`. Deploy the backend behind HTTPS or provide a deliberately restricted development tunnel for the internal endpoint. Do not expose the loopback demo UI through a tunnel.

## Application identity for hosting

`APP_AUTH_MODE=local` accepts only loopback client addresses and localhost/loopback Host names. It intentionally permits demo role switching. Keep both Uvicorn and Streamlit bound to `127.0.0.1` and do not publish this profile through a reverse proxy or tunnel. Streamlit refuses local demo mode if its listener is configured for non-loopback access. Browser session IP headers are not used as an authentication mechanism.

For hosting use `APP_AUTH_MODE=proxy` and `KPI_BACKEND=n8n`. Your reverse proxy must authenticate the user, support Streamlit WebSocket connections, strip any client-provided copies, and set these headers on the initial Streamlit connection:

- `X-SinceAI-Proxy-Secret`: matching `APP_PROXY_SECRET`.
- `X-SinceAI-User`: authenticated user identifier (maximum 200 characters).
- `X-SinceAI-Role`: one authorized role below.

Streamlit validates these headers per session and forwards only the verified identity headers to FastAPI. It never shares user identity, conversations or cached dashboard responses between sessions. Configure `APP_AUTH_MODE` and `APP_PROXY_SECRET` identically for both processes. The public dashboard can use a private loopback FastAPI origin; expose the calculation route separately where n8n needs it. Restrict direct backend network access. Preserve the public Host and scheme so same-origin write checks work; trust forwarded headers only from the actual proxy. Set an incoming JSON body limit, for example 256 KiB, at the proxy. The `/api/internal/replenishment` route uses its separate service credential instead of an interactive user login; allow n8n to reach that route. Do not forward all `/api/*` routes without authentication.

The UI shows only the authenticated role in proxy mode. A body role that disagrees with the trusted role is rejected. Registry, approval and audit endpoints require the data steward. Factory meter totals are filtered by effective role; steward totals cover all integrated roles.

Roles: `tehtaan_johtaja`, `vuoropaallikko`, `tuotantotyontekija`, `data_steward`. The three factory roles have the configured factory plant; the steward has all-plant scope. This prototype mapping is not a multi-plant user directory.

## Chat contract to implement in n8n

Streamlit sends server-side requests to `POST /api/ask` with `question`, `role`, UUID `sessionId`/`request_id`, `language`, `history`, and optional `chart_id`. FastAPI generates UUIDs if omitted, bounds message/history content, and sends this to n8n:

```json
{
  "message": "OTIF monthly",
  "role": "tehtaan_johtaja",
  "actor": "Authenticated user",
  "sessionId": "27e03283-ff81-45fa-9e62-a7ede0048f88",
  "request_id": "bb11911d-dd3a-4775-a17d-fde2ff38b9b9",
  "language": "en",
  "history": [],
  "chart_id": null,
  "scope": {"plants": ["Plant-A"], "all_plants": false}
}
```

The scope and actor are server-derived. Enforce scope deterministically on normal queries, saved refresh and CSV. Do not infer authorization from LLM output. Only the steward may use `{"plants":[],"all_plants":true}`. Validate saved specs and approval status again. `chart_id` requests may have an empty message and must skip the LLM.

All successful responses must be JSON objects with these **required** fields:

```json
{
  "type": "chart",
  "route": "BUILD",
  "message": "Chart registered and awaiting approval.",
  "request_id": "bb11911d-dd3a-4775-a17d-fde2ff38b9b9",
  "sessionId": "27e03283-ff81-45fa-9e62-a7ede0048f88",
  "data_quality_warnings": [],
  "chart_id": "CH-EXAMPLE",
  "chart_status": "pending_approval",
  "chart": {"data": [{"type":"bar","x":["2026-10"],"y":[95]}], "layout": {}},
  "table": [{"series":"OTIF","period":"2026-10","value":95,"unit":"%"}],
  "csv": "period,value\n2026-10,95\n",
  "receipt": {"source_row_count":1}
}
```

Echo both correlation UUIDs exactly. Allowed combinations:

| `type` | `route` | Additional requirement |
| --- | --- | --- |
| `clarify` | `CLARIFY` | `suggestions` array, no invented calculation |
| `answer` | `ANSWER` or `REUSE` | Optional headline, compact Plotly figure |
| `chart` | `BUILD`, `EXTEND`, `REUSE` | Required `chart_id`; show actual approval status |
| `build_request` | `BUILD` | Required `approval_id` |

Warnings are `{code, kpi_ids, detail}`. Figures use Plotly `{data,layout}`. The application supports ordinary KPI scatter, bar, table, indicator, pie and heatmap traces; external image/map resources are rejected. Receipts, table and figure must describe the same deterministic calculation. No arbitrary code or queries in specs.

Technical failures should use appropriate non-2xx status codes and safe JSON error bodies. The adapter preserves useful 400/403/404/409/429/503/504 statuses, otherwise returns a safe 502. It never passes raw upstream errors to the browser. Schema-invalid 200 responses, mismatched IDs, non-JSON responses and oversized responses fail with 502. HTTP body limit is 8 MB; CSV string limit is 4 million characters and table limit is 20,000 rows. Tighten n8n source query limits to fit these bounds.

A client timeout can happen after writes succeeded. There is no automatic retry, local fallback or implemented request replay. Add persistent deduplication in n8n before enabling retries. `request_id` alone is not idempotency.

## Governance contract to implement in n8n

Create `POST /webhook/kpi-governance` with the same KPI Header Auth credential. The app forwards steward actions as:

```json
{
  "action": "propose",
  "proposal_action": "certify",
  "chart_id": "CH-EXAMPLE",
  "role": "data_steward",
  "actor": "Authenticated steward",
  "request_id": "bb11911d-dd3a-4775-a17d-fde2ff38b9b9"
}
```

`proposal_action` is `certify` or `retire`. Return:

```json
{"approval_id":"APR-EXAMPLE","chart_id":"CH-EXAMPLE","status":"pending"}
```

Decisions use:

```json
{
  "action": "decide",
  "approval_id": "APR-EXAMPLE",
  "approved": true,
  "role": "data_steward",
  "actor": "Authenticated steward",
  "request_id": "bb11911d-dd3a-4775-a17d-fde2ff38b9b9"
}
```

Return the matching `approval_id` and `status` (`approved` or `rejected`), optionally `chart_id`/`message`. Enforce pending-state transitions atomically, identical-decision idempotency and rejection of conflicting decisions. New-chart approval activates only that chart; formula-request approval does not deploy a formula. Only active/certified charts are reusable; never reactivate retired charts during refresh. Record lifecycle changes in `audit_log`.

FastAPI does not write duplicate approval, registry or request records in n8n mode. Legacy callbacks are rejected for integrated approvals.

## Shared record schema and migration boundary

FastAPI's integrated views expect:

- `chart_registry`: `chart_id` (string), `fingerprint`, `title`, `owner`, `role` (creator), `status`, `usage_count`, `used_by_roles`, `created_at`, `updated_at`, `last_used_at`, `kpi_ids`.
- `chart_requests`: one accepted request per `request_id`, with `sessionId`, `role`, `route`, `response_type`, `chart_id`/`approval_id` when applicable, and `ts`.
- `approvals`: `approval_id` (string), `chart_id` when applicable, `title`, `kind`/`action`, `status`, `decided_by`, `created_at`.
- `audit_log`: `ts`, `event`, relevant IDs, `title`, `actor`.

Store UTC timestamps as BSON dates. Integrated registry/approval views are capped at the newest 200 records; audit at 100. Meter aggregation runs in MongoDB. The new-chart count counts registered charts, not every BUILD route, because BUILD may represent a missing-formula request. Legacy `request_log` and `proposals` are not included. Legacy chart documents without `chart_id` remain untouched and excluded from integrated registry reads. Certification/retirement recommendations are not recreated in Python; n8n remains the governance owner.

Before production switchover, inventory legacy documents and approve a dry-run mapping for `use_count -> usage_count`, legacy proposal IDs, statuses and chart IDs. Preserve the Python fingerprint meaning (filter keys) versus the actual n8n fingerprint meaning; never assume equal identity from an unrelated hash. Do not simply give old documents new IDs and assume deduplication works. Use an atomic unique canonical identity for new registrations and verify spec equality. No migrations or indexes are changed automatically by the app. Do not run both engines writing the same registry during migration; use an isolated database for local-mode rollback/testing.

## Python replenishment service

Configure an n8n HTTP Request node:

- Method: `POST`.
- URL: `https://<your-sinceai-host>/api/internal/replenishment`.
- Header Auth credential: `X-Replenishment-Secret` matching `N8N_REPLENISHMENT_SECRET`.
- JSON body below. Send the supported subset of the validated replenishment spec; extra fields/operators are rejected.
- Use a bounded timeout (for example 30 seconds) and route its failures to an explicit webhook error response.

```json
{
  "role": "tehtaan_johtaja",
  "request_id": "bb11911d-dd3a-4775-a17d-fde2ff38b9b9",
  "sessionId": "27e03283-ff81-45fa-9e62-a7ede0048f88",
  "spec": {
    "metric": "Replenishment Reorder-By Date",
    "dimensions": ["product", "market"],
    "filters": {"product_ids":[],"market_ids":[],"plants":[],"statuses":[]},
    "chart_type": "bar",
    "title": "Replenishment priorities"
  }
}
```

Supported status filters: `STOCKOUT_RISK`, `ORDER_NOW`, `URGENT`, `PLAN`, `OK`. This endpoint does not accept caller-supplied all-plant authorization: it derives scope again from the role configuration and rejects forbidden explicit plants. It validates reference IDs, refreshes source calculations, uses the existing `assumptions.json`/reorder model and returns Plotly `chart`, `table`, `csv`, `receipt`, `spec`, IDs and `data_quality_warnings`. `receipt.source_row_count` counts CSV rows; the existing receipt's `source.rows_used` counts replenishment product/market results. CSV includes relevant source history plus supply rows, scoped to eligible pairs. Empty data produces empty results. No Gemini, registry or approval writes occur here.

n8n adds its own route, type, message and chart/approval metadata around this calculation result. Preserve registered metric `MET-REORDER-BY-001`. Validate the needed catalogue/governance entry before enabling it; do not manufacture approval. Keep monthly n8n KPI definitions consistent with Python briefing definitions (currently plant briefing OTIF is a mean of actual-like rows in the latest month).

## Start locally

Run both processes from `C:\Users\jan_k\Documents\SinceAI\application`, using the existing repository-level `.venv`.

Install dependencies once:

```powershell
..\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

In the first PowerShell terminal, load the existing environment and start FastAPI:

```powershell
Get-Content .env | ForEach-Object { if ($_ -match '^\s*([^#=][^=]*)=(.*)$') { Set-Item "env:$($matches[1].Trim())" $matches[2].Trim() } }
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a second terminal in the same folder, load the same environment and start Streamlit:

```powershell
Get-Content .env | ForEach-Object { if ($_ -match '^\s*([^#=][^=]*)=(.*)$') { Set-Item "env:$($matches[1].Trim())" $matches[2].Trim() } }
..\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

This loader expects simple unquoted `KEY=value` lines with no inline comments. On macOS/Linux, activate the repository-level environment and use `set -a; source .env; set +a` in both terminals before running the equivalent Python module commands.

Open **http://localhost:8501/** for the dashboard. FastAPI's root returns service information; interactive API documentation is at http://localhost:8000/docs. The `.streamlit/config.toml` file binds the dashboard to loopback, keeps CORS/XSRF protections enabled and disables usage telemetry. For existing Python-only operation set `KPI_BACKEND=local` explicitly. Both local and n8n figures render through Python Plotly with assets supplied by Streamlit. There are no project-managed JavaScript files, browser CDN imports or npm build steps.

Chat history, responses, language and session IDs live in `st.session_state`. Role or authenticated identity changes clear private conversation state. Ordinary widget reruns and CSV downloads do not resend questions. A timeout consumes the pending event without retrying it. Briefing/dashboard failures do not prevent chat. Dashboard reads are reused within the current session until explicitly refreshed or invalidated by a successful action.

## Verification and rollout

Offline checks:

```powershell
..\.venv\Scripts\python.exe -m pytest tests -q
git diff --check
```

The original nine Excel-based tests need `DATA_PACK_XLSX`; they skip without it. New integration tests use HTTPX mock transport, mongomock and small deterministic source fixtures, so no business data or service secrets are needed. Native Streamlit AppTest tests exercise chat, charts, downloads, role isolation, governance, optional-source failures and rerun behavior. HTTPX mock transport tests cover the server-side UI client and trusted proxy identity. These tests do not invoke live services or provide browser visual verification.

Deployment order:

1. Export the existing n8n workflow into Git and apply the agreed node/security changes. Align exact contracts and shared fields above; original responses without `request_id`/approval IDs will be rejected.
2. Create the governance webhook, configure both outbound Header Auth credentials, and verify all response branches, missing charts, unapproved charts, scope, empty data and errors.
3. Deploy the backend HTTPS endpoint and authenticated UI proxy if needed. Configure the separate inbound calculation credential and connect the n8n replenishment branch.
4. Confirm both components use the same seeded database and plant mapping. Review legacy chart identity migration before enabling reuse across old/new records.
5. Set `KPI_BACKEND=n8n`, load the configured environment in both terminals and restart FastAPI and Streamlit. Smoke-test clarification, one-off answer, BUILD, approved REUSE, EXTEND, missing-formula approval, CSV, saved refresh and governance decisions. Compare representative values to the original deterministic implementation.
6. Test invalid identity/scope, timeouts and repeated/concurrent requests. Verify charts/approvals do not duplicate. Only then publish the deployment for users. Never enable POST retries without persistent deduplication.

Official references: [n8n Webhook authentication and URL lifecycle](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/), [HTTPX timeout semantics](https://www.python-httpx.org/advanced/timeouts/), [Streamlit chart rendering](https://docs.streamlit.io/develop/api-reference/charts/st.plotly_chart), [Streamlit application testing](https://docs.streamlit.io/develop/api-reference/app-testing/st.testing.v1.apptest).
