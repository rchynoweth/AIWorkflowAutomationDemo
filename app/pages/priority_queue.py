"""Priority Queue: ranked attention loans; clicking a loan ID opens Loan 360."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.components import priority_table
from app.components.priority_table import STATUS_LABEL, nice
from app.components.talk_track import active_chapter_banner, notes
from app.state import ApiError, get_client, reviewer

CONDITIONS = ["VERIFICATION_FAILURE", "DATA_EXCEPTION", "ALREADY_ACTIONED", "DUPLICATE_RISK", "OVERDUE",
              "MISSING_FOLLOWUP", "DUE", "COMPLETED_NEEDS_NEXT", "PENDING_REVIEW", "PENDING_ACTION", "UPCOMING",
              "COMPLETED", "NO_ACTION"]


def _batch(client, rows: list[dict]) -> None:
    with st.container(border=True):
        left, mid, right = st.columns([3, 1, 1], vertical_alignment="bottom")
        left.markdown("**Agent triage** - let the AI agent investigate the top loans that only have a rules "
                      "baseline. Runs in parallel; proposals still wait for your approval.")
        n = mid.number_input("Loans", min_value=1, max_value=12, value=3, step=1, key="pq_batch_n")
        if right.button("Analyze with agent", icon=":material/auto_awesome:", type="primary",
                        use_container_width=True):
            targets = [r["loan_id"] for r in rows if r.get("recommendation_source") != "llm"][: int(n)]
            if not targets:
                st.session_state["pq_batch_result"] = {"results": [], "seconds": 0}
            else:
                rid, _ = reviewer()
                with st.spinner(f"Agent investigating {len(targets)} loans with its tools..."):
                    try:
                        st.session_state["pq_batch_result"] = client.batch(loan_ids=targets, user_id=rid)
                    except ApiError as exc:
                        st.session_state["pq_batch_result"] = {"error": str(exc.detail), "results": []}
            st.rerun()
        result = st.session_state.get("pq_batch_result")
        if result:
            if result.get("error"):
                st.error(f"Agent triage failed: {result['error']}")
            elif not result["results"]:
                st.info("Every loan shown already has an AI agent proposal.")
            else:
                st.success(f"Agent analyzed {len(result['results'])} loans in {result['seconds']} s. "
                           "Proposals are waiting for review - click a loan ID to decide.")
                df = pd.DataFrame(result["results"])
                df["condition"] = df["condition"].map(nice)
                df["recommended_action"] = df["recommended_action"].map(nice)
                st.dataframe(df[["loan_id", "priority", "condition", "recommended_action", "confidence"]].rename(
                    columns={"loan_id": "Loan", "priority": "Priority", "condition": "Condition",
                             "recommended_action": "Agent proposes", "confidence": "Confidence"}),
                    hide_index=True, use_container_width=True)


def render() -> None:
    active_chapter_banner("priority_queue")
    st.markdown("## Priority queue")
    notes("priority_queue")
    client = get_client()
    c1, c2, c3 = st.columns(3)
    priority = c1.multiselect("Priority", ["CRITICAL", "HIGH", "MEDIUM", "LOW"], key="pq_priority",
                              placeholder="All priorities", format_func=nice)
    condition = c2.multiselect("Condition", CONDITIONS, key="pq_condition", placeholder="All conditions",
                               format_func=nice)
    review = c3.multiselect("Status", list(STATUS_LABEL), key="pq_review", placeholder="All statuses",
                            format_func=lambda c: STATUS_LABEL.get(c, c))
    rows = client.queue(priority=",".join(priority) or None, condition=",".join(condition) or None,
                        review_status=",".join(review) or None, limit=2000)
    _batch(client, rows)
    st.caption(f"{len(rows):,} loans need attention, ranked by priority and score - click a loan ID to open it")
    priority_table.render(rows, key="queue_list", page_size=15)
