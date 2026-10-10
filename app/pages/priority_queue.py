"""Priority Queue: ranked attention loans with filters; rows link to Loan 360."""
from __future__ import annotations

import streamlit as st

from app.components import priority_table
from app.state import ApiError, get_client, reviewer

CONDITIONS = ["VERIFICATION_FAILURE", "DATA_EXCEPTION", "ALREADY_ACTIONED", "DUPLICATE_RISK", "OVERDUE",
              "MISSING_FOLLOWUP", "DUE", "COMPLETED_NEEDS_NEXT", "PENDING_REVIEW", "PENDING_ACTION", "UPCOMING",
              "COMPLETED", "NO_ACTION"]
REVIEW_STATES = ["NOT_ANALYZED", "AWAITING_APPROVAL", "APPROVED", "SUBMITTED", "REJECTED", "DEFERRED", "ESCALATED",
                 "VERIFIED", "VERIFICATION_FAILED", "AGENT_FAILED"]


def render() -> None:
    st.markdown("### Priority Queue")
    st.caption("Loans with escalation FOLLOW_UP, ESCALATE, or CRITICAL, ranked by deterministic priority and "
               "attention score. Every row explains why it is prioritized.")
    client = get_client()
    c1, c2, c3, c4 = st.columns(4)
    priority = c1.multiselect("Priority", ["CRITICAL", "HIGH", "MEDIUM", "LOW"], key="pq_priority")
    condition = c2.multiselect("Condition", CONDITIONS, key="pq_condition")
    review = c3.multiselect("Review state", REVIEW_STATES, key="pq_review")
    rows_all = client.queue(limit=2000)
    specialists = sorted({r["specialist_name"] for r in rows_all if r["specialist_name"]})
    specialist = c4.multiselect("Specialist", specialists, key="pq_specialist")
    rows = client.queue(priority=",".join(priority) or None, condition=",".join(condition) or None,
                        review_status=",".join(review) or None, specialist=",".join(specialist) or None, limit=2000)
    left, right = st.columns([4, 1])
    left.caption(f"{len(rows):,} of {len(rows_all):,} attention loans")
    n = right.number_input("Analyze top N with agent", min_value=1, max_value=20, value=3, step=1,
                           label_visibility="collapsed")
    if right.button(f"Analyze top {n} with agent", icon=":material/auto_awesome:", use_container_width=True):
        rid, _ = reviewer()
        progress = st.progress(0.0)
        for i, row in enumerate(rows[: int(n)]):
            try:
                client.agent("assess", loan_id=row["loan_id"], user_id=rid)
            except ApiError as exc:
                st.warning(f"{row['loan_id']}: {exc.detail}")
            progress.progress((i + 1) / int(n))
        st.session_state["flash"] = f"Agent analyzed {min(int(n), len(rows))} loans"
        st.rerun()
    priority_table.render(rows, key="queue_table", height=640)
