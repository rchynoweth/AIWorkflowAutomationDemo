"""Priority/task tables with row selection that opens Loan 360."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.state import open_loan

PRIORITY_ICON = {"CRITICAL": "🔴 Critical", "HIGH": "🟠 High", "MEDIUM": "🟡 Medium", "LOW": "⚪ Low"}
STATUS_LABEL = {"NOT_ANALYZED": "—", "AWAITING_APPROVAL": "Awaiting approval", "APPROVED": "Approved",
                "SUBMITTED": "Submitted", "REJECTED": "Rejected", "DEFERRED": "Deferred", "ESCALATED": "Escalated",
                "VERIFIED": "Verified", "VERIFICATION_FAILED": "Failed verification", "AGENT_FAILED": "Agent failed"}

COLUMNS = {
    "priority": "Priority", "loan_id": "Loan", "borrower_display_name": "Borrower", "condition": "Condition",
    "attention_score": "Score", "why": "Why it's here", "recommendation": "Agent suggests", "status": "Status",
    "specialist_name": "Specialist", "current_milestone": "Milestone", "days_overdue": "Days overdue",
}
COMPACT = ["priority", "loan_id", "condition", "attention_score", "why"]
STANDARD = ["priority", "loan_id", "borrower_display_name", "condition", "attention_score", "why", "recommendation",
            "status"]


def queue_frame(rows: list[dict], columns: list[str]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["priority"] = df["priority"].map(PRIORITY_ICON)
    df["condition"] = df["primary_condition"].str.replace("_", " ").str.title()
    df["why"] = df["top_drivers_text"]
    df["recommendation"] = df["recommended_action"].fillna("").str.replace("_", " ").str.title()
    df["status"] = df["review_status"].map(STATUS_LABEL).fillna(df["review_status"])
    return df[columns].rename(columns=COLUMNS)


def render(rows: list[dict], key: str, compact: bool = False, height: int | None = None,
           columns: list[str] | None = None) -> None:
    df = queue_frame(rows, columns or (COMPACT if compact else STANDARD))
    if df.empty:
        st.info("No loans match the current filters.")
        return
    event = st.dataframe(
        df, key=key, hide_index=True, use_container_width=True, on_select="rerun", selection_mode="single-row",
        height=height or min(600, 38 + 35 * len(df)),
        column_config={"Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
                       "Why it's here": st.column_config.TextColumn(width="large")},
    )
    selected = event.selection.rows if event and event.selection else []
    if selected:
        open_loan(df.iloc[selected[0]]["Loan"])
