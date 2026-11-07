# FastAPI + Vue application

This is the supported SinceAI application. See the repository [README](../README.md)
for environment setup and complete Windows startup commands, and
[architecture](../README_ARCHITECTURE.md) for module responsibilities.

The repository-local virtual environment is `../.venv`; do not create a second
environment inside this directory. From here, after loading the environment:

```powershell
& '..\.venv\Scripts\python.exe' -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://localhost:8000. Keep Python and all its arguments on the same line.
Stop with Ctrl+C before starting another server on port 8000.

The header provides English / Suomi and dark / light controls. English and dark
mode are the defaults. The browser saves the selected preferences; Gemini answers
and fallback responses use the selected language. Existing chat messages retain
their original text, and switching language does not regenerate them.

`POST /api/ask` accepts `language: "en" | "fi"`. `/api/roles` and
`/api/briefing/{role}` accept the same `language` query parameter. It defaults
to English. Restart the backend after Python changes and refresh the browser.

## Dependencies and tests

```powershell
& '..\.venv\Scripts\python.exe' -m pip install -r requirements-dev.txt
& '..\.venv\Scripts\python.exe' -m pytest -q
node tests/frontend_language.cjs
```

For runtime-only installation, use `requirements.txt`. The test suite uses the
included workbook by default; `DATA_PACK_XLSX` can select another fixture.
Live import/search tools are documented in [DATA_IMPORT.md](DATA_IMPORT.md).
