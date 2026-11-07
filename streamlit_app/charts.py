"""Chart, verdict badge and receipt rendering (pure helpers are smoke-testable headless)."""

import pandas as pd
import streamlit as st

VERDICT_BADGES = {
    "reuse": "♻️ UUDELLEENKÄYTETTY (REUSE)",
    "extend": "➕ LAAJENNETTU (EXTEND)",
    "answer": "💬 KERTAKYSYMYS (ANSWER)",
    "build": "🆕 UUSI MITTARI (BUILD)",
}


def to_dataframe(data, x_key="date", y_key="value"):
    df = pd.DataFrame(data)[[x_key, y_key]]
    return df.set_index(x_key)


def ensure_csv(response, x_key="date", y_key="value"):
    if response.get("csv"):
        return response["csv"]
    rows = response.get("chart", {}).get("data", [])
    if not rows:
        return ""
    df = pd.DataFrame(rows)[[x_key, y_key]]
    return df.to_csv(index=False)


def render_chart(chart):
    spec = chart.get("spec", {})
    df = to_dataframe(chart["data"], spec.get("x", "date"), spec.get("y", "value"))
    if spec.get("chart_type") == "bar":
        st.bar_chart(df)
    else:
        st.line_chart(df)


def render_receipt(receipt, csv, key="receipt"):
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Kaava**")
        st.caption(receipt.get("formula", "—"))
        st.markdown("**Lähteet**")
        st.caption(receipt.get("source", "—"))
    with col2:
        st.markdown("**Oletukset**")
        st.caption(f"versio {receipt.get('assumption_version', '—')} · "
                   f"{receipt.get('source_rows', '—')} lähderivtiä")
        st.markdown("**Tuoreus**")
        st.caption(receipt.get("freshness", "—"))
    st.download_button("Lataa raakadata (CSV)", data=csv, key=f"{key}-csv",
                       file_name="raakadata.csv", mime="text/csv",
                       use_container_width=True)


def render_verdict(response, key="verdict"):
    badge = VERDICT_BADGES.get(response["type"], response["type"].upper())
    st.markdown(f"**{badge}**")
    matched = response.get("matched_chart")
    if matched:
        st.caption(f"Vastine kaaviorekisterissä: **{matched['id']} — {matched['title']}**")
    st.markdown(response["text"])
    render_chart(response["chart"])
    with st.expander("Kuiti ja raakadata"):
        render_receipt(response.get("receipt", {}), ensure_csv(response), key=f"{key}-receipt")
