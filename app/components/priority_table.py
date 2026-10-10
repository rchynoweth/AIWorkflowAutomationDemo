"""Priority/task tables with row selection that opens Loan 360."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.state import open_loan

PRIORITY_ICON = {"CRITICAL": "🔴 CRITICAL", "HIGH": "🟠 HIGH", "MEDIUM": "🟡 MEDIUM", "LOW": "⚪ LOW"}


def queue_frame(rows: list[dict], compact: bool = False) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["priority"] = df["priority"].map(PRIORITY_ICON)
    df["recommendation"] = df["recommended_action"].fillna("")
    cols = {
        "priority": "Priority", "loan_id": "Loan", "borrower_display_name": "Borrower (synthetic)",
        "primary_condition": "Condition", "severity": "Severity", "current_milestone": "Milestone",
        "effective_followup_date": "Follow-up", "days_overdue": "Days Overdue", "attention_score": "Score",
        "top_drivers_text": "Drivers", "recommendation": "Recommendation", "confidence": "Confidence",
        "specialist_name": "Specialist", "review_status": "Status", "why_prioritized": "Why prioritized",
    }
    if compact:
        keep = ["priority", "loan_id", "borrower_display_name", "primary_condition", "attention_score",
                "top_drivers_text", "recommendation", "specialist_name", "review_status", "why_prioritized"]
    else:
        keep = list(cols)
    return df[keep].rename(columns=cols)


def render(rows: list[dict], key: str, compact: bool = False, height: int | None = None) -> None:
    df = queue_frame(rows, compact)
    if df.empty:
        st.info("No loans match the current filters.")
        return
    event = st.dataframe(
        df, key=key, hide_index=True, use_container_width=True, on_select="rerun", selection_mode="single-row",
        height=height or min(600, 38 + 35 * len(df)),
        column_config={"Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
                       "Why prioritized": st.column_config.TextColumn(width="large"),
                       "Drivers": st.column_config.TextColumn(width="medium")},
    )
    selected = event.selection.rows if event and event.selection else []
    if selected:
        open_loan(df.iloc[selected[0]]["Loan"])
