import sys
from pathlib import Path

import streamlit as st

# Streamlit puts only this file's directory on sys.path; make the repo root
# importable so factory/, govagent/ and streamlit_app/ resolve from any cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from factory.n8n import config as n8n_config
from govagent import tools as T
from govagent.llm import config as llm_config
from streamlit_app import state
from streamlit_app.roles import get_role

st.set_page_config(page_title="Tuotannon analytiikka-assistentti", layout="wide")

state.init()

pages = [
    st.Page(state.HOME, title="Etusivu · rooli", icon="🏠", default=True),
    st.Page(state.BRIEFING, title="Aamubriiffi", icon="🌅"),
    st.Page(state.ASK, title="Kysy", icon="💬"),
    st.Page(state.STEWARD, title="Data steward", icon="🛡️"),
]
nav = st.navigation(pages)

with st.sidebar:
    llm = llm_config()
    if llm["provider"] == "stub":
        st.warning("LLM offline stub mode (steward flows). Set GOVAGENT_* env vars.")
    else:
        st.success(f"LLM: {llm['model']}"
                   + (f" @ {llm['base_url']}" if llm["base_url"] else ""))
    n8n = n8n_config()
    if n8n["provider"] == "stub":
        st.warning("n8n: offline stub — canned demo flows. Set N8N_PROVIDER=live and "
                   "N8N_BASE_URL to connect real workflows.")
    else:
        st.success(f"n8n: {n8n['base_url']}")
    st.divider()
    if state.get_role():
        role = get_role(state.get_role())
        st.markdown(f"**Rooli:** {role['icon']} {role['label']}")
        if st.button("Vaihda roolia", use_container_width=True):
            state.clear_role()
            state.go_to(state.HOME)
    st.caption(f"♻️ Build-less: {st.session_state.requests_count} pyyntöä → "
               f"{st.session_state.new_charts_count} uutta kaaviota")
    st.divider()
    st.subheader("BI estate (Bayer demo)")
    try:
        counts = T.tool_estate_overview()["data"]["counts"]
        st.caption(f"{counts['assets']} assets | {counts['semantic_models']} semantic models | "
                   f"{counts['kpis']} KPI definitions\n\n"
                   f"{counts['governance_signals']} governance signals | "
                   f"{counts['migration_items']} migration items")
    except Exception as e:
        st.error(f"Database not reachable: {e}")

nav.run()
