# Data import and diagnostics

Run these commands from `fastapi+vue/` using `../.venv`. Install
`requirements.txt` and load your environment as described in the root README.

The workbook is synthetic. The importer stores each data sheet as a normal
MongoDB collection, retaining numeric types and `_source` provenance. It enriches
KPI aliases and report descriptions for similarity search. Vector results suggest
candidates; deterministic fingerprints decide chart reuse.

## Offline preview

This command writes local JSONL/index definitions with fake vectors. It does not
contact MongoDB or Gemini:

```powershell
& '..\.venv\Scripts\python.exe' seed_mongo.py --xlsx '..\Bayer_SinceAI2026 _1_\Bayer_SinceAI2026\Bayer_Pharmaceuticals_SinceAI_2026_FINAL_Builder_Data_Pack.xlsx' --dry-run out
```

## Import into Atlas

Set `MONGODB_URI`, `MONGODB_DB` (default `bayer_hackathon`) and `GEMINI_API_KEY`.
Allow your machine's public IP in Atlas Network Access and give the database user
the permissions needed to import data and manage indexes.

**Import replaces the source collections.** Use it for initial loading or a deliberate
data refresh, not ordinary app startup. `chart_registry` is preserved.

```powershell
& '..\.venv\Scripts\python.exe' seed_mongo.py --xlsx '..\Bayer_SinceAI2026 _1_\Bayer_SinceAI2026\Bayer_Pharmaceuticals_SinceAI_2026_FINAL_Builder_Data_Pack.xlsx'
```

The implementation defines three vector indexes: `kpi_vector`, `asset_vector`
and `chart_vector`. `GEMINI_EMBED_MODEL` defaults to `gemini-embedding-001`;
`EMBED_DIM` defaults to 768 and must match the indexes. Changing dimensions
requires regenerating vectors and updating the index definitions. The shared
helper retains its existing pacing and transient-error retry behavior.

## Live search

These commands call Gemini for embeddings and query Atlas:

```powershell
& '..\.venv\Scripts\python.exe' search.py kpi 'delivery reliability'
& '..\.venv\Scripts\python.exe' search.py kpi 'net sales' --all-variants
& '..\.venv\Scripts\python.exe' search.py asset 'Nubeqa sales growth by country'
& '..\.venv\Scripts\python.exe' search.py chart 'OTIF trend by market'
```

`python test_search.py --only kpi` checks KPI search and vector-index readiness.
The `--only chart` check (also included when no `--only` is supplied) temporarily
registers a test chart and deletes it afterwards. Run it only against an appropriate
test/demo database. It is intentionally excluded from the offline pytest suite.

## Replenishment export

The deterministic CLI remains available for inspecting the same assumptions and
calculations used by the app, without MongoDB or Gemini:

```powershell
& '..\.venv\Scripts\python.exe' -m reorder.cli --xlsx '..\Bayer_SinceAI2026 _1_\Bayer_SinceAI2026\Bayer_Pharmaceuticals_SinceAI_2026_FINAL_Builder_Data_Pack.xlsx' --today 2026-11-06 --out output
```

It writes forecast CSV/JSON, a plant summary and the governed metric definition.
`out/` and `output/` are ignored by Git.
