"""Agent assessment panel: deterministic facts, agent recommendation, evidence, uncertainty."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.components.styles import badge, esc


def render(rec: dict | None, state: dict) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f"**Condition**<br>{badge(state['primary_condition'], '#175CD3')}", unsafe_allow_html=True)
    c2.markdown(f"**Priority**<br>{badge(state['priority'])} &nbsp; score **{state['attention_score']}**",
                unsafe_allow_html=True)
    c3.markdown(f"**Escalation**<br>{badge(state['escalation_state'], '#344054')} → {esc(state['required_role'])}",
                unsafe_allow_html=True)
    c4.markdown(f"**Secondary**<br>{' '.join(badge(c, '#667085') for c in state['secondary_conditions']) or '—'}",
                unsafe_allow_html=True)

    reasons = "".join(f"<li><code>{esc(c['rule_id'])}</code> {esc(c['detail'])}</li>" for c in state["raw_conditions"])
    st.markdown(f'<div class="lsi-rule"><b>Rule facts (deterministic)</b><ul style="margin-bottom:0">{reasons}</ul>'
                f'<span style="font-size:0.85rem">Allowed actions: <b>{esc(", ".join(state["allowed_actions"]))}</b>'
                f'</span></div>', unsafe_allow_html=True)
    if not rec:
        st.info("No agent recommendation yet. Run the agent analysis to investigate this loan.")
        return

    mode = rec.get("agent_mode", "deterministic")
    status_color = {"PENDING_REVIEW": "#6941C6", "APPROVED": "#067647", "REJECTED": "#B42318"}.get(rec["status"])
    st.markdown(
        f'<div class="lsi-ai">✨ <b>Agent recommendation</b> ({esc(mode)}, {esc(rec.get("agent_version"))}) '
        f'{badge(rec["status"], status_color)}<br>'
        f'<span style="font-size:1.15rem"><b>{esc(rec["recommended_action"])}</b></span>'
        + (f' → {esc(rec.get("recommended_event_type"))} follow-up <b>{esc(rec.get("recommended_followup_date"))}</b>'
           if rec.get("recommended_event_type") else "")
        + f' &nbsp; confidence {badge(rec["confidence"], "#344054")}<br>'
        f'<div style="margin-top:6px">{esc(rec.get("rationale"))}</div></div>', unsafe_allow_html=True)

    left, right = st.columns(2)
    with left:
        st.markdown("**Suggested note**")
        st.write(rec.get("suggested_note") or "—")
        if rec.get("suggested_outreach"):
            st.markdown("**Suggested outreach (draft)**")
            st.write(rec["suggested_outreach"])
    with right:
        st.markdown("**Uncertainty**")
        st.write(rec.get("uncertainty") or "—")
        st.markdown("**Missing information**")
        st.write(", ".join(rec.get("missing_information") or []) or "None identified")
        validation = rec.get("validation") or {}
        if validation:
            if validation.get("valid"):
                st.success("Proposed event passes validation (RULE-VALIDATION-001).", icon=":material/verified:")
            else:
                st.error("Validation: " + "; ".join(f"{e['code']}: {e['message']}" for e in validation.get("errors", [])))

    with st.expander(f"Evidence ({len(rec.get('evidence') or [])})", expanded=True):
        ev = pd.DataFrame(rec.get("evidence") or [])
        if not ev.empty:
            st.dataframe(ev[["source_type", "source_identifier", "description", "value"]], hide_index=True,
                         use_container_width=True)
    with st.expander(f"Tool calls ({len(rec.get('tool_calls') or [])})"):
        tc = pd.DataFrame(rec.get("tool_calls") or [])
        if not tc.empty:
            st.dataframe(tc[[c for c in ("tool_name", "origin", "success", "duration_ms", "input_summary",
                                         "output_summary") if c in tc.columns]], hide_index=True,
                         use_container_width=True)
    if rec.get("proposed_event", {}).get("creates_event"):
        with st.expander("Proposed outbound event (uncommitted draft)"):
            st.json(rec["proposed_event"])
