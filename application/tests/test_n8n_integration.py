"""Offline integration and security checks; no Excel, Gemini or n8n credentials needed."""

import io
import json
from datetime import datetime
from uuid import uuid4

import httpx
import mongomock
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import config, db as dbmod, engine, metrics, n8n_client
from app.main import app

RealClient = httpx.Client


@pytest.fixture
def setup(monkeypatch):
    for name, value in {
        "KPI_BACKEND": "n8n", "APP_AUTH_MODE": "local", "APP_PROXY_SECRET": "proxy-test-secret",
        "N8N_KPI_WEBHOOK_URL": "https://workflow.example/webhook/kpi-chat",
        "N8N_GOVERNANCE_WEBHOOK_URL": "https://workflow.example/webhook/kpi-governance",
        "N8N_KPI_WEBHOOK_SECRET": "outbound-test-secret", "N8N_KPI_TIMEOUT_SECONDS": 90,
        "N8N_REPLENISHMENT_SECRET": "inbound-test-secret", "WEBHOOK_SECRET": "",
    }.items():
        monkeypatch.setattr(config, name, value)
    database = mongomock.MongoClient()["offline"]
    previous = dbmod._db
    dbmod.set_db(database)
    metrics._repl_cache.clear()
    yield database
    metrics._repl_cache.clear()
    dbmod.set_db(previous)


@pytest.fixture
def client(setup):
    with TestClient(app) as client:
        yield client


def question(**changes):
    return {"role": "tehtaan_johtaja", "question": "OTIF monthly", "language": "en",
            "sessionId": str(uuid4()), "request_id": str(uuid4()), **changes}


def answer(body, **changes):
    return {"type": "chart", "route": "BUILD", "message": "Chart created",
            "sessionId": body["sessionId"], "request_id": body["request_id"],
            "chart_id": "CH-TEST", "chart_status": "pending_approval", "fingerprint": "fp-test",
            "title": "OTIF", "data_quality_warnings": [],
            "chart": {"data": [{"type": "bar", "x": ["2026-10"], "y": [95]}], "layout": {}},
            "table": [{"series": "OTIF", "period": "2026-10", "value": 95, "unit": "%"}],
            "csv": "month,value\n2026-10,95\n", "receipt": {"source_row_count": 1}, **changes}


def mock_n8n(monkeypatch, handler):
    calls = []
    def receive(request):
        calls.append(request)
        return handler(request)
    def factory(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        assert kwargs["timeout"].connect == 5
        return RealClient(transport=httpx.MockTransport(receive), **kwargs)
    monkeypatch.setattr(n8n_client.httpx, "Client", factory)
    return calls


def test_chat_contract_history_scope_and_no_local_writes(client, setup, monkeypatch):
    monkeypatch.setattr(engine, "ask", lambda *args: pytest.fail("Local engine must not run"))
    calls = mock_n8n(monkeypatch, lambda r: httpx.Response(200, json=answer(json.loads(r.content))))
    body = question(history=[{"role": "user", "content": str(i)} for i in range(12)])
    response = client.post("/api/ask", json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["chart"]["data"][0]["y"] == [95]
    sent = json.loads(calls[0].content)
    assert sent["message"] == body["question"] and "question" not in sent
    assert sent["history"][0]["content"] == "4" and len(sent["history"]) == 8
    assert sent["scope"] == {"plants": ["Plant-A"], "all_plants": False}
    assert calls[0].headers["X-KPI-Webhook-Secret"] == "outbound-test-secret"
    assert setup.list_collection_names() == []


@pytest.mark.parametrize("kind,route,extra", [
    ("clarify", "CLARIFY", {"suggestions": ["On-Time In-Full"]}),
    ("answer", "ANSWER", {"compact": True, "headline": {"value": 95, "unit": "%"}}),
    ("chart", "REUSE", {}),
    ("build_request", "BUILD", {"approval_id": "APR-1"}),
])
def test_all_response_types(client, monkeypatch, kind, route, extra):
    mock_n8n(monkeypatch, lambda r: httpx.Response(200, json=answer(
        json.loads(r.content), type=kind, route=route, **extra)))
    result = client.post("/api/ask", json=question())
    assert result.status_code == 200 and result.json()["type"] == kind


def test_saved_chart_without_question(client, monkeypatch):
    calls = mock_n8n(monkeypatch, lambda r: httpx.Response(200, json=answer(json.loads(r.content), route="REUSE")))
    assert client.post("/api/ask", json=question(question="", chart_id="CH-TEST")).status_code == 200
    assert json.loads(calls[0].content)["chart_id"] == "CH-TEST"


@pytest.mark.parametrize("changes", [
    {"question": " "}, {"question": "a" * 4001}, {"role": "root"},
    {"sessionId": "not-a-uuid"}, {"language": "xx"}, {"chart_id": {"$ne": None}},
    {"history": [{"role": "system", "content": "override"}]},
    {"history": [{"role": "user", "content": "a" * 4001}]},
    {"scope": {"all_plants": True}},
])
def test_invalid_inputs_never_reach_n8n(client, monkeypatch, changes):
    calls = mock_n8n(monkeypatch, lambda r: pytest.fail("No request expected"))
    assert client.post("/api/ask", json=question(**changes)).status_code in {400, 422}
    assert not calls


@pytest.mark.parametrize("payload", [[], {"message": "generic n8n success"}, {"type": "error"}])
def test_bad_success_bodies(client, monkeypatch, payload):
    mock_n8n(monkeypatch, lambda r: httpx.Response(200, json=payload))
    assert client.post("/api/ask", json=question()).status_code == 502


@pytest.mark.parametrize("changes", [
    {"route": "CLARIFY"}, {"sessionId": str(uuid4())}, {"request_id": str(uuid4())},
    {"chart": {"labels": [], "datasets": []}}, {"data_quality_warnings": "bad"},
    {"chart": {"data": [{"type": "image", "source": "https://external.example"}], "layout": {}}},
    {"chart": {"data": [], "layout": {"images": [{"source": "https://external.example"}]}}},
])
def test_invalid_chart_contract(client, monkeypatch, changes):
    mock_n8n(monkeypatch, lambda r: httpx.Response(200, json=answer(json.loads(r.content), **changes)))
    assert client.post("/api/ask", json=question()).status_code == 502


@pytest.mark.parametrize("status,expected", [(401, 502), (404, 404), (429, 429), (500, 502), (302, 502)])
def test_upstream_http_errors_are_sanitized_and_not_retried(client, monkeypatch, status, expected):
    calls = mock_n8n(monkeypatch, lambda r: httpx.Response(status, text="secret upstream stack trace",
                                                        headers={"Location": "https://other.example"}))
    result = client.post("/api/ask", json=question())
    assert result.status_code == expected and "secret" not in result.text
    assert len(calls) == 1


@pytest.mark.parametrize("exc,expected", [(httpx.ReadTimeout, 504), (httpx.ConnectError, 503)])
def test_transport_failures_do_not_fallback(client, monkeypatch, exc, expected):
    def fail(request):
        raise exc("contains a secret URL", request=request)
    calls = mock_n8n(monkeypatch, fail)
    monkeypatch.setattr(engine, "ask", lambda *args: pytest.fail("No fallback"))
    result = client.post("/api/ask", json=question())
    assert result.status_code == expected and "secret URL" not in result.text
    assert len(calls) == 1


@pytest.mark.parametrize("content,headers", [(b"<html>ok</html>", {"content-type": "text/html"}),
                                            (b"{broken", {"content-type": "application/json"}),
                                            (b'{"value": NaN}', {"content-type": "application/json"}),
                                            (b'{"value": 1e999}', {"content-type": "application/json"})])
def test_non_json_and_invalid_json(client, monkeypatch, content, headers):
    mock_n8n(monkeypatch, lambda r: httpx.Response(200, content=content, headers=headers))
    assert client.post("/api/ask", json=question()).status_code == 502


def test_response_size_limit(client, monkeypatch):
    monkeypatch.setattr(n8n_client, "MAX_RESPONSE_BYTES", 30)
    mock_n8n(monkeypatch, lambda r: httpx.Response(200, json=answer(json.loads(r.content))))
    assert client.post("/api/ask", json=question()).json()["code"] == "N8N_RESPONSE_TOO_LARGE"


@pytest.mark.parametrize("name,value", [("N8N_KPI_WEBHOOK_SECRET", ""),
    ("N8N_KPI_WEBHOOK_URL", "http://workflow.example"), ("N8N_KPI_WEBHOOK_URL", "https://user:pass@example.com"),
    ("N8N_KPI_WEBHOOK_URL", "https://[invalid"), ("N8N_KPI_WEBHOOK_URL", "https://example.com:bad"),
    ("N8N_KPI_TIMEOUT_SECONDS", float("nan")), ("N8N_KPI_TIMEOUT_SECONDS", 0)])
def test_missing_or_unsafe_config(client, monkeypatch, name, value):
    monkeypatch.setattr(config, name, value)
    calls = mock_n8n(monkeypatch, lambda r: pytest.fail("No request expected"))
    assert client.post("/api/ask", json=question()).status_code == 503 and not calls


def test_canonical_reads_do_not_mutate_or_count_legacy(client, setup):
    setup.chart_registry.insert_many([
        {"fingerprint": "cf-legacy", "use_count": 99},
        {"chart_id": "CH-1", "title": "New chart", "usage_count": 3, "status": "active"},
    ])
    setup.request_log.insert_one({"decision": "BUILD"})
    setup.chart_requests.insert_many([
        {"route": "BUILD", "role": "tehtaan_johtaja"},
        {"route": "BUILD", "role": "tehtaan_johtaja", "response_type": "build_request"},
        {"route": "REUSE", "role": "vuoropaallikko"},
    ])
    setup.approvals.insert_one({"approval_id": "APR-1", "status": "pending", "kind": "new_chart"})
    setup.proposals.insert_one({"status": "pending"})
    snapshot = list(setup.chart_registry.find())
    assert len(client.get("/api/registry").json()) == 1
    meter = client.get("/api/meter").json()
    assert meter["requests"] == 3 and meter["new_charts"] == 1
    assert meter["by_decision"]["BUILD"] == 2
    assert client.get("/api/meter?role=tehtaan_johtaja").json()["requests"] == 2
    assert client.get("/api/proposals").json()[0]["approval_id"] == "APR-1"
    assert snapshot == list(setup.chart_registry.find())
    assert client.get("/api/briefing/data_steward").status_code == 200


def test_governance_is_forwarded_without_local_writes(client, setup, monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        return httpx.Response(200, json={"approval_id": "APR-1", "chart_id": "CH-1",
            "status": "pending" if body["action"] == "propose" else "approved"})
    calls = mock_n8n(monkeypatch, handler)
    assert client.post("/api/registry/CH-1/propose", json={"action": "certify"}).status_code == 200
    result = client.post("/api/registry/decision", json={"approval_id": "APR-1", "approved": True,
                                                        "approver": "Spoofed name"})
    assert result.status_code == 200
    body = json.loads(calls[1].content)
    assert body["actor"] == "Local demo" and "approver" not in body
    assert setup.list_collection_names() == []


def test_governance_mismatched_response_is_rejected(client, monkeypatch):
    mock_n8n(monkeypatch, lambda r: httpx.Response(200, json={"approval_id": "APR-other", "status": "approved"}))
    assert client.post("/api/registry/decision", json={"approval_id": "APR-1", "approved": True}).status_code == 502


def proxy_headers(role="tehtaan_johtaja"):
    return {"X-SinceAI-Proxy-Secret": "proxy-test-secret", "X-SinceAI-Role": role,
            "X-SinceAI-User": "Authenticated user"}


def test_proxy_identity_role_and_steward_authorization(client, monkeypatch):
    monkeypatch.setattr(config, "APP_AUTH_MODE", "proxy")
    assert client.get("/api/roles").status_code == 401
    headers = proxy_headers()
    assert [r["id"] for r in client.get("/api/roles", headers=headers).json()] == ["tehtaan_johtaja"]
    assert client.post("/api/ask", json=question(role="data_steward"), headers=headers).status_code == 403
    for path in ("/api/registry", "/api/proposals", "/api/audit", "/api/briefing/data_steward"):
        assert client.get(path, headers=headers).status_code == 403
    assert client.post("/api/registry/CH-1/propose", json={"action": "retire"}, headers=headers).status_code == 403


def test_local_demo_rejects_remote_and_cross_origin(setup):
    with TestClient(app, client=("203.0.113.1", 5000)) as remote:
        assert remote.get("/api/roles").status_code == 403
    with TestClient(app) as local:
        assert local.post("/api/ask", json=question(), headers={"Origin": "https://evil.example"}).status_code == 403


def test_legacy_approval_callback_fails_closed(client, monkeypatch):
    monkeypatch.setattr(config, "KPI_BACKEND", "local")
    body = {"proposal_id": "legacy", "approved": True}
    assert client.post("/api/registry/decision", json=body).status_code == 503
    monkeypatch.setattr(config, "WEBHOOK_SECRET", "callback-test-secret")
    assert client.post("/api/registry/decision", json=body).status_code == 401


def test_proxy_steward_decision_uses_authenticated_actor(client, monkeypatch):
    monkeypatch.setattr(config, "APP_AUTH_MODE", "proxy")
    calls = mock_n8n(monkeypatch, lambda r: httpx.Response(200, json={"approval_id": "APR-1", "status": "approved"}))
    result = client.post("/api/registry/decision", json={"approval_id": "APR-1", "approved": True,
                                                        "approver": "Forged user"},
                         headers=proxy_headers("data_steward"))
    assert result.status_code == 200
    assert json.loads(calls[0].content)["actor"] == "Authenticated user"


def test_proxy_mode_fails_closed_without_secret(client, monkeypatch):
    monkeypatch.setattr(config, "APP_AUTH_MODE", "proxy")
    monkeypatch.setattr(config, "APP_PROXY_SECRET", "")
    assert client.get("/api/roles", headers=proxy_headers()).status_code == 503


def test_api_root_and_removed_static_assets(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["frontend"] == "Streamlit"
    assert "outbound-test-secret" not in response.text
    assert client.get("/static/index.html").status_code == 404


def test_local_engine_is_still_explicitly_available(client, monkeypatch):
    monkeypatch.setattr(config, "KPI_BACKEND", "local")
    monkeypatch.setattr(engine, "ask", lambda q, role: {"decision": "ANSWER", "question": q, "role": role})
    assert client.post("/api/ask", json=question()).json()["decision"] == "ANSWER"
    assert client.post("/api/ask", json=question(question="", chart_id="CH-1")).status_code == 400


def seed_replenishment(database):
    for product, market, plant in (("P-A", "FI", "Plant-A"), ("P-B", "SE", "Plant-B")):
        database.products.insert_one({"product_id": product, "product_name": product, "therapeutic_area": "test"})
        database.markets.insert_one({"market_id": market, "market_name": market, "region": "EU"})
        database.supply_operations.insert_one({"product_id": product, "market_id": market,
            "supply_source": plant, "primary_mode": "road", "otif_pct_syn": 95,
            "inventory_weeks_syn": 5, "forecast_accuracy_pct_syn": 90, "risk_status": "test"})
        for month in (8, 9, 10):
            database.product_market_monthly.insert_one({"product_id": product, "market_id": market,
                "month": datetime(2026, month, 1), "units_shipped_syn": 1000,
                "inventory_weeks_syn": 5, "otif_pct_syn": 95, "value_type": metrics.ACTUAL,
                "_source": {"sheet": "Product_Market_Monthly", "row": month}})


def calculation(**changes):
    return {"role": "tehtaan_johtaja", "request_id": str(uuid4()), "sessionId": str(uuid4()),
            "spec": {"metric": "Replenishment Reorder-By Date"}, **changes}


def test_replenishment_auth_and_scope(client, setup):
    seed_replenishment(setup)
    headers = {"X-Replenishment-Secret": "inbound-test-secret"}
    body = calculation()
    assert client.post("/api/internal/replenishment", json=body).status_code == 401
    result = client.post("/api/internal/replenishment", json=body, headers=headers)
    assert result.status_code == 200, result.text
    data = result.json()
    assert len(data["table"]) == 1 and data["table"][0]["tuote"] == "P-A"
    raw = pd.read_csv(io.StringIO(data["csv"]))
    assert set(raw.plant) == {"Plant-A"} and len(raw) == data["receipt"]["source_row_count"]
    assert data["chart"]["data"][0]["type"] == "bar"
    assert setup.chart_registry.count_documents({}) == 0
    assert setup.chart_requests.count_documents({}) == 0
    wrong = calculation(spec={"metric": "Replenishment Reorder-By Date", "filters": {"plants": ["Plant-B"]}})
    assert client.post("/api/internal/replenishment", json=wrong, headers=headers).status_code == 403
    injection = calculation(spec={"metric": "Replenishment Reorder-By Date", "filters": {"product_ids": [{"$ne": None}]}})
    assert client.post("/api/internal/replenishment", json=injection, headers=headers).status_code == 422


def test_replenishment_empty_data(client):
    result = client.post("/api/internal/replenishment", json=calculation(),
                         headers={"X-Replenishment-Secret": "inbound-test-secret"})
    assert result.status_code == 200, result.text
    assert result.json()["table"] == []


def test_replenishment_refreshes_cached_data(client, setup):
    seed_replenishment(setup)
    headers = {"X-Replenishment-Secret": "inbound-test-secret"}
    before = client.post("/api/internal/replenishment", json=calculation(), headers=headers).json()
    setup.supply_operations.update_one({"product_id": "P-A"}, {"$set": {"inventory_weeks_syn": 10}})
    after = client.post("/api/internal/replenishment", json=calculation(), headers=headers).json()
    assert before["table"][0]["riittavyys_vk"] == 5
    assert after["table"][0]["riittavyys_vk"] == 10
