"""End-to-end tests with an in-memory MongoDB (mongomock) and a fake Gemini.

    python -m pytest -q

Uses the included workbook unless DATA_PACK_XLSX selects another fixture.
"""

import io
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

import mongomock
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_XLSX = (ROOT.parent / "data" / "bayer"
                / "Bayer_Pharmaceuticals_SinceAI_2026_FINAL_Builder_Data_Pack.xlsx")
XLSX = os.environ.get("DATA_PACK_XLSX", str(DEFAULT_XLSX))
pytestmark = pytest.mark.skipif(not Path(XLSX).is_file(), reason="Data-pack workbook not found")

os.environ["TODAY"] = "2026-11-06"
os.environ["GEMINI_API_KEY"] = ""   # no network (also blocks .env from setting it): embeddings and search fall back

from backend import dashboards as dashmod, db as dbmod, engine, spec as specmod  # noqa: E402
from backend.spec import ChartSpec, Filters  # noqa: E402

# question -> what Gemini would return
FAKE = {
    "näytä toimitusvarmuus kuukausittain": ChartSpec(metric="On-Time In-Full", dimensions=["month"], chart_type="line", title="Toimitusvarmuus kuukausittain"),
    "miten toimitukset ovat onnistuneet kuukausittain?": ChartSpec(metric="On-Time In-Full", dimensions=["month"], chart_type="line", title="Toimitusten onnistuminen"),
    "toimitusvarmuus kuukausittain plant b": ChartSpec(metric="On-Time In-Full", dimensions=["month"], filters=Filters(plants=["Plant-B"]), chart_type="line", title="OTIF Plant B"),
    "mitkä tilaukset pitää tehdä tällä viikolla?": ChartSpec(metric="Replenishment Reorder-By Date", dimensions=["product", "market"], filters=Filters(statuses=["STOCKOUT_RISK", "ORDER_NOW"]), chart_type="table", title="Tilattavat nyt"),
    "mikä on varaston riittävyys suomessa nyt?": ChartSpec(metric="Inventory Coverage", dimensions=[], filters=Filters(market_ids=["FI"]), intent="one_off", title="Varaston riittävyys Suomessa"),
    "mikä on budjettipoikkeama?": ChartSpec(metric="UNSUPPORTED", understood=False, clarification_question="Budjettidataa ei ole hallitussa datassa. Tarkoititko ennustepoikkeamaa?"),
    "create a global nubeqa dashboard showing sales growth, forecast variance and market access by country.":
        ChartSpec(metric="UNSUPPORTED", understood=False,
                  clarification_question="Voin näyttää yhden mittarin kerrallaan. Valitse ensin: Net Sales Growth, Forecast Variance tai Market Access Coverage."),
    "myynnin kasvu markkinoittain": ChartSpec(metric="Net Sales Growth", dimensions=["market"], title="Myynnin kasvu"),
    "ennustepoikkeama tuotteittain toteumasta": ChartSpec(metric="Forecast Variance", dimensions=["product"], actuals_only=True, title="Ennustepoikkeama"),
    "ennustepoikkeama kuukausittain markkinoittain": ChartSpec(metric="Forecast Variance", dimensions=["month", "market"],
                                                                chart_type="line", title="Ennustepoikkeama markkinoittain"),
    # follow-up and chat
    "entä plant b?": ChartSpec(metric="On-Time In-Full", dimensions=["month"], filters=Filters(plants=["Plant-B"]), chart_type="line", title="Toimitusvarmuus kuukausittain, Plant B"),
    "mitä osaat?": ChartSpec(metric="UNSUPPORTED", mode="chat", reply="Voin näyttää tehtaan luvut ja kaaviot hallituilla määritelmillä."),
    "nettomyynti markkinoittain": ChartSpec(metric="Net Sales", dimensions=["market"], title="Nettomyynti markkinoittain"),
    "toimitetut kappaleet markkinoittain": ChartSpec(metric="Units Shipped", dimensions=["market"], title="Toimitetut kappaleet"),
    "nettomyynti kuukausittain": ChartSpec(metric="Net Sales", dimensions=["month"], chart_type="line", title="Nettomyynti kuukausittain"),
    "nettomyynti nubeqa saksassa kuukausittain": ChartSpec(metric="Net Sales", dimensions=["month"],
                                                           filters=Filters(product_ids=["P-NUB"], market_ids=["DE"]),
                                                           chart_type="line", title="Nubeqan myynti Saksassa"),
}
PROMPTS: list[str] = []


@pytest.fixture(scope="module")
def client():
    from tools import seed_mongo as seed

    cols = seed.load_sheets(Path(XLSX))
    aliases = {k: v for k, v in json.loads((ROOT / "config" / "kpi_aliases.json").read_text()).items() if not k.startswith("_")}
    seed.enrich_kpis(cols["kpi_catalog"], aliases)
    seed.enrich_assets(cols["analytics_assets"], cols["asset_kpi_map"], cols["kpi_catalog"], cols["workspaces"], cols["markets"])
    db = mongomock.MongoClient()["test"]
    seed.write_mongo(db, cols, skip_vector_indexes=True, wait=0)
    dbmod.set_db(db)

    def fake_gemini(prompt: str, language="fi") -> ChartSpec:
        PROMPTS.append(prompt)
        q = prompt.rsplit('"""', 2)[-2].strip().lower()
        return FAKE[q].model_copy(deep=True)

    specmod._call_gemini = fake_gemini
    from fastapi.testclient import TestClient

    from backend.main import app
    return TestClient(app)


def ask(client, q, role="tehtaan_johtaja", session_id=None, language="fi"):
    r = client.post("/api/ask", json={"role": role, "question": q, "session_id": session_id, "language": language})
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


def test_multiline_month_by_market(client):
    """A month x market question becomes one line per market: labels = sorted months, datasets = series."""
    a = ask(client, "Ennustepoikkeama kuukausittain markkinoittain")
    chart = a["chart"]
    assert chart["type"] == "line"
    assert chart["labels"] == sorted(set(chart["labels"])) and len(chart["labels"]) == 10   # 2026-01..2026-10
    assert len(chart["datasets"]) == 8                                     # 14 markets in scope -> top-8 series cap
    assert all(len(d["data"]) == len(chart["labels"]) for d in chart["datasets"])
    assert {"month", "market", "arvo"} <= set(a["rows"][0])               # rows stay long-format

    # every series and value must match a pandas reference over the same rows (Plant-A scope)
    x = pd.read_excel(XLSX, sheet_name=None)
    pmm, so = x["Product_Market_Monthly"], x["Supply_Operations"]
    pa = so[so.supply_source == "Plant-A"][["product_id", "market_id"]]
    df = pmm.merge(pa, on=["product_id", "market_id"])
    df["month"] = pd.to_datetime(df["month"]).dt.strftime("%Y-%m")
    ref = df.groupby(["month", "market_id"])[["net_sales_m_eur_syn", "forecast_m_eur_syn"]].sum().reset_index()
    ref["value"] = (ref["net_sales_m_eur_syn"] - ref["forecast_m_eur_syn"]).round(2)
    ref["label"] = ref["market_id"].map(dbmod.lookups()["markets"])
    top8 = ref.groupby("label")["value"].mean().abs().sort_values(ascending=False).head(8).index
    assert {d["label"] for d in chart["datasets"]} == set(top8)
    for d in chart["datasets"]:
        part = ref[ref["label"] == d["label"]]
        expected = dict(zip(part["month"], part["value"]))
        got = {m: v for m, v in zip(chart["labels"], d["data"]) if v is not None}
        assert got == pytest.approx(expected, abs=0.011)


def test_chart_pivots_long_format_into_series(client):
    from backend.metrics import _chart

    df = pd.DataFrame([
        {"month": "2026-02", "market": "FI", "value": 11.7},
        {"month": "2026-02", "market": "SE", "value": 257.7},
        {"month": "2026-03", "market": "FI", "value": -62.2},
        {"month": "2026-03", "market": "SE", "value": 31.8},
        {"month": "2026-04", "market": "FI", "value": -61.6},
        {"month": "2026-04", "market": "SE", "value": -60.1},
    ])
    chart = _chart(df, ["month", "market"], "value", "line", "Ennustepoikkeama")
    assert chart["type"] == "line"
    assert chart["labels"] == ["2026-02", "2026-03", "2026-04"]
    by_label = {d["label"]: d["data"] for d in chart["datasets"]}
    assert set(by_label) == {"Finland", "Sweden"}                          # lookups() maps FI/SE to names
    assert by_label["Finland"] == [11.7, -62.2, -61.6]
    assert by_label["Sweden"] == [257.7, 31.8, -60.1]

    # a series missing a month keeps the month axis aligned with a None gap
    sparse = df[~((df["market"] == "SE") & (df["month"] == "2026-03"))]
    gapped = _chart(sparse, ["month", "market"], "value", "line", "Ennustepoikkeama")
    se = next(d for d in gapped["datasets"] if d["label"] == "Sweden")
    assert se["data"] == [257.7, None, -60.1]


def test_spec_falls_back_to_cached_spec_when_gemini_fails(client, monkeypatch):
    """A rehearsed question keeps working from an older cache entry when Gemini is unreachable."""
    db = dbmod.get_db()
    db.llm_cache.replace_one({"_id": "old-v3-key"}, {"_id": "old-v3-key", "kind": "spec",
                                                     "question": "Ennustepoikkeama Suomessa ja Ruotsissa kuukausittain",
                                                     "role": "tehtaan_johtaja",
                                                     "spec": ChartSpec(metric="Forecast Variance", dimensions=["month", "market"],
                                                                       filters=Filters(market_ids=["FI", "SE"]), chart_type="line",
                                                                       title="Ennustepoikkeama Suomessa ja Ruotsissa").model_dump(),
                                                     "hints": [], "model": "old-model",
                                                     "created_at": datetime.now(timezone.utc)}, upsert=True)

    def dead_gemini(prompt, language="en"):
        raise RuntimeError("model is broken")

    monkeypatch.setattr(specmod, "_call_gemini", dead_gemini)
    spec, meta = specmod.generate_spec("Ennustepoikkeama Suomessa ja Ruotsissa kuukausittain",
                                       "tehtaan_johtaja", [], "fi")
    assert spec.metric == "Forecast Variance" and spec.dimensions == ["month", "market"]
    assert spec.filters.market_ids == ["FI", "SE"]
    assert meta["fallback"] is True


def test_replenishment_matches_xlsx_module(client):
    a = ask(client, "Mitkä tilaukset pitää tehdä tällä viikolla?", role="vuoropaallikko")
    assert a["decision"] == "BUILD"
    from backend.replenishment import Assumptions, compute_all, load_data_pack
    ref = compute_all(load_data_pack(XLSX), Assumptions.load(ROOT / "config" / "assumptions.json"), today=date(2026, 11, 6))
    expected = {(r["product_name"], r["market_name"]) for r in ref
                if r["supply_source"] == "Plant-A" and r["status"] in ("STOCKOUT_RISK", "ORDER_NOW")}
    assert {(r["tuote"], r["markkina"]) for r in a["rows"]} == expected


def test_answer_and_clarify(client):
    a = ask(client, "Mikä on varaston riittävyys Suomessa nyt?")
    assert a["decision"] == "ANSWER" and len(a["rows"]) == 1
    c = ask(client, "Mikä on budjettipoikkeama?")
    assert c["decision"] == "CLARIFY" and "Budjetti" in c["reason"]
    assert [s["question"] for s in c["suggestions"]] == ["Net Sales", "On-Time In-Full", "Units Shipped", "Inventory Coverage"]
    assert "suggestions" not in a


def test_clarify_suggests_the_mentioned_metrics(client):
    q = "Create a global Nubeqa dashboard showing sales growth, forecast variance and market access by country."
    a = ask(client, q)
    assert a["decision"] == "CLARIFY"
    assert [s["question"] for s in a["suggestions"]] == ["Forecast Variance", "Market Access Coverage", "Net Sales Growth"]
    assert a["suggestions"][0]["label"] == "Ennustepoikkeama"          # localized chip label (fi)


def test_growth_and_variance(client):
    g = ask(client, "Myynnin kasvu markkinoittain")
    assert g["rows"] and all("markkina" not in r for r in g["rows"])
    v = ask(client, "Ennustepoikkeama tuotteittain toteumasta")
    assert v["receipt"]["actuals_only"] is True
    assert any("jätettiin pois" in w for w in v["receipt"]["warnings"])


def test_forecast_share_in_charts(client):
    mo = pd.read_excel(XLSX, sheet_name="Product_Market_Monthly")
    mo = mo.assign(m=mo.month.dt.strftime("%Y-%m"))

    a = ask(client, "Nettomyynti kuukausittain", role="data_steward")
    dsa = a["chart"]["datasets"][0]
    assert len(dsa["forecastShare"]) == len(dsa["data"]) == len(a["chart"]["labels"])
    exp = (mo[mo.value_type != "actual_like_synthetic"].groupby("m").net_sales_m_eur_syn.sum()
           / mo.groupby("m").net_sales_m_eur_syn.sum()).round(3)
    assert dict(zip(a["chart"]["labels"], dsa["forecastShare"])) == pytest.approx(exp.to_dict(), abs=0.0011)
    assert any(0 < s < 1 for s in dsa["forecastShare"])

    b = ask(client, "Nettomyynti Nubeqa Saksassa kuukausittain", role="data_steward")
    dsb = b["chart"]["datasets"][0]
    one = mo[(mo.product_id == "P-NUB") & (mo.market_id == "DE")]
    assert {r.m: 0.0 if r.value_type == "actual_like_synthetic" else 1.0 for r in one.itertuples()} \
        == dict(zip(b["chart"]["labels"], dsb["forecastShare"]))

    c = ask(client, "Nettomyynti markkinoittain", role="data_steward")
    dsc = c["chart"]["datasets"][0]
    fc = mo.value_type != "actual_like_synthetic"
    by_market = (mo[fc].groupby("market_id").net_sales_m_eur_syn.sum()
                 / mo.groupby("market_id").net_sales_m_eur_syn.sum()).round(3)
    assert len(dsc["forecastShare"]) == len(dsc["data"]) == len(c["chart"]["labels"])
    assert sorted(dsc["forecastShare"]) == pytest.approx(sorted(by_market), abs=0.0011)
    assert any(0 < s < 1 for s in dsc["forecastShare"])

    d = ask(client, "Ennustepoikkeama tuotteittain toteumasta", role="data_steward")
    assert all(s == 0.0 for s in d["chart"]["datasets"][0]["forecastShare"])

    card = client.get("/api/briefing/tehtaan_johtaja/card/otif").json()
    otif_share = card["chart"]["datasets"][0]["forecastShare"]
    assert len(otif_share) == len(card["chart"]["datasets"][0]["data"])
    assert any(s > 0 for s in otif_share)


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
        assert all(c["key"] for c in b["cards"]), role
        assert "deviations" in b
    b = client.get("/api/briefing/tehtaan_johtaja").json()
    otif = next(c for c in b["cards"] if c["key"] == "otif")
    assert otif["target"] == 95.0 and otif["lower_is_better"] is False
    assert otif["ask_hint"] == "Show monthly delivery reliability"
    urgent = next(c for c in b["cards"] if c["key"] == "urgent")
    assert urgent["target"] == 0 and urgent["lower_is_better"] is True
    assert urgent["ask_hint"] == "Which orders need to be placed this week?"
    fi = client.get("/api/briefing/tehtaan_johtaja?language=fi").json()
    fi_hints = {c["key"]: c["ask_hint"] for c in fi["cards"] if "ask_hint" in c}
    assert fi_hints["otif"] == "Näytä toimitusvarmuus kuukausittain"
    assert fi_hints["urgent"] == "Mitkä tilaukset pitää tehdä tällä viikolla?"


def test_briefing_deviations_follow_targets(client, monkeypatch):
    monkeypatch.setattr("backend.config.CARD_TARGETS", {
        "pairs": {"target": 10**9, "lower_is_better": False, "severity": "high"},
        "volume": {"target": 10**9, "lower_is_better": False, "severity": "low"},
    })
    b = client.get("/api/briefing/tehtaan_johtaja").json()
    targeted = {c["key"] for c in b["cards"] if c.get("target") is not None}
    assert targeted == {"pairs", "volume"}
    assert [d["card_key"] for d in b["deviations"]] == ["pairs", "volume"]      # high before low
    assert b["deviations"][0]["severity"] == "high" and b["deviations"][1]["severity"] == "low"
    assert "Product–market pairs" in b["deviations"][0]["message"]
    assert all("vs target" in d["message"] for d in b["deviations"])
    fi = client.get("/api/briefing/tehtaan_johtaja?language=fi").json()
    assert "Tuote–markkina-pareja" in fi["deviations"][0]["message"]
    assert all("vs tavoite" in d["message"] for d in fi["deviations"])


def test_card_detail(client):
    b = client.get("/api/briefing/tehtaan_johtaja").json()
    otif = next(c for c in b["cards"] if c["key"] == "otif")
    d = client.get("/api/briefing/tehtaan_johtaja/card/otif").json()
    assert d["description"] and d["kpi"]["id"] == "KPI-020" and d["kpi"]["definition"]
    assert d["chart"]["type"] == "line" and d["chart"]["labels"]
    assert d["chart"]["datasets"][0]["data"][-1] == pytest.approx(otif["value"], abs=0.051)
    assert d["target"] == 95.0 and d["ask_hint"] == "Show monthly delivery reliability" and d["source"]
    assert "On-Time In-Full" in d["description"] and "rows" in d["source"]
    assert d["kpi"]["definition"] == "On-time in-full deliveries (%), averaged over rows."
    fi = client.get("/api/briefing/tehtaan_johtaja/card/otif?language=fi").json()
    assert fi["ask_hint"] == "Näytä toimitusvarmuus kuukausittain"
    assert "Toimitusvarmuus" in fi["description"] and "riviä" in fi["source"]
    assert fi["kpi"]["definition"] == "Ajallaan ja täysimääräisenä toimitettujen osuus (%), rivien keskiarvo."
    urgent = next(c for c in b["cards"] if c["key"] == "urgent")
    u = client.get("/api/briefing/tehtaan_johtaja/card/urgent").json()
    assert len(u["rows"]) == urgent["value"] and u["chart"]["labels"]
    assert all("tuote" in r and "tila" in r and "tilaa viimeistään" in r for r in u["rows"])
    vol = client.get("/api/briefing/tehtaan_johtaja/card/volume").json()
    assert vol["chart"]["type"] == "bar"
    assert sum(vol["chart"]["datasets"][0]["data"]) == pytest.approx(vol["value"], rel=0.01)
    for role in ("vuoropaallikko", "tuotantotyontekija"):
        for c in client.get(f"/api/briefing/{role}").json()["cards"]:
            d = client.get(f"/api/briefing/{role}/card/{c['key']}").json()
            assert d["description"] and d["key"] == c["key"]
    for key in ("requests", "new_charts", "handled", "certify_suggestions", "retire_suggestions"):
        d = client.get(f"/api/briefing/data_steward/card/{key}").json()
        assert d["description"] and "rows" in d
    assert client.get("/api/briefing/tehtaan_johtaja/card/nope").status_code == 404
    assert client.get("/api/briefing/data_steward/card/otif").status_code == 404
    assert client.get("/api/briefing/x/card/otif").status_code == 404


def test_card_charts(client):
    """Each briefing card whose detail has a chart also ships a compact sparkline for inline rendering."""
    for role in ("tehtaan_johtaja", "vuoropaallikko", "tuotantotyontekija"):
        sparks = client.get(f"/api/briefing/{role}/charts").json()
        cards = client.get(f"/api/briefing/{role}").json()["cards"]
        assert set(sparks) <= {c["key"] for c in cards}, role
        for c in cards:
            full = client.get(f"/api/briefing/{role}/card/{c['key']}").json().get("chart") or {}
            labels = full.get("labels") or []
            if not labels:
                assert c["key"] not in sparks, (role, c["key"])
                continue
            spark = sparks[c["key"]]
            n = min(12 if full["type"] == "line" else 6, len(labels))
            take = slice(-n, None) if full["type"] == "line" else slice(0, n)
            assert spark["type"] == full["type"], (role, c["key"])
            assert spark["labels"] == labels[take], (role, c["key"])
            assert spark["datasets"][0]["data"] == full["datasets"][0]["data"][take], (role, c["key"])
            if "forecastShare" in full["datasets"][0]:
                assert spark["datasets"][0]["forecastShare"] == full["datasets"][0]["forecastShare"][take], (role, c["key"])
    otif = client.get("/api/briefing/tehtaan_johtaja/charts").json()["otif"]
    assert otif["type"] == "line" and any(s > 0 for s in otif["datasets"][0]["forecastShare"])
    urgent = client.get("/api/briefing/tehtaan_johtaja/charts").json()["urgent"]
    assert urgent["type"] == "bar" and len(urgent["labels"]) <= 6
    assert client.get("/api/briefing/data_steward/charts").json() == {}
    assert client.get("/api/briefing/x/charts").status_code == 404


def test_propose_and_decide(client, monkeypatch):
    fp = ask(client, "Näytä toimitusvarmuus kuukausittain")["fingerprint"]
    p = client.post(f"/api/registry/{fp}/propose", json={"action": "certify"}).json()
    assert p["status"] == "pending" and p["sent_to_n8n"] is False
    monkeypatch.setattr("backend.config.WEBHOOK_SECRET", "s3cret")
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


def test_followup_uses_conversation(client):
    first = ask(client, "Näytä toimitusvarmuus kuukausittain")
    sid = first["session_id"]
    assert first["answer"]                                     # text answer (fallback without Gemini)
    follow = ask(client, "Entä Plant B?", session_id=sid)
    assert follow["session_id"] == sid
    assert follow["decision"] == "EXTEND" and follow["fingerprint"] == first["fingerprint"]
    assert "Conversation so far" in PROMPTS[-1] and "Näytä toimitusvarmuus kuukausittain" in PROMPTS[-1]
    conv = client.get(f"/api/conversations/{sid}").json()
    assert [t["q"] for t in conv["turns"]] == ["Näytä toimitusvarmuus kuukausittain", "Entä Plant B?"]


def test_chat_mode_does_not_count_as_request(client):
    before = client.get("/api/meter").json()["requests"]
    a = ask(client, "Mitä osaat?")
    assert a["decision"] == "CHAT" and "hallituilla" in a["answer"]
    assert client.get("/api/meter").json()["requests"] == before


def test_fallback_answer_uses_computed_numbers(client):
    a = ask(client, "Näytä toimitusvarmuus kuukausittain")
    last_month, last_value = a["chart"]["labels"][-1], a["chart"]["datasets"][0]["data"][-1]
    assert last_month in a["answer"] and f"{last_value:g}" in a["answer"]
    r = ask(client, "Mitkä tilaukset pitää tehdä tällä viikolla?", role="vuoropaallikko")
    assert r["rows"][0]["tuote"] in r["answer"]



def test_briefing_and_chart_agree_on_otif(client):
    b = client.get("/api/briefing/tehtaan_johtaja").json()
    card = next(c for c in b["cards"] if c["label"].startswith("OTIF"))
    a = ask(client, "Näytä toimitusvarmuus kuukausittain")
    assert round(a["chart"]["datasets"][0]["data"][-1], 1) == card["value"]


# --------------------------------------------------------------------------- dashboards


def _certify(client, fp):
    p = client.post(f"/api/registry/{fp}/propose", json={"action": "certify"}).json()
    d = client.post("/api/registry/decision", json={"proposal_id": p["proposal_id"], "approved": True})
    assert d.status_code == 200, d.text
    return d.json()


def test_dashboard_certified_only_and_matching_numbers(client):
    a = ask(client, "Nettomyynti markkinoittain")
    assert a["decision"] == "BUILD"
    fp = a["fingerprint"]
    assert client.get("/api/dashboards/x").status_code == 404
    d = client.get("/api/dashboards/tehtaan_johtaja").json()          # active -> not on the dashboard
    assert not any(t["fingerprint"] == fp for t in d["tiles"])
    assert client.post("/api/dashboards/tehtaan_johtaja/charts", json={"fingerprint": fp}).status_code == 400
    assert client.post("/api/dashboards/tehtaan_johtaja/charts", json={"fingerprint": "cf-nope"}).status_code == 404
    _certify(client, fp)
    d = client.get("/api/dashboards/tehtaan_johtaja").json()
    tile = next(t for t in d["tiles"] if t["fingerprint"] == fp)
    assert tile["pinned"] is False and tile["kpi_ids"] == ["KPI-001"]
    assert tile["chart"]["labels"] == a["chart"]["labels"]
    assert tile["chart"]["datasets"][0]["data"] == pytest.approx(a["chart"]["datasets"][0]["data"])
    assert tile["receipt"]["kpi"]["id"] == "KPI-001"
    assert "KPI-001" in d["kpi_ids"]


def test_dashboard_pin_unpin_retire(client):
    a = ask(client, "Toimitetut kappaleet markkinoittain", role="vuoropaallikko")
    fp = a["fingerprint"]
    _certify(client, fp)
    d = client.get("/api/dashboards/tuotantotyontekija").json()      # worker never used it
    assert not any(t["fingerprint"] == fp for t in d["tiles"])
    meta = client.get("/api/dashboards/tuotantotyontekija?tiles=false").json()
    assert "tiles" not in meta and meta["pinned"] == []               # metadata-only view for the steward UI
    r = client.post("/api/dashboards/tuotantotyontekija/charts", json={"fingerprint": fp})
    assert r.status_code == 200 and r.json()["pinned"] == [fp]       # pin -> tile for a role that never used it
    d = client.get("/api/dashboards/tuotantotyontekija").json()
    assert d["tiles"][0]["fingerprint"] == fp and d["tiles"][0]["pinned"] is True
    assert d["tiles"][0]["chart"]["datasets"][0]["data"] == pytest.approx(a["chart"]["datasets"][0]["data"])
    assert client.delete("/api/dashboards/tuotantotyontekija/charts/" + fp).status_code == 200
    d = client.get("/api/dashboards/tuotantotyontekija").json()      # unpin -> auto rule only -> gone
    assert d["pinned"] == [] and not any(t["fingerprint"] == fp for t in d["tiles"])
    p = client.post(f"/api/registry/{fp}/propose", json={"action": "retire"}).json()
    client.post("/api/registry/decision", json={"proposal_id": p["proposal_id"], "approved": True})
    d = client.get("/api/dashboards/vuoropaallikko").json()          # retired -> drops from every dashboard
    assert not any(t["fingerprint"] == fp for t in d["tiles"])
    events = [e["event"] for e in client.get("/api/audit").json()]
    assert "chart_pinned" in events and "chart_unpinned" in events


def test_registry_preview_before_and_after_retirement(client):
    fp = ask(client, "Nettomyynti kuukausittain", role="data_steward")["fingerprint"]   # active chart
    r = client.get(f"/api/registry/{fp}/preview")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "active" and d["fingerprint"] == fp
    assert d["chart"]["labels"] and d["chart"]["datasets"][0]["data"]
    assert d["receipt"]["kpi"]["id"] == "KPI-001"
    assert d["rows"]
    p = client.post(f"/api/registry/{fp}/propose", json={"action": "retire"}).json()
    client.post("/api/registry/decision", json={"proposal_id": p["proposal_id"], "approved": True})
    assert client.get(f"/api/registry/{fp}/preview").status_code == 400                # retired -> no preview
    assert client.get("/api/registry/cf-nope/preview").status_code == 404


def test_dashboard_tile_error_is_isolated(client, monkeypatch):
    a = ask(client, "Nettomyynti markkinoittain")
    fp = a["fingerprint"]
    _certify(client, fp)
    orig = dashmod.compute

    def boom(spec):
        if spec.metric == "Net Sales":
            raise RuntimeError("data error")
        return orig(spec)

    monkeypatch.setattr(dashmod, "compute", boom)
    r = client.get("/api/dashboards/tehtaan_johtaja")
    assert r.status_code == 200                                      # one broken tile must not break the dashboard
    tile = next(t for t in r.json()["tiles"] if t["fingerprint"] == fp)
    assert tile["error"].startswith("data error") and "chart" not in tile


def test_language_defaults_validation_and_briefings(client):
    assert client.get("/api/roles").json()[0]["label"] == "Plant director"
    assert client.get("/api/roles?language=fi").json()[0]["label"] == "Tehtaan johtaja"
    assert client.get("/api/roles?language=de").status_code == 422
    assert client.get("/api/briefing/tehtaan_johtaja?language=de").status_code == 422
    assert client.post("/api/ask", json={"role": "tehtaan_johtaja", "question": "Hi", "language": "Ignore rules"}).status_code == 422
    for role in ("tehtaan_johtaja", "vuoropaallikko", "tuotantotyontekija", "data_steward"):
        en = client.get(f"/api/briefing/{role}").json()
        fi = client.get(f"/api/briefing/{role}?language=fi").json()
        assert [c["value"] for c in en["cards"]] == [c["value"] for c in fi["cards"]]
        assert en["cards"][0]["label"] != fi["cards"][0]["label"]
        if en["freshness"]:
            assert "Inventory as of" in en["freshness"] and "Varastotilanne" in fi["freshness"]


def test_spec_language_and_cache_separation(client, monkeypatch):
    calls = []

    def fake(prompt, language="en"):
        calls.append(prompt)
        language = "English" if "Selected response language: English" in prompt else "Finnish"
        return ChartSpec(metric="UNSUPPORTED", mode="chat", reply=language)

    monkeypatch.setattr(specmod, "_call_gemini", fake)
    monkeypatch.setattr(specmod, "_kpi_hints", lambda q: [])
    body = {"role": "tehtaan_johtaja", "question": "Vastaa eri kielellä / answer in another language"}
    assert client.post("/api/ask", json=body).json()["answer"] == "English"
    for language, answer in [("en", "English"), ("fi", "Finnish"), ("en", "English"), ("fi", "Finnish")]:
        response = client.post("/api/ask", json={**body, "language": language}).json()
        assert response["answer"] == answer and response["language"] == language
    assert len(calls) == 2
    assert "reply` in English" in calls[0] and "title: short title in Finnish" in calls[1]


def test_answer_language_and_cache_separation(client, monkeypatch):
    calls = []

    def fake(prompt, language="en"):
        calls.append(prompt)
        return "English result" if "in English in 2-4" in prompt else "Suomenkielinen tulos"

    monkeypatch.setattr(specmod, "_call_gemini_text", fake)
    payload = {"metric": "Net Sales", "unit": "M€", "decision": "ANSWER", "decision_reason": "test",
               "rows": [{"arvo": 123}], "warnings": []}
    for language, expected in [("en", "English result"), ("fi", "Suomenkielinen tulos")]:
        assert specmod.write_answer("Language cache test", payload, language) == expected
        assert specmod.write_answer("Language cache test", payload, language) == expected
    assert len(calls) == 2


def test_metric_localization_preserves_calculations(client):
    from backend import metrics

    for name in metrics.METRICS:
        spec = ChartSpec(metric=name, dimensions=["product"], filters=Filters(plants=["Plant-A"]))
        en, fi = metrics.compute(spec, "en"), metrics.compute(spec, "fi")
        # Only explanatory text changes; source provenance and every numeric value stay identical.
        assert en["source"] == fi["source"]
        assert [{k: v for k, v in r.items() if k != "nopeutus"} for r in en["rows"]] == [
            {k: v for k, v in r.items() if k != "nopeutus"} for r in fi["rows"]]
        assert [d["data"] for d in en["chart"]["datasets"]] == [d["data"] for d in fi["chart"]["datasets"]]
        assert en["receipt"]["definition"] != fi["receipt"]["definition"]
        if name == "On-Time In-Full":
            assert any("source rows are forecast-like" in w for w in en["receipt"]["warnings"])
            assert any("lähderiviä" in w for w in fi["receipt"]["warnings"])


def test_localized_fallbacks_and_empty_results(client, monkeypatch):
    from backend import metrics

    monkeypatch.setattr(engine, "write_answer", lambda *args: None)
    monkeypatch.setattr(specmod, "_kpi_hints", lambda q: [])
    monkeypatch.setattr(specmod, "_call_gemini", lambda p, language="en": ChartSpec(
        metric="Replenishment Reorder-By Date", title="Orders", dimensions=["product"]))
    en = ask(client, "localization fallback", language="en")
    fi = ask(client, "localization fallback", language="fi")
    assert "order by" in en["answer"] and "tilaa viimeistään" in fi["answer"]
    assert "by " in en["reason"] or "chart" in en["reason"]
    missing = ChartSpec(metric="On-Time In-Full", filters=Filters(product_ids=["not-a-product"]))
    empty = metrics.compute(missing, "en")
    assert empty["rows"] == [] and empty["receipt"]["warnings"] == ["No rows match the selection."]
    assert engine.fallback_answer(missing, empty, "en") == "No data matches the selection."


def test_reuse_across_languages_keeps_identity(client, monkeypatch):
    monkeypatch.setattr(engine, "write_answer", lambda *args: None)
    monkeypatch.setattr(specmod, "_kpi_hints", lambda q: [])
    monkeypatch.setattr(specmod, "_call_gemini", lambda p, language="en": ChartSpec(
        metric="Units Shipped", dimensions=["market", "product"],
        title="Shipped units" if "Selected response language: English" in p else "Toimitetut kappaleet"))
    en = ask(client, "bilingual chart identity", language="en")
    fi = ask(client, "bilingual chart identity", language="fi", session_id=en["session_id"])
    assert en["fingerprint"] == fi["fingerprint"] and fi["decision"] == "REUSE"
    assert en["title"] == "Shipped units" and fi["title"] == "Toimitetut kappaleet"
    chart = dbmod.get_db().chart_registry.find_one({"fingerprint": en["fingerprint"]})
    assert chart["titles"] == {"en": "Shipped units", "fi": "Toimitetut kappaleet"}
    assert len(dbmod.get_db().conversations.find_one({"_id": en["session_id"]})["turns"]) == 2


def test_static_responses_always_revalidate(client):
    index = client.get("/")
    assert index.status_code == 200
    assert index.headers["cache-control"] == "no-cache"
    i18n = client.get("/static/i18n.js")
    assert i18n.status_code == 200
    assert i18n.headers["cache-control"] == "no-cache"
