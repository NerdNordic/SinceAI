"""Run the SinceAI app for the video demo.

Database: mongomock seeded from the Bayer data pack, plus deterministic
lived-in state (request meter 76/19/32, chart registry, dashboards, audit,
proposals) matching the local instance's numbers. Real Gemini by default;
set VIDEO_DEMO_FAST=1 to replay the canned specs/answers in responses_fast.json
(fingerprints, decisions, charts, receipts and CSV exports are still computed
for real). Set VIDEO_DEMO_REGISTRY_JSON to a file containing a /api/registry
JSON array to import real charts instead of the synthetic ones.

Run from the application directory with the project venv:
  python -m tools.video_demo.app_offline
"""

import json
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

APP = Path(__file__).resolve().parents[2]          # .../application
ROOT = APP.parent                                 # repository root
XLSX = ROOT / "data/bayer/Bayer_Pharmaceuticals_SinceAI_2026_FINAL_Builder_Data_Pack.xlsx"
FAST_RESPONSES = Path(__file__).resolve().parent / "responses_fast.json"

os.environ["N8N_WEBHOOK_URL"] = ""                # no live notifications during recording
sys.path.insert(0, str(APP))

import mongomock  # noqa: E402

from tools import seed_mongo as seed  # noqa: E402
from backend import config, metrics  # noqa: E402
from backend import db as dbmod  # noqa: E402
from backend import engine  # noqa: E402
from backend.spec import ChartSpec  # noqa: E402

cols = seed.load_sheets(XLSX)
aliases = {k: v for k, v in
           json.loads((APP / "config" / "kpi_aliases.json").read_text(encoding="utf-8")).items()
           if not k.startswith("_")}
seed.enrich_kpis(cols["kpi_catalog"], aliases)
seed.enrich_assets(cols["analytics_assets"], cols["asset_kpi_map"], cols["kpi_catalog"],
                   cols["workspaces"], cols["markets"])
db = mongomock.MongoClient()[config.MONGODB_DB or "bayer_hackathon"]
seed.write_mongo(db, cols, skip_vector_indexes=True, wait=0)
dbmod.set_db(db)
print(f"seeded mongomock db '{db.name}': {len(db.list_collection_names())} collections", flush=True)

# ---------------------------------------------------------------- lived-in state
random.seed(42)
now_dt = datetime.now(timezone.utc).replace(tzinfo=None)   # naive UTC, like pymongo returns


def iso_ago(**kw):
    return (now_dt - timedelta(**kw)).isoformat()


# request_log -> header meter: 76 requests / 19 new charts / 32 without a new chart
decisions = (["BUILD"] * 19 + ["REUSE"] * 24 + ["EXTEND"] * 5 + ["ANSWER"] * 3 + ["CLARIFY"] * 25)
roles_pool = (["tehtaan_johtaja"] * 34 + ["vuoropaallikko"] * 22 +
              ["tuotantotyontekija"] * 12 + ["data_steward"] * 8)
random.shuffle(decisions)
for i, dec in enumerate(decisions):
    db.request_log.insert_one({
        "ts": now_dt - timedelta(hours=random.uniform(0, 96)),
        "decision": dec, "role": roles_pool[i % len(roles_pool)],
    })


def add_chart(metric, dimensions, title, *, status, owner_role, used_by, use_count,
              last_used_days, filters=None):
    spec = ChartSpec(metric=metric, dimensions=dimensions, filters=filters or {}, title=title)
    fp = engine.fingerprint(spec)
    m = metrics.METRICS[metric]
    db.chart_registry.insert_one({
        "fingerprint": fp, "title": title, "titles": {"en": title}, "language": "en",
        "description": f"{metric} by {', '.join(dimensions) or 'total'}",
        "role": owner_role, "plant": (spec.filters.plants or [None])[0],
        "kpi_ids": [m.kpi_id], "spec": spec.model_dump(), "filters": spec.filters.model_dump(),
        "owner": config.ROLES[owner_role]["label"], "status": status,
        "review_by": (now_dt + timedelta(days=60)).date().isoformat(),
        "used_by_roles": used_by, "use_count": use_count,
        "created_at": now_dt - timedelta(days=last_used_days + 30),
        "updated_at": now_dt - timedelta(days=last_used_days),
        "last_used_at": now_dt - timedelta(days=last_used_days),
    })
    return fp


JOHTAJA, VUORO = "tehtaan_johtaja", "vuoropaallikko"
registry_json = os.environ.get("VIDEO_DEMO_REGISTRY_JSON")
if registry_json:
    # import real charts from a pasted /api/registry response
    docs = json.loads(Path(registry_json).read_text(encoding="utf-8"))
    dt_fields = ("created_at", "updated_at", "last_used_at")
    for doc in docs:
        for k in dt_fields:
            if isinstance(doc.get(k), str):
                doc[k] = datetime.fromisoformat(doc[k].replace("Z", "+00:00")).replace(tzinfo=None) \
                    if "+" in doc[k] else datetime.fromisoformat(doc[k])
        doc.pop("suggestion", None)
        db.chart_registry.insert_one(doc)
    print(f"imported {len(docs)} charts from {registry_json}", flush=True)
else:
    # Both metric mappings Gemini may produce for "Show net sales month over month"
    # are seeded certified, so the first demo question REUSEs either way.
    fp_sales = add_chart("Net Sales", ["month"], "Net Sales by month",
                         status="certified", owner_role=JOHTAJA, used_by=[JOHTAJA, VUORO],
                         use_count=6, last_used_days=1,
                         filters={"plants": [config.DEMO_PLANT]})
    add_chart("Net Sales Growth", ["month"], "Net Sales Growth by Month",
              status="certified", owner_role=JOHTAJA, used_by=[JOHTAJA, VUORO],
              use_count=3, last_used_days=2,
              filters={"plants": [config.DEMO_PLANT]})
    fp_otif = add_chart("On-Time In-Full", ["market"], "OTIF by market",
                        status="certified", owner_role=VUORO, used_by=[VUORO],
                        use_count=4, last_used_days=2,
                        filters={"plants": [config.DEMO_PLANT]})
    fp_units = add_chart("Units Shipped", ["product"], "Units Shipped by product",
                         status="active", owner_role=JOHTAJA, used_by=[JOHTAJA, VUORO],
                         use_count=2, last_used_days=3)
    add_chart("Net Sales", ["market"], "Net Sales by market",
              status="active", owner_role=JOHTAJA, used_by=[JOHTAJA],
              use_count=4, last_used_days=1)
    fp_inv = add_chart("Inventory Coverage", ["market"], "Inventory Coverage by market",
                       status="active", owner_role=VUORO, used_by=[VUORO],
                       use_count=1, last_used_days=60)
    db.dashboards.insert_one({"_id": JOHTAJA, "charts": [fp_sales]})
    db.dashboards.insert_one({"_id": VUORO, "charts": [fp_otif]})
    for ev, kwargs, hours in [
        ("chart_registered", {"fingerprint": fp_sales, "role": JOHTAJA, "title": "Net Sales by month"}, 96),
        ("chart_pinned", {"fingerprint": fp_sales, "role": JOHTAJA}, 70),
        ("chart_registered", {"fingerprint": fp_units, "role": JOHTAJA, "title": "Units Shipped by product"}, 60),
        ("chart_pinned", {"fingerprint": fp_otif, "role": VUORO}, 50),
    ]:
        db.audit_log.insert_one({"ts": now_dt - timedelta(hours=hours), "event": ev, **kwargs})
    pid = uuid.uuid4().hex[:10]
    db.proposals.insert_one({
        "_id": pid, "fingerprint": fp_units, "title": "Units Shipped by product", "action": "certify",
        "status": "pending",
        "evidence": {"use_count": 2, "used_by_roles": [JOHTAJA, VUORO],
                     "last_used_at": iso_ago(days=3), "owner": config.ROLES[JOHTAJA]["label"],
                     "kpi_ids": [metrics.METRICS["Units Shipped"].kpi_id]},
        "created_at": now_dt - timedelta(days=2),
    })
    db.proposals.insert_one({
        "_id": uuid.uuid4().hex[:10], "fingerprint": fp_inv, "title": "Inventory Coverage by market",
        "action": "retire", "status": "approved",
        "evidence": {"use_count": 1, "used_by_roles": [VUORO],
                     "last_used_at": iso_ago(days=60), "owner": config.ROLES[VUORO]["label"],
                     "kpi_ids": [metrics.METRICS["Inventory Coverage"].kpi_id]},
        "created_at": now_dt - timedelta(days=20),
        "decided_by": "Data Steward", "decided_at": now_dt - timedelta(days=19),
    })

print(f"seeded state: {db.request_log.count_documents({})} requests, "
      f"{db.chart_registry.count_documents({})} charts, "
      f"{db.audit_log.count_documents({})} audit events, "
      f"{db.proposals.count_documents({})} proposals", flush=True)

# ---------------------------------------------------------------- fast mode
if os.environ.get("VIDEO_DEMO_FAST") == "1":
    canned = json.loads(FAST_RESPONSES.read_text(encoding="utf-8"))["questions"]

    def fake_generate_spec(question, role, history=None, language="en", **_):
        entry = canned.get(question)
        if entry is None:
            raise RuntimeError(f"VIDEO_DEMO_FAST: no canned spec for question {question!r}")
        return ChartSpec.model_validate(entry["spec"]), {"cached": False, "hints": []}

    def fake_write_answer(question, payload, language="en"):
        entry = canned[question]
        return entry["answers"].get(language) or entry["answers"]["en"]

    engine.generate_spec = fake_generate_spec
    engine.write_answer = fake_write_answer
    print("VIDEO_DEMO_FAST: replaying canned Gemini responses", flush=True)

import uvicorn  # noqa: E402

uvicorn.run("backend.main:app", host="0.0.0.0", port=int(os.environ.get("VIDEO_DEMO_PORT", "8000")),
            log_level="info")
