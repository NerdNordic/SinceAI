"""Generative questions/answers and isolated, supported effects; all tests offline."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend import engine, intake, suggestions
from backend.spec import ChartSpec, Filters, Interpretation
from test_intake import sandbox, source, post

VALUES = {"products": {"P-NUB": "Nubeqa"}, "markets": {"FI": "Finland", "DE": "Germany"},
          "plants": ["Plant-A", "Plant-B"]}
QUESTION = {"id": "markets", "field": "scope", "text": "Which markets would you like to include?"}


@pytest.fixture
def domain(monkeypatch):
    monkeypatch.setattr(suggestions, "lookups", lambda: deepcopy(VALUES))


def clarification(question=None, language="en"):
    q = question or QUESTION
    fi = language == "fi"
    return intake.ModelClarification(question=intake.IntakeQuestion(**q), suggestions=[
        intake.ClarificationSuggestion(question_id=q["id"], label="Kaikki markkinat mukaan" if fi else "Include every market",
            answer="Näytä kaikki markkinat." if fi else "Please include all markets.",
            changes=intake.SuggestionChanges(market_ids=[])),
        intake.ClarificationSuggestion(question_id=q["id"], label="Rajaa Suomeen" if fi else "Focus on Finland",
            answer="Tarkastellaan vain Suomea." if fi else "Focus on Finland only.",
            changes=intake.SuggestionChanges(market_ids=["FI"]))])


def pending(generated=None):
    generated = generated or clarification()
    brief = intake.RequestBrief(original_request="Sales for Nubeqa at Plant-B, actuals only",
        product_ids=["P-NUB"], plants=["Plant-B"], market_ids=["FI"], scope="explicit",
        period="all_available", actual_forecast="actual_only", usage="one_off", requested_metrics=["Net Sales"])
    spec = ChartSpec(metric="Net Sales", dimensions=["product"], intent="one_off", understood=False,
        filters=Filters(product_ids=brief.product_ids, market_ids=brief.market_ids, plants=brief.plants))
    return intake.PendingRequest(original_request=brief.original_request, brief=brief,
        latest_questions=[generated.question], unresolved_questions=[generated.question],
        draft_spec=spec.model_dump(), suggestions=generated.suggestions, suggestion_language="en")


def fake_model(monkeypatch, payload):
    calls = []
    def generate(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(parsed=None, text=json.dumps(payload, ensure_ascii=False))
    monkeypatch.setattr("backend.vector_store._gemini",
                        lambda: SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    return calls


@pytest.mark.parametrize("language", ["en", "fi"])
def test_model_writes_question_and_labels_in_context(domain, monkeypatch, language):
    question = QUESTION | {"text": "Mitkä markkinat otetaan mukaan?" if language == "fi" else QUESTION["text"]}
    proposed = clarification(question, language)
    calls = fake_model(monkeypatch, proposed.model_dump())
    result = suggestions.generate([question], "Nubeqa at Plant-B", {"plants": ["Plant-B"]}, {"pending": True}, language)
    assert result == proposed
    context = json.loads(calls[0]["contents"])
    assert context["requirements"] == [question] and context["response_language"] == language
    assert context["brief"]["plants"] == ["Plant-B"]
    assert context["supported_values"]["markets"] == VALUES["markets"]
    assert "allowed_answers" not in context
    assert result.suggestions[0].label != result.suggestions[0].answer
    assert "changes" not in result.suggestions[0].public()


@pytest.mark.parametrize("mutation", ["question", "question_id", "unknown_id", "unrelated_scope", "unknown_metric", "internal_name"])
def test_untrusted_generated_answers_fail_closed(domain, monkeypatch, mutation):
    payload = clarification().model_dump()
    choice = payload["suggestions"][0]
    if mutation == "question": payload["question"]["id"] = "stale"
    if mutation == "question_id": choice["question_id"] = "other"
    if mutation == "unknown_id": choice["changes"]["market_ids"] = ["MARS"]
    if mutation == "unrelated_scope": choice["changes"]["plants"] = []
    if mutation == "unknown_metric": choice["changes"]["selected_metric"] = "Invented metric"
    if mutation == "internal_name": choice["label"] = "Set market_ids"
    fake_model(monkeypatch, payload)
    assert suggestions.generate([QUESTION], "Nubeqa Plant-B", {}, {}, "en") is None


@pytest.mark.parametrize("count", [0, 1, 4])
def test_question_requires_two_or_three_answers(domain, monkeypatch, count):
    payload = clarification().model_dump()
    payload["suggestions"] = (payload["suggestions"] * 2)[:count]
    fake_model(monkeypatch, payload)
    assert suggestions.generate([QUESTION], "request", {}, {}, "en") is None


def test_provider_failure_does_not_modify_pending(domain, monkeypatch):
    state = pending()
    before = state.model_dump()
    def fail(**kwargs): raise RuntimeError("private provider detail")
    monkeypatch.setattr("backend.vector_store._gemini",
                        lambda: SimpleNamespace(models=SimpleNamespace(generate_content=fail)))
    assert suggestions.generate([QUESTION], state.original_request, state.brief.model_dump(), before, "en") is None
    assert state.model_dump() == before


def test_generated_all_markets_answer_preserves_other_scope_and_constraints(domain):
    state = pending()
    before = state.model_dump()
    spec, brief = suggestions.resolve(state, state.suggestions[0].answer, "tehtaan_johtaja")
    assert brief.market_ids == spec.filters.market_ids == []
    assert brief.plants == ["Plant-B"] and brief.product_ids == ["P-NUB"]
    assert brief.actual_forecast == "actual_only" and brief.period == "all_available"
    assert brief.original_request == state.original_request
    assert state.model_dump() == before


def test_stale_question_cannot_apply_a_previous_choice(domain):
    state = pending()
    state.latest_questions = []
    assert suggestions.resolve(state, state.suggestions[0].answer, "tehtaan_johtaja") is None


def test_explicit_metric_request_cannot_be_replaced_by_generated_different_metric(domain):
    q = intake.IntakeQuestion(id="metric", field="metric", text="Which measure?")
    choices = [intake.ClarificationSuggestion(question_id=q.id, label=name, answer=name,
        changes=intake.SuggestionChanges(selected_metric=name)) for name in ("Inventory Coverage", "Units Shipped")]
    with pytest.raises(ValueError):
        suggestions.validate(intake.ModelClarification(question=q, suggestions=choices), [], "Net Sales only", {})


@pytest.mark.parametrize("timeout", [1, 8, 10, 30, 120])
def test_actual_sdk_deadline_is_accepted_by_provider(domain, monkeypatch, timeout):
    import httpx
    from google import genai
    from google.genai import types
    requests = []
    def handle(request):
        requests.append(request)
        if int(request.headers["X-Server-Timeout"]) < 10:
            return httpx.Response(400, json={"error": {"code": 400, "message": "deadline too short"}})
        return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [
            {"text": clarification().model_dump_json()}]}}]})
    client = genai.Client(api_key="offline-placeholder", http_options=types.HttpOptions(
        client_args={"transport": httpx.MockTransport(handle)}))
    monkeypatch.setattr("backend.vector_store._gemini", lambda: client)
    monkeypatch.setattr(suggestions.config, "ROUTER_TIMEOUT_SECONDS", timeout)
    try:
        assert suggestions.generate([QUESTION], "Nubeqa Plant-B", {}, {}, "en") is not None
        assert len(requests) == 1 and 10 <= int(requests[0].headers["X-Server-Timeout"]) <= 20
    finally:
        client.close()


def metric_clarification():
    q = intake.IntakeQuestion(id="metric", field="metric", text="Millä perusteella haluat priorisoida tuotteet?")
    return intake.ModelClarification(question=q, suggestions=[
        intake.ClarificationSuggestion(question_id=q.id, label="Vähäinen varasto ensin", answer="Varaston riittävyyden perusteella.",
            changes=intake.SuggestionChanges(selected_metric="Inventory Coverage")),
        intake.ClarificationSuggestion(question_id=q.id, label="Kiireellisimmät tilaukset ensin", answer="Täydennystarpeen perusteella.",
            changes=intake.SuggestionChanges(selected_metric="Replenishment Reorder-By Date"))])


def test_prioritization_prompt_then_metric_choice_does_not_repeat_definition(sandbox, monkeypatch):
    client, db = sandbox
    generated = metric_clarification()
    calls = fake_model(monkeypatch, generated.model_dump())
    monkeypatch.setattr("backend.spec._call_gemini", lambda *args: Interpretation(
        brief=intake.RequestBrief(requested_metrics=["priorisoidaan"], unresolved_terms=["priorisoidaan"],
            missing_information=["metric", "definition"], usage="one_off"), outcome="ASK",
        spec=ChartSpec(metric="UNSUPPORTED", dimensions=["product"], understood=False, intent="one_off")))
    first = post(client, "Mitä tuotteita priorisoidaan?", language="fi").json()
    assert first["intake"]["questions"] == [generated.question.model_dump()]
    assert first["suggestions"] == [s.public() for s in generated.suggestions]
    assert "Määrittele priorisoidaan" not in first["answer"]
    second = post(client, generated.suggestions[0].answer, first["session_id"], "fi").json()
    assert second["decision"] == "ANSWER" and second["intake"]["pending"] is False
    assert second["spec"]["metric"] == "Inventory Coverage"
    assert second["brief"]["unresolved_terms"] == second["brief"]["missing_information"] == []
    assert "pending_request" not in db.conversations.find_one({"_id": first["session_id"]})
    assert len(calls) == 1


@pytest.mark.parametrize("blocked", ["time", "capability"])
def test_selected_metric_cannot_bypass_other_limits(sandbox, domain, monkeypatch, blocked):
    client, db = sandbox
    state = pending(metric_clarification())
    state.original_request = state.brief.original_request = "Mitä tuotteita priorisoidaan?"
    state.brief.requested_metrics, state.brief.unresolved_terms = ["priorisoidaan"], ["priorisoidaan"]
    state.brief.missing_information = ["metric", "definition"]
    state.brief.questions = [state.latest_questions[0]]
    if blocked == "time": state.brief.period, state.brief.start_month = "range", "2026-01"
    else: state.brief.unsupported = ["Power BI export"]
    db.conversations.insert_one({"_id": "blocked", "pending_request": state.model_dump(), "turns": []})
    monkeypatch.setattr(engine.metrics, "compute", lambda *args: pytest.fail("constraint bypassed"))
    response = post(client, state.suggestions[0].answer, "blocked").json()
    assert response["decision"] == "CLARIFY"
    assert db.results.count_documents({}) == 0


def test_classifier_question_and_choices_are_one_atomic_clarification(sandbox, monkeypatch):
    from backend import routing
    from backend.router import Classification
    client, db = sandbox
    generated = metric_clarification()
    responses = iter([
        Classification(intent="analytics_request", action=None, needs_clarification=True,
                       ambiguity_reason="Missing priority criterion", clarification=generated),
        Classification(intent="clarification_reply", action=None, needs_clarification=False, ambiguity_reason=None)])
    monkeypatch.setattr(routing, "classify", lambda *args: (next(responses), 1.0))
    first = post(client, "Mitä tuotteita priorisoidaan?", language="fi").json()
    assert first["answer"] == generated.question.text
    assert len(first["suggestions"]) == 2
    assert db.results.count_documents({}) == db.request_log.count_documents({}) == 0
    monkeypatch.setattr("backend.spec._call_gemini", lambda *args: Interpretation(
        brief=intake.RequestBrief(usage="one_off", unresolved_terms=["priorisoidaan"]), outcome="ASK",
        spec=ChartSpec(metric="UNSUPPORTED", dimensions=["product"], intent="one_off", understood=False)))
    second = post(client, generated.suggestions[0].answer, first["session_id"], "fi").json()
    assert second["question"] == generated.suggestions[0].answer
    assert second["decision"] == "ANSWER" and second["spec"]["metric"] == "Inventory Coverage"
    turns = db.conversations.find_one({"_id": first["session_id"]})["turns"]
    assert [t["q"] for t in turns] == ["Mitä tuotteita priorisoidaan?", generated.suggestions[0].answer]


def test_nested_model_answers_are_linked_to_their_actual_parent_question(domain):
    payload = clarification().model_dump()
    for choice in payload["suggestions"]:
        choice.pop("question_id")
    result = suggestions.validate(payload, [QUESTION], "Nubeqa Plant-B", {})
    assert all(choice.question_id == QUESTION["id"] for choice in result.suggestions)
    assert all(choice.public()["question_id"] == QUESTION["id"] for choice in result.suggestions)


def test_question_does_not_change_scope_not_asked_about(domain):
    payload = clarification().model_dump()
    payload["question"]["text"] = "All markets and plants?"
    for choice in payload["suggestions"]:
        choice["changes"]["plants"] = []
    with pytest.raises(ValueError):
        suggestions.validate(payload, [QUESTION], "Nubeqa Plant-B", {})


def test_data_refresh_invalidates_removed_identifiers(domain, monkeypatch):
    state = pending()
    changed = deepcopy(VALUES)
    changed["markets"].pop("FI")
    monkeypatch.setattr(suggestions, "lookups", lambda: changed)
    assert suggestions.resolve(state, state.suggestions[1].answer, "tehtaan_johtaja") is None
