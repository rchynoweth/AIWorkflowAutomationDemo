"""Portfolio: filterable table of every synthetic loan; selecting a row opens Loan 360."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.components.priority_table import PRIORITY_ICON
from app.state import get_client, open_loan

FILTERS = [
    ("state", "property_state", "State"), ("portfolio", "portfolio_id", "Portfolio"),
    ("loan_status", "loan_status", "Loan Status"), ("payment_status", "payment_status", "Payment Status"),
    ("foreclosure_status", "foreclosure_status", "Foreclosure Status"), ("milestone", "current_milestone", "Milestone"),
    ("health", "health_segment", "Health"), ("priority", "priority", "Priority"),
    ("specialist", "specialist_name", "Specialist"), ("agent_status", "agent_status", "Agent Status"),
]
COLUMNS = {
    "loan_id": "Loan", "borrower_display_name": "Borrower (synthetic)", "property_state": "State",
    "portfolio_id": "Portfolio", "current_balance": "Current Balance", "payment_status": "Payment Status",
    "days_delinquent": "Days Delinquent", "loan_status": "Loan Status", "foreclosure_status": "Foreclosure Status",
    "current_milestone": "Current Milestone", "effective_followup_date": "Next Follow-Up",
    "health_segment": "Milestone Health", "attention_score": "Attention Score", "priority": "Priority",
    "specialist_name": "Assigned Specialist", "agent_status": "Agent Status",
}


def render() -> None:
    st.markdown("### Portfolio")
    client = get_client()
    all_rows = client.loans()
    df_all = pd.DataFrame(all_rows)
    preset = st.session_state.pop("portfolio_health_preset", None)

    search = st.text_input("Search loan ID, synthetic borrower, state, or county", key="pf_search",
                           placeholder="e.g. LSI-SYN-000005, Synthetic Borrower 0042, TX, Synthetic County 07")
    filters = {}
    cols = st.columns(5)
    for i, (param, col, label) in enumerate(FILTERS):
        options = sorted(o for o in df_all[col].dropna().astype(str).unique() if o and o != "None")
        default = [preset] if (preset and param == "health") else []
        filters[param] = cols[i % 5].multiselect(label, options, default=default, key=f"pf_{param}")

    params = {k: ",".join(v) for k, v in filters.items() if v}
    rows = client.loans(search=search or None, **params)
    df = pd.DataFrame(rows)
    st.caption(f"{len(df):,} of {len(df_all):,} synthetic loans")
    if df.empty:
        st.info("No loans match the filters.")
        return
    df["priority"] = df["priority"].map(PRIORITY_ICON)
    view = df[list(COLUMNS)].rename(columns=COLUMNS)
    event = st.dataframe(
        view, hide_index=True, use_container_width=True, height=620, on_select="rerun", selection_mode="single-row",
        key="portfolio_table",
        column_config={
            "Current Balance": st.column_config.NumberColumn(format="$%.0f"),
            "Attention Score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d"),
        })
    if event and event.selection and event.selection.rows:
        open_loan(view.iloc[event.selection.rows[0]]["Loan"])
