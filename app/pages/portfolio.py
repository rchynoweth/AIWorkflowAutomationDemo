"""Portfolio: every synthetic loan; clicking a loan ID opens Loan 360."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app import ui
from app.ui import active_chapter_banner, notes
from app.client import get_client

FILTERS = [
    ("health", "health_segment", "Health"), ("priority", "priority", "Priority"),
    ("milestone", "current_milestone", "Milestone"), ("state", "property_state", "State"),
    ("portfolio", "portfolio_id", "Portfolio"), ("payment_status", "payment_status", "Payment status"),
    ("foreclosure_status", "foreclosure_status", "Foreclosure status"), ("loan_status", "loan_status", "Loan status"),
    ("specialist", "specialist_name", "Specialist"), ("agent_status", "agent_status", "Agent status"),
]


def render() -> None:
    active_chapter_banner("portfolio")
    st.markdown("## Portfolio")
    notes("portfolio")
    client = get_client()
    df_all = pd.DataFrame(client.loans())
    search = st.text_input("Search", key="pf_search", label_visibility="collapsed",
                           placeholder="Search loan ID, synthetic borrower, state, or county")
    filters = {}
    with st.expander("Filters"):
        cols = st.columns(5)
        for i, (param, col, label) in enumerate(FILTERS):
            options = sorted(o for o in df_all[col].dropna().astype(str).unique() if o and o != "None")
            filters[param] = cols[i % 5].multiselect(label, options, key=f"pf_{param}")
    params = {k: ",".join(v) for k, v in filters.items() if v}
    rows = client.loans(search=search or None, **params)
    rows.sort(key=lambda r: (-int(r["attention_score"] or 0), r["loan_id"]))
    st.caption(f"{len(rows):,} of {len(df_all):,} synthetic loans, highest attention first - click a loan ID to "
               "open it")
    ui.loan_list(rows, key="portfolio_list", page_size=15, columns=ui.PORTFOLIO)
    with st.expander("Download view"):
        st.download_button("Download CSV (synthetic)", pd.DataFrame(rows).to_csv(index=False),
                           file_name="synthetic_portfolio.csv", mime="text/csv")
