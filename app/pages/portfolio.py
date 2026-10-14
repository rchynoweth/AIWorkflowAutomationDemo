"""Portfolio: every loan, with the AI that Databricks created for it."""
from __future__ import annotations

from datetime import date

import streamlit as st

from app import ui
from app.client import get_client

PRIORITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]


def render() -> None:
    client = get_client()
    st.markdown("## Portfolio")
    ui.notes("portfolio")
    summary = client.summary()
    ai = client.backend_ai()
    loans = [r for r in client.loans() if r["is_active"]]

    reviews, insights = ai.get("reviews", {}), ai.get("insights", {})
    cols = st.columns(4)
    cols[0].markdown(ui.card("Active loans", f"{summary['active_loans']:,}"), unsafe_allow_html=True)
    cols[1].markdown(ui.card("Need attention", f"{summary['need_attention']:,}", "#B54708"), unsafe_allow_html=True)
    cols[2].markdown(ui.card("AI summaries", f"{len(insights):,}", "#6941C6"), unsafe_allow_html=True)
    cols[3].markdown(ui.card("Reviewed by the agent", f"{len(reviews):,}", "#6941C6"), unsafe_allow_html=True)
    st.write("")

    briefing = ai.get("briefing")
    if briefing:
        st.markdown(f"#### Today's briefing - {date.today():%B %d, %Y}")
        ui.ai_box(ui.strip_title(briefing["briefing"]),
                  f"Written in Databricks by AI Functions (ai_query, {briefing.get('model_endpoint')}), "
                  f"{str(briefing.get('generated_at'))[:16]} UTC", key="briefing")
    elif not ai.get("available"):
        st.info(ai.get("reason", "Run the lsi-pipeline workflow to generate AI outputs."))
    st.write("")

    c1, c2, c3 = st.columns([3, 2, 1.4], vertical_alignment="bottom")
    search = c1.text_input("Search", placeholder="Loan ID, synthetic borrower, state, or county",
                           label_visibility="collapsed")
    priority = c2.multiselect("Priority", PRIORITIES, placeholder="All priorities", label_visibility="collapsed",
                              format_func=ui.nice)
    only_ai = c3.toggle("Only loans with AI", value=True)

    rows = loans
    if search:
        s = search.lower()
        rows = [r for r in rows if s in f"{r['loan_id']} {r['borrower_display_name']} {r['property_state']} "
                                         f"{r['property_county']}".lower()]
    if priority:
        rows = [r for r in rows if r["priority"] in priority]
    if only_ai and (insights or reviews):
        rows = [r for r in rows if r["loan_id"] in insights or r["loan_id"] in reviews]
    rows.sort(key=lambda r: (-int(r["attention_score"] or 0), r["loan_id"]))
    st.caption(f"{len(rows):,} of {len(loans):,} active synthetic loans, highest attention first. "
               "Click a loan ID to open it.")
    ui.loan_list(rows, ai, key="portfolio", columns=["loan", "priority", "condition", "score", "ai", "agent"])
