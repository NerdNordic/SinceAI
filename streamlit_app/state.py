"""Session-state helpers and page paths for the multi-page factory app."""

import streamlit as st

# Page paths, relative to the entrypoint (streamlit_app/streamlit_app.py).
# Single source of truth: used for st.Page in the entrypoint and go_to() in pages.
HOME = "pages/home.py"
BRIEFING = "pages/briefing.py"
ASK = "pages/ask.py"
STEWARD = "pages/steward.py"


def init():
    defaults = {
        "role": None,
        "factory_chat": [],
        "briefing": {},
        "pending_question": None,
        "requests_count": 0,
        "new_charts_count": 0,
        "steward_messages": [],
        "steward_audit": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def get_role():
    return st.session_state.get("role")


def set_role(role_id):
    st.session_state.role = role_id
    st.session_state.factory_chat = []
    st.session_state.briefing = {}


def clear_role():
    st.session_state.role = None
    st.session_state.factory_chat = []
    st.session_state.briefing = {}


def record_request(verdict=None):
    st.session_state.requests_count += 1
    if verdict == "build":
        st.session_state.new_charts_count += 1


def go_to(page_path):
    try:
        st.switch_page(page_path)
    except st.errors.StreamlitAPIException:
        pass
