"""Proposed event panel: confirm and schedule an agent-proposed event, with light edits (human in the loop)."""
from __future__ import annotations

from datetime import date

import streamlit as st

from app.components.styles import badge, esc
from app.state import ApiError, get_client, reviewer


def nice(code: str | None) -> str:
    return (code or "").replace("_", " ").title()


def _confirm(rec: dict, followup: date | None, note: str, outreach: str, send_now: bool) -> None:
    client = get_client()
    rid, role = reviewer()
    original_fu = rec.get("recommended_followup_date")
    new_fu = followup.isoformat() if followup else None
    edited = (new_fu != original_fu or note.strip() != (rec.get("suggested_note") or "").strip()
              or outreach.strip() != (rec.get("suggested_outreach") or "").strip())
    body = {"decision": "EDIT" if edited else "APPROVE", "reviewer_id": rid, "reviewer_role": role,
            "reason": "Confirmed from timeline" + (" with edits" if edited else ""),
            "edits": {"followup_date": new_fu, "note": note, "outreach": outreach} if edited else None}
    try:
        result = client.decide(rec["recommendation_id"], body)
    except ApiError as exc:
        detail = exc.detail
        if isinstance(detail, dict) and detail.get("errors"):
            detail = "; ".join(f"{e['code']}: {e['message']}" for e in detail["errors"])
        st.session_state["proposal_error"] = f"Not scheduled - the proposal failed re-validation: {detail}"
        return
    action = result.get("action")
    if not action:
        st.session_state["flash"] = "Decision recorded (no event required)."
        return
    if send_now:
        submitted = client.submit(action["action_id"])
        if submitted["status"] == "SUBMITTED":
            st.session_state["flash"] = (f"Scheduled: {nice(action['event_type'])} on {action.get('followup_date')}"
                                         " - sent to the servicing system, awaiting verification.")
        else:
            st.session_state["flash"] = f"Servicing system rejected the event: {submitted.get('failure_reason')}"
    else:
        st.session_state["flash"] = "Approved - ready to send from the Agent & decision tab."


def _dismiss(rec: dict, reason: str) -> None:
    rid, role = reviewer()
    try:
        get_client().decide(rec["recommendation_id"], {"decision": "REJECT", "reviewer_id": rid,
                                                       "reviewer_role": role, "reason": reason})
        st.session_state["flash"] = "Proposal dismissed and recorded."
    except ApiError as exc:
        st.session_state["proposal_error"] = f"Could not dismiss: {exc.detail}"


def render(rec: dict | None) -> None:
    error = st.session_state.pop("proposal_error", None)
    if error:
        st.error(error)
    if not rec or rec.get("status") != "PENDING_REVIEW":
        return
    event = rec.get("proposed_event") or {}
    if not event.get("creates_event"):
        return
    with st.container(border=True):
        source = "AI agent" if rec.get("agent_mode") == "llm" else "Rules baseline"
        st.markdown(f"**Proposed event** {badge('Proposed', '#6941C6')} "
                    f"<span style='color:#667085'>({source}, confidence {esc(rec.get('confidence', '').title())})"
                    f"</span><br><span style='font-size:1.1rem'><b>{esc(nice(rec['recommended_action']))}</b> - "
                    f"{esc(nice(event.get('event_type')))} for {esc(nice(event.get('milestone_type')) or 'the loan')}"
                    f"</span><br><span class='lsi-why'>{esc(rec.get('rationale'))}</span>", unsafe_allow_html=True)
        with st.form(f"proposal_{rec['recommendation_id']}", border=False):
            c1, c2 = st.columns([1, 3])
            default_fu = rec.get("recommended_followup_date")
            followup = c1.date_input("Follow-up date", value=date.fromisoformat(default_fu) if default_fu else None,
                                     min_value=date.fromisoformat(event["event_date"]))
            send_now = c1.checkbox("Send to servicing system now", value=True)
            note = c2.text_area("Servicing note", value=rec.get("suggested_note") or "", height=80, max_chars=1000)
            outreach = c2.text_area("Outreach message", value=rec.get("suggested_outreach") or "", height=80,
                                    disabled=not rec.get("suggested_outreach"))
            b1, b2, b3 = st.columns([1.3, 1, 2])
            confirm = b1.form_submit_button("Confirm and schedule", type="primary", icon=":material/event_available:")
            dismiss = b2.form_submit_button("Dismiss", icon=":material/close:")
            reason = b3.text_input("Reason (for dismiss)", value="Not needed", label_visibility="collapsed")
        st.caption("Your confirmation is recorded with your name and any edits. The proposal is re-checked before "
                   "anything is sent; nothing is scheduled without this step.")
        if confirm:
            _confirm(rec, followup, note, outreach or "", send_now)
            st.rerun()
        if dismiss:
            _dismiss(rec, reason or "Dismissed from timeline")
            st.rerun()
