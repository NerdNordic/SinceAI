# Build Less, Build Better — AI for Governed Analytics

Since AI Hackathon 2026 (Bayer challenge). An AI assistant that turns business questions into
**fewer, better, governed analytics products** — recommending reuse, consolidation, migration or
retirement of BI assets instead of creating another dashboard by default, always with cited
evidence and human-approval gates.

Built on the synthetic Bayer builder data pack (`bayer_sinceai.db`, 22 tables, 8,120 rows).
No real Bayer data is represented; all names, usage and figures are synthetic.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env         # then edit: any OpenAI-compatible endpoint + model

streamlit run app.py         # chat UI + governance audit
# or headless:
python cli.py audit          # full governance audit report
python cli.py ask "Can we build a launch dashboard for Lynkuet with market access and adoption?"
python cli.py demo           # canned demo questions
python smoke_test_tools.py   # verifies every tool against the DB (no LLM needed)
```

Set `GOVAGENT_PROVIDER=stub` to exercise the agent loop and UI with no LLM endpoint
(offline rehearsal mode).

## Architecture

```
Business user
   │  question ("we need a dashboard for X")
   ▼
Streamlit app / CLI ──► govagent/loop.py (tool-calling agent loop, max 12 iterations)
   │                        │
   │                        ▼
   │                   govagent/llm.py  (any OpenAI-compatible endpoint via env vars;
   │                                     function calling; offline stub provider)
   │                        │
   │                        ▼
   └──────────────► govagent/tools.py  (12 evidence-first tools over read-only SQLite)
                                    │
                                    ▼
                        bayer_sinceai.db (Analytics_Assets, KPI_Catalog, Semantic_Models,
                         Asset_Usage, Lineage_Edges, Governance_Signals, Migration_Backlog,
                         Business_Requests + pharma context sheets)
```

### The 12 tools (govagent/tools.py)

| Tool | Purpose |
|---|---|
| `estate_overview` | estate scale and platform × lifecycle split |
| `find_kpi_conflicts` | canonical metrics with conflicting KPI variants, unapproved variants, assets mixing definitions |
| `find_assets_using_kpi` | resolve a metric to its variants and the assets using each (approval status) |
| `find_duplicate_assets` | identical-scope groups, cross-platform overlap, duplicate names |
| `asset_report` | one asset: usage decile, ownership, KPIs, signals, DQ issues, lineage |
| `blast_radius` | downstream exposure of a semantic model |
| `migration_review` | backlog path/target/complexity + migrate-vs-retire usage sanity flags |
| `ground_metric` | is a metric computable from context data (grounded / derived / not grounded) |
| `find_reuse_candidates` | active assets already covering a product × market × KPI-domain scope |
| `usage_stats` | monthly history, decile, momentum |
| `similar_requests` | match request text to known request templates |
| `run_readonly_sql` | SELECT/WITH-only escape hatch (validator + row cap, `mode=ro` connection) |

Every tool returns `{summary, evidence[], data}`; the agent is required by its system prompt to
cite that evidence (asset IDs AST-xxx, KPI IDs KPI-xxx, model IDs SM-xxx, exact numbers).

### Two flows

1. **Governance audit** (`cli.py audit` / sidebar button): the auditor agent proactively scans
   for KPI conflicts, unapproved KPI usage, duplicates, missing owners, high-reach unendorsed
   assets, failed-refresh exposure, risky retirements, migration sanity and ungrounded metrics.
   Output: markdown report + JSON issue list with severity, evidence, recommended action and
   `requires_human_approval`.
2. **Request triage** (chat / `cli.py ask`): the 6-step recommended flow — identify product/
   market/metric → resolve to governed KPIs (flag conflicts + unapproved variants + data gaps)
   → find existing coverage → check usage/ownership/lineage/governance → verdict via the
   decision ladder: **REUSE > CONSOLIDATE > MIGRATE > RETIRE > NEW BUILD**, with hard guardrails
   (never retire top-decile-usage or embedded assets without flagging; never new-build while
   covering active assets exist; always flag not-grounded metrics).

## Governance controls

- **Read-only by construction**: SQLite opened `mode=ro`; the SQL tool rejects non-SELECT and
  multi-statement input; row and cell caps.
- **Advisory only**: the agent recommends; every actionable issue carries
  `requires_human_approval`. Nothing is executed against the estate.
- **Evidence-first**: recommendations must cite IDs and numbers returned by tools; the
  system prompts forbid inventing values and require the synthetic-data disclaimer.
- **KPI consistency**: metric resolution always surfaces conflicting variants and unapproved
  variants, steering users to canonical approved definitions.
- **Decision ladder + guardrails** encoded in the system prompt (see `govagent/prompts.py`).

## Data assumptions

- All data is synthetic (Since AI 2026 builder pack). Usage windows: 2026-01..2026-10.
- KPI grounding map (`govagent/tools.py`, `KPI_GROUNDING`) encodes which canonical metrics are
  computable from the context sheets: 8 grounded, 3 derived, 7 not grounded (e.g. Budget
  Variance and Gross-to-Net Rate have no backing columns in the pack).
- Usage deciles (bottom/top 10%) are computed estate-wide from `Asset_Usage` totals.
- Business requests are templated (150 requests, 10 distinct texts); product/market contexts
  are carried as structured columns, not derived from the text.

## Enterprise-BI integration path (production)

The tool layer is the only part that touches data; swapping it for real APIs keeps the agent,
prompts and UI unchanged:

| Prototype (SQLite) | Production |
|---|---|
| `Analytics_Assets`, `Workspaces` | Power BI REST / Fabric APIs (dashboards, reports, workspaces) |
| `Semantic_Models`, `Lineage_Edges` | Fabric/Purview lineage + semantic model metadata |
| `Asset_Usage` | Power BI activity log / usage metrics |
| `KPI_Catalog` | Governed metric store / Purview catalog |
| `Governance_Signals`, `Data_Quality` | Purview scans, quality rules, endorsement state |
| `Migration_Backlog` | ITSM/change backlog |
| pharma context sheets | governed data warehouse / Fabric lakehouse tables |

Governance controls carry over: read-only service accounts, approval workflow before any
lifecycle change, evidence logging of every tool call (the agent already returns a full trace).

## Repository layout

```
govagent/            agent package (tools, llm, prompts, loop)
app.py               Streamlit chat UI + governance audit
cli.py               headless CLI (audit / ask / call / tools / demo)
smoke_test_tools.py  36 assertions over the tool layer (no LLM needed)
explore_bayer_db.py  exploratory analysis that produced the detection logic + findings.json
some_findings.md     estate profile (the domain analysis behind the agent's checks)
requirements.txt     openai, streamlit
.env.example         endpoint configuration template
```
