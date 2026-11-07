"""Native Streamlit UI tests with an offline FastAPI boundary."""

from pathlib import Path
from uuid import UUID

import pytest
from streamlit.testing.v1 import AppTest

from app import dashboard_client
from app.dashboard_client import DashboardError

SCRIPT = Path(__file__).resolve().parents[1] / "streamlit_app.py"


@pytest.fixture
def dashboard(monkeypatch):
    calls = []
    reply = {"type": "chart", "route": "BUILD", "message": "Chart created",
             "chart_id": "CH-TEST", "chart_status": "active", "title": "OTIF",
             "chart": {"data": [{"type": "bar", "x": ["Oct"], "y": [95]}], "layout": {}},
             "table": [{"series": "OTIF", "value": 95}], "csv": "period,value\nOct,95\n",
             "receipt": {"source_row_count": 1},
             "data_quality_warnings": [{"code": "TEST_WARNING", "detail": "Source warning"}]}
    failure = {}

    def request(self, path, body=None, *, csv=False):
        calls.append((path, body))
        if path in failure:
            raise DashboardError(failure[path])
        if path == "/api/settings":
            return {"backend": "n8n", "auth_mode": "local"}
        if path == "/api/roles":
            return [{"id": "tehtaan_johtaja", "label": "Plant manager"},
                    {"id": "vuoropaallikko", "label": "Shift manager"},
                    {"id": "data_steward", "label": "Data steward"}]
        if path.startswith("/api/briefing/"):
            return {"cards": [{"label": "OTIF", "value": 95, "unit": "%"}], "items": [], "plant": "Plant-A"}
        if path.startswith("/api/meter"):
            return {"requests": 3, "new_charts": 1, "handled_without_new_chart": 2}
        if path == "/api/registry":
            return [{"chart_id": "CH-TEST", "title": "OTIF", "status": "active", "usage_count": 3}]
        if path == "/api/proposals":
            return [{"approval_id": "APR-TEST", "title": "OTIF", "kind": "new_chart", "status": "pending"}]
        if path == "/api/audit":
            return []
        if path == "/api/ask":
            return dict(reply)
        if path.endswith("/raw.csv") and csv:
            return "period,value\nOct,95\n"
        if path.startswith("/api/registry/"):
            return {"status": "pending"}
        pytest.fail(f"Unexpected API call: {path}")

    monkeypatch.setattr(dashboard_client, "identity_headers", lambda headers, address: {})
    monkeypatch.setattr(dashboard_client.DashboardClient, "request", request)
    app = AppTest.from_file(str(SCRIPT), default_timeout=15).run()
    assert not app.exception
    return app, calls, reply, failure


def button(app, label):
    return next(widget for widget in app.button if widget.label == label)


def asks(calls):
    return [body for path, body in calls if path == "/api/ask"]


def test_chat_chart_csv_receipt_and_no_post_on_rerun(dashboard):
    app, calls, _, _ = dashboard
    app.chat_input[0].set_value("OTIF monthly").run()
    assert not app.exception
    assert len(asks(calls)) == 1
    body = asks(calls)[0]
    assert body["question"] == "OTIF monthly"
    UUID(body["request_id"])
    UUID(body["sessionId"])
    assert body["role"] == "tehtaan_johtaja"
    assert len(app.get("plotly_chart")) == 1
    assert len(app.get("download_button")) == 1
    assert any(warning.value == "TEST_WARNING: Source warning" for warning in app.warning)
    assert any(expander.label == "Calculation receipt" for expander in app.expander)
    app.run()
    assert len(asks(calls)) == 1


def test_clarification_followup_and_bounded_history(dashboard):
    app, calls, reply, _ = dashboard
    reply.update(type="clarify", route="CLARIFY", chart=None, suggestions=["On-Time In-Full"])
    app.chat_input[0].set_value("Which KPI?").run()
    button(app, "On-Time In-Full").click().run()
    assert not app.exception
    assert len(asks(calls)) == 2
    assert asks(calls)[1]["question"] == "On-Time In-Full"
    assert asks(calls)[1]["history"][0]["content"] == "Which KPI?"
    for index in range(4):
        app.chat_input[0].set_value(f"Question {index}").run()
    assert len(asks(calls)[-1]["history"]) == 8
    assert len(app.session_state["history"]) == 8


def test_refresh_saved_chart_skips_question_and_preserves_history(dashboard):
    app, calls, _, _ = dashboard
    app.chat_input[0].set_value("OTIF").run()
    button(app, "Refresh saved chart").click().run()
    assert not app.exception
    assert asks(calls)[1]["chart_id"] == "CH-TEST"
    assert asks(calls)[1]["question"] == ""
    assert len(app.session_state["history"]) == 2
    assert asks(calls)[0]["sessionId"] == asks(calls)[1]["sessionId"]


def test_role_and_new_conversation_reset_private_state(dashboard):
    app, calls, _, _ = dashboard
    app.chat_input[0].set_value("Private question").run()
    session = app.session_state["session_id"]
    app.selectbox(key="selected_role").select("vuoropaallikko").run()
    assert app.session_state["history"] == []
    assert app.session_state["messages"] == []
    assert app.session_state["session_id"] != session
    assert len(asks(calls)) == 1
    app.chat_input[0].set_value("New question").run()
    assert asks(calls)[1]["history"] == []
    button(app, "New conversation").click().run()
    assert app.session_state["history"] == []
    assert len(asks(calls)) == 2


def test_timeout_not_replayed_by_language_or_dashboard_refresh(dashboard):
    app, calls, _, failure = dashboard
    failure["/api/ask"] = "Request timed out; completion is unknown"
    app.chat_input[0].set_value("OTIF").run()
    assert any("timed out" in error.value for error in app.error)
    app.selectbox(key="language").select("en").run()
    button(app, "Refresh dashboard").click().run()
    assert not app.exception
    assert len(asks(calls)) == 1
    assert app.session_state["history"] == []


def test_briefing_failure_does_not_block_chat(dashboard):
    app, calls, _, failure = dashboard
    failure["/api/briefing/tehtaan_johtaja"] = "Source unavailable"
    button(app, "Refresh dashboard").click().run()
    app.chat_input[0].set_value("OTIF").run()
    assert not app.exception and len(asks(calls)) == 1
    assert any("Source unavailable" in warning.value for warning in app.warning)


def test_governance_uses_canonical_ids_and_no_replay(dashboard):
    app, calls, _, _ = dashboard
    app.selectbox(key="selected_role").select("data_steward").run()
    button(app, "Propose certification").click().run()
    button(app, "Approve").click().run()
    assert not app.exception
    writes = [(path, body) for path, body in calls if path.startswith("/api/registry/") and body]
    assert writes == [("/api/registry/CH-TEST/propose", {"action": "certify"}),
                      ("/api/registry/decision", {"approval_id": "APR-TEST", "approved": True})]
    app.run()
    assert len([body for path, body in calls if body and path.startswith("/api/registry/")]) == 2


def test_invalid_chart_keeps_table_and_receipt(dashboard):
    app, calls, reply, _ = dashboard
    reply["chart"] = {"data": [{"type": "not-a-chart"}], "layout": {}}
    app.chat_input[0].set_value("OTIF").run()
    assert not app.exception and len(asks(calls)) == 1
    assert any("could not be rendered" in warning.value for warning in app.warning)
    assert any(expander.label == "Calculation receipt" for expander in app.expander)


def test_oneoff_and_build_request(dashboard):
    app, _, reply, _ = dashboard
    reply.update(type="answer", route="ANSWER", compact=True,
                 headline={"value": 95, "unit": "%", "period": "Oct"})
    app.chat_input[0].set_value("What is OTIF?").run()
    assert not app.exception and any(metric.value == "95 %" for metric in app.metric)
    reply.update(type="build_request", route="BUILD", approval_id="APR-NEW", chart=None)
    app.chat_input[0].set_value("New KPI").run()
    assert not app.exception and any("APR-NEW" in caption.value for caption in app.caption)


def test_local_chart_and_source_csv_remain_available(dashboard):
    app, calls, reply, _ = dashboard
    app.session_state["settings"] = {"backend": "local", "auth_mode": "local"}
    reply.clear()
    reply.update(decision="ANSWER", reason="Local answer", result_id="result-1",
                 chart={"type": "line", "labels": ["Oct"],
                        "datasets": [{"label": "OTIF", "data": [95]}]}, rows=[{"value": 95}])
    app.chat_input[0].set_value("OTIF locally").run()
    assert not app.exception and len(app.get("plotly_chart")) == 1
    button(app, "Prepare source CSV").click().run()
    assert not app.exception and len(app.get("download_button")) == 1
    assert len(asks(calls)) == 1
    assert any(path == "/api/results/result-1/raw.csv" for path, _ in calls)


def test_authenticated_identity_change_clears_conversation(dashboard, monkeypatch):
    app, calls, _, _ = dashboard
    app.chat_input[0].set_value("Private request").run()
    previous_session = app.session_state["session_id"]
    monkeypatch.setattr(dashboard_client, "identity_headers", lambda headers, address: {
        "X-SinceAI-Role": "tehtaan_johtaja", "X-SinceAI-User": "Different user"})
    app.run()
    assert not app.exception
    assert app.session_state["messages"] == [] and app.session_state["history"] == []
    assert app.session_state["session_id"] != previous_session
    assert len(asks(calls)) == 1
