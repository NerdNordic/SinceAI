"""Intake integration tests: seeded in-memory data and strictly mocked external services."""

import json
from copy import deepcopy
from pathlib import Path

import mongomock
import pytest
from fastapi.testclient import TestClient

from backend import config, db as dbmod, engine, intake, spec as specmod
from backend.main import app
from backend.spec import ChartSpec, Filters, Interpretation
from tools import seed_mongo

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def source():
    xlsx = next((ROOT.parent / "data/bayer").glob("*.xlsx"))
    cols = seed_mongo.load_sheets(xlsx)
    aliases = json.loads((ROOT / "config/kpi_aliases.json").read_text(encoding="utf-8"))
    seed_mongo.enrich_kpis(cols["kpi_catalog"], {k: v for k, v in aliases.items() if not k.startswith("_")})
    return cols


@pytest.fixture
def sandbox(source, monkeypatch):
    previous = dbmod._db
    db = mongomock.MongoClient()["intake_test"]
    for name, rows in source.items():
        if rows:
            db[name].insert_many(deepcopy(rows))
    dbmod.set_db(db)
    monkeypatch.setattr(config, "N8N_WEBHOOK_URL", "")
    monkeypatch.setattr(config, "WEBHOOK_SECRET", "")
    monkeypatch.setattr(specmod, "_kpi_hints", lambda q: [])
    monkeypatch.setattr(engine, "write_answer", lambda *args: None)
    monkeypatch.setattr(engine, "_similar_charts", lambda *args: [])
    monkeypatch.setattr(engine, "_related_reports", lambda *args: [])

    def no_external(*args, **kwargs):
        raise RuntimeError("External services disabled in intake tests")

    monkeypatch.setattr("backend.vector_store._gemini", no_external)
    monkeypatch.setattr("backend.vector_store.register_chart", no_external)
    with TestClient(app) as client:
        yield client, db
    dbmod.set_db(previous)


def interpreted(metric="Net Sales", outcome="READY", **brief):
    return Interpretation(brief=intake.RequestBrief(**brief), outcome=outcome,
                          spec=ChartSpec(metric=metric, dimensions=["market"], title="Sales"))


def post(client, question, sid=None, language="en", **extra):
    return client.post("/api/ask", json={"question": question, "role": "tehtaan_johtaja",
                                       "session_id": sid, "language": language, **extra})


def test_clear_request_proceeds_without_business_interview(sandbox, monkeypatch):
    client, db = sandbox
    monkeypatch.setattr(specmod, "_call_gemini", lambda *args: interpreted(usage="one_off"))
    result = post(client, "Show net sales by market").json()
    assert result["decision"] == "ANSWER" and result["intake"]["outcome"] == "READY"
    assert result["brief"]["business_decision"] is None
    assert result["rows"] and db.chart_registry.count_documents({}) == 0


def test_ambiguity_does_not_compute_register_or_consume_chart_usage(sandbox, monkeypatch):
    client, db = sandbox
    monkeypatch.setattr(specmod, "_call_gemini", lambda *args: interpreted(outcome="ASK", unresolved_terms=["supply risk"]))
    monkeypatch.setattr(engine.metrics, "compute", lambda *args: pytest.fail("computed during intake"))
    monkeypatch.setattr(engine, "_register", lambda *args: pytest.fail("registered during intake"))
    a = post(client, "We need a monthly supply-risk dashboard by medicine and country").json()
    assert a["decision"] == "CLARIFY" and len(a["intake"]["questions"]) <= 2
    assert db.results.count_documents({}) == db.chart_registry.count_documents({}) == 0
    assert db.conversations.find_one({"_id": a["session_id"]})["pending_request"]["original_request"].startswith("We need")


def test_multi_metric_requests_cannot_be_narrowed_by_model_alone(sandbox, monkeypatch):
    client, db = sandbox
    monkeypatch.setattr(specmod, "_call_gemini", lambda *args: interpreted(
        "Forecast Variance", requested_metrics=["Forecast Variance"], selected_metric="Forecast Variance",
        scope="global", product_ids=["P-NUB"], usage="one_off"))
    q = "Create a global Nubeqa dashboard showing sales growth, forecast variance and market access by country."
    a = post(client, q).json()
    assert a["decision"] == "CLARIFY"
    assert set(a["brief"]["requested_metrics"]) == {"Forecast Variance", "Net Sales Growth", "Market Access Coverage"}
    assert a["brief"]["selected_metric"] is None
    # Even a model that repeats the role's plant default must preserve the
    # original explicit global scope during a short metric-selection reply.
    def next_interpretation(*args):
        response = interpreted("Forecast Variance", usage="one_off")
        response.spec.filters.plants = ["Plant-A"]
        return response

    monkeypatch.setattr(specmod, "_call_gemini", next_interpretation)
    b = post(client, "Forecast Variance", a["session_id"]).json()
    assert b["decision"] == "ANSWER"
    assert set(b["brief"]["requested_metrics"]) == set(a["brief"]["requested_metrics"])
    assert b["spec"]["filters"]["product_ids"] == ["P-NUB"]
    assert b["spec"]["filters"]["plants"] == []
    assert "pending_request" not in db.conversations.find_one({"_id": a["session_id"]})


def test_separate_sales_and_growth_mentions_are_both_retained():
    assert set(intake.mentioned_metrics("Net Sales and Net Sales Growth")) == {"Net Sales", "Net Sales Growth"}


def test_budget_variance_is_not_forecast_variance(sandbox, monkeypatch):
    client, db = sandbox
    monkeypatch.setattr(specmod, "_call_gemini", lambda *args: interpreted("Forecast Variance", usage="one_off"))
    a = post(client, "Show budget variance by product").json()
    assert a["decision"] == "CLARIFY"
    assert "Budget Variance" in a["brief"]["requested_metrics"]
    assert db.results.count_documents({}) == 0


def test_global_scope_overrides_role_default_not_products(sandbox, monkeypatch):
    client, _ = sandbox
    response = interpreted(scope="global", usage="one_off", product_ids=["P-NUB"])
    response.spec.filters = Filters(product_ids=["P-NUB"], plants=["Plant-A"])
    monkeypatch.setattr(specmod, "_call_gemini", lambda *args: response)
    a = post(client, "Show global Nubeqa net sales by country").json()
    assert a["decision"] == "ANSWER"
    assert a["spec"]["filters"] == {"product_ids": ["P-NUB"], "market_ids": [], "plants": [], "statuses": []}


@pytest.mark.parametrize("field,value", [("product_ids", "P-INVALID"), ("market_ids", "ZZ"), ("plants", "Plant-X")])
def test_unknown_identifiers_are_never_dropped(sandbox, monkeypatch, field, value):
    client, db = sandbox
    response = interpreted(usage="one_off")
    setattr(response.spec.filters, field, [value])
    monkeypatch.setattr(specmod, "_call_gemini", lambda *args: response)
    a = post(client, "Show net sales").json()
    assert a["decision"] == "CLARIFY" and value in a["answer"]
    assert db.results.count_documents({}) == 0


@pytest.mark.parametrize("brief", [
    {"period": "range", "start_month": "2026-02", "end_month": "2026-03"},
    {"scope": "regional", "regions": ["EMEA"]}, {"comparison": "yoy"},
    {"actual_forecast": "forecast_only"}, {"granularity": "quarter"},
])
def test_unsupported_semantics_require_an_explicit_alternative(sandbox, monkeypatch, brief):
    client, db = sandbox
    monkeypatch.setattr(specmod, "_call_gemini", lambda *args: interpreted(usage="one_off", **brief))
    a = post(client, "Show net sales by market").json()
    assert a["decision"] == "CLARIFY" and a["intake"]["alternatives"]
    assert db.results.count_documents({}) == 0


def test_accepting_supported_time_alternative_clears_blocker(sandbox, monkeypatch):
    client, _ = sandbox
    calls = iter([interpreted(usage="one_off", period="range", start_month="2026-02"), interpreted(usage="one_off")])
    monkeypatch.setattr(specmod, "_call_gemini", lambda *args: next(calls))
    a = post(client, "Show net sales in 2026-02").json()
    assert a["decision"] == "CLARIFY"
    b = post(client, a["intake"]["alternatives"][0]["label"], a["session_id"]).json()
    assert b["decision"] == "ANSWER" and b["brief"]["period"] == "all_available"


def test_grill_mode_accumulates_answers_without_repeating_resolved_fields(sandbox, monkeypatch):
    client, db = sandbox
    calls = []
    responses = iter([
        interpreted(usage="unknown"),
        interpreted(usage="recurring", audience="management", questions=[intake.IntakeQuestion(id="audience", field="audience", text="Who will use it?")]),
        interpreted(usage="recurring", business_decision="Plan next month's inventory", audience=""),
    ])

    def fake(prompt, language):
        calls.append(prompt)
        return next(responses)

    monkeypatch.setattr(specmod, "_call_gemini", fake)
    a = post(client, "/grill-me").json()
    assert a["decision"] == "CLARIFY" and not calls
    b = post(client, "Show net sales by country", a["session_id"]).json()
    assert b["intake"]["mode"] == "grill"
    c = post(client, "monthly, for the management team", a["session_id"], language="fi").json()
    assert c["decision"] == "CLARIFY" and c["brief"]["audience"] == "management"
    assert all(q["field"] not in {"audience", "usage"} for q in c["intake"]["questions"])
    d = post(client, "Plan next month's inventory", a["session_id"]).json()
    assert d["decision"] == "BUILD" and d["brief"]["original_request"] == "Show net sales by country"
    assert d["brief"]["audience"] == "management"
    assert '"audience": "management"' in calls[-1]
    assert "pending_request" not in db.conversations.find_one({"_id": a["session_id"]})


def test_pending_survives_provider_failure_and_new_conversation_abandons_it(sandbox, monkeypatch):
    client, db = sandbox
    monkeypatch.setattr(specmod, "_call_gemini", lambda *args: interpreted(outcome="ASK", unresolved_terms=["performance"]))
    a = post(client, "Show performance").json()
    before = db.conversations.find_one({"_id": a["session_id"]})["pending_request"]

    def fail(*args):
        raise RuntimeError("private provider details")

    monkeypatch.setattr(specmod, "_call_gemini", fail)
    response = post(client, "monthly", a["session_id"])
    assert response.status_code == 503 and "private" not in response.text
    assert db.conversations.find_one({"_id": a["session_id"]})["pending_request"] == before
    assert post(client, "", a["session_id"], abandon_pending=True).status_code == 200
    assert "pending_request" not in db.conversations.find_one({"_id": a["session_id"]})


def test_explicit_replacement_does_not_inherit_old_scope(sandbox, monkeypatch):
    client, _ = sandbox
    responses = iter([interpreted(outcome="ASK", unresolved_terms=["performance"], product_ids=["P-NUB"]),
                      interpreted("Units Shipped", usage="one_off")])
    monkeypatch.setattr(specmod, "_call_gemini", lambda *args: next(responses))
    a = post(client, "Show Nubeqa performance").json()
    b = post(client, "New request: units shipped by country", a["session_id"]).json()
    assert b["decision"] == "ANSWER" and b["spec"]["filters"]["product_ids"] == []
    assert b["brief"]["requested_metrics"] == ["Units Shipped"]


def test_pending_state_is_part_of_cache_identity(sandbox, monkeypatch):
    calls = []
    monkeypatch.setattr(specmod, "_call_gemini", lambda *args: calls.append(args) or interpreted())
    a = intake.PendingRequest(original_request="sales", brief=intake.RequestBrief(audience="directors")).model_dump()
    b = deepcopy(a)
    b["brief"]["audience"] = "operators"
    for state in [a, b, a]:
        specmod.generate_spec("monthly", "tehtaan_johtaja", [], "en", state)
    assert len(calls) == 2


def test_verified_reuse_is_distinct_from_search_outage(sandbox, monkeypatch):
    _, db = sandbox
    brief = intake.RequestBrief(requested_metrics=["Net Sales"], usage="recurring")
    spec = ChartSpec(metric="Net Sales", dimensions=["market"])
    db.chart_registry.insert_one({"fingerprint": "cf-verified", "title": "Sales by market", "status": "certified",
                                  "spec": spec.model_dump(), "filters": Filters(plants=["Plant-A"]).model_dump()})
    evidence = intake.reuse_evidence(spec, brief, "tehtaan_johtaja")
    assert evidence["status"] == "verified" and evidence["candidates"][0]["id"] == "cf-verified"

    def fail():
        raise RuntimeError("DB down")

    monkeypatch.setattr(dbmod, "get_db", fail)
    evidence = intake.reuse_evidence(spec, brief, "tehtaan_johtaja")
    assert evidence["status"] == "unavailable" and evidence["search_failed"]


def test_catalog_candidates_are_not_claimed_verified(sandbox):
    _, db = sandbox
    db.analytics_assets.insert_one({"_id": "AST-TEST", "canonical_metrics": ["Net Sales"],
                                    "lifecycle_status": "active", "asset_name": "Unknown scope"})
    evidence = intake.reuse_evidence(ChartSpec(metric="Net Sales"), intake.RequestBrief(requested_metrics=["Net Sales"]), "tehtaan_johtaja")
    assert evidence["status"] == "needs_verification"
    db.analytics_assets.delete_one({"_id": "AST-TEST"})
    assert intake.reuse_evidence(ChartSpec(metric="Net Sales"), intake.RequestBrief(requested_metrics=["Net Sales"]), "tehtaan_johtaja")["status"] == "none"


def test_model_cannot_silently_relax_time_requirement(sandbox, monkeypatch):
    client, db = sandbox
    responses = iter([interpreted(usage="one_off", period="range", start_month="2025-01"),
                      interpreted(usage="one_off", period="all_available")])
    monkeypatch.setattr(specmod, "_call_gemini", lambda *args: next(responses))
    a = post(client, "Show net sales for 2025").json()
    b = post(client, "monthly", a["session_id"]).json()
    assert b["decision"] == "CLARIFY" and b["brief"]["period"] == "range"
    assert db.results.count_documents({}) == 0


def test_answered_model_question_does_not_trigger_repeated_interview(sandbox, monkeypatch):
    client, _ = sandbox
    question = intake.IntakeQuestion(id="audience", field="audience", text="Who will use it?")
    monkeypatch.setattr(specmod, "_call_gemini", lambda *args: interpreted(
        outcome="ASK", usage="one_off", audience="management", questions=[question]))
    a = post(client, "Show net sales by market for management").json()
    assert a["decision"] == "ANSWER"


def test_no_turn_limit_for_unresolved_request(sandbox, monkeypatch):
    client, db = sandbox
    monkeypatch.setattr(specmod, "_call_gemini", lambda *args: interpreted(unresolved_terms=["supply risk"]))
    a = post(client, "supply risk").json()
    for _ in range(6):
        a = post(client, "monthly", a["session_id"]).json()
        assert a["decision"] == "CLARIFY"
    assert db.results.count_documents({}) == 0


def test_snapshot_history_requires_accepting_snapshot_alternative(sandbox, monkeypatch):
    client, _ = sandbox
    response = interpreted("Demand Forecast Accuracy", usage="one_off", granularity="month")
    response.spec.dimensions = ["month"]
    monkeypatch.setattr(specmod, "_call_gemini", lambda *args: response.model_copy(deep=True))
    a = post(client, "Show monthly forecast accuracy").json()
    assert a["decision"] == "CLARIFY"
    b = post(client, a["intake"]["alternatives"][0]["label"], a["session_id"]).json()
    assert b["decision"] == "ANSWER" and "month" not in b["spec"]["dimensions"]


def test_model_replacement_flag_cannot_erase_multi_metric_brief(sandbox, monkeypatch):
    client, _ = sandbox
    original = interpreted(requested_metrics=["Net Sales", "Forecast Variance"], usage="one_off", missing_information=["metric"])
    replacement = interpreted(usage="one_off")
    replacement.replacement_request = True
    responses = iter([original, replacement])
    monkeypatch.setattr(specmod, "_call_gemini", lambda *args: next(responses))
    a = post(client, "net sales and forecast variance").json()
    b = post(client, "monthly", a["session_id"]).json()
    assert b["decision"] == "CLARIFY" and len(b["brief"]["requested_metrics"]) == 2


def test_malformed_interpretation_preserves_pending(sandbox, monkeypatch):
    client, db = sandbox
    a = post(client, "/grill-me").json()
    before = db.conversations.find_one({"_id": a["session_id"]})["pending_request"]
    monkeypatch.setattr(specmod, "_call_gemini", lambda *args: {"outcome": "READY", "spec": {"metric": "SQL injection"}})
    response = post(client, "monthly", a["session_id"])
    assert response.status_code == 503
    assert db.conversations.find_one({"_id": a["session_id"]})["pending_request"] == before


@pytest.mark.parametrize("question", [
    "Create a global Nubeqa dashboard showing sales growth, forecast variance and market access by country.",
    "Please create a Power BI replacement for our legacy Tableau Xarelto commercial workbook.",
    "Please build a new report for market access coverage and reimbursement status by product.",
    "We need a monthly supply-risk dashboard by medicine and country.",
    "I need a new Kerendia management report for monthly performance in EMEA and North America.",
    "Can we have a new finance dashboard for net sales, gross-to-net and budget variance by product?",
    "I need a dashboard comparing product performance across oncology brands and markets.",
    "Can we build a launch dashboard for Lynkuet with market access, first sales and adoption indicators?",
    "Can you create a country-level Beyonttra report for launch readiness and reimbursement progress?",
    "We need one executive view combining net sales, forecast accuracy and inventory coverage for Bayer Pharma.",
])
def test_representative_ambiguous_requests_cannot_be_forced_ready(sandbox, monkeypatch, question):
    client, db = sandbox
    # A confidently incomplete model interpretation must not authorize computation.
    monkeypatch.setattr(specmod, "_call_gemini", lambda *args: interpreted())
    result = post(client, question).json()
    assert result["decision"] == "CLARIFY"
    assert len(result["intake"]["questions"]) <= 2
    assert db.results.count_documents({}) == db.chart_registry.count_documents({}) == 0


def test_unsupported_dimensions_and_status_filters_do_not_disappear(sandbox, monkeypatch):
    client, db = sandbox
    response = interpreted(usage="one_off")
    response.spec.dimensions = ["month", "market", "product"]
    response.spec.filters.statuses = ["STOCKOUT_RISK"]
    monkeypatch.setattr(specmod, "_call_gemini", lambda *args: response)
    result = post(client, "Show net sales").json()
    assert result["decision"] == "CLARIFY" and db.results.count_documents({}) == 0


def test_bare_grill_upgrade_keeps_pending_draft_and_scope(sandbox, monkeypatch):
    client, db = sandbox
    response = interpreted(requested_metrics=["Net Sales", "Forecast Variance"], product_ids=["P-NUB"], usage="one_off")
    monkeypatch.setattr(specmod, "_call_gemini", lambda *args: response)
    first = post(client, "Nubeqa net sales and forecast variance by country").json()
    before = db.conversations.find_one({"_id": first["session_id"]})["pending_request"]
    second = post(client, "/grill-me", first["session_id"]).json()
    after = db.conversations.find_one({"_id": first["session_id"]})["pending_request"]
    assert second["decision"] == "CLARIFY" and after["brief"]["mode"] == "grill"
    assert after["draft_spec"] == before["draft_spec"]
    assert after["original_request"] == before["original_request"]
    assert after["alternatives"] == before["alternatives"]
