"""Home: KPIs, portfolio health, Today's Portfolio Briefing, prioritized task preview."""
from __future__ import annotations

import streamlit as st

from app.components import kpi_cards, portfolio_health, priority_table
from app.state import ApiError, get_client


def _briefing(client) -> None:
    st.markdown("#### ✨ Today's Portfolio Briefing")
    if "briefing" not in st.session_state or st.session_state.get("briefing_stale"):
        with st.spinner("Agent drafting briefing from deterministic facts..."):
            try:
                st.session_state["briefing"] = client.agent("briefing")
            except ApiError as exc:
                st.session_state["briefing"] = {"text": f"Briefing unavailable: {exc.detail}", "source": "error",
                                                "facts": []}
        st.session_state["briefing_stale"] = False
    b = st.session_state["briefing"]
    label = {"llm": "Agent (LLM) — number-checked against deterministic facts",
             "deterministic": "Deterministic template"}.get(b.get("source"), b.get("source"))
    st.markdown(f'<div class="lsi-ai">{b["text"].replace(chr(10), "<br>")}</div>', unsafe_allow_html=True)
    cols = st.columns([3, 1])
    cols[0].caption(f"Source: {label}" + (f" · LLM draft rejected: {b['rejected_reason']}" if b.get("rejected_reason") else ""))
    if cols[1].button("Regenerate", icon=":material/refresh:", use_container_width=True):
        st.session_state["briefing_stale"] = True
        st.rerun()
    with st.expander("Deterministic facts used (the only inputs to the briefing)"):
        st.dataframe(b.get("facts") or [], hide_index=True, use_container_width=True)


def render() -> None:
    client = get_client()
    summary = client.summary()
    st.markdown("### Portfolio monitoring")
    st.caption("Every active synthetic loan is evaluated each cycle by deterministic, configuration-driven rules. "
               "Metrics below are calculated, not hard-coded.")
    kpi_cards.render(summary)

    left, right = st.columns([3, 2])
    with left:
        st.markdown("#### Portfolio health")
        segment = portfolio_health.render(summary)
        st.markdown("#### Prioritized tasks" + (f" — {segment}" if segment else ""))
        if segment == "Healthy":
            st.info("Healthy loans need no action. Open the Portfolio page to browse them.")
            rows = []
        else:
            rows = client.queue(limit=500)
            if segment:
                health_by_loan = {r["loan_id"]: r["health_segment"] for r in client.loans(health=segment)}
                rows = [r for r in rows if r["loan_id"] in health_by_loan]
        priority_table.render(rows[:10], key="home_queue", compact=True)
        if rows:
            st.caption(f"Showing top {min(10, len(rows))} of {len(rows)} loans needing attention. Select a row to open Loan 360.")
    with right:
        _briefing(client)
