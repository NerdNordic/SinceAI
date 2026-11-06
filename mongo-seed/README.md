# Data pack → MongoDB Atlas (+ Gemini embeddings)

Loads the Bayer builder data pack into MongoDB Atlas. **Every sheet becomes a normal collection**: numbers stay numbers and are queried exactly. **Vectors are added only where similarity search helps:**

| Collection | Embedding text | Used for |
|---|---|---|
| `kpi_catalog` | KPI name, canonical metric, domain, unit + curated aliases (EN/FI, `kpi_aliases.json`) | "toimitusvarmuus" → On-Time In-Full (KPI-020) |
| `analytics_assets` | what the report **measures** (from Asset_KPI_Map), product, market, workspace. Not the name: names in the data pack don't match content | find existing Bayer reports similar to a request |
| `chart_registry` | title + description of each chart the bot creates (empty at start, never overwritten) | near-duplicate charts the exact fingerprint missed |

Vector search **suggests**, it does not decide. Conflicting KPI variants ("Net Sales" vs "Net Sales Local") embed close together, so a hit is always resolved to its `canonical_metric`, and REUSE is decided by the exact chart fingerprint.

Every document carries `_source` (file, sheet, Excel row, provenance), so a receipt can point to the exact source row. Derived or curated fields are listed in `_enrichment`.

## Setup on the Red Hat server

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export MONGODB_URI='mongodb+srv://<user>:<password>@<cluster>.mongodb.net/'
export GEMINI_API_KEY='...'
# optional: MONGODB_DB (default bayer_hackathon), GEMINI_EMBED_MODEL (default gemini-embedding-001), EMBED_DIM (default 768)
```

In Atlas: create a database user, and add the server's public IP under **Network Access → IP Access List**.

## Run

```bash
# 1. check what would be written (no Mongo, no Gemini; fake vectors)
python seed_mongo.py --xlsx /path/to/Bayer_..._Builder_Data_Pack.xlsx --dry-run out/

# 2. load for real: collections, regular indexes, embeddings, 3 vector indexes
python seed_mongo.py --xlsx /path/to/Bayer_..._Builder_Data_Pack.xlsx

# 3. try it
python search.py kpi "toimitusvarmuus"
python search.py kpi "net sales" --all-variants
python search.py asset "Nubeqa sales growth and market access by country"
```

The seed is safe to re-run: collections are emptied and refilled (search indexes are kept), and `chart_registry` is never touched.

## Limits

- **Atlas M0 (free): 3 search or vector indexes in total.** This setup uses exactly three. Flex allows 10.
- Embedding about 420 texts takes roughly 10 Gemini calls; rate-limit errors are retried with backoff.
- `EMBED_DIM` must match the index `numDimensions`. Changing it means re-running the seed (the script updates the index definition).

## From the backend

```python
from pymongo import MongoClient
import vector_store as vs

db = MongoClient(MONGODB_URI)["bayer_hackathon"]
vs.search_kpis(db, "toimitusvarmuus")                  # canonical KPIs only by default
vs.search_charts(db, "OTIF trend by market", filter={"plant": "Plant-A"})
vs.register_chart(db, {"fingerprint": "...", "title": "...", "description": "...", "role": "vuoropäällikkö",
                       "plant": "Plant-A", "kpi_ids": ["KPI-020"], "spec": {...}, "owner": "..."})
```
