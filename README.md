# SinceAI - Build Less assistant

AI-assisted, governed plant analytics for the Bayer challenge at Since AI 2026.
The application answers business questions using canonical KPIs, reuses existing
charts before creating new ones, and records definitions and source evidence.
All supplied operational data is synthetic; it does not represent real Bayer performance.

## Current stack

- FastAPI backend and a Vue 3 / Chart.js browser interface, served by the same process.
- MongoDB for source data, chart registry, conversations, results and audit records.
- Google Gemini for interpreting questions and wording answers. Python computes all numbers.
- Optional n8n workflow for certification and retirement proposals; a human approves decisions.
- English/Finnish interface and responses; English is the default. Dark/light appearance.
  The browser remembers both preferences. Existing chat messages retain their original text.

## Setup (Windows PowerShell)

Run from the repository root:

```powershell
cd C:\Users\jan_k\Documents\SinceAI
# Create the environment only if it does not already exist:
if (-not (Test-Path -LiteralPath '.\.venv\Scripts\python.exe')) { python -m venv .venv }
& '.\.venv\Scripts\python.exe' -m pip install -r '.\fastapi+vue\requirements.txt'
```

If `python` is unavailable, use an installed interpreter's full path. This checkout
also has `C:\Users\jan_k\miniconda3\python.exe`. Environment activation is optional
when invoking the project's Python by its full or relative path.

For a new configuration, copy `fastapi+vue/.env.example` to `fastapi+vue/.env` and
fill in `MONGODB_URI`, `MONGODB_DB`, `GEMINI_API_KEY` and a Gemini model available to
your account. The current local checkout also has a configuration in `application/.env`;
the startup commands below use it if `fastapi+vue/.env` is absent. Both locations are
Git-ignored. Never commit credentials. The example's fixed `TODAY` date is for demos.

The MongoDB database must contain the source collections. See
[data import](fastapi+vue/DATA_IMPORT.md) for first-time loading. Do not re-seed a
working database merely to start the application.

## Start (Windows PowerShell)

Paste the whole block into a fresh terminal. The absolute first path makes it work
regardless of the terminal's current folder:

```powershell
Set-Location -LiteralPath 'C:\Users\jan_k\Documents\SinceAI'
$sinceaiEnv = if (Test-Path -LiteralPath '.\fastapi+vue\.env') { '.\fastapi+vue\.env' } else { '.\application\.env' }
Get-Content -LiteralPath $sinceaiEnv -ErrorAction Stop | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') {
        Set-Item -Path "env:$($matches[1])" -Value $matches[2].Trim()
    }
}
Set-Location -LiteralPath '.\fastapi+vue'
& '..\.venv\Scripts\python.exe' -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Use plain `KEY=value` lines in the environment file. These commands do not execute
its contents as shell code. Settings must be loaded before starting Uvicorn.

Open **http://localhost:8000**. The health endpoint is `/api/health`; API docs are
at `/docs`. Vue and Chart.js load from a CDN, so the UI needs Internet access.
No npm installation or frontend build is required.

Stop the server with **Ctrl+C** in the terminal running Uvicorn. `deactivate` only
exits the virtual environment. If port 8000 is occupied, stop the earlier server
before restarting. Restart after backend changes; refresh after frontend changes.

On macOS/Linux, create `.venv` with `python3 -m venv .venv`, install the same
manifest with `.venv/bin/python -m pip`, export the configured variables, and run
`../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000` from
`fastapi+vue/`. Do not source an untrusted environment file as a shell script.

## Verification

From the repository root:

```powershell
& '.\.venv\Scripts\python.exe' -m pip install -r '.\fastapi+vue\requirements-dev.txt'
& '.\.venv\Scripts\python.exe' -m pytest -q
node '.\fastapi+vue\tests\frontend_language.cjs'
& '.\.venv\Scripts\python.exe' -m pip check
```

The backend suite uses the included workbook, an in-memory MongoDB and fake Gemini;
it does not seed the live database or call the LLM. Set `DATA_PACK_XLSX` to use a
different workbook. Node is needed only for the dependency-free frontend checks.

## Repository

| Path | Purpose |
| --- | --- |
| `fastapi+vue/app/` | API, decision engine, governed metrics, Gemini integration and translations |
| `fastapi+vue/app/static/` | Vue interface, Chart.js rendering and frontend translations |
| `fastapi+vue/reorder/` | Deterministic replenishment calculations and export CLI |
| `fastapi+vue/tests/` | Offline backend and frontend checks |
| `fastapi+vue/seed_mongo.py` | Workbook importer and index setup |
| `fastapi+vue/vector_store.py` | Shared embedding/search helpers |
| `fastapi+vue/search.py`, `test_search.py` | Live vector-search diagnostics (see data import guide) |
| `Bayer_SinceAI2026 _1_/Bayer_SinceAI2026/` | Source workbook, challenge briefs and data-pack description |
| `n8n/` | Optional governance-scan workflow and setup instructions |
| `application/.env` | Existing local configuration, not application source; Git-ignored |

See [architecture](README_ARCHITECTURE.md), [data import](fastapi+vue/DATA_IMPORT.md)
and [n8n setup](n8n/N8N.md). Keep this prototype bound to loopback: choosing a role
is application context, not authenticated authorization.
