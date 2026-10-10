"""Portfolio: every synthetic loan; selecting a row opens Loan 360."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.components.priority_table import PRIORITY_ICON
from app.components.talk_track import active_chapter_banner, notes
from app.state import get_client, open_loan

FILTERS = [
    ("state", "property_state", "State"), ("portfolio", "portfolio_id", "Portfolio"),
    ("loan_status", "loan_status", "Loan status"), ("payment_status", "payment_status", "Payment status"),
    ("foreclosure_status", "foreclosure_status", "Foreclosure status"), ("milestone", "current_milestone", "Milestone"),
    ("health", "health_segment", "Health"), ("priority", "priority", "Priority"),
    ("specialist", "specialist_name", "Specialist"), ("agent_status", "agent_status", "Agent status"),
]
ALL_COLUMNS = {
    "loan_id": "Loan", "borrower_display_name": "Borrower", "property_state": "State", "portfolio_id": "Portfolio",
    "current_balance": "Balance", "payment_status": "Payment status", "days_delinquent": "Days delinquent",
    "loan_status": "Loan status", "foreclosure_status": "Foreclosure status", "current_milestone": "Milestone",
    "effective_followup_date": "Next follow-up", "health_segment": "Health", "attention_score": "Score",
    "priority": "Priority", "specialist_name": "Specialist", "agent_status": "Agent status",
}
SIMPLE = ["loan_id", "borrower_display_name", "property_state", "current_balance", "current_milestone",
          "effective_followup_date", "health_segment", "attention_score", "priority"]


def render() -> None:
    active_chapter_banner("portfolio")
    st.markdown("## Portfolio")
    notes("portfolio")
    client = get_client()
    all_rows = client.loans()
    df_all = pd.DataFrame(all_rows)
    c1, c2 = st.columns([4, 1])
    search = c1.text_input("Search", key="pf_search", label_visibility="collapsed",
                           placeholder="Search loan ID, synthetic borrower, state, or county")
    show_all = c2.toggle("All columns", key="pf_all_cols")
    filters = {}
    with st.expander("Filters"):
        cols = st.columns(5)
        for i, (param, col, label) in enumerate(FILTERS):
            options = sorted(o for o in df_all[col].dropna().astype(str).unique() if o and o != "None")
            filters[param] = cols[i % 5].multiselect(label, options, key=f"pf_{param}")
    params = {k: ",".join(v) for k, v in filters.items() if v}
    df = pd.DataFrame(client.loans(search=search or None, **params))
    st.caption(f"{len(df):,} of {len(df_all):,} synthetic loans · click a row to open it")
    if df.empty:
        st.info("No loans match.")
        return
    df["priority"] = df["priority"].map(PRIORITY_ICON)
    keys = list(ALL_COLUMNS) if show_all else SIMPLE
    view = df[keys].rename(columns=ALL_COLUMNS)
    event = st.dataframe(
        view, hide_index=True, use_container_width=True, height=600, on_select="rerun", selection_mode="single-row",
        key="portfolio_table",
        column_config={"Balance": st.column_config.NumberColumn(format="$%.0f"),
                       "Score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d")})
    if event and event.selection and event.selection.rows:
        open_loan(view.iloc[event.selection.rows[0]]["Loan"])
