import json
import re

import streamlit as st

from govagent import (AUDIT_KICKOFF, AUDITOR_SYSTEM, DEMO_QUESTIONS, TRIAGE_SYSTEM,
                      run_agent)
from govagent import tools as T
from govagent.llm import config

st.set_page_config(page_title="Build Less, Build Better", layout="wide")
st.title("Build Less, Build Better — Governed Analytics Agent")
st.caption("AI assistant that recommends reuse, consolidation, migration or retirement of BI "
           "products instead of creating another dashboard. Synthetic Since AI 2026 challenge data.")

cfg = config()
with st.sidebar:
    if cfg["provider"] == "stub":
        st.warning("Offline stub mode. Set GOVAGENT_BASE_URL / GOVAGENT_API_KEY / "
                   "GOVAGENT_MODEL for real answers.")
    else:
        st.success(f"LLM: {cfg['model']}" + (f" @ {cfg['base_url']}" if cfg["base_url"] else ""))
    st.divider()
    st.subheader("BI estate")
    try:
        counts = T.tool_estate_overview()["data"]["counts"]
        st.caption(f"{counts['assets']} assets | {counts['semantic_models']} semantic models | "
                   f"{counts['kpis']} KPI definitions\n\n"
                   f"{counts['governance_signals']} governance signals | "
                   f"{counts['migration_items']} migration items")
    except Exception as e:
        st.error(f"Database not reachable: {e}")
    if st.button("Run governance audit", type="primary", use_container_width=True):
        with st.spinner("Auditing the estate..."):
            st.session_state["audit"] = run_agent(AUDITOR_SYSTEM, AUDIT_KICKOFF)
    st.divider()
    st.subheader("Demo questions")
    for i, q in enumerate(DEMO_QUESTIONS):
        if st.button(q, key=f"demo{i}", use_container_width=True):
            st.session_state["pending_question"] = q


def render_trace(trace):
    with st.expander(f"Evidence — {len(trace)} tool call(s)"):
        for t in trace:
            st.markdown(f"**{t['tool']}** `{json.dumps(t['args'], default=str)}`")
            st.caption(t["summary"])


def render_audit(res):
    st.subheader("Governance audit")
    st.markdown(res["answer"])
    m = re.search(r"```json\s*(\[.*?\])\s*```", res["answer"], re.S)
    if m:
        try:
            issues = json.loads(m.group(1))
        except json.JSONDecodeError:
            issues = []
        if issues:
            st.subheader(f"Issues ({len(issues)})")
            for issue in issues:
                sev = str(issue.get("severity", "low")).upper()
                with st.container():
                    st.markdown(f"**[{sev}] {issue.get('issue_type')}** — {issue.get('subject')}")
                    st.caption(" | ".join(str(e) for e in issue.get("evidence", [])))
                    action = issue.get("recommended_action", "")
                    if issue.get("requires_human_approval"):
                        action += " — requires human approval"
                    st.markdown(f"Recommended action: **{action}**")
                    st.divider()
    if res.get("trace"):
        render_trace(res["trace"])


if "messages" not in st.session_state:
    st.session_state.messages = []

if "audit" in st.session_state:
    render_audit(st.session_state.pop("audit"))

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m.get("trace"):
            render_trace(m["trace"])

pending = st.session_state.pop("pending_question", None)
prompt = st.chat_input("Ask for a dashboard, report or analysis...")
if pending:
    prompt = pending

if prompt:
    history = list(st.session_state.messages)
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Checking the estate before recommending..."):
            res = run_agent(TRIAGE_SYSTEM, prompt, history=history)
        st.markdown(res["answer"])
        if res["trace"]:
            render_trace(res["trace"])
    st.session_state.messages.append({"role": "assistant", "content": res["answer"],
                                       "trace": res["trace"]})
