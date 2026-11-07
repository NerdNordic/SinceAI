# SinceAI - Build Less assistant

SinceAI is a local prototype for the **Bayer challenge at Since AI 2026**. It turns
business questions into governed plant analytics, reuses charts where possible,
and shows how the figures were calculated. All supplied operational data is
synthetic and does not represent actual Bayer performance.

## What the application does

- Offers plant-director, shift-supervisor, production-worker and data-steward views.
- Shows morning briefings, inventory risks and replenishment priorities.
- Answers questions with charts, tables, calculation receipts and raw-source CSV exports.
- Chooses **Reuse**, **Extend**, **One-off answer**, **New chart** or **Clarify**.
- Tracks chart ownership, usage, certification/retirement proposals and audit events.
- Supports English/Finnish and dark/light mode. English and dark mode are the defaults;
  the browser remembers your selections. New AI replies follow the selected language.
  Existing conversation messages retain their original text.

FastAPI serves the API and the Vue 3 / Chart.js interface in one process. MongoDB
stores source data and application state. Gemini interprets questions and words
answers; deterministic Python code computes the numbers. n8n governance scanning
is optional. No npm installation or frontend build is required.

## Which folder should I use?

| Folder | Purpose |
| --- | --- |
| [application/](application/README.md) | **Application source and working directory for Uvicorn and module-based tools.** Contains backend, frontend, configuration and tests. |
| `.venv/` | Shared project Python environment at the repository root. |
| [Bayer data pack](<data/bayer/README.md>) | Source workbook and challenge briefs; the workbook also supplies offline test data. |
| [integrations/n8n/](integrations/n8n/README.md) | Optional workflow and governance setup. |
| [docs/](docs/architecture.md) | Architecture, data-import guide and historical cleanup record. |
| [Production and governance](docs/production-and-governance.md) | Deployment target, access, ownership, RACI and how quality is reproduced. |

```text
SinceAI/
  README.md
  work_plan.md
  pyproject.toml
  application/
    README.md
    .env                 # Local secrets; ignored
    .env.example
    requirements.txt
    requirements-dev.txt
    backend/
      replenishment/
      vector_store.py
    frontend/
    config/
    tools/
    tests/
      backend/
      frontend/
  data/bayer/
  integrations/n8n/
  docs/
  .venv/                 # Local environment; ignored
```

## Requirements

- Python with `venv` and pip. The local checkout has been verified with Python 3.13.5.
- Access to a populated MongoDB database; Atlas vector indexes enable similarity search.
- A Gemini API key and a generation model available to your account for new AI requests.
- Internet access: Gemini/Atlas are external services and the browser loads Vue/Chart.js
  from pinned CDN URLs. The app is not an offline demo.
- Node.js only if you want to run the frontend checks.

## First-time setup - Windows PowerShell

From the repository root:

```powershell
Set-Location -LiteralPath 'C:\Users\jan_k\Documents\SinceAI'
if (-not (Test-Path -LiteralPath '.\.venv\Scripts\python.exe')) { python -m venv .venv }
& '.\.venv\Scripts\python.exe' -m pip install -r '.\application\requirements.txt'
```

If `python` is not on PATH, use the full path to an installed interpreter when
creating the environment, for example `& 'C:\Users\jan_k\miniconda3\python.exe' -m venv .venv`
on this machine. You do not need to activate the environment when using its Python directly.

For a new checkout, copy `application/.env.example` to `application/.env` and replace
the placeholders. **Do not overwrite a working `.env`.** The application has one
local environment file; the existing configuration has been preserved.

Configure `MONGODB_URI`, `MONGODB_DB`, `GEMINI_API_KEY` and `GEMINI_MODEL` as described
in the [application configuration table](application/README.md#configuration).
Environment files are Git-ignored. Use plain, unquoted `KEY=value` lines for the
PowerShell loader below; it does not expand variables or execute the file.

The app does **not** automatically load `.env` files. Load settings into the same
terminal before starting Uvicorn. If the database has not been populated, follow
[data import](docs/data-import.md) first. Importing replaces source collections;
it is not a normal startup step.

## Start - Windows PowerShell

Paste this complete block. Its first command resets the working directory, so it
also works if your terminal is already inside `application`:

```powershell
Set-Location -LiteralPath 'C:\Users\jan_k\Documents\SinceAI'
$sinceaiEnv = '.\application\.env'
Get-Content -LiteralPath $sinceaiEnv -ErrorAction Stop | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') {
        Set-Item -Path "env:$($matches[1])" -Value $matches[2].Trim()
    }
}
Set-Location -LiteralPath '.\application'
& '..\.venv\Scripts\python.exe' -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

| URL | Purpose |
| --- | --- |
| http://localhost:8000 | Application |
| http://localhost:8000/api/health | MongoDB connectivity, counts and configured generation model |
| http://localhost:8000/docs | Interactive API documentation |

`/api/health` does not call Gemini or verify vector-index readiness. Keep the server
terminal open. Stop with **Ctrl+C** there before restarting. `deactivate` only exits
the virtual environment; it does not stop another running server.

Restart after backend/configuration changes. After frontend changes, use **Ctrl+F5**
in the browser. In a new terminal, reload the environment before starting again.
Optional activation from `application/`: `& '..\.venv\Scripts\Activate.ps1'`.

For macOS/Linux setup and startup, see the [application guide](application/README.md#macos-and-linux).

## Quality evaluation

40 golden questions (Finnish and English; production, commercial and finance; questions without
data; chat) check that Gemini interprets questions correctly and the same way every time. Run from
`application/` with the environment loaded; it calls the real model, about 6-10 minutes:

```bash
python -m tools.run_eval              # 40 questions x 2 repeats
python -m tools.run_eval --repeats 1  # faster, no consistency check
```

The result is saved to MongoDB and shown in **Data Steward -> Quality assurance**, with a copy in
`application/eval/results/latest.md`. See [production and governance](docs/production-and-governance.md#3-how-quality-is-reproduced-every-time).

## Verify changes

Run from the repository root:

```powershell
& '.\.venv\Scripts\python.exe' -m pip install -r '.\application\requirements-dev.txt'
$env:N8N_WEBHOOK_URL = ''
& '.\.venv\Scripts\python.exe' -m pytest -q
node '.\application\tests\frontend\preferences.test.cjs'
& '.\.venv\Scripts\python.exe' -m pip check
```

Use a separate test terminal; the empty `N8N_WEBHOOK_URL` prevents inherited live
webhook settings from sending notifications during proposal tests.
The current suite has 19 backend tests and 4 frontend checks. Backend tests load the
included workbook into an in-memory MongoDB and replace Gemini; they do not alter
the live database or call external APIs. `DATA_PACK_XLSX` can select another workbook.
The frontend checks exercise JavaScript behavior with simulated browser APIs; they
are not a visual browser test. Live search diagnostics are separate and documented
in the [data guide](docs/data-import.md).

## Troubleshooting

| Symptom | Action |
| --- | --- |
| `application\application` path does not exist | You changed into the folder twice. Use the complete startup block above. |
| `-m` is not recognized, or Python shows `>>>` | Keep the Python executable and `-m uvicorn ...` on one line. Use `exit()` to leave the Python prompt. |
| `WinError 10048` / port 8000 already in use | Open the existing app or stop its server with Ctrl+C before starting another instance. |
| `Set MONGODB_URI`, missing API key or wrong model | Load the intended environment file in the same terminal, then restart. |
| MongoDB authentication/selection failure | Check credentials, database name and Atlas network access for your machine. |
| Gemini `503 UNAVAILABLE` / high demand | The provider rejected the request. Wait and retry; restarting Python does not resolve provider overload. |
| Gemini `429` / quota exceeded | Check your account quota and request rate before retrying. |
| Blank or stale interface | Hard-refresh and check CDN connectivity and the browser console. |

## Limits and further reading

Role selection is application context, **not authenticated authorization**. Some
API routes expose or modify shared state, and the optional callback secret protects
only the decision endpoint. Keep the prototype on `127.0.0.1`; do not treat it as a
production deployment. AI specification failures can still fail the request after
retries; deterministic fallbacks cover answer wording, not every provider call.

- [Architecture and request flow](docs/architecture.md)
- [Application development, configuration and API](application/README.md)
- [Data import, search and replenishment exports](docs/data-import.md)
- [Optional n8n governance workflow](integrations/n8n/README.md)
