# SinceAI cleanup plan

Scope: retain the working FastAPI + Vue application and its current English/Finnish
and dark/light controls. Preserve calculations, MongoDB collections, Gemini behavior,
chart reuse, approval flows, data import and useful project diagnostics.

## Baseline (before deletion)

- 19 backend tests passed against the included workbook, using mongomock/fake Gemini.
- 4 Node frontend checks passed; no npm dependencies are needed.
- `python -m pip check`: no broken requirements.
- Existing uncommitted interface/language work will be preserved. No commits or
  remote changes are part of this cleanup.

## Stages

1. Remove the unreferenced UI and its backend: `streamlit_app/`, `.streamlit/`,
   `factory/`, `govagent/`, root `cli.py`, and `smoke_test_tools.py`.
   Rerun backend and frontend checks.
2. Remove duplicate `mongo-seed/` implementations. Keep the copies in `fastapi+vue/`:
   its vector helper includes newer rate-limit handling that the duplicate lacks.
   Remove SQLite-only exploration (`explore_bayer_db.py`, `findings.json`,
   `some_findings.md`, generated `bayer_sinceai.db`, and `load_xlsx_to_sqlite.py`).
   Retain the workbook, challenge PDF/DOCX and current data-pack documentation.
   Rerun checks and exercise the retained import/search/replenishment CLI entry points.
3. Split runtime and development dependency manifests, configure root pytest discovery
   and the default included data fixture, and remove demonstrably unused helpers/imports.
   Replace outdated READMEs with the actual architecture and startup instructions.
4. Remove the UI-only installed packages from the project-local `.venv`, checking
   installed dependency metadata before removing transitive packages. Preserve shared
   runtime/dev dependencies and packages with other consumers.
5. Rerun all checks, verify static/API responses and scan for obsolete references.

## Local state

- Keep `application/.env`, the existing local configuration used during this session;
  do not print, delete or commit its contents. Clear only obsolete caches beside it.
- Preserve the local `.venv` and editor settings.
- Preserve the intentional untracked `gemini.md` local note.
- Do not seed/write the live MongoDB database or call Gemini during verification.
- Validate every absolute deletion target is inside this repository before deleting.

## Completion evidence

- Stage 1: removed the unused UI/backend paths; 19 backend tests and 4 frontend
  checks passed afterwards.
- Stage 2: removed the duplicate importer/search folder and SQLite-only artifacts;
  preserved the source workbook and challenge documents. The same 19 + 4 checks passed.
- Stage 3: runtime/dev manifests separated, root pytest configuration added and
  default workbook selected automatically. Current architecture/startup/import
  documentation replaces the old design notes. Removed unused helper/imports only.
- Stage 4: uninstalled 18 UI-exclusive packages from the project `.venv`, including
  the removed UI framework, Altair, Plotly, PyDeck, PyArrow and Watchdog. Protected
  shared runtime/dev dependencies using the installed dependency graph. Removed
  obsolete bytecode caches; `application/.env` and the local note remain untouched.
- Windows still holds a temporary uninstalled protobuf file under
  `.venv/Lib/site-packages/google/~upb`. Its distribution is uninstalled; the
  residual file is locked by a running process and does not provide an installed
  dependency. Other pip temporary directories were removed.
- Final verification: 19 backend tests passed from the repository root without
  manually setting the workbook path; 4 frontend checks passed; `pip check` clean.
- All retained CLI help entry points import successfully. Offline importer preview
  produced 21 source collections. Replenishment export produced 98 product-market
  results. Both checks used temporary paths under the repository and no external APIs.
- API/static checks returned HTTP 200 for `/`, `/static/i18n.js`, `/api/roles` and
  `/api/roles?language=fi`. Supported Python sources parse; local documentation links
  resolve; `git diff --check` passes.
- Removed 38 tracked legacy/duplicate files. Active code and current documentation
  have no references to the removed runtime, agent backend or SQLite tooling.
