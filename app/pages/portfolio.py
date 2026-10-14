"""Portfolio: every active loan, with the AI that Databricks created for it."""
from datetime import date

import streamlit as st

from app import data, ui

st.markdown("## Portfolio")
ui.notes("portfolio")

loans = data.loans()
ai = data.backend_ai()

cols = st.columns(4)
cols[0].markdown(ui.card("Active loans", f"{len(loans):,}"), unsafe_allow_html=True)
cols[1].markdown(ui.card("Need attention", f"{sum(r['priority'] in ('CRITICAL', 'HIGH') for r in loans):,}", "#B54708"),
                 unsafe_allow_html=True)
cols[2].markdown(ui.card("AI summaries", f"{len(ai['insights']):,}", "#6941C6"), unsafe_allow_html=True)
cols[3].markdown(ui.card("Next steps drafted by the agent", f"{len(ai['reviews']):,}", "#6941C6"),
                 unsafe_allow_html=True)
st.write("")

if ai["briefing"]:
    st.markdown(f"#### Today's briefing - {date.today():%B %d, %Y}")
    ui.ai_box(ai["briefing"]["briefing"], f"Written in Databricks by AI Functions (ai_query, "
              f"{ai['briefing']['model_endpoint']}), {str(ai['briefing']['generated_at'])[:16]} UTC", key="briefing")
else:
    st.info("Run the lsi-pipeline workflow to generate the AI outputs.")
st.write("")

c1, c2, c3 = st.columns([3, 2, 1.4], vertical_alignment="bottom")
search = c1.text_input("Search", placeholder="Loan ID, synthetic borrower, state, or county",
                       label_visibility="collapsed")
priorities = c2.multiselect("Priority", ["CRITICAL", "HIGH", "MEDIUM", "LOW"], placeholder="All priorities",
                            label_visibility="collapsed", format_func=ui.nice)
only_ai = c3.toggle("Only loans with AI", value=True)

rows = loans
if search:
    rows = [r for r in rows if search.lower() in f"{r['loan_id']} {r['borrower_display_name']} {r['property_state']} "
                                                 f"{r['property_county']}".lower()]
if priorities:
    rows = [r for r in rows if r["priority"] in priorities]
if only_ai and (ai["insights"] or ai["reviews"]):
    rows = [r for r in rows if r["loan_id"] in ai["insights"] or r["loan_id"] in ai["reviews"]]
st.caption(f"{len(rows):,} of {len(loans):,} active synthetic loans, highest attention first. Click a loan ID to open it.")
ui.loan_list(rows, ai)
