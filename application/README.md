# SinceAI application

Streamlit provides the dashboard and chat interface. FastAPI provides the validated application API and authenticated n8n calculation endpoint. Both use the existing Python implementation and n8n integration.

## Install

From this folder, use the repository-level environment:

```powershell
..\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

If the environment does not exist, create it from the repository root with `python -m venv .venv`. On macOS/Linux use `../.venv/bin/python` in place of the Windows interpreter path.

## Configure

Keep your settings in `application/.env`. Merge [n8n.env.example](n8n.env.example) into it when enabling n8n; do not overwrite existing credentials. The application reads environment variables, so load this file in **both** launching terminals.

- `KPI_BACKEND=local` preserves the Python pipeline; `n8n` calls the governed workflow.
- `SINCEAI_API_URL=http://127.0.0.1:8000` connects the dashboard to FastAPI.
- `APP_AUTH_MODE=local` is for loopback demonstrations. Public hosting requires the authenticated proxy setup in [INTEGRATION.md](INTEGRATION.md).
- MongoDB settings and n8n webhook URLs/credentials remain documented in the integration guide.

## Run

In the first PowerShell terminal, from this folder:

```powershell
Get-Content .env | ForEach-Object { if ($_ -match '^\s*([^#=][^=]*)=(.*)$') { Set-Item "env:$($matches[1].Trim())" $matches[2].Trim() } }
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a second terminal, from the same folder:

```powershell
Get-Content .env | ForEach-Object { if ($_ -match '^\s*([^#=][^=]*)=(.*)$') { Set-Item "env:$($matches[1].Trim())" $matches[2].Trim() } }
..\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

These commands expect simple unquoted `KEY=value` lines. On macOS/Linux, load the environment with `set -a; source .env; set +a` in both terminals and run the equivalent Python module commands.

Open **http://localhost:8501/**. FastAPI documentation is at http://localhost:8000/docs. Its root is an API information response, not the frontend.

The dashboard includes chat history, clarification suggestions, Plotly charts, source tables/CSV, warnings, receipts, saved-chart refresh, morning briefings and steward governance actions. Conversations and dashboard reads are isolated by session; reruns do not replay submitted requests.

## Verify

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
```

The original Excel regression tests require `DATA_PACK_XLSX`. Native Streamlit UI and mocked API integration tests run without business data or live service credentials.
