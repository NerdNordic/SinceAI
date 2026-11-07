# Bayer Pharmaceuticals × Since AI 2026 — Builder Data Pack

Rendered from the `START_HERE` and `Package_Overview` worksheets of
`Bayer_Pharmaceuticals_SinceAI_2026_FINAL_Builder_Data_Pack.xlsx` (v2.0).
The dataset itself is loaded into `bayer_sinceai.db` (SQLite) by `load_xlsx_to_sqlite.py`.

## Challenge

**Build Less, Build Better: AI for Governed Analytics** — fastest path to a strong prototype.

## Scope

Bayer Pharmaceuticals / prescription-medicine analytics only. No Crop Science, no Consumer Health.

## Purpose

Provide a realistic synthetic pharma analytics estate for an AI assistant that can discover,
reuse, consolidate, repair, migrate or retire BI products instead of creating another
dashboard by default.

## Recommended MVP flow

Business user asks a question -> AI identifies business intent -> finds relevant governed
KPIs + semantic models + existing reports -> checks usage, ownership, lineage and governance
-> recommends reuse / consolidation / migration / retirement / new build with evidence.

### Agent workflow (from START_HERE)

| Step | Use | Agent task | Evidence | Output |
|---|---|---|---|---|
| 1 | Business_Requests | Parse business question | request text + domain + market + product | structured intent |
| 2 | KPI_Catalog | Resolve metric definitions | canonical KPI + aliases + conflicts | governed metric set |
| 3 | Analytics_Assets + Asset_Usage | Find existing analytics | similarity + adoption + freshness | reuse / consolidate candidates |
| 4 | Semantic_Models + Lineage_Edges | Trace data dependencies | model, source, downstream reports | impact & lineage explanation |
| 5 | Governance_Signals + Data_Quality | Check trust and ownership | owner, certification, sensitivity, refresh, quality | risk / repair actions |
| 6 | Migration_Backlog | Handle Tableau -> Power BI | legacy status + duplicate destination + complexity | migrate / retire / consolidate recommendation |

## Critical disclaimer

ALL report names, workspaces, owners, usage, sales, forecast, market-access, launch, KPI,
lineage, quality and governance values in this workbook are **SYNTHETIC / ILLUSTRATIVE**.
Product and therapeutic-area names may reflect public Bayer Pharmaceuticals context, but no
internal Bayer data is represented.

## No patient data

There is no patient-level, HCP-level or personal data. Commercial and operational measures
are aggregated synthetic business data.

## Sheet roles

- **Core builder sheets:** Business_Requests, Analytics_Assets, KPI_Catalog, Semantic_Models,
  Asset_Usage, Lineage_Edges, Governance_Signals, Migration_Backlog
- **Pharma context sheets:** Products, Markets, Product_Market_Monthly, Launch_Milestones,
  Market_Access, Supply_Operations
- **Important design rule:** the system should explain why a recommendation was made and
  cite the metadata, usage, KPI, lineage or governance evidence behind it.

## Out of scope

Clinical decision support, treatment recommendations, pharmacovigilance case processing,
patient profiling, real Bayer internal systems, and any claim that synthetic figures are
actual Bayer performance.

## Package metrics (Package_Overview)

| Metric | Value |
|---|---|
| Products / public-context brands | 7 |
| Markets | 14 |
| Analytics assets | 360 |
| Semantic models | 75 |
| KPI definitions | 56 |
| Monthly asset-usage rows | 3,600 |
| Lineage edges | 438 |
| Product-market-month rows | 980 |
| Governance signals | 410 |
| Migration backlog items | 94 |
| Business requests | 150 |

Synthetic market-month rows per product: Nubeqa 140, Kerendia 140, Eylea 140, Xarelto 140,
Lynkuet 140, Beyonttra 140, Hyrnuo 140.

## Builder notes

- This package is intentionally realistic and messy enough to require discovery, governance
  reasoning and lineage analysis — not just charting.
- No judging answers: there are no ground-truth lifecycle labels or evaluation answers in
  this workbook.
- The challenge can be solved entirely with enterprise BI metadata and aggregated synthetic
  business data (no patient/HCP data).
- Real Bayer Pharma names/context are clearly separated from synthetic operational values.
- The workbook can be loaded into Python/SQL/Fabric/Power BI, split into CSVs, or used as a
  seed for a graph/RAG/agent workflow.
- Production path: a production implementation would replace synthetic sheets with approved
  catalog, Power BI/Fabric APIs, lineage, usage and governed pharma business data.

## Using the SQLite database

```python
import sqlite3

con = sqlite3.connect("bayer_sinceai.db")
for row in con.execute(
    "SELECT asset_name, platform, lifecycle_status FROM Analytics_Assets LIMIT 5"
):
    print(row)
```

Note: this folder lives on a virtiofs mount, where SQLite's default rollback
journal fails ("attempt to write a readonly database"). Plain SELECTs are
unaffected. If you ever write to the database from Python, set
`con.execute("PRAGMA journal_mode=MEMORY")` first, or rebuild it with the
loader below.

One table per worksheet (names and row counts above; 22 tables, 8,120 rows total).
Convenience views:

- `v_asset_monthly` — assets × monthly usage (+ owner / workspace / semantic model)
- `v_governance` — governance signals × asset × owner
- `v_migration` — migration backlog × asset × target model × usage totals
- `v_product_monthly` — product-market-month × product / market names
- `v_kpi_conflicts` — KPI variants grouped by canonical metric

Rebuild the database any time with:

```bash
python3 load_xlsx_to_sqlite.py
```
