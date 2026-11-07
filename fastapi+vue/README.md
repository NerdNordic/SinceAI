# Build Less assistant: governed analytics for factory roles

Our Since AI Hackathon 2026 entry for Bayer's *Build Less, Build Better: AI for Governed Analytics*.

A role-based assistant: a plant manager, shift supervisor or production worker picks a role, sees the morning briefing and asks for numbers or charts in plain language. **A new chart is created only when nothing that already exists can answer the question.**

```
question ─► Gemini: question → chart spec (JSON, structured output)
         ─► canonical KPI check (vector search hints over the KPI catalogue)
         ─► fingerprint: metric + dimensions + which filters are used
         ─► REUSE   same chart exists                    → shown with fresh data
            EXTEND  same chart, other filter values      → no new asset
            ANSWER  one-off question                     → number, nothing registered
            BUILD   nothing matches                      → registered with owner, KPI, review date
            CLARIFY ambiguous / no governed metric       → asks back
         ─► computation in code from MongoDB (the LLM never calculates)
         ─► chart + receipt (KPI, definition, source rows, filters, warnings) + raw data CSV
         ─► lifecycle: use count, roles, certify / retire proposals → n8n approval → audit log
```

## Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill in, then:
set -a; source .env; set +a

# once: load the data pack into MongoDB Atlas (+ embeddings, vector indexes)
python seed_mongo.py --xlsx /path/to/Bayer_..._Builder_Data_Pack.xlsx

uvicorn app.main:app --host 0.0.0.0 --port 8000
# open http://localhost:8000
```

`GEMINI_MODEL` defaults to `gemini-2.5-flash`. Check the model list in AI Studio and set a current Flash-class model if needed. Gemini answers are cached in the `llm_cache` collection, so a rehearsed demo question runs the same way and costs no quota the second time.

## Tests

```bash
DATA_PACK_XLSX=/path/to/data_pack.xlsx pytest -q tests     # in-memory MongoDB + fake Gemini
python test_search.py                                      # real Atlas + Gemini vector search
```

The end-to-end tests cover:

- BUILD, then REUSE by another role with other words, then EXTEND
- OTIF numbers checked against pandas computed straight from the Excel file
- replenishment results matching the stand-alone module
- ANSWER and CLARIFY
- the raw CSV
- the meter
- briefings for all roles
- the approval flow with webhook secret
- the LLM cache

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/roles` | roles |
| `GET /api/briefing/{role}` | morning briefing: latest period, exceptions, freshness |
| `POST /api/ask` `{role, question}` | the whole flow above |
| `GET /api/results/{id}/raw.csv` | source rows behind a result, with sheet and Excel row |
| `GET /api/meter` | Build less meter: requests vs new charts |
| `GET /api/registry` | chart registry with use counts and certify / retire suggestions |
| `POST /api/registry/{fingerprint}/propose` `{action}` | creates a proposal and calls the n8n webhook |
| `POST /api/registry/decision` `{proposal_id, approved, approver}` | n8n (or UI) callback, header `X-Webhook-Secret` |
| `GET /api/audit` | audit log |

## n8n approval playbook

`POST /api/registry/{fp}/propose` sends this to `N8N_WEBHOOK_URL`:

```json
{"proposal_id": "...", "fingerprint": "cf-...", "title": "...", "action": "certify|retire",
 "evidence": {"use_count": 3, "used_by_roles": ["..."], "last_used_at": "...", "owner": "...", "kpi_ids": ["KPI-020"]},
 "callback_url": "https://<backend>/api/registry/decision"}
```

The n8n flow is **Webhook → Send and wait for approval** (email, Teams or Slack) **→ HTTP Request** POST to `callback_url` with `{"proposal_id", "approved", "approver"}` and header `X-Webhook-Secret`.

## Governance mapping (Bayer rules)

- **RULE-001, reuse before build:** fingerprint and registry lookup before anything is created.
- **RULE-002, canonical KPI first:** every metric is bound to a canonical KPI. Unknown metrics trigger CLARIFY.
- **RULE-003, owner required:** BUILD registers an owner and a review date.
- **RULE-005, high reach requires trust:** charts used by several roles are proposed for certification.
- **RULE-008, explain every action:** every answer carries the decision, the rule, the reason and a receipt.

## Data assumptions

- The data pack is synthetic, monthly from January to October 2026.
- `value_type` mixes actual-like and forecast-like rows. Results show how many forecast-like rows were used, and the user can ask for actuals only.
- Factory roles are scoped to one plant (`DEMO_PLANT`, default Plant-A) through Supply_Operations' product × market → supply source mapping. The data pack has no shift- or line-level data.
- Replenishment lead times are explicit assumptions in `assumptions.json` (see `reorder/`).
