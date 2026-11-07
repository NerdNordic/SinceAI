import streamlit as st

from factory import n8n
from streamlit_app import state
from streamlit_app.roles import get_role

state.init()
role_id = state.get_role()
role = get_role(role_id)
if not role_id or role_id == "steward":
    st.info("Valitse ensin rooli etusivulta.")
    state.go_to(state.HOME)
    st.stop()
doc = st.session_state.briefing.get(role_id)
if doc is None:
    doc = n8n.get_briefing(role_id)
    st.session_state.briefing[role_id] = doc

st.title(f"{role['icon']} Aamubriiffi — {role['label']}")
st.caption(f"Laadittu {doc['as_of']} · {role['briefing_focus']}")

left, right = st.columns([4, 1])
with right:
    if st.button("Päivitä briiffi", use_container_width=True):
        st.session_state.briefing.pop(role_id, None)
        st.rerun()

kpis = doc["kpis"]
LOWER_IS_BETTER = {"KPI-007", "KPI-012", "KPI-014"}
for kpi_index, kpi in enumerate(kpis):
    if kpi_index % 3 == 0:
        cols = st.columns(3)
    with cols[kpi_index % 3]:
        name = f"⚠️ {kpi['name']}" if kpi["status"] == "deviation" else kpi["name"]
        fmt = f"{kpi['value']:,}".replace(",", " ")
        delta = None
        if kpi.get("target") is not None:
            delta = kpi["value"] - kpi["target"]
        st.metric(name, f"{fmt} {kpi['unit']}", delta=delta,
                  delta_color="inverse" if kpi["id"] in LOWER_IS_BETTER else "normal")
        fresh = kpi["freshness"]
        icon = "🟢" if fresh["state"] == "fresh" else "🟠"
        st.caption(f"{icon} Päivitetty {fresh['last_refresh']}"
                   + (" — data vanhentunut" if fresh["state"] == "stale" else ""))
        if st.button("Kysy tästä", key=f"ask-kpi-{kpi_index}", use_container_width=True):
            st.session_state.pending_question = \
                f"Näytä {kpi['name']} kehitys viimeiset 14 päivää"
            state.go_to(state.ASK)

deviations = doc.get("deviations", [])
if deviations:
    st.subheader("Poikkeamat")
    renderers = {"high": st.error, "medium": st.warning, "low": st.info}
    for dev in deviations:
        renderers.get(dev["severity"], st.info)(
            f"**{dev['kpi_id']}**: {dev['message']}")
else:
    st.success("Ei poikkeamia — kaikki tunnusluvut tavoitteissa.")

st.divider()
if st.button("💬 Siirry kysymään chatista"):
    state.go_to(state.ASK)
