"""Agent proposal panel: recommendation, drafts, uncertainty; details in expanders."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.components.styles import badge, esc


def nice(code: str | None) -> str:
    return (code or "").replace("_", " ").title()


def render(rec: dict | None, state: dict) -> None:
    if not rec:
        st.info("No agent proposal yet. Click **Run agent analysis** to let the agent investigate this loan.")
        return
    mode = "LLM agent" if rec.get("agent_mode") == "llm" else "Deterministic agent"
    status_color = {"PENDING_REVIEW": "#6941C6", "APPROVED": "#067647", "REJECTED": "#B42318"}.get(rec["status"])
    follow = (f" · follow-up <b>{esc(rec.get('recommended_followup_date'))}</b>"
              if rec.get("recommended_followup_date") else "")
    st.markdown(
        f'<div class="lsi-ai">✨ <b>Agent proposal</b> <span style="color:#667085">({mode})</span> '
        f'{badge(nice(rec["status"]), status_color)}'
        f'<div style="font-size:1.25rem; margin:6px 0"><b>{esc(nice(rec["recommended_action"]))}</b>{follow} '
        f'&nbsp; {badge("Confidence " + rec["confidence"].title(), "#344054")}</div>'
        f'{esc(rec.get("rationale"))}</div>', unsafe_allow_html=True)

    left, right = st.columns(2)
    with left:
        st.markdown("**Draft servicing note**")
        st.caption(rec.get("suggested_note") or "—")
    with right:
        if rec.get("suggested_outreach"):
            st.markdown("**Draft outreach**")
            st.caption(rec["suggested_outreach"])
    st.markdown(f'<div class="lsi-why"><b>Uncertainty:</b> {esc(rec.get("uncertainty") or "—")}'
                f'<br><b>Missing information:</b> {esc(", ".join(rec.get("missing_information") or []) or "none")}'
                f'</div>', unsafe_allow_html=True)
    validation = rec.get("validation") or {}
    if validation and not validation.get("valid"):
        st.error("Validation: " + "; ".join(f"{e['code']}: {e['message']}" for e in validation.get("errors", [])))

    e1, e2, e3 = st.columns(3)
    with e1.popover(f"Evidence ({len(rec.get('evidence') or [])})", use_container_width=True):
        ev = pd.DataFrame(rec.get("evidence") or [])
        if not ev.empty:
            st.dataframe(ev[["source_type", "source_identifier", "description", "value"]], hide_index=True)
    with e2.popover(f"Tool calls ({len(rec.get('tool_calls') or [])})", use_container_width=True):
        tc = pd.DataFrame(rec.get("tool_calls") or [])
        if not tc.empty:
            st.dataframe(tc[[c for c in ("tool_name", "origin", "success", "duration_ms") if c in tc.columns]],
                         hide_index=True)
    with e3.popover("Allowed actions", use_container_width=True):
        st.write(", ".join(nice(a) for a in state["allowed_actions"]))
        st.caption("The agent can only choose from this list (RULE-ACTIONS-001).")
