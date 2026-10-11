"""Home: portfolio at a glance, top tasks, Today's briefing."""
from __future__ import annotations

import streamlit as st

from app.components import kpi_cards, portfolio_health, priority_table
from app.components.talk_track import active_chapter_banner, notes
from app.state import ApiError, get_client


def _briefing(client) -> None:
    head, button = st.columns([5, 1])
    head.markdown("#### Today's briefing")
    if button.button("Regenerate", icon=":material/refresh:", use_container_width=True):
        st.session_state["briefing_stale"] = True
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
    st.caption("Written by the agent; every number is checked against rule facts" if b.get("source") == "llm"
               else "Deterministic summary")
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
    segment = portfolio_health.render(summary)
    st.markdown("#### Top tasks today" + (f" - {segment}" if segment else ""))
    if segment == "Healthy":
        st.info("Healthy loans need no action today.")
    else:
        rows = client.queue(limit=500)
        if segment:
            in_segment = {r["loan_id"] for r in client.loans(health=segment)}
            rows = [r for r in rows if r["loan_id"] in in_segment]
        priority_table.render(rows, key="home_queue", page_size=8)
        st.caption(f"{len(rows)} loans need attention - click a loan ID to open it")
    st.divider()
    _briefing(client)
