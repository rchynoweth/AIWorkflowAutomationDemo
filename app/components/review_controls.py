"""Review controls: Approve, Edit, Reject, Defer, Escalate; then submit via adapter and verify."""
from __future__ import annotations

from datetime import date

import streamlit as st

from app.components.styles import badge
from app.state import ApiError, get_client, reviewer

ROLES = ["SENIOR_SPECIALIST", "SERVICING_MANAGER"]


def _decide(rec: dict, decision: str, reason: str = "", comment: str = "", edits: dict | None = None) -> None:
    rid, role = reviewer()
    body = {"decision": decision, "reviewer_id": rid, "reviewer_role": role, "reason": reason, "comment": comment,
            "edits": edits}
    try:
        res = get_client().decide(rec["recommendation_id"], body)
        action = res.get("action")
        st.session_state["flash"] = f"{decision} recorded" + (f"; action {action['action_id']} created" if action else "")
        if action:
            st.session_state["last_action_id"] = action["action_id"]
    except ApiError as exc:
        detail = exc.detail
        if isinstance(detail, dict) and detail.get("errors"):
            st.session_state["review_error"] = "; ".join(f"{e['code']}: {e['message']}" for e in detail["errors"])
        else:
            st.session_state["review_error"] = str(detail)
    st.rerun()


def render(rec: dict | None, state: dict) -> None:
    error = st.session_state.pop("review_error", None)
    if error:
        st.error(f"Not approved — revalidation failed: {error}")
    if not rec or rec.get("status") != "PENDING_REVIEW":
        return
    st.markdown("#### Specialist review")
    st.caption("The agent only prepares proposals. Approval revalidates currency, duplicates, pending actions, "
               "fields, and allowed actions before any outbound event is created.")
    tabs = st.tabs(["Approve", "Edit", "Reject", "Defer", "Escalate"])
    with tabs[0]:
        if st.button(f"Approve {rec['recommended_action']}", type="primary", key="approve",
                     disabled=rec.get("status") != "PENDING_REVIEW"):
            _decide(rec, "APPROVE", reason="Approved as recommended")
    with tabs[1]:
        with st.form("edit_form"):
            allowed = state["allowed_actions"]
            idx = allowed.index(rec["recommended_action"]) if rec["recommended_action"] in allowed else 0
            action = st.selectbox("Action (allowed only)", allowed, index=idx)
            default_fu = rec.get("recommended_followup_date")
            fu = st.date_input("Follow-up date", value=date.fromisoformat(default_fu) if default_fu else None)
            note = st.text_area("Note", value=rec.get("suggested_note") or "", max_chars=1000)
            outreach = st.text_area("Outreach draft", value=rec.get("suggested_outreach") or "")
            reason = st.text_input("Reason for edit", value="Adjusted by specialist")
            if st.form_submit_button("Approve with edits", type="primary"):
                _decide(rec, "EDIT", reason=reason, edits={
                    "action_type": action, "followup_date": fu.isoformat() if fu else None, "note": note,
                    "outreach": outreach})
    with tabs[2]:
        with st.form("reject_form"):
            reason = st.text_input("Reason (required)")
            if st.form_submit_button("Reject"):
                if not reason.strip():
                    st.session_state["review_error"] = "A reason is required to reject."
                    st.rerun()
                _decide(rec, "REJECT", reason=reason)
    with tabs[3]:
        with st.form("defer_form"):
            reason = st.text_input("Reason", value="Awaiting additional information")
            if st.form_submit_button("Defer"):
                _decide(rec, "DEFER", reason=reason)
    with tabs[4]:
        with st.form("escalate_form"):
            target = st.selectbox("Escalate to", ROLES, index=1 if state["escalation_state"] == "CRITICAL" else 0)
            reason = st.text_input("Reason", value=f"{state['primary_condition']} requires senior review")
            if st.form_submit_button("Escalate"):
                _decide(rec, "ESCALATE", reason=reason, edits={"escalation_target": target})


def render_actions(detail: dict) -> None:
    """Outbound events for approved actions, adapter submission, and verification."""
    actions = detail.get("actions") or []
    if not actions:
        return
    client = get_client()
    st.markdown("#### Approved actions")
    for action in actions:
        full = client.action(action["action_id"])
        v = (full.get("verification") or {}).get("verification_status")
        st.markdown(f"**{action['action_id']}** · {action['action_type']} → {action['event_type']} "
                    f"(follow-up {action.get('followup_date') or '—'}) &nbsp; {badge(action['status'], '#344054')} "
                    f"&nbsp; verification {badge(v)}", unsafe_allow_html=True)
        c1, c2, c3 = st.columns([1, 1, 3])
        if action["status"] == "APPROVED":
            if c1.button("Submit via synthetic adapter", key=f"submit_{action['action_id']}", type="primary",
                         icon=":material/send:"):
                res = client.submit(action["action_id"])
                st.session_state["flash"] = (f"{res['status']}: {res['adapter_result'].get('message')}")
                st.rerun()
        if action["status"] in ("SUBMITTED", "VERIFICATION_FAILED", "FAILED"):
            if c2.button("Refresh source & verify", key=f"refresh_{action['action_id']}", icon=":material/sync:"):
                res = client.refresh()
                st.session_state["flash"] = f"Cycle {res['refresh_cycle']}: {res['verification'] or 'nothing to verify'}"
                st.rerun()
        if full.get("adapter_result"):
            c3.caption(f"Adapter: {full['adapter_result'].get('mode')} — {full['adapter_result'].get('message')}")
        diffs = (full.get("verification") or {}).get("differences")
        if diffs:
            st.warning("Differences: " + "; ".join(f"{d['field']}: approved {d['approved']} vs actual {d['actual']}"
                                                    for d in diffs))
        with st.expander("Outbound servicing event (synthetic, loan-servicing-system-compatible)"):
            st.json(full.get("outbound_payload") or {})
