"""End-to-end tests with an in-memory MongoDB (mongomock) and a fake Gemini.

    DATA_PACK_XLSX=/path/to/data_pack.xlsx pytest -q
"""

import io
import json
import os
from datetime import date
from pathlib import Path

import mongomock
import pandas as pd
import pytest

XLSX = os.environ.get("DATA_PACK_XLSX")
pytestmark = pytest.mark.skipif(not XLSX, reason="DATA_PACK_XLSX not set")
ROOT = Path(__file__).resolve().parent.parent

os.environ["TODAY"] = "2026-11-06"
os.environ.pop("GEMINI_API_KEY", None)        # no network: embeddings and search fall back

from app import db as dbmod, engine, spec as specmod  # noqa: E402
from app.spec import ChartSpec, Filters  # noqa: E402

# question -> what Gemini would return
FAKE = {
    "näytä toimitusvarmuus kuukausittain": ChartSpec(metric="On-Time In-Full", dimensions=["month"], chart_type="line", title="Toimitusvarmuus kuukausittain"),
    "miten toimitukset ovat onnistuneet kuukausittain?": ChartSpec(metric="On-Time In-Full", dimensions=["month"], chart_type="line", title="Toimitusten onnistuminen"),
    "toimitusvarmuus kuukausittain plant b": ChartSpec(metric="On-Time In-Full", dimensions=["month"], filters=Filters(plants=["Plant-B"]), chart_type="line", title="OTIF Plant B"),
    "mitkä tilaukset pitää tehdä tällä viikolla?": ChartSpec(metric="Replenishment Reorder-By Date", dimensions=["product", "market"], filters=Filters(statuses=["STOCKOUT_RISK", "ORDER_NOW"]), chart_type="table", title="Tilattavat nyt"),
    "mikä on varaston riittävyys suomessa nyt?": ChartSpec(metric="Inventory Coverage", dimensions=[], filters=Filters(market_ids=["FI"]), intent="one_off", title="Varaston riittävyys Suomessa"),
    "mikä on budjettipoikkeama?": ChartSpec(metric="UNSUPPORTED", understood=False, clarification_question="Budjettidataa ei ole hallitussa datassa. Tarkoititko ennustepoikkeamaa?"),
    "myynnin kasvu markkinoittain": ChartSpec(metric="Net Sales Growth", dimensions=["market"], title="Myynnin kasvu"),
    "ennustepoikkeama tuotteittain toteumasta": ChartSpec(metric="Forecast Variance", dimensions=["product"], actuals_only=True, title="Ennustepoikkeama"),
}


@pytest.fixture(scope="module")
def client():
    import seed_mongo as seed

    cols = seed.load_sheets(Path(XLSX))
    aliases = {k: v for k, v in json.loads((ROOT / "kpi_aliases.json").read_text()).items() if not k.startswith("_")}
    seed.enrich_kpis(cols["kpi_catalog"], aliases)
    seed.enrich_assets(cols["analytics_assets"], cols["asset_kpi_map"], cols["kpi_catalog"], cols["workspaces"], cols["markets"])
    db = mongomock.MongoClient()["test"]
    seed.write_mongo(db, cols, skip_vector_indexes=True, wait=0)
    dbmod.set_db(db)

    def fake_gemini(prompt: str) -> ChartSpec:
        q = prompt.rsplit('"""', 2)[-2].strip().lower()
        return FAKE[q].model_copy(deep=True)

    specmod._call_gemini = fake_gemini
    from fastapi.testclient import TestClient

    from app.main import app
    return TestClient(app)


def ask(client, q, role="tehtaan_johtaja"):
    r = client.post("/api/ask", json={"role": role, "question": q})
    assert r.status_code == 200, r.text
    return r.json()


def test_build_reuse_extend(client):
    a = ask(client, "Näytä toimitusvarmuus kuukausittain")
    assert a["decision"] == "BUILD"
    assert a["receipt"]["kpi"]["id"] == "KPI-020"
    assert a["receipt"]["filters"]["plants"] == ["Plant-A"]          # role default plant
    b = ask(client, "Miten toimitukset ovat onnistuneet kuukausittain?", role="vuoropaallikko")
    assert b["decision"] == "REUSE" and b["fingerprint"] == a["fingerprint"]
    c = ask(client, "Toimitusvarmuus kuukausittain Plant B")
    assert c["decision"] == "EXTEND" and c["fingerprint"] == a["fingerprint"]
    reg = client.get("/api/registry").json()
    chart = next(x for x in reg if x["fingerprint"] == a["fingerprint"])
    assert chart["use_count"] == 2 and set(chart["used_by_roles"]) == {"tehtaan_johtaja", "vuoropaallikko"}
    assert chart["suggestion"] == "certify"


def test_otif_numbers_match_pandas(client):
    a = ask(client, "Näytä toimitusvarmuus kuukausittain")
    x = pd.read_excel(XLSX, sheet_name=None)
    pmm, so = x["Product_Market_Monthly"], x["Supply_Operations"]
    pa = so[so.supply_source == "Plant-A"][["product_id", "market_id"]]
    df = pmm.merge(pa, on=["product_id", "market_id"])
    expected = df.groupby(df.month.dt.strftime("%Y-%m")).otif_pct_syn.mean()
    got = dict(zip(a["chart"]["labels"], a["chart"]["datasets"][0]["data"]))
    assert got == pytest.approx(expected.to_dict(), abs=0.006)
    assert a["receipt"]["source"]["forecast_like_rows"] > 0
    assert any("forecast_like" in w for w in a["receipt"]["warnings"])


def test_replenishment_matches_xlsx_module(client):
    a = ask(client, "Mitkä tilaukset pitää tehdä tällä viikolla?", role="vuoropaallikko")
    assert a["decision"] == "BUILD"
    from reorder import Assumptions, compute_all, load_data_pack
    ref = compute_all(load_data_pack(XLSX), Assumptions.load(ROOT / "assumptions.json"), today=date(2026, 11, 6))
    expected = {(r["product_name"], r["market_name"]) for r in ref
                if r["supply_source"] == "Plant-A" and r["status"] in ("STOCKOUT_RISK", "ORDER_NOW")}
    assert {(r["tuote"], r["markkina"]) for r in a["rows"]} == expected


def test_answer_and_clarify(client):
    a = ask(client, "Mikä on varaston riittävyys Suomessa nyt?")
    assert a["decision"] == "ANSWER" and len(a["rows"]) == 1
    c = ask(client, "Mikä on budjettipoikkeama?")
    assert c["decision"] == "CLARIFY" and "Budjetti" in c["reason"]


def test_growth_and_variance(client):
    g = ask(client, "Myynnin kasvu markkinoittain")
    assert g["rows"] and all("markkina" not in r for r in g["rows"])
    v = ask(client, "Ennustepoikkeama tuotteittain toteumasta")
    assert v["receipt"]["actuals_only"] is True
    assert any("jätettiin pois" in w for w in v["receipt"]["warnings"])


def test_raw_csv(client):
    a = ask(client, "Näytä toimitusvarmuus kuukausittain")
    r = client.get(f"/api/results/{a['result_id']}/raw.csv")
    df = pd.read_csv(io.StringIO(r.text))
    assert {"sheet", "excel_row", "otif_pct_syn", "plant"} <= set(df.columns)
    assert set(df["plant"]) == {"Plant-A"} and len(df) == a["receipt"]["source"]["rows_used"]


def test_meter_and_briefings(client):
    m = client.get("/api/meter").json()
    assert m["requests"] >= 5 and m["new_charts"] >= 1
    assert m["handled_without_new_chart"] == m["by_decision"]["REUSE"] + m["by_decision"]["EXTEND"] + m["by_decision"]["ANSWER"]
    for role in ("tehtaan_johtaja", "vuoropaallikko", "tuotantotyontekija", "data_steward"):
        b = client.get(f"/api/briefing/{role}").json()
        assert b["cards"], role


def test_propose_and_decide(client, monkeypatch):
    fp = ask(client, "Näytä toimitusvarmuus kuukausittain")["fingerprint"]
    p = client.post(f"/api/registry/{fp}/propose", json={"action": "certify"}).json()
    assert p["status"] == "pending" and p["sent_to_n8n"] is False
    monkeypatch.setattr("app.config.WEBHOOK_SECRET", "s3cret")
    assert client.post("/api/registry/decision", json={"proposal_id": p["proposal_id"], "approved": True}).status_code == 401
    d = client.post("/api/registry/decision", headers={"X-Webhook-Secret": "s3cret"},
                    json={"proposal_id": p["proposal_id"], "approved": True, "approver": "Maya Andersson"}).json()
    assert d["status"] == "approved"
    chart = next(x for x in client.get("/api/registry").json() if x["fingerprint"] == fp)
    assert chart["status"] == "certified"
    assert any(e["event"] == "proposal_decided" for e in client.get("/api/audit").json())


def test_llm_cache(client):
    calls = []
    orig = specmod._call_gemini
    specmod._call_gemini = lambda p: calls.append(p) or orig(p)
    ask(client, "Myynnin kasvu markkinoittain")       # asked before -> served from llm_cache
    specmod._call_gemini = orig
    assert calls == []
