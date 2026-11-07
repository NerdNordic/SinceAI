import streamlit as st

from streamlit_app import state
from streamlit_app.roles import ROLES, STEWARD

state.init()

st.title("Tuotannon analytiikka-assistentti")
st.caption("Roolikohtainen aamubriiffi ja chat, joka tuottaa vähemmän ja parempia kaavioita — "
           "uudelleenkäyttö ennen uutta rakentamista. Synthetic Since AI 2026 demo.")

st.subheader("Valitse roolisi")
cols = st.columns(3)
for col, role in zip(cols, ROLES.values()):
    with col:
        with st.container(border=True):
            st.markdown(f"### {role['icon']} {role['label']}")
            st.markdown(role["description"])
            if st.button("Valitse", key=f"role-{role['id']}", use_container_width=True,
                         type="primary"):
                state.set_role(role["id"])
                state.go_to(state.BRIEFING)

st.divider()
with st.container(border=True):
    st.markdown(f"### {STEWARD['icon']} {STEWARD['label']}")
    st.markdown(STEWARD["description"])
    if st.button("Avaa hallinnan näkymä", key="role-steward", use_container_width=True):
        state.set_role("steward")
        state.go_to(state.STEWARD)

st.divider()
with st.expander("Miten tämä toimii? (build-less -periaate)"):
    st.markdown(
        "1. **Aamubriiffi** — roolisi tärkeimmät luvut, poikkeamat ja datan tuoreus.\n"
        "2. **Kysy chatissa** — kysymys muutetaan kanoniseksi kaaviospesifikaatioksi.\n"
        "3. **Sormenjälkitarkistus** — onko vastaava kaavio jo olemassa?\n"
        "4. **Päätös**: ♻️ REUSE (uudelleenkäytä) · ➕ EXTEND (laajenna) · "
        "💬 ANSWER (kertavastaus) · 🆕 BUILD (uusi hallittu mittari).\n"
        "5. **Kuiti** — kaava, lähteet, oletusten versio, tuoreus ja raakadata CSV:nä.")
