"""SinceAI dashboard. Run with: python -m streamlit run streamlit_app.py."""

from __future__ import annotations

from urllib.parse import quote
from uuid import uuid4

import plotly.graph_objects as go
import streamlit as st

from app.dashboard_client import DashboardClient, DashboardError, identity_headers


def reset_conversation() -> None:
    st.session_state.session_id = str(uuid4())
    st.session_state.messages = []
    st.session_state.history = []
    st.session_state.pop("pending", None)
    st.session_state.pop("error", None)


def queue_question(question: str = "", chart_id: str | None = None) -> None:
    st.session_state.pending = {"question": question, "chart_id": chart_id}
    st.rerun()


def submit(client: DashboardClient, question: str, chart_id: str | None = None) -> None:
    """Called only after a user event; rerunning a page never replays a POST."""
    try:
        response = client.request("/api/ask", {
            "question": question, "chart_id": chart_id, "role": st.session_state.selected_role,
            "language": st.session_state.language, "sessionId": st.session_state.session_id,
            "request_id": str(uuid4()), "history": st.session_state.history[-8:],
        })
    except DashboardError as exc:
        st.session_state.error = str(exc)
        return
    message = response.get("message", response.get("reason", ""))
    st.session_state.messages.append({"id": str(uuid4()), "question": question,
                                      "chart_id": chart_id, "response": response})
    st.session_state.messages = st.session_state.messages[-30:]
    if not chart_id:
        st.session_state.history = (st.session_state.history + [
            {"role": "user", "content": question},
            {"role": "assistant", "content": message[:4000]},
        ])[-8:]
    st.session_state.pop("error", None)
    st.session_state.dashboard = None


def make_figure(chart: dict) -> go.Figure:
    if "data" in chart:
        return go.Figure(chart)
    # The local Python engine keeps its existing response contract. Both modes
    # now render through the same Python plotting dependency.
    figure = go.Figure()
    for series in chart.get("datasets", []):
        if chart.get("type") == "line":
            figure.add_scatter(x=chart["labels"], y=series["data"], name=series["label"], mode="lines+markers")
        else:
            figure.add_bar(x=chart["labels"], y=series["data"], name=series["label"])
    return figure


def render_answer(client: DashboardClient, entry: dict) -> None:
    response = entry["response"]
    key = entry["id"]
    with st.chat_message("user"):
        st.text(entry["question"] or f"Refresh {entry['chart_id']}")
    with st.chat_message("assistant"):
        st.caption(" · ".join(str(value) for value in (
            response.get("route", response.get("decision")), response.get("title"),
            response.get("chart_status")) if value))
        st.text(response.get("message", response.get("reason", "")))
        for warning in response.get("data_quality_warnings", []):
            st.warning(f"{warning['code']}: {warning['detail']}")
        if response.get("approval_id"):
            st.caption(f"Approval: {response['approval_id']}")
        headline = response.get("headline")
        if headline:
            st.metric(str(headline.get("period", "Result")),
                      f"{headline.get('value', '—')} {headline.get('unit', '')}")
        chart = response.get("chart")
        if chart and chart.get("type") != "table":
            try:
                figure = make_figure(chart)
                figure.update_layout(height=230 if response.get("compact") else 360)
                st.plotly_chart(figure, width="stretch", key=f"chart-{key}",
                                config={"displaylogo": False, "displayModeBar": False})
            except (ValueError, TypeError):
                st.warning("The chart could not be rendered. Table and receipt remain available.")
        rows = response.get("table", response.get("rows", []))
        if rows:
            with st.expander(f"Table ({len(rows)} rows)"):
                st.dataframe(rows, hide_index=True, width="stretch")
        if response.get("csv"):
            st.download_button("Download source CSV", response["csv"], file_name="kpi.csv",
                               mime="text/csv", key=f"csv-{key}", on_click="ignore")
        elif response.get("result_id") and st.session_state.settings["backend"] == "local":
            if st.button("Prepare source CSV", key=f"prepare-{key}"):
                try:
                    response["csv"] = client.request(
                        f"/api/results/{quote(response['result_id'], safe='')}/raw.csv", csv=True)
                    st.rerun()
                except DashboardError as exc:
                    st.error(str(exc))
        if response.get("receipt"):
            with st.expander("Calculation receipt"):
                st.json(response["receipt"])
        related = response.get("related_assets", response.get("related_reports", []))
        if related:
            with st.expander("Related assets"):
                st.json(related)
        if response.get("type") == "clarify":
            for index, suggestion in enumerate(response.get("suggestions", [])):
                if st.button(suggestion, key=f"suggestion-{key}-{index}"):
                    queue_question(suggestion)
        if (response.get("chart_id") and response.get("chart_status") in {"active", "certified"}
                and st.session_state.settings["backend"] == "n8n"):
            if st.button("Refresh saved chart", key=f"refresh-{key}"):
                queue_question(chart_id=response["chart_id"])


def load_dashboard(client: DashboardClient, role: str) -> dict:
    paths = {"brief": f"/api/briefing/{quote(role, safe='')}",
             "meter": f"/api/meter?role={quote(role, safe='')}"}
    if role == "data_steward":
        paths.update(registry="/api/registry", approvals="/api/proposals", audit="/api/audit")
    data = {"errors": []}
    for key, path in paths.items():
        try:
            data[key] = client.request(path)
        except DashboardError as exc:
            data["errors"].append(f"{key}: {exc}")
    return data


def render_briefing(brief: dict) -> None:
    st.subheader("Morning briefing")
    if brief.get("plant"):
        st.caption(brief["plant"])
    for card in brief.get("cards", []):
        st.metric(card["label"], f"{card.get('value', '—')} {card.get('unit', '')}")
    for item in brief.get("items", []):
        st.text(f"{item['product']} → {item['market']} · {item['status_fi']}")
        st.caption(f"Order by {item['reorder_by']} · {item['weekly_units']} units/week")
        if item.get("expedite"):
            st.warning(item["expedite"])
    if brief.get("freshness"):
        st.caption(brief["freshness"])


def governance_action(client: DashboardClient, path: str, body: dict) -> None:
    try:
        client.request(path, body)
    except DashboardError as exc:
        st.error(str(exc))
        return
    st.session_state.dashboard = None
    st.session_state.flash = "Governance request completed."
    st.rerun()


def render_governance(client: DashboardClient, data: dict) -> None:
    st.subheader("Chart registry")
    charts = data.get("registry", [])
    st.dataframe(charts, hide_index=True, width="stretch")
    eligible = [chart for chart in charts if chart.get("status") in {"active", "certified"}]
    if eligible:
        chart = st.selectbox("Chart", eligible,
                             format_func=lambda item: f"{item.get('title', '')} ({item.get('status')})")
        identifier = chart.get("chart_id") or chart["fingerprint"]
        certify, retire = st.columns(2)
        if certify.button("Propose certification", disabled=chart.get("status") != "active"):
            governance_action(client, f"/api/registry/{quote(identifier, safe='')}/propose", {"action": "certify"})
        if retire.button("Propose retirement"):
            governance_action(client, f"/api/registry/{quote(identifier, safe='')}/propose", {"action": "retire"})
    st.subheader("Approvals")
    approvals = data.get("approvals", [])
    st.dataframe(approvals, hide_index=True, width="stretch")
    pending = [approval for approval in approvals if approval.get("status") == "pending"]
    if pending and st.session_state.settings["backend"] == "n8n":
        approval = st.selectbox("Pending approval", pending,
            format_func=lambda item: f"{item.get('title', '')} · {item.get('kind', item.get('action', 'Approval'))}")
        approve, reject = st.columns(2)
        for column, label, decision in ((approve, "Approve", True), (reject, "Reject", False)):
            if column.button(label):
                governance_action(client, "/api/registry/decision",
                                  {"approval_id": approval["approval_id"], "approved": decision})
    elif pending:
        st.info("Local approval decisions require the authenticated legacy callback.")
    with st.expander("Audit log"):
        st.dataframe(data.get("audit", []), hide_index=True, width="stretch")


def render_chat(client: DashboardClient) -> None:
    for entry in st.session_state.messages:
        render_answer(client, entry)
    question = st.chat_input("Ask about a KPI or request a chart", max_chars=4000)
    if question and question.strip():
        queue_question(question.strip())


def main() -> None:
    st.set_page_config(page_title="SinceAI", page_icon="📊", layout="wide")
    st.title("SinceAI")
    st.caption("Governed KPI assistant")
    try:
        headers = identity_headers(dict(st.context.headers), st.get_option("server.address"))
        client = DashboardClient(headers)
        # Reset all user data when the trusted identity changes. Never cache
        # credentials, role-sensitive responses or conversations across sessions.
        identity = (headers.get("X-SinceAI-Role"), headers.get("X-SinceAI-User"))
        if st.session_state.get("identity") != identity:
            st.session_state.clear()
            st.session_state.identity = identity
        if "settings" not in st.session_state:
            settings = client.request("/api/settings")
            roles = client.request("/api/roles")
            st.session_state.settings = settings
            st.session_state.roles = roles
        roles = st.session_state.roles
        if not roles:
            raise DashboardError("No authorized application role is available")
    except DashboardError as exc:
        st.error(str(exc))
        st.stop()
    with st.sidebar:
        labels = {role["id"]: role["label"] for role in roles}
        role = st.selectbox("Role", list(labels), format_func=labels.get, key="selected_role")
        st.selectbox("Language", ["fi", "en"], key="language")
        if st.session_state.settings["auth_mode"] == "local":
            st.info("Local demo: role selection is not user authentication.")
        if role != st.session_state.get("active_role"):
            reset_conversation()
            st.session_state.active_role = role
            st.session_state.dashboard = None
        if st.button("New conversation"):
            reset_conversation()
            st.rerun()
        if st.button("Refresh dashboard"):
            st.session_state.dashboard = None
    # Consume the event before I/O so downloads, selections and failed reruns
    # cannot accidentally repeat a chart/approval-creating POST.
    pending = st.session_state.pop("pending", None)
    if pending:
        with st.spinner("Processing your request…"):
            submit(client, **pending)
    if st.session_state.get("dashboard") is None:
        st.session_state.dashboard = load_dashboard(client, role)
    data = st.session_state.dashboard
    if st.session_state.get("error"):
        st.error(st.session_state.error)
    if st.session_state.get("flash"):
        st.success(st.session_state.pop("flash"))
    for error in data["errors"]:
        st.warning(error)
    meter = data.get("meter", {})
    columns = st.columns(3)
    for column, label, field in zip(columns, ("Requests", "Registered charts", "Handled without a new chart"),
                                    ("requests", "new_charts", "handled_without_new_chart")):
        column.metric(label, meter.get(field, "—"))
    with st.sidebar:
        if data.get("brief"):
            render_briefing(data["brief"])
    if role == "data_steward":
        chat, governance = st.tabs(["Chat", "Governance"])
        with chat:
            render_chat(client)
        with governance:
            render_governance(client, data)
    else:
        render_chat(client)


if __name__ == "__main__":
    main()
