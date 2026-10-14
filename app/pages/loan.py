"""Loan: rule facts, AI created by the Databricks backend, and on-demand analysis by the deployed agent."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from app import ui
from app.client import ApiError, get_client

ANALYSIS_PROMPT = ("Review loan {loan_id}. Using your tools, explain in 3 to 5 short bullets why it needs attention "
                   "and what has already happened. End with exactly one line: 'Recommended action: <ACTION>' "
                   "choosing an action returned by lsi_get_allowed_actions.")


def _pick_loan(client) -> str | None:
    ids = [r["loan_id"] for r in client.loans(limit=5000)]
    selected = st.session_state.get("selected_loan_id")
    if selected in ids and st.session_state.get("loan_picker") != selected:
        st.session_state["loan_picker"] = selected
    choice = st.selectbox("Loan", ids, index=None, key="loan_picker", label_visibility="collapsed",
                          placeholder="Select a synthetic loan, for example LSI-SYN-000005")
    if choice:
        st.session_state["selected_loan_id"] = choice
    return choice


def _rule_facts(detail: dict) -> None:
    state, loan = detail["state"], detail["loan"]
    st.markdown("#### Rules engine facts")
    items = "".join(f"<li>{ui.esc(c['detail'])} <code>{ui.esc(c['rule_id'])}</code></li>"
                    for c in state["raw_conditions"])
    st.markdown(f'<div class="lsi-rule"><b>Why it needs attention</b> (deterministic, notebook 04)'
                f'<ul style="margin-bottom:0">{items}</ul></div>', unsafe_allow_html=True)
    drivers = pd.DataFrame(state["score_drivers"])
    if not drivers.empty:
        st.markdown(f"**Attention score {state['attention_score']}** - how it adds up")
        st.bar_chart(drivers.set_index("detail")["points"], horizontal=True, height=170)
    st.markdown(f"Milestone **{ui.nice(state['current_milestone']) or 'none'}** - next follow-up "
                f"**{state['effective_followup_date'] or '-'}** - escalation **{ui.nice(state['escalation_state'])}** - "
                f"balance **${float(loan['current_balance'] or 0):,.0f}**")


def _backend_ai(loan_id: str, ai: dict) -> None:
    st.markdown("#### AI from the Databricks backend")
    insight = ai.get("insights", {}).get(loan_id)
    review = ai.get("reviews", {}).get(loan_id)
    if not insight and not review:
        st.info("The backend workflow has not summarized this loan (it covers the CRITICAL and HIGH loans). "
                "Use the on-demand analysis below.")
        return
    if insight:
        ui.ai_box(insight["ai_summary"], f"AI Functions (ai_query, {insight.get('model_endpoint')}) in notebook 07",
                  key=f"insight_{loan_id}")
    if review:
        action = ui.nice(review.get("recommended_action")) or "See review"
        body = ui.strip_recommended_line(review["review"])
        ui.ai_box(f"**Recommended action: {action}**" + "\n\n" + body,
                  f"Loan Servicing Agent in notebook 08 - {review.get('tool_call_count')} Unity Catalog tool calls",
                  key=f"review_{loan_id}")


def _preferred_action(loan_id: str, ai: dict) -> str | None:
    """The agent's latest suggestion: on-demand analysis first, then the batch review."""
    for item in st.session_state.get(f"analysis_{loan_id}", []):
        action = ui.recommended_action(item.get("answer", ""))
        if action:
            return action
    review = ai.get("reviews", {}).get(loan_id)
    return review.get("recommended_action") if review else None


def _next_step(client, loan_id: str, detail: dict, ai: dict) -> None:
    st.markdown("#### Next step - you decide")
    actions = detail.get("actions") or []
    latest = actions[0] if actions else None
    if latest and latest["status"] in ("APPROVED", "SUBMITTED", "VERIFIED", "FAILED", "VERIFICATION_FAILED"):
        verification = (client.action(latest["action_id"]).get("verification") or {}).get("verification_status")
        label = ui.nice(latest["action_type"])
        if verification == "VERIFIED":
            st.success(f"**{label}** was verified in the servicing system (follow-up {latest.get('followup_date')}).",
                       icon=":material/verified:")
        elif latest["status"] in ("FAILED", "VERIFICATION_FAILED") or verification in ("NOT_FOUND", "MISMATCH",
                                                                                       "DUPLICATE", "FAILED"):
            st.error(f"**{label}** did not land in the servicing system ({ui.nice(verification)}). "
                     "It is back in the queue.", icon=":material/error:")
        else:
            st.info(f"**{label}** is scheduled in the servicing system (follow-up {latest.get('followup_date')}) "
                    "and awaiting verification.", icon=":material/schedule:")
            if st.button("Verify now", icon=":material/sync:", help="Refresh from the servicing system and check"):
                client.refresh()
                st.rerun()
            return
    preferred = _preferred_action(loan_id, ai)
    preview = client.next_step(loan_id, preferred)
    allowed = [a for a in preview["allowed_actions"] if a != "NO_ACTION"]
    if preview["pending_actions"]:
        st.info("An approved action is already pending for this loan.")
        return
    if not allowed:
        st.success("No action is needed for this loan right now.", icon=":material/check_circle:")
        return
    default = preview["action_type"] if preview["action_type"] in allowed else allowed[0]
    action = st.selectbox("Action", allowed, index=allowed.index(default), format_func=ui.nice,
                          key=f"next_action_{loan_id}",
                          help="Only actions the rules allow for this loan. Preselected: the agent's recommendation.")
    event = client.next_step(loan_id, action)["event"]
    source = "the agent's recommendation" if preferred == action else "your choice"
    st.caption(f"Proposed: **{ui.nice(event.get('event_type'))}** for **{ui.nice(event.get('milestone_type'))}** "
               f"({source}). Nothing is sent until you confirm.")
    with st.form(f"schedule_{loan_id}_{action}", border=False):
        c1, c2 = st.columns([1, 3])
        followup = c1.date_input("Follow-up date", value=date.fromisoformat(event["followup_date"])
                                 if event.get("followup_date") else None)
        note = c2.text_area("Servicing note", value=event.get("event_note") or "", height=70)
        outreach = event.get("outreach_text") or ""
        if action in ("CONTACT_ATTORNEY", "CONTACT_SERVICING_VENDOR"):
            outreach = st.text_area("Outreach message", value=outreach, height=90)
        if st.form_submit_button("Confirm and schedule", type="primary", icon=":material/event_available:"):
            try:
                result = client.schedule(loan_id, {"action_type": action,
                                                   "followup_date": followup.isoformat() if followup else None,
                                                   "note": note, "outreach": outreach or None})
                status = result["action"]["status"] if result.get("action") else "recorded"
                st.toast(f"{ui.nice(action)}: {ui.nice(status)}")
            except ApiError as exc:
                detail_text = exc.detail
                if isinstance(detail_text, dict) and detail_text.get("errors"):
                    detail_text = "; ".join(e["message"] for e in detail_text["errors"])
                st.session_state[f"schedule_error_{loan_id}"] = str(detail_text)
            st.rerun()
    error = st.session_state.pop(f"schedule_error_{loan_id}", None)
    if error:
        st.error(f"Not scheduled - the rules rejected it: {error}")


def _on_demand(client, loan_id: str) -> None:
    st.markdown("#### On-demand AI analysis")
    st.caption("Calls the deployed Loan Servicing Agent on Model Serving right now. It chooses its own Unity "
               "Catalog tools; nothing is changed or sent.")
    history = st.session_state.setdefault(f"analysis_{loan_id}", [])
    instructions = ui.instructions_box(f"loan_{loan_id}")
    left, right = st.columns([1, 3])
    run = left.button("Run AI analysis now", type="primary", icon=":material/auto_awesome:")
    question = right.chat_input("Ask the agent about this loan")
    prompt = ANALYSIS_PROMPT.format(loan_id=loan_id) if run else (
        f"About loan {loan_id}: {question}" if question else None)
    if prompt:
        with st.spinner("The agent is choosing tools and querying Unity Catalog..."):
            try:
                result = client.agent_chat([{"role": "user", "content": prompt}], instructions or None)
                history.insert(0, {"question": "Full analysis" if run else question, "instructions": instructions,
                                   **result})
            except ApiError as exc:
                st.error(f"The deployed agent did not respond (it may be waking from scale-to-zero): {exc.detail}")
    for item in history:
        with st.container(border=True):
            st.markdown(f"**{ui.esc(item['question'])}**")
            if item.get("instructions"):
                st.caption(f"Custom instructions: {item['instructions']}")
            ui.agent_response(item)


def render() -> None:
    client = get_client()
    st.markdown("## Loan")
    ui.notes("loan")
    loan_id = _pick_loan(client)
    if not loan_id:
        st.info("Pick a loan, or open one from the Portfolio.")
        return
    try:
        detail = client.loan(loan_id)
    except ApiError as exc:
        st.error(f"Could not load {loan_id}: {exc.detail}")
        return
    loan, state = detail["loan"], detail["state"]
    st.markdown(f"<div style='font-size:1.3rem; font-weight:700'>{ui.esc(loan_id)} - "
                f"{ui.esc(loan['borrower_display_name'])} &nbsp; {ui.badge(ui.nice(state['priority']), ui.PRIORITY_COLORS.get(state['priority']))}"
                f"</div><div class='lsi-why'>{ui.esc(ui.nice(state['primary_condition']))} - "
                f"{state['days_overdue']} days overdue - {ui.esc(ui.nice(loan['payment_status']))} - "
                f"{ui.esc(ui.nice(loan['foreclosure_status']))}</div>", unsafe_allow_html=True)
    st.write("")
    ai = client.backend_ai()
    _backend_ai(loan_id, ai)
    st.divider()
    _rule_facts(detail)
    st.divider()
    _on_demand(client, loan_id)
    st.divider()
    left, right = st.columns([3, 2], gap="large")
    with left:
        _next_step(client, loan_id, detail, ai)
    with right:
        st.markdown("#### Servicing timeline")
        ui.timeline(client.events(loan_id)[-8:])
