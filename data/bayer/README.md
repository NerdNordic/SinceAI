# Bayer Pharmaceuticals × Since AI 2026 — Builder Data Pack

Rendered from the `START_HERE` and `Package_Overview` worksheets of
`Bayer_Pharmaceuticals_SinceAI_2026_FINAL_Builder_Data_Pack.xlsx` (v2.0).
The active application imports this workbook into MongoDB with
[`tools/seed_mongo.py`](../../application/tools/seed_mongo.py). See the
[project README](../../README.md) for setup and the
[application README](../../application/README.md) for current capabilities.

This directory preserves the original [PDF challenge brief](Since_AI_Bayer_Challenge_Brief_FINAL.pdf)
and [Word challenge brief](Since_AI_Bayer_Challenge_Brief_FINAL.docx) alongside the workbook.
It is source material and test data, not an application working directory.

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

The following table summarizes the original challenge brief. It is a target
workflow, not a claim that the current app implements every migration, lineage
or estate-audit feature. The implemented request decisions are REUSE, EXTEND,
ANSWER, BUILD and CLARIFY, with separate chart-certification/retirement proposals.

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

## Using the data pack

The workbook is the source fixture for the MongoDB importer and offline regression tests.
See [data import instructions](../../docs/data-import.md) for the import and
vector-search tools. The application computes governed metrics from MongoDB;
the test suite loads the workbook into an isolated in-memory database.

The importer reads 21 data sheets and excludes workbook instruction/overview sheets.
Seven products across fourteen markets produce 98 product–market replenishment
results. The workbook's monthly operational period is January–October 2026.

For a local preview without MongoDB or Gemini, use the importer's `--dry-run`
option. A real import replaces the imported source collections, so it should not
be run merely to start the application. Restart the app after a source refresh
to clear its process-local data caches.

From the repository root, run the offline backend suite with:

```powershell
$env:N8N_WEBHOOK_URL = ''
& '.\.venv\Scripts\python.exe' -m pytest -q
```

`DATA_PACK_XLSX` can select another workbook fixture. It does not change which
database the live application uses. No real service credentials are needed for
the supported offline tests. Run them in a separate terminal; the empty webhook
setting prevents accidental notifications from inherited live configuration.
