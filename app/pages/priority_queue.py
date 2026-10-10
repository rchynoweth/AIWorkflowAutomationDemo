"""Priority Queue: ranked attention loans; rows open Loan 360."""
from __future__ import annotations

import streamlit as st

from app.components import priority_table
from app.components.talk_track import active_chapter_banner, notes
from app.state import ApiError, get_client, reviewer

CONDITIONS = ["VERIFICATION_FAILURE", "DATA_EXCEPTION", "ALREADY_ACTIONED", "DUPLICATE_RISK", "OVERDUE",
              "MISSING_FOLLOWUP", "DUE", "COMPLETED_NEEDS_NEXT", "PENDING_REVIEW", "PENDING_ACTION", "UPCOMING",
              "COMPLETED", "NO_ACTION"]
REVIEW_STATES = ["NOT_ANALYZED", "AWAITING_APPROVAL", "APPROVED", "SUBMITTED", "REJECTED", "DEFERRED", "ESCALATED",
                 "VERIFIED", "VERIFICATION_FAILED", "AGENT_FAILED"]


def render() -> None:
    active_chapter_banner("priority_queue")
    st.markdown("## Priority queue")
    notes("priority_queue")
    client = get_client()
    c1, c2, c3 = st.columns(3)
    priority = c1.multiselect("Priority", ["CRITICAL", "HIGH", "MEDIUM", "LOW"], key="pq_priority",
                              placeholder="All priorities")
    condition = c2.multiselect("Condition", CONDITIONS, key="pq_condition", placeholder="All conditions",
                               format_func=lambda c: c.replace("_", " ").title())
    review = c3.multiselect("Status", REVIEW_STATES, key="pq_review", placeholder="All statuses",
                            format_func=lambda c: priority_table.STATUS_LABEL.get(c, c))
    rows = client.queue(priority=",".join(priority) or None, condition=",".join(condition) or None,
                        review_status=",".join(review) or None, limit=2000)
    st.caption(f"{len(rows):,} loans need attention, ranked by priority and score · click a row to open it")
    priority_table.render(rows, key="queue_table", height=600)

    with st.expander("Bulk agent analysis"):
        n = st.number_input("Analyze the top N loans with the agent", min_value=1, max_value=20, value=3, step=1)
        if st.button(f"Analyze top {n}", icon=":material/auto_awesome:"):
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
