"""Agent activity trace: step chain and tool-call table (summaries only; no prompts or reasoning)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

FLOW = [
    ("candidate_detected", "Candidate detected", ("candidate_detected",)),
    ("context", "Context retrieved", ("get_loan_context",)),
    ("milestone", "Milestone checked", ("get_current_milestone", "check_milestone_completion")),
    ("events", "Events retrieved", ("get_event_history", "check_followup_status")),
    ("duplicates", "Duplicates checked", ("check_existing_event",)),
    ("rule", "Rule retrieved", ("get_milestone_rule", "get_allowed_actions")),
    ("pending", "Pending action checked", ("check_pending_action",)),
    ("score", "Score calculated", ("calculate_loan_attention_score",)),
    ("allowed", "Allowed actions retrieved", ("get_allowed_actions", "calculate_escalation_state")),
    ("recommendation", "Recommendation generated", ("recommendation_generated",)),
    ("approval", "Awaiting approval", ("awaiting_approval",)),
]


def render_flow(records: list[dict]) -> None:
    seen = {r.get("tool_name") or r.get("step") for r in records}
    parts = []
    for _, label, keys in FLOW:
        done = any(k in seen for k in keys)
        parts.append(f'<span class="lsi-step {"done" if done else "miss"}">{"✓ " if done else ""}{label}</span>')
    st.markdown('<div class="lsi-flow">' + " → ".join(parts) + "</div>", unsafe_allow_html=True)


def render_table(records: list[dict], height: int = 400) -> None:
    if not records:
        st.info("No activity recorded yet.")
        return
    df = pd.DataFrame(records)
    cols = {"created_at": "Timestamp", "run_id": "Run", "loan_id": "Loan", "actor": "Actor", "step": "Step",
            "tool_name": "Tool", "input_summary": "Input (summary)", "output_summary": "Output (summary)",
            "duration_ms": "ms", "success": "OK"}
    df = df[[c for c in cols if c in df.columns]].rename(columns=cols)
    st.dataframe(df, hide_index=True, use_container_width=True, height=height)
