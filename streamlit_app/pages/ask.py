import streamlit as st

from factory import n8n
from streamlit_app import charts, state
from streamlit_app.roles import get_role

state.init()
role_id = state.get_role()
role = get_role(role_id)
if not role_id or role_id == "steward":
    st.info("Valitse ensin rooli etusivulta.")
    state.go_to(state.HOME)
    st.stop()
st.title(f"💬 Kysy — {role['icon']} {role['label']}")
st.caption("Kysymyksestä kanoninen kaavio: uudelleenkäyttö ennen uutta rakentamista. "
           "Jokaiseen vastaukseen liittyy kuiti ja raakadata.")

DEMO_QUESTIONS = [
    "Näytä OEE viimeiset 14 päivää",
    "OEE yövuoroissa",
    "Paljonko tuotettiin viime yönä?",
    "Tuotantomäärä linjoittain",
    "Energiankulutus linjoittain",
    "tuotanto?",
]


def _submit(question):
    st.session_state.factory_chat.append({"role": "user", "content": question})
    with st.spinner("Muodostetaan kanoninen kaaviospesifikaatio ja tarkistetaan "
                    "kaaviorekisteriä..."):
        try:
            resp = n8n.ask(role_id, question,
                           history=[m["content"] for m in st.session_state.factory_chat[:-1]])
        except RuntimeError as e:
            st.session_state.factory_chat.append(
                {"role": "assistant", "content": f"Virhe: {e}", "response": None})
            st.rerun()
            return
    state.record_request(resp.get("type"))
    st.session_state.factory_chat.append(
        {"role": "assistant",
         "content": resp["text"] if resp["type"] != "clarify" else resp["question"],
         "response": resp})
    st.rerun()


def _render_response(msg, index):
    resp = msg.get("response")
    if resp is None:
        st.markdown(msg["content"])
        return
    if resp["type"] == "clarify":
        st.markdown(resp["question"])
        for i, sug in enumerate(resp["suggestions"]):
            if st.button(f"Käytä kanonista: {sug['label']} ({sug['kpi_id']})",
                         key=f"sug-{index}-{i}", use_container_width=True):
                _submit(f"Näytä {sug['label']} viimeiset 14 päivää")
        return
    charts.render_verdict(resp, key=f"msg-{index}")


chips = st.columns(len(DEMO_QUESTIONS))
for col, question in zip(chips, DEMO_QUESTIONS):
    with col:
        if st.button(question, key=f"demo-{question}", use_container_width=True):
            _submit(question)

for index, msg in enumerate(st.session_state.factory_chat):
    with st.chat_message(msg["role"]):
        if msg["role"] == "user":
            st.markdown(msg["content"])
        else:
            _render_response(msg, index)

pending = st.session_state.pop("pending_question", None)
if pending:
    _submit(pending)

prompt = st.chat_input("Kysy kaaviosta tai luvusta (esim. 'Näytä OEE viimeiset 14 päivää')")
if prompt:
    _submit(prompt)
