"""Home: portfolio at a glance, Today's Portfolio Briefing, top tasks."""
from __future__ import annotations

import streamlit as st

from app.components import kpi_cards, portfolio_health, priority_table
from app.components.talk_track import active_chapter_banner, notes
from app.state import ApiError, get_client


def _briefing(client) -> None:
    st.markdown("#### ✨ Today's briefing")
    if "briefing" not in st.session_state or st.session_state.get("briefing_stale"):
        with st.spinner("Agent drafting the briefing from today's facts..."):
            try:
                st.session_state["briefing"] = client.agent("briefing")
            except ApiError as exc:
                st.session_state["briefing"] = {"text": f"Briefing unavailable: {exc.detail}", "source": "error",
                                                "facts": []}
        st.session_state["briefing_stale"] = False
    b = st.session_state["briefing"]
    st.markdown(f'<div class="lsi-ai">{b["text"].replace(chr(10), "<br>")}</div>', unsafe_allow_html=True)
    source = "Written by the agent, numbers checked against rule facts" if b.get("source") == "llm" \
        else "Deterministic summary"
    c1, c2 = st.columns([3, 1])
    c1.caption(source)
    if c2.button("Regenerate", icon=":material/refresh:", use_container_width=True):
        st.session_state["briefing_stale"] = True
        st.rerun()
    with st.expander("Facts the briefing is allowed to use"):
        st.dataframe([{"group": f["fact_group"], "fact": f["fact_name"], "value": f["fact_value"]}
                      for f in b.get("facts") or []], hide_index=True, use_container_width=True)


def render() -> None:
    active_chapter_banner("home")
    client = get_client()
    summary = client.summary()
    st.markdown("## Portfolio at a glance")
    notes("home")
    kpi_cards.render(summary)
    st.write("")
    left, right = st.columns([3, 2], gap="large")
    with left:
        segment = portfolio_health.render(summary)
        st.markdown("#### Top tasks today" + (f" · {segment}" if segment else ""))
        rows = [] if segment == "Healthy" else client.queue(limit=500)
        if segment and segment != "Healthy":
            in_segment = {r["loan_id"] for r in client.loans(health=segment)}
            rows = [r for r in rows if r["loan_id"] in in_segment]
        if segment == "Healthy":
            st.info("Healthy loans need no action today.")
        else:
            priority_table.render(rows[:8], key="home_queue", compact=True)
            st.caption(f"{len(rows)} loans need attention · click a row to open it")
    with right:
        _briefing(client)
