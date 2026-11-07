# Production deployment, ownership and repeatable quality

This document answers three questions from the Bayer challenge owner:

1. Does the solution work beyond the plant?
2. Where would it live in a real deployment, how is access governed, and who owns what?
3. How does it produce the same quality over and over, not just one polished dashboard?

The prototype runs locally on synthetic data. Statements about production describe the
intended target design, not something already deployed.

## 1. Beyond the plant

Nothing in the engine is specific to manufacturing. The fingerprint, chart registry, receipts,
lifecycle and evaluation work the same for any business function. What is specific lives in
configuration and the metric catalogue:

| Part | Where | What changes for a new business area |
|---|---|---|
| Roles and default scope | `backend/config.py` `ROLES` | Add a role with its default scope (plant today; also country, division or cost centre) |
| Governed metrics | `backend/metrics.py` `METRICS` + KPI catalogue | Register the canonical KPI: ID, formula, source, unit, owner |
| Source data | MongoDB collections from the importer | Load the function's governed source tables |

Adding Finance or Commercial means adding definitions, not building dashboards. The prototype shows this with two roles outside the plant: a country manager scoped to Finland and a finance controller across all markets. Each is one entry in `ROLES`; their morning briefing, chat answers and card details use the same governed metric code as the plant roles. The data pack
already supports commercial and finance metrics (net sales, growth, market access, forecast
variance, forecast accuracy). The golden-question set covers them alongside production:

| Function | Example role | Default scope | Metrics available now |
|---|---|---|---|
| Production / supply | Plant director, shift supervisor, production worker | Plant | OTIF, inventory cover, units shipped, reorder-by dates |
| Commercial | Country manager, Finland (in the prototype) | Market (FI) | Net sales, net sales growth, market access coverage, OTIF and stock-out risks in the market |
| Finance | Finance controller (in the prototype) | All markets | Forecast variance, net sales, net sales growth, forecast accuracy |
| Quality, R&D, Legal | QA lead, portfolio lead, compliance | Site, portfolio | Need their own governed sources (not in the data pack) |

The pain points are the same everywhere: too many requests for too few BI developers,
duplicated reports, conflicting definitions and unclear ownership.

## 2. Where it lives in production

| Component | Prototype | Production target |
|---|---|---|
| Source data | MongoDB Atlas, loaded from the Excel data pack; every row keeps `_source` | Governed semantic models in Fabric / Power BI. The importer becomes a connector, and `_source` provenance maps to lineage (Purview). |
| Metric catalogue | Python definitions bound to KPI IDs | The semantic layer (Power BI / Fabric measures) with the same KPI IDs, owned by the KPI owners |
| Chart registry | `chart_registry` collection: fingerprint, spec, owner, lifecycle | Registry service. Certified charts are published as Power BI reports or embedded visuals into role workspaces and apps. |
| Assistant | FastAPI + Vue, one process | Container in Bayer's cloud (Azure Container Apps or OpenShift), reachable as a web app and a Teams tab |
| Language model | Gemini API | Enterprise-approved model endpoint with data-residency terms. The model only interprets and words; it can be swapped after passing the evaluation. |
| Governance automation | n8n Cloud scan writing proposals | Self-hosted n8n or Power Automate; approvals in the app or Teams |
| Audit and quality evidence | `audit_log`, `request_log`, `eval_runs` | Central logging / SIEM, retained with the chart registry |

### Access and identity

- **Single sign-on with Entra ID (OIDC).** The role comes from Entra group membership (for example `BI-PlantA-ShiftSupervisors`), not from a picker. The role picker in the prototype is a demo device and is not a security boundary.
- **Row-level scope enforced on the server.** The same mechanism that scopes plant roles to Plant-A today (a default filter added after interpretation) is driven by group claims: plant, market, division. It applies to computations, raw-data CSV export and registry search alike.
- **Data classification.** The data pack labels workspaces confidential or internal. Sources above the user's clearance are not shown; the assistant names the owner to request access from.
- **Least-privilege service identities.** The backend reads sources through a managed identity. The governance scan has a database user that can read the registry and write only proposals and audit entries.
- **Every export and decision is logged** with the user identity, so the security team can review who saw and changed what.

### What ownership means

Ownership is an accountable named person, a review date, a lifecycle state and an audit trail.
It is not just a name in a column.

| Owner | Accountable for | In the prototype |
|---|---|---|
| KPI owner | The formula and its versions. Every chart references the KPI ID, so a definition change reaches every chart that uses it. | `owner_id` in the KPI catalogue; canonical KPI ID on every receipt |
| Chart owner | That a chart is still useful; reviewed at its review date | Requesting role recorded at BUILD; `review_by` 90 days later |
| Data steward | Lifecycle: certify, retire, reassign charts whose owner has left | Data Steward view, proposals, approvals |
| Data / source owner | Source quality and refresh | `_source` provenance and data-quality warnings on receipts |
| Platform / AI team | Assistant, prompts, model and the evaluation gate | `PROMPT_VERSION`, golden questions, test suite |

### Roles and responsibilities (RACI)

R = responsible, A = accountable, C = consulted, I = informed.

| Activity | Business user | Chart owner | Data steward | KPI owner | Platform / AI team | Security |
|---|---|---|---|---|---|---|
| Ask a question, get a governed answer | R/A | | | | | |
| Create a new chart (BUILD) | R | A | I | | | |
| Reuse or extend an existing chart | R/A | I | | | | |
| Define or change a KPI | I | I | R | A | C | |
| Certify a chart | | C | A | C | | |
| Retire a chart | I | C | A | | | |
| Propose certification / retirement (scan) | | | A | | R | |
| Change prompt or model | | | I | | R/A | C |
| Grant data access | | | C | C | R | A |
| Review audit log and exports | | | I | | | R/A |

## 3. How quality is reproduced every time

Quality does not come from one hand-tuned dashboard. Every answer passes through the same
controlled pipeline, and each layer is checked:

| Layer | What it guarantees | How it is checked |
|---|---|---|
| Constrained interpretation | Gemini returns a schema-validated `ChartSpec`: one metric from an enumerated list, enumerated dimensions and statuses, temperature 0. Filters are sanitized against catalogue IDs. Anything outside the catalogue becomes a clarifying question. | Golden-question evaluation |
| Deterministic computation | Numbers are computed in Python from governed definitions; the model never calculates. Same specification + same data = same numbers. | Backend tests compare results with pandas computed straight from the workbook |
| Chart identity | The fingerprint (metric + dimensions + filter keys) maps the same question in other words to the same chart, so no duplicates are created | Backend tests: BUILD then REUSE by another role, EXTEND with other filter values |
| Evidence | Every answer carries a receipt (KPI ID, definition, source rows, filters, warnings) and a raw-data CSV | Backend tests on receipts and CSV export |
| Lifecycle | Owners, review dates, certification and retirement with an audit trail | Backend tests on proposals and decisions |

### Golden-question evaluation

`application/eval/questions.json` holds 40 questions with the interpretation each one should get:

- Finnish and English, six roles (three plant roles, country manager, finance controller, data steward), different wordings of the same intent
- production (20), commercial (7), finance (6)
- 4 questions the data cannot answer: the assistant must ask back, never guess
- 3 conversational messages

`python -m tools.run_eval` (from `application/`) asks every question twice from the real model,
without the cache, and measures:

- **Accuracy:** the interpretation matches the expectation (metric, dimensions, filters, statuses, actuals-only)
- **Consistency:** both runs give the same interpretation
- **No guessing:** unsupported questions end in a clarifying question

Each run is stored in MongoDB (`eval_runs`) and shown in the Data Steward view under
*Quality assurance*. A copy is written to `application/eval/results/latest.md` as evidence.

**Release gate:** a change to the prompt or the model is accepted only if accuracy and
consistency do not drop and no unsupported question is answered by guessing. The same gate
lets the language model be replaced with an enterprise-approved one safely.

### Known limits

- The evaluation covers interpretation, not the wording of text answers. Answers may only use
  computed numbers, but the prose is model output.
- Role and plant are user-selected in the prototype; production scoping requires SSO (section 2).
- All data is synthetic and monthly. Figures do not represent Bayer performance.
