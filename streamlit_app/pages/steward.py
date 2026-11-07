import json
import re

import streamlit as st

from govagent import AUDIT_KICKOFF, AUDITOR_SYSTEM, DEMO_QUESTIONS, TRIAGE_SYSTEM, run_agent
from govagent import tools as T
from streamlit_app import state

state.init()


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


st.title("🛡️ Data steward — Build Less, Build Better")
st.caption("The governed-analytics advisor: reuse, consolidation, migration or retirement of "
           "BI products instead of another dashboard by default. Advisory only — a human "
           "approves every lifecycle change. Synthetic Since AI 2026 challenge data.")

requests = st.session_state.requests_count
new_charts = st.session_state.new_charts_count
st.info(f"Build-less meter (factory assistant): **{requests} chat request(s) → "
        f"{new_charts} new chart(s)**. Certify-popular / retire-unused flows "
        "(n8n playbook) are planned.")

col1, col2 = st.columns([1, 2])
with col1:
    if st.button("Run governance audit", type="primary", use_container_width=True):
        with st.spinner("Auditing the estate..."):
            st.session_state.steward_audit = run_agent(AUDITOR_SYSTEM, AUDIT_KICKOFF)
    st.subheader("Demo questions")
    for i, q in enumerate(DEMO_QUESTIONS):
        if st.button(q, key=f"steward-demo{i}", use_container_width=True):
            st.session_state.factory_pending = q

if st.session_state.steward_audit:
    render_audit(st.session_state.steward_audit)
    st.divider()

for m in st.session_state.steward_messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m.get("trace"):
            render_trace(m["trace"])

pending = st.session_state.pop("factory_pending", None)
prompt = st.chat_input("Ask for a dashboard, report or analysis...")
if pending:
    prompt = pending

if prompt:
    history = list(st.session_state.steward_messages)
    st.session_state.steward_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Checking the estate before recommending..."):
            res = run_agent(TRIAGE_SYSTEM, prompt, history=history)
        st.markdown(res["answer"])
        if res["trace"]:
            render_trace(res["trace"])
    st.session_state.steward_messages.append({"role": "assistant", "content": res["answer"],
                                               "trace": res["trace"]})
