"""Loan 360: header, Overview, Events, Agent Analysis (+ review, Ask the Agent), Recommendations, Activity."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.components import activity_trace, agent_assessment, event_timeline, review_controls
from app.components.styles import badge, esc
from app.state import ApiError, get_client, reviewer

SUGGESTED_QUESTIONS = [
    "Why is this loan prioritized?", "What should happen next?", "What information is missing?",
    "Is there already a follow-up?", "What evidence supports this?", "Which rule applies?",
    "What happens if I reject?", "Are there pending actions?",
]


def _picker(client) -> str | None:
    loans = client.loans(limit=5000)
    ids = [r["loan_id"] for r in loans]
    current = st.session_state.get("selected_loan_id")
    index = ids.index(current) if current in ids else None
    choice = st.selectbox("Loan", ids, index=index, placeholder="Select a synthetic loan (e.g. LSI-SYN-000005)",
                          format_func=lambda lid: lid, key="l360_picker")
    if choice and choice != current:
        st.session_state["selected_loan_id"] = choice
        st.rerun()
    return choice


def _header(detail: dict) -> None:
    loan, state = detail["loan"], detail["state"]
    st.markdown(
        f"<div style='font-size:1.4rem; font-weight:700'>{esc(loan['loan_id'])} · {esc(loan['borrower_display_name'])} "
        f"{badge(state['priority'])}</div>", unsafe_allow_html=True)
    cols = st.columns(7)
    for col, (label, value) in zip(cols, [
        ("Loan status", loan["loan_status"]), ("Payment status", loan["payment_status"]),
        ("Days delinquent", loan["days_delinquent"]), ("Foreclosure status", loan["foreclosure_status"]),
        ("Priority", state["priority"]), ("Score", state["attention_score"]), ("Days overdue", state["days_overdue"]),
    ]):
        col.markdown(f'<div class="lsi-card"><div class="label">{esc(label)}</div>'
                     f'<div style="font-weight:700; font-size:1.05rem">{esc(value)}</div></div>', unsafe_allow_html=True)


def _overview(detail: dict) -> None:
    loan, state, parties = detail["loan"], detail["state"], detail["parties"]
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**Loan (synthetic)**")
        st.write({"Portfolio": loan["portfolio_id"], "Boarding date": loan["boarding_date"],
                  "Original balance": f"${float(loan['original_balance'] or 0):,.2f}",
                  "Current balance": f"${float(loan['current_balance'] or 0):,.2f}",
                  "Property": f"{loan['property_city']}, {loan['property_county']}, {loan['property_state']}"})
    with c2:
        st.markdown("**Assigned parties**")
        party = parties.get("party") or {}
        st.write({"Specialist": f"{parties['specialist']['name']} ({parties['specialist']['team']})",
                  "Attorney / vendor": f"{party.get('name')} ({party.get('type')})" if party else "None assigned",
                  "Required party type": parties.get("required_party_type") or "—",
                  "Required party present": parties.get("party_ok")})
    with c3:
        st.markdown("**Servicing state**")
        st.write({"Current milestone": state["current_milestone"] or "No servicing track",
                  "Milestone status": state["milestone_status"], "Effective follow-up": state["effective_followup_date"],
                  "Days to follow-up": state["days_to_followup"], "Health": state["health_segment"],
                  "Escalation": f"{state['escalation_state']} ({state['required_role']})"})
    st.markdown("**Open conditions (deterministic rules)**")
    st.dataframe(pd.DataFrame(state["raw_conditions"]), hide_index=True, use_container_width=True)
    left, right = st.columns(2)
    with left:
        st.markdown("**Score drivers** (config/attention_scoring.yml)")
        drivers = pd.DataFrame(state["score_drivers"])
        if not drivers.empty:
            st.bar_chart(drivers.set_index("detail")["points"], horizontal=True, height=220)
    with right:
        st.markdown("**Escalation reasons**")
        st.dataframe(pd.DataFrame(state["escalation_reasons"]), hide_index=True, use_container_width=True)
        st.markdown("**Pending actions**")
        st.write(detail["pending_actions"] or "None")
        if detail.get("latest_verification"):
            v = detail["latest_verification"]
            st.markdown(f"Latest verification: {badge(v['verification_status'])} {esc(v['detail'])}",
                        unsafe_allow_html=True)


def _ask(client, loan_id: str) -> None:
    st.markdown("#### ✨ Ask the Agent")
    st.caption("Governed questions about this loan. Answers use deterministic tools; tool calls are shown.")
    cols = st.columns(4)
    asked = None
    for i, q in enumerate(SUGGESTED_QUESTIONS):
        if cols[i % 4].button(q, key=f"q_{i}", use_container_width=True):
            asked = q
    with st.form("ask_form", clear_on_submit=True):
        free = st.text_input("Your question")
        if st.form_submit_button("Ask") and free.strip():
            asked = free.strip()
    if asked:
        rid, _ = reviewer()
        with st.spinner("Agent investigating with tools..."):
            try:
                st.session_state[f"answer_{loan_id}"] = {"q": asked, **client.agent("ask", loan_id, asked, rid)}
            except ApiError as exc:
                st.session_state[f"answer_{loan_id}"] = {"q": asked, "answer": f"Agent unavailable: {exc.detail}",
                                                         "tool_calls": [], "agent_mode": "error"}
    answer = st.session_state.get(f"answer_{loan_id}")
    if answer:
        st.markdown(f'<div class="lsi-ai"><b>Q:</b> {esc(answer["q"])}<br><b>A</b> ({esc(answer.get("agent_mode"))}): '
                    f'{esc(answer["answer"])}</div>', unsafe_allow_html=True)
        with st.expander(f"Tool calls ({len(answer.get('tool_calls') or [])})"):
            st.dataframe(pd.DataFrame(answer.get("tool_calls") or []), hide_index=True, use_container_width=True)


def render() -> None:
    client = get_client()
    st.markdown("### Loan 360")
    loan_id = _picker(client)
    if not loan_id:
        st.info("Select a loan, or open one from the Priority Queue or Portfolio.")
        return
    try:
        detail = client.loan(loan_id)
    except ApiError as exc:
        st.error(f"Could not load {loan_id}: {exc.detail}")
        return
    _header(detail)
    tabs = st.tabs(["Overview", "Events", "Agent Analysis", "Recommendations", "Activity"])
    with tabs[0]:
        _overview(detail)
    with tabs[1]:
        include = st.toggle("Include payment history", value=False, key="tl_payments")
        event_timeline.render(client.events(loan_id, include))
    with tabs[2]:
        recs = client.recommendations(loan_id)
        current = next((r for r in recs if r["status"] != "SUPERSEDED"), None)
        b1, b2 = st.columns([1, 3])
        if b1.button("Run agent analysis", type="primary", icon=":material/auto_awesome:", key="run_agent"):
            rid, _ = reviewer()
            with st.spinner("Agent investigating with approved tools..."):
                try:
                    res = client.agent("assess", loan_id, user_id=rid)
                    st.session_state["flash"] = (f"Agent ({res['agent_mode']}) recommended "
                                                 f"{(res.get('recommendation') or {}).get('recommended_action')}"
                                                 if res.get("recommendation") else
                                                 "Agent analysis failed — routed to specialist review")
                except ApiError as exc:
                    st.session_state["flash"] = f"Agent analysis failed — routed to specialist review ({exc.detail})"
            st.rerun()
        b2.caption(f"Review status: {detail['review_status']}. The agent never executes actions; it prepares "
                   "proposals for your authorization.")
        agent_assessment.render(current, detail["state"])
        review_controls.render(current, detail["state"])
        review_controls.render_actions(detail)
        st.divider()
        _ask(client, loan_id)
    with tabs[3]:
        recs = client.recommendations(loan_id)
        if not recs:
            st.info("No recommendations yet.")
        else:
            df = pd.DataFrame(recs)[["created_at", "recommendation_id", "agent_mode", "recommended_action",
                                     "recommended_followup_date", "confidence", "attention_score", "priority",
                                     "status"]]
            st.dataframe(df, hide_index=True, use_container_width=True)
        if detail.get("actions"):
            st.markdown("**Actions**")
            st.dataframe(pd.DataFrame(detail["actions"])[["action_id", "action_type", "event_type", "followup_date",
                                                          "status", "approved_by", "approved_at", "submitted_at",
                                                          "adapter_mode"]], hide_index=True, use_container_width=True)
    with tabs[4]:
        records = client.loan_activity(loan_id)
        activity_trace.render_flow(records)
        activity_trace.render_table(records)
