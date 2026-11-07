"""Router contract, state isolation and real briefing/API integration; no live calls."""

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import mongomock
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend import config, db as dbmod, engine, router, routing
from backend.main import app
from backend.spec import InterpretationUnavailable
from tools import seed_mongo


def classification(intent):
    from backend.intake import IntakeQuestion, ModelClarification, ClarificationSuggestion
    clarification = None
    if intent in ("mixed", "ambiguous"):
        clarification = ModelClarification(question=IntakeQuestion(id="route", field="routing", text="Which task first?"),
            suggestions=[ClarificationSuggestion(question_id="route", label="Open briefing", answer="Open the briefing first"),
                         ClarificationSuggestion(question_id="route", label="Analytics", answer="Continue analytics")])
    return router.Classification(intent=intent, action="open_briefing" if intent == "ui_action" else None,
                                 needs_clarification=intent in ("mixed", "ambiguous"),
                                 ambiguity_reason="Several possibilities" if intent in ("mixed", "ambiguous") else None,
                                 clarification=clarification)


@pytest.fixture
def isolated(monkeypatch):
    previous = dbmod._db
    db = mongomock.MongoClient()["router_test"]
    dbmod.set_db(db)
    monkeypatch.setattr(engine, "ask", lambda *args: pytest.fail("unexpected analytics execution"))
    with TestClient(app) as client:
        yield client, db
    dbmod.set_db(previous)


def post(client, message, session="existing", language="en"):
    return client.post("/api/ask", json={"question": message, "role": "tehtaan_johtaja",
                                       "session_id": session, "language": language})


def seed_pending(db):
    pending = {"original_request": "Compare sales in Finland, actuals only", "brief": {"scope": "explicit"},
               "latest_questions": [{"id": "usage", "text": "One-off or recurring?"}]}
    db.conversations.insert_one({"_id": "existing", "pending_request": pending,
                                 "turns": [{"q": "sales", "answer": "One-off or recurring?"}]})
    return pending


@pytest.mark.parametrize("changes", [
    {"action": "delete_database"}, {"intent": "ui_action", "action": None},
    {"intent": "mixed", "needs_clarification": False}, {"needs_clarification": "false"},
    {"extra": "injected"}, {"intent": "conversation", "action": "open_briefing"},
])
def test_invalid_contract_rejected(changes):
    value = classification("analytics_request").model_dump() | changes
    with pytest.raises(ValidationError):
        router.Classification.model_validate(value)


def test_needs_clarification_requires_a_model_written_question_and_choices():
    with pytest.raises(ValidationError):
        router.Classification(intent="analytics_request", action=None, needs_clarification=True,
                              ambiguity_reason="Missing criterion")


@pytest.mark.parametrize("message", ["Avaa aamubriifingi", "Open teh briefing", "Öffne die Übersicht",
                                          "Don't open the briefing", "vain toteumat", "why?"])
def test_classifier_forwards_multilingual_message_and_context(monkeypatch, message):
    calls = []
    expected = classification("conversation")

    def generate(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text="```json\n" + expected.model_dump_json() + "\n```", parsed=None)

    monkeypatch.setattr("backend.vector_store._gemini",
                        lambda: SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    monkeypatch.setattr(config, "ROUTER_MODEL", "gemma-4-26b-a4b-it")
    result, elapsed = router.classify(message, [{"q": "Sales?", "answer": "Which market?"}],
                                     {"original_request": "Sales"}, [{"text": "Which market?"}])
    assert result == expected and elapsed >= 0
    context = json.loads(calls[0]["contents"])
    assert context["message"] == message
    assert context["pending_request"]["original_request"] == "Sales"
    assert context["latest_questions"] == [{"text": "Which market?"}]
    assert calls[0]["config"].thinking_config.thinking_level.value.lower() == "minimal"
    assert calls[0]["model"] == config.ROUTER_MODEL
    assert calls[0]["config"].response_schema is None


@pytest.mark.parametrize("failure", ["bad_json", "provider"])
def test_classifier_failure_leaves_all_state_untouched(isolated, monkeypatch, failure):
    client, db = isolated
    seed_pending(db)
    before = deepcopy(db.conversations.find_one({"_id": "existing"}))

    def generate(**kwargs):
        if failure == "provider":
            raise RuntimeError("private provider details")
        return SimpleNamespace(text='{"intent":"ui_action","action":"arbitrary"}', parsed=None)

    monkeypatch.setattr("backend.vector_store._gemini",
                        lambda: SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    monkeypatch.setattr(routing, "classify", router.classify)
    response = post(client, "open briefing")
    assert response.status_code == 503 and "private" not in response.text
    assert db.conversations.find_one({"_id": "existing"}) == before
    assert db.request_log.count_documents({}) == db.chart_registry.count_documents({}) == 0


@pytest.mark.parametrize("status", [408, 500, 502, 503, 504, None])
def test_transient_failure_recovers_with_one_retry(monkeypatch, status):
    from google.genai.errors import APIError
    from httpx import ConnectError

    calls, waits = [], []
    expected = classification("ui_action")

    def generate(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            if status is None:
                raise ConnectError("private connection detail")
            raise APIError(status, {"error": {"message": "private provider detail"}})
        return SimpleNamespace(parsed=None, text=expected.model_dump_json())

    monkeypatch.setattr("backend.vector_store._gemini",
                        lambda: SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    monkeypatch.setattr(router, "sleep", waits.append)
    result, elapsed = router.classify("Open briefing", [], None, [])
    assert result == expected and elapsed >= 0
    assert len(calls) == 2 and waits == [0.5]
    assert calls[0]["contents"] == calls[1]["contents"]
    for call in calls:
        assert call["config"].http_options.retry_options.attempts == 1
        assert call["config"].http_options.timeout == config.ROUTER_TIMEOUT_SECONDS * 1000


@pytest.mark.parametrize("timeout_seconds", [30, 60])
def test_real_sdk_uses_configured_deadline_without_nested_retries(monkeypatch, timeout_seconds):
    """Exercise the actual SDK transport: its HTTP timeout also sets the server deadline."""
    import httpx
    from google import genai
    from google.genai import types

    requests = []
    expected = classification("conversation")

    def handle(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(504, json={"error": {"code": 504, "message": "synthetic deadline"}})
        return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [
            {"text": expected.model_dump_json()}]}}]})

    client = genai.Client(api_key="offline-placeholder", http_options=types.HttpOptions(
        client_args={"transport": httpx.MockTransport(handle)}))
    monkeypatch.setattr("backend.vector_store._gemini", lambda: client)
    monkeypatch.setattr(config, "ROUTER_TIMEOUT_SECONDS", timeout_seconds)
    waits = []
    monkeypatch.setattr(router, "sleep", waits.append)
    try:
        result, _ = router.classify("Synthetic request", [], None, [])
        assert result == expected
        assert len(requests) == 2 and waits == [0.5]
        assert all(request.headers["X-Server-Timeout"] == str(timeout_seconds) for request in requests)
        assert all(request.extensions["timeout"]["read"] == timeout_seconds for request in requests)
    finally:
        client.close()


@pytest.mark.parametrize("status, expected_attempts", [(400, 1), (401, 1), (403, 1), (404, 1),
                                                      (429, 1), (503, 2)])
def test_retry_budget_and_state_safety(isolated, monkeypatch, caplog, status, expected_attempts):
    from google.genai.errors import APIError

    client, db = isolated
    seed_pending(db)
    before = deepcopy(db.conversations.find_one({"_id": "existing"}))
    calls = []

    def generate(**kwargs):
        calls.append(True)
        raise APIError(status, {"error": {"message": "private prompt and key"}})

    monkeypatch.setattr("backend.vector_store._gemini",
                        lambda: SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    monkeypatch.setattr(router, "sleep", lambda seconds: None)
    monkeypatch.setattr(routing, "classify", router.classify)
    response = post(client, "Open briefing")
    assert response.status_code == 503 and len(calls) == expected_attempts
    assert db.conversations.find_one({"_id": "existing"}) == before
    assert db.request_log.count_documents({}) == db.chart_registry.count_documents({}) == 0
    assert "private prompt" not in caplog.text + response.text


def test_invalid_classifier_output_is_never_retried(monkeypatch):
    calls = []

    def generate(**kwargs):
        calls.append(True)
        return SimpleNamespace(parsed=None, text='{"intent":"ui_action","action":"delete"}')

    monkeypatch.setattr("backend.vector_store._gemini",
                        lambda: SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    monkeypatch.setattr(router, "sleep", lambda seconds: pytest.fail("validation must not retry"))
    with pytest.raises(InterpretationUnavailable):
        router.classify("Open briefing", [], None, [])
    assert len(calls) == 1


def test_rejected_suggestions_report_safe_reason_and_preserve_state(isolated, monkeypatch, caplog):
    client, db = isolated
    seed_pending(db)
    before = deepcopy(db.conversations.find_one({"_id": "existing"}))
    payload = classification("ambiguous").model_dump()
    payload["clarification"]["question"]["field"] = "scope"
    payload["clarification"]["question"]["text"] = "Which markets?"
    for item in payload["clarification"]["suggestions"]:
        item["label"] = "PRIVATE_LABEL"
        item["changes"] = {"market_ids": ["PRIVATE_INVALID_ID"]}
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(parsed=None, text=json.dumps(payload))

    monkeypatch.setattr("backend.vector_store._gemini",
                        lambda: SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    monkeypatch.setattr(routing, "classify", router.classify)
    response = post(client, "Saksa ja Ranska")
    assert response.status_code == 503 and len(calls) == 1
    assert "reason=insufficient_safe_answers" in caplog.text
    assert '"unsupported_identifier": 2' in caplog.text
    assert "PRIVATE_" not in caplog.text + response.text
    assert db.conversations.find_one({"_id": "existing"}) == before
    assert db.request_log.count_documents({}) == 0


def test_schema_failure_logs_type_without_untrusted_values(isolated, monkeypatch, caplog):
    client, _ = isolated
    payload = classification("conversation").model_dump() | {"PRIVATE_EXTRA_KEY": "PRIVATE_VALUE"}
    monkeypatch.setattr("backend.vector_store._gemini", lambda: SimpleNamespace(models=SimpleNamespace(
        generate_content=lambda **kwargs: SimpleNamespace(parsed=None, text=json.dumps(payload)))))
    monkeypatch.setattr(routing, "classify", router.classify)
    assert post(client, "Saksa ja Ranska").status_code == 503
    assert "stage=json_schema" in caplog.text and "extra_forbidden" in caplog.text
    assert "PRIVATE_" not in caplog.text


def test_country_followup_keeps_original_request_and_validated_context(isolated, monkeypatch):
    client, db = isolated
    original = "N\u00e4yt\u00e4 nettomyynti"
    question = "Milt\u00e4 markkinoilta haluat n\u00e4hd\u00e4 nettomyynnin?"
    db.conversations.insert_one({"_id": "existing", "turns": [{"q": original, "answer": question}],
                                "routing_pending": {"messages": [original], "question": question}})
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(parsed=None, text=classification("clarification_reply").model_dump_json())

    monkeypatch.setattr("backend.vector_store._gemini",
                        lambda: SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    monkeypatch.setattr(routing, "classify", router.classify)
    analytics = []
    monkeypatch.setattr(engine, "ask", lambda *args: analytics.append(args) or {"decision": "CLARIFY"})
    assert post(client, "Saksa ja Ranska", language="fi").status_code == 200
    assert analytics[0][0] == "Saksa ja Ranska" and analytics[0][5] == [original]
    context = json.loads(calls[0]["contents"])
    assert context["unresolved_routing"]["messages"] == [original]
    assert context["latest_questions"] == [{"text": question}]
    assert "JSON Schema:" in calls[0]["config"].system_instruction


def test_followup_cannot_replace_original_metric_during_clarification(isolated, monkeypatch):
    from test_suggestions import metric_clarification
    client, db = isolated
    pending = seed_pending(db)
    before = deepcopy(db.conversations.find_one({"_id": "existing"}))
    proposed = router.Classification(intent="clarification_reply", action=None, needs_clarification=True,
                                    ambiguity_reason="criterion", clarification=metric_clarification())
    monkeypatch.setattr(routing, "classify", lambda *args: (proposed, 1.0))
    assert post(client, "Saksa ja Ranska").status_code == 503
    assert db.conversations.find_one({"_id": "existing"}) == before


@pytest.mark.parametrize("intent", ["mixed", "ambiguous"])
def test_unresolved_routes_preserve_complete_request_and_existing_pending(isolated, monkeypatch, intent):
    client, db = isolated
    pending = seed_pending(db)
    monkeypatch.setattr(routing, "classify", lambda *args: (classification(intent), 1.2))
    response = post(client, "Open briefing and calculate sales for FI only").json()
    saved = db.conversations.find_one({"_id": "existing"})
    assert saved["pending_request"] == pending
    assert saved["routing_pending"]["messages"] == ["Open briefing and calculate sales for FI only"]
    assert response["intake"]["pending"] is True
    assert "scope" not in response["answer"] and "intent" not in response["answer"]
    assert db.request_log.count_documents({}) == 0


@pytest.mark.parametrize("intent", ["analytics_request", "clarification_reply"])
def test_analytics_dispatch_preserves_original_pending_and_unresolved_text(isolated, monkeypatch, intent):
    client, db = isolated
    pending = seed_pending(db)
    db.conversations.update_one({"_id": "existing"}, {"$set": {"routing_pending": {
        "messages": ["Open briefing and calculate sales for FI only"], "question": "Which first?"}}})
    calls = []

    def analytics(*args):
        calls.append(args)
        assert db.conversations.find_one({"_id": "existing"})["pending_request"] == pending
        return {"decision": "CLARIFY"}

    monkeypatch.setattr(engine, "ask", analytics)
    monkeypatch.setattr(routing, "classify", lambda *args: (classification(intent), 2.0))
    assert post(client, "The analytics first, actuals only").status_code == 200
    assert calls[0][0] == "The analytics first, actuals only"
    assert calls[0][5] == ["Open briefing and calculate sales for FI only"]
    assert calls[0][2] == "existing"


@pytest.mark.parametrize("language", ["en", "fi"])
def test_real_briefing_fetched_for_current_role_without_analytics(isolated, monkeypatch, language):
    client, db = isolated
    workbook = next((Path(__file__).resolve().parents[3] / "data/bayer").glob("*.xlsx"))
    for collection, rows in seed_mongo.load_sheets(workbook).items():
        if rows:
            db[collection].insert_many(deepcopy(rows))
    pending = seed_pending(db)
    monkeypatch.setattr(routing, "classify", lambda *args: (classification("ui_action"), 3.0))
    expected = client.get(f"/api/briefing/tehtaan_johtaja?language={language}").json()
    response = post(client, "open briefing", language=language)
    assert response.status_code == 200
    assert response.json()["action"] == {"name": "open_briefing", "briefing": expected}
    assert expected["cards"]
    assert db.conversations.find_one({"_id": "existing"})["pending_request"] == pending
    assert db.request_log.count_documents({}) == db.results.count_documents({}) == 0
    assert db.chart_registry.count_documents({}) == 0


@pytest.mark.parametrize("intent", ["conversation", "explain_previous"])
def test_chat_and_explanation_use_context_without_erasing_pending(isolated, monkeypatch, intent):
    client, db = isolated
    pending = seed_pending(db)
    monkeypatch.setattr(routing, "classify", lambda *args: (classification(intent), 1.0))
    response = post(client, "explain that").json()
    assert response["decision"] == "CHAT" and "One-off or recurring?" in response["answer"]
    assert db.conversations.find_one({"_id": "existing"})["pending_request"] == pending
    assert db.request_log.count_documents({}) == 0
