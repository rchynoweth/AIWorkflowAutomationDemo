"""Loan lists where clicking the loan ID opens Loan 360."""
from __future__ import annotations

import math

import streamlit as st

from app.components.styles import HEALTH_COLORS, PRIORITY_COLORS, esc
from app.state import open_loan

STATUS_LABEL = {"NOT_ANALYZED": "Not analyzed", "AWAITING_APPROVAL": "Awaiting approval", "APPROVED": "Approved",
                "SUBMITTED": "Submitted", "REJECTED": "Rejected", "DEFERRED": "Deferred", "ESCALATED": "Escalated",
                "VERIFIED": "Verified", "VERIFICATION_FAILED": "Failed verification", "AGENT_FAILED": "Agent failed"}


def nice(code) -> str:
    return str(code or "").replace("_", " ").title()


def _cell(row: dict, col: str) -> str:
    if col == "priority":
        color = PRIORITY_COLORS.get(row["priority"], "#475467")
        return f'<span style="color:{color}; font-weight:700">{nice(row["priority"])}</span>'
    if col == "condition":
        return esc(nice(row["primary_condition"]))
    if col == "score":
        return f'<b>{row["attention_score"]}</b>'
    if col == "why":
        return f'<span class="lsi-why">{esc(row.get("top_drivers_text"))}</span>'
    if col == "suggests":
        source = "AI agent" if row.get("recommendation_source") == "llm" else "Rules baseline"
        action = nice(row.get("recommended_action"))
        return f'{esc(action)}<br><span class="lsi-why">{source}</span>' if action else "-"
    if col == "status":
        return esc(STATUS_LABEL.get(row.get("review_status"), nice(row.get("review_status"))))
    if col == "borrower":
        return esc(row.get("borrower_display_name"))
    if col == "state":
        return esc(row.get("property_state"))
    if col == "balance":
        return f"${float(row.get('current_balance') or 0):,.0f}"
    if col == "milestone":
        return esc(nice(row.get("current_milestone")) or "-")
    if col == "followup":
        return esc(row.get("effective_followup_date") or "-")
    if col == "health":
        color = HEALTH_COLORS.get(row.get("health_segment"), "#475467")
        return f'<span style="color:{color}">{esc(row.get("health_segment"))}</span>'
    if col == "agent_status":
        return esc(STATUS_LABEL.get(row.get("agent_status"), nice(row.get("agent_status"))))
    return esc(row.get(col))


HEADERS = {"priority": "Priority", "loan": "Loan", "borrower": "Borrower", "condition": "Condition", "score": "Score",
           "why": "Why it's here", "suggests": "Agent suggests", "status": "Status",
           "state": "State", "balance": "Balance", "milestone": "Milestone", "followup": "Next follow-up",
           "health": "Health", "agent_status": "Agent status"}
WIDTHS = {"priority": 1.0, "loan": 1.4, "borrower": 1.6, "condition": 1.5, "score": 0.7, "why": 3.6,
          "suggests": 1.8, "status": 1.3, "state": 0.6, "balance": 1.1,
          "milestone": 1.7, "followup": 1.2, "health": 1.3, "agent_status": 1.4}
COMPACT = ["priority", "loan", "condition", "score", "why", "suggests"]
STANDARD = ["priority", "loan", "borrower", "condition", "score", "why", "suggests", "status"]
PORTFOLIO = ["loan", "borrower", "state", "balance", "milestone", "followup", "health", "score", "priority",
             "agent_status"]


def render(rows: list[dict], key: str, compact: bool = False, page_size: int = 12,
           columns: list[str] | None = None) -> None:
    if not rows:
        st.info("No loans match the current filters.")
        return
    columns = columns or (COMPACT if compact else STANDARD)
    pages = max(1, math.ceil(len(rows) / page_size))
    page = st.session_state.get(f"{key}_page", 1)
    page = min(max(page, 1), pages)
    widths = [WIDTHS[c] for c in columns]
    header = st.columns(widths)
    for col, name in zip(header, columns):
        col.markdown(f"<span style='color:#667085; font-size:0.8rem; font-weight:600'>{HEADERS[name]}</span>",
                     unsafe_allow_html=True)
    for i, row in enumerate(rows[(page - 1) * page_size: page * page_size]):
        cells = st.columns(widths, vertical_alignment="center")
        for col, name in zip(cells, columns):
            if name == "loan":
                if col.button(row["loan_id"], key=f"{key}_{row['loan_id']}_{i}", type="tertiary",
                              help="Open in Loan 360"):
                    open_loan(row["loan_id"])
            else:
                col.markdown(_cell(row, name), unsafe_allow_html=True)
    if pages > 1:
        left, mid, right = st.columns([1, 2, 1])
        if left.button("Previous", key=f"{key}_prev", disabled=page <= 1, icon=":material/chevron_left:"):
            st.session_state[f"{key}_page"] = page - 1
            st.rerun()
        mid.markdown(f"<div style='text-align:center; color:#667085'>Page {page} of {pages}</div>",
                     unsafe_allow_html=True)
        if right.button("Next", key=f"{key}_next", disabled=page >= pages, icon=":material/chevron_right:"):
            st.session_state[f"{key}_page"] = page + 1
            st.rerun()
