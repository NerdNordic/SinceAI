# SinceAI data import, search and replenishment tools

Use these tools from `application/` with the shared `../.venv` environment.
Install [runtime requirements](../application/requirements.txt). For live commands, load settings
using the [application startup guide](../application/README.md#start-from-this-folder---windows-powershell)
but omit the final Uvicorn command. A running API is not required for these CLIs.

The [source workbook](../data/bayer/README.md)
contains synthetic data. `tools/seed_mongo.py` imports 21 data sheets into ordinary
MongoDB collections. It retains numeric types and source file/sheet/Excel-row
provenance in `_source`; enriched fields are marked in `_enrichment`.

## Offline import preview

This writes local JSONL and index definitions using deterministic fake vectors.
It does not need credentials and does not contact MongoDB or Gemini:

```powershell
& '..\.venv\Scripts\python.exe' -m tools.seed_mongo --xlsx '..\data\bayer\Bayer_Pharmaceuticals_SinceAI_2026_FINAL_Builder_Data_Pack.xlsx' --dry-run out
```

`out/` is Git-ignored. Do not use fake-vector output as real semantic search data.

## Import into MongoDB Atlas

Load `MONGODB_URI`, `MONGODB_DB` (default `bayer_hackathon`) and `GEMINI_API_KEY`.
Configure a database user with the import/index permissions it needs and allow
your machine's public IP in Atlas network access.

**This command deletes and replaces the imported source collections' contents.**
Use it only for first-time loading or a deliberate source-data refresh. It does
not reset `chart_registry` or the app's conversations/proposals/results. Mixed old
application state and refreshed source data should be reviewed deliberately.

```powershell
& '..\.venv\Scripts\python.exe' -m tools.seed_mongo --xlsx '..\data\bayer\Bayer_Pharmaceuticals_SinceAI_2026_FINAL_Builder_Data_Pack.xlsx'
```

After a source refresh, restart the application to refresh process-local catalog
and replenishment caches. Ordinary startup does not import data.

## Embeddings and indexes

| Collection | Enriched embedding text | Index |
| --- | --- | --- |
| `kpi_catalog` | KPI name, canonical metric, domain/unit and curated aliases. | `kpi_vector` |
| `analytics_assets` | KPIs actually measured, product, market and workspace. | `asset_vector` |
| `chart_registry` | Titles and descriptions of charts registered by the app. | `chart_vector` |

`config/kpi_aliases.json` supplies KPI aliases. `backend/vector_store.py` is shared by the importer,
application and CLI tools. Vector hits are suggestions; exact chart fingerprints
and canonical metric code decide reuse and compute numbers.

Code defaults are `GEMINI_EMBED_MODEL=gemini-embedding-001`, `EMBED_DIM=768` and
`EMBED_RPM=90`. Account availability/limits can differ. Embedding dimensions must
match the index definitions; changing dimensions requires regenerating vectors
and updating the indexes. The helper applies process-local pacing and retries.

Importer options:

| Option | Effect |
| --- | --- |
| `--db NAME` | Override the target database. |
| `--aliases PATH` | Use a different alias JSON file. |
| `--dry-run DIR` | Local preview; implies fake embeddings and no external writes/calls. |
| `--skip-embeddings` | Skip generating new embeddings. |
| `--fake-embeddings` | Testing-only deterministic vectors; does not by itself prevent MongoDB writes. |
| `--skip-vector-indexes` | Skip vector-index creation/update. |
| `--wait SECONDS` | Maximum index-readiness wait; default 120 seconds. |

Skipping embeddings/indexes can help with test setup but does not provide working
semantic search. Index-creation failures or index readiness need to be checked
separately; `/api/health` does not check them.

## Live vector-search diagnostics

These commands embed the question with Gemini and query MongoDB Atlas. They can
consume API quota; run them against the intended demo/test database:

```powershell
& '..\.venv\Scripts\python.exe' -m tools.search kpi 'delivery reliability'
& '..\.venv\Scripts\python.exe' -m tools.search kpi 'net sales' --all-variants
& '..\.venv\Scripts\python.exe' -m tools.search asset 'Nubeqa sales growth by country'
& '..\.venv\Scripts\python.exe' -m tools.search chart 'OTIF trend by market'
& '..\.venv\Scripts\python.exe' -m tools.check_vector_search --only kpi
```

`python -m tools.check_vector_search --only chart` temporarily writes a test chart, searches for it and
deletes it afterwards. Running the script without `--only` includes that check.
This diagnostic is deliberately outside the offline pytest suite. Check each
script's `--help` before changing database or import options.

## Gemini spec-generation eval

A curated question set (`application/tools/eval_dataset.json`, 37 English and
Finnish phrasings, including follow-up questions) checks the
question-to-chart-spec step against real Gemini. The driver runs the production
path (KPI hints -> prompt -> Gemini -> sanitize) without the `llm_cache`, so a
second pass measures true reproducibility:

```powershell
& '..\.venv\Scripts\python.exe' -m tools.eval_spec                 # all cases, 2 passes
& '..\.venv\Scripts\python.exe' -m tools.eval_spec --only otif     # cases whose id contains 'otif'
& '..\.venv\Scripts\python.exe' -m tools.eval_spec --validate      # dataset check, no Gemini calls
& '..\.venv\Scripts\python.exe' -m tools.eval_spec --no-hints      # prompt without vector hints
```

- Accuracy is reported per pass over the core fields (metric, dimensions,
  filters) and separately over extras (`chart_type`, `intent`, `actuals_only`,
  `mode`, `understood`). Expected values are post-sanitize, so plant-role
  defaults (`plants=["Plant-A"]`) are part of the expectations.
- Reproducibility compares the first and last pass on the semantic spec
  fields; title differences are informational only.
- A run makes about `2 x N` generate-content calls and `N` embedding calls
  (hints) and needs the same environment as the app (`MONGODB_URI`,
  `GEMINI_API_KEY`). It reads MongoDB but never writes to it.
- `--report PATH` (for example `..\ignore\eval_report.json`, Git-ignored)
  saves a machine-readable result for comparing prompt or model changes.
- Exit codes: `0` run completed (mismatches are measurements, not failures),
  `1` a Gemini call failed after retries, `2` configuration or dataset error.

## Offline replenishment export

This CLI loads the workbook directly and uses the same deterministic replenishment
model and assumptions as the app, without MongoDB or Gemini:

```powershell
& '..\.venv\Scripts\python.exe' -m backend.replenishment.cli --xlsx '..\data\bayer\Bayer_Pharmaceuticals_SinceAI_2026_FINAL_Builder_Data_Pack.xlsx' --today 2026-11-06 --out output
```

It writes `reorder_forecast.csv`, `reorder_forecast.json`, `plant_summary.csv` and
`metric_definition.json`. `output/` is Git-ignored. The demo date above is explicit;
without `--today`, risk statuses use the system date. `--as-of` sets the inventory
snapshot date and `--assumptions` selects another assumptions file.

The included workbook produces 98 product-market results (7 products x 14 markets).
Use [the offline test suite](../application/README.md#development-and-verification) to compare app
calculations and outputs without touching live services.
