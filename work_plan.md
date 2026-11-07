# SinceAI directory restructuring plan

Approved scope: implement the directory and naming proposal in stages, preserving
the existing FastAPI/Vue behavior, language/theme controls, calculations, source
provenance, credentials and uncommitted documentation improvements.

The earlier completed cleanup record is preserved in `docs/cleanup-plan.md`.
No commits or remote publication are included unless separately requested.

## Safety and baseline

- Inspect imports, callers, resource paths and commands before each move.
- Preserve `application/.env` byte-for-byte, without printing or committing it.
  If another `.env` exists, stop on a conflict instead of silently merging secrets.
- Preserve `.venv`, editor settings and the intentional local `gemini.md` note.
- Verify every move/deletion source and destination stays inside this repository.
- Keep original workbook/PDF/DOCX filenames and content for provenance.
- Do not write to live MongoDB, call Gemini or run live vector-search diagnostics.
- Establish 19 backend tests + 4 frontend checks and `pip check` before moving code.
  Record actual results below; repeat checks after every functional stage.

## Stage 1 - Consolidate application source

- Move the contents of `fastapi+vue/` into the existing `application/` directory.
- Merge the application README with local-configuration guidance.
- Keep a single `application/.env` and matching `.env.example`; remove old fallback paths.
- Update pytest discovery, startup/install commands and documentation paths.
- Preserve the current `app.main:app` entry point until stage 2.
- Gate: backend/frontend checks, import/CLI help, static/API checks and secret hash.

## Stage 2 - Separate backend and browser assets

- Rename `application/app/` to `application/backend/`.
- Move static assets to `application/frontend/`; FastAPI still serves them.
- Move `vector_store.py` into the backend and `reorder/` to `backend/replenishment/`.
- Change Python imports to package-relative/explicit backend imports.
- Move assumptions/aliases into `application/config/`; resolve resource locations
  from module paths rather than the terminal working directory.
- Split test locations into `tests/backend/test_workflows.py` and
  `tests/frontend/preferences.test.cjs`, updating fixture/static paths.
- New server entry point: `backend.main:app` from `application/`.
- Gate: identical backend/frontend results, API/static resources, SDK request
  construction and deterministic replenishment export.

## Stage 3 - Organize tools, data and documentation

- Move importer/search tools into `application/tools/` as a Python package.
- Rename the live diagnostic to `check_vector_search.py`, keeping it outside pytest.
- Run tools as `python -m tools.seed_mongo`, `tools.search`, and
  `tools.check_vector_search` from `application/`.
- Move source assets into `data/bayer/`, preserving their original filenames.
- Rename data-pack documentation to `data/bayer/README.md`.
- Move the n8n workflow into `integrations/n8n/` and rename its guide to `README.md`.
- Move architecture/import guides into `docs/architecture.md` and `docs/data-import.md`.
- Update all links, commands, fixture paths and the repository map.
- Gate: regression checks; offline importer preview (21 collections); replenishment
  export (98 product-market pairs); links/anchors; PowerShell syntax; obsolete-path scan.

## Final verification and handoff

- Verify tests from repository root and application directory, package imports from
  an unrelated working directory with an explicit application path, and dependency integrity.
- Verify source-asset hashes and local secret hash against the pre-move inventory.
- Check `git diff --check`, changeset scope and absence of credentials/generated files.
- Document the exact new startup/test/tool commands and any remaining limitations.
- Update this file after each stage; keep all changes reviewable on the current branch.

## Execution record

- Baseline: 19 backend tests, 4 frontend checks and `pip check` passed.
- Stage 1 completed: source consolidated under `application/`; existing `.env`
  hash unchanged. All 19 + 4 checks passed. The empty old source directory is held
  by another Windows process; retry removal during final verification.
- Stage 2 completed: backend/frontend split, resource configuration and package
  imports updated. All 19 + 4 checks passed, as did static/API responses and the
  replenishment CLI import. No business calculations or model prompts changed.
- Stage 3 completed: tools now form `application/tools/`; source assets are under
  `data/bayer/`; n8n is under `integrations/n8n/`; architecture/import guides are
  under `docs/`. Commands, fixture paths, links and repository documentation updated.
- Verification after stage 3: all 19 backend tests and 4 frontend checks passed.
  Backend tests also passed from `application/`; dependency integrity is clean.
- All four CLI modules load. Offline import preview produced 21 collections;
  replenishment export produced 98 product-market results. Temporary outputs
  were confined to the repository and removed after verification.
- Backend imports, resource defaults and Uvicorn loading also passed from an
  unrelated temporary working directory with an explicit application path.
- API/static checks passed for the new frontend location and role endpoints.
  Actual SDK request builders retain English/Finnish system instructions.
- `.env` and all three source assets match their pre-move SHA-256 fingerprints.
- Remaining filesystem limitation: the old `fastapi+vue/` directory is empty but
  held open by another Windows process. Stop the old server and change any terminal
  working directory out of it before deleting that empty folder. It contains no
  source/configuration and is no longer referenced by active code or instructions.
- At implementation handoff, changes were uncommitted on `refactor/fastapi-vue-cleanup`;
  no live services were changed or called during verification.
- Publication follow-up: the user requested committing and pushing the verified
  restructuring and documentation to the existing GitHub branch.
