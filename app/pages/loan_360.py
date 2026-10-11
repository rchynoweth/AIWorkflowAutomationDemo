"""Loan 360: why this loan, timeline, agent proposal + human decision, history, activity."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.components import activity_trace, agent_assessment, event_timeline, review_controls
from app.components.agent_assessment import nice
from app.components.styles import badge, esc
from app.components.talk_track import active_chapter_banner, notes
from app.state import ApiError, get_client, reviewer

SUGGESTED_QUESTIONS = ["Why is this loan prioritized?", "What should happen next?", "What information is missing?",
                       "What happens if I reject?"]


def _picker(client) -> str | None:
    ids = [r["loan_id"] for r in client.loans(limit=5000)]
    selected = st.session_state.get("selected_loan_id")
    if selected in ids and st.session_state.get("l360_picker") != selected:
        st.session_state["l360_picker"] = selected
    choice = st.selectbox("Loan", ids, index=None, key="l360_picker", label_visibility="collapsed",
                          placeholder="Select a synthetic loan, e.g. LSI-SYN-000005")
    if choice:
        st.session_state["selected_loan_id"] = choice
    return choice


def _header(detail: dict) -> None:
    loan, state = detail["loan"], detail["state"]
    facts = [nice(state["primary_condition"]), state["current_milestone"] and nice(state["current_milestone"]),
             f"{state['days_overdue']} days overdue" if state["days_overdue"] else None,
             f"score {state['attention_score']}", nice(loan["payment_status"])]
    st.markdown(f"<div style='font-size:1.3rem; font-weight:700'>{esc(loan['loan_id'])} · "
                f"{esc(loan['borrower_display_name'])} &nbsp; {badge(state['priority'])}</div>"
                f"<div style='color:#475467'>{esc(' · '.join(f for f in facts if f))}</div>",
                unsafe_allow_html=True)


def _overview(detail: dict) -> None:
    state, loan, parties = detail["state"], detail["loan"], detail["parties"]
    left, right = st.columns([3, 2], gap="large")
    with left:
        items = "".join(f"<li>{esc(c['detail'])} <code>{esc(c['rule_id'])}</code></li>"
                        for c in state["raw_conditions"])
        st.markdown(f'<div class="lsi-rule"><b>Why this loan needs attention</b> (deterministic rules)'
                    f'<ul style="margin-bottom:0">{items}</ul></div>', unsafe_allow_html=True)
        st.write("")
        drivers = pd.DataFrame(state["score_drivers"])
        if not drivers.empty:
            st.markdown(f"**Attention score {state['attention_score']}** — how it adds up")
            st.bar_chart(drivers.set_index("detail")["points"], horizontal=True, height=180)
    with right:
        party = parties.get("party") or {}
        st.markdown("**Key facts**")
        st.markdown(
            f"- Milestone: **{esc(nice(state['current_milestone']) or 'none')}**"
            f" ({esc((state['milestone_status'] or '').title())})\n"
            f"- Next follow-up: **{esc(state['effective_followup_date'] or '—')}**\n"
            f"- Escalation: **{esc(nice(state['escalation_state']))}** → {esc(nice(state['required_role']))}\n"
            f"- Balance: **${float(loan['current_balance'] or 0):,.0f}** · {esc(nice(loan['foreclosure_status']))}\n"
            f"- Specialist: {esc(parties['specialist']['name'])}\n"
            f"- Attorney / vendor: {esc(party.get('name') or 'none assigned')}")
        if detail["pending_actions"]:
            st.info(f"Pending action: {detail['pending_actions'][0]['action_id']} "
                    f"({nice(detail['pending_actions'][0]['action_type'])}), awaiting verification.")


def _ask(client, loan_id: str) -> None:
    st.markdown("#### Ask the agent")
    cols = st.columns(len(SUGGESTED_QUESTIONS))
    asked = None
    for i, q in enumerate(SUGGESTED_QUESTIONS):
        if cols[i].button(q, key=f"q_{i}", use_container_width=True):
            asked = q
    free = st.chat_input("Ask a question about this loan")
    asked = asked or free
    if asked:
        rid, _ = reviewer()
        with st.spinner("Agent checking the facts with its tools..."):
            try:
                st.session_state[f"answer_{loan_id}"] = {"q": asked, **client.agent("ask", loan_id, asked, rid)}
            except ApiError as exc:
                st.session_state[f"answer_{loan_id}"] = {"q": asked, "answer": f"Agent unavailable: {exc.detail}",
                                                         "tool_calls": []}
    answer = st.session_state.get(f"answer_{loan_id}")
    if answer:
        st.markdown(f'<div class="lsi-ai"><b>{esc(answer["q"])}</b><br>{esc(answer["answer"])}</div>',
                    unsafe_allow_html=True)
        st.caption(f"Used {len(answer.get('tool_calls') or [])} tool calls · "
                   + ", ".join(sorted({c['tool_name'] for c in answer.get('tool_calls') or []})))


def render() -> None:
    active_chapter_banner("loan_360")
    client = get_client()
    st.markdown("## Loan 360")
    notes("loan_360")
    loan_id = _picker(client)
    if not loan_id:
        st.info("Pick a loan above, or open one from the Priority Queue.")
        return
    try:
        detail = client.loan(loan_id)
    except ApiError as exc:
        st.error(f"Could not load {loan_id}: {exc.detail}")
        return
    _header(detail)
    tabs = st.tabs(["Overview", "Timeline", "Agent & decision", "History", "Activity"])
    with tabs[0]:
        _overview(detail)
    with tabs[1]:
        include = st.toggle("Include payment history", value=False, key="tl_payments")
        event_timeline.render(client.events(loan_id, include))
    with tabs[2]:
        recs = client.recommendations(loan_id)
        current = next((r for r in recs if r["status"] != "SUPERSEDED"), None)
        if st.button("Run agent analysis", type="primary", icon=":material/auto_awesome:", key="run_agent"):
            rid, _ = reviewer()
            with st.spinner("Agent investigating with approved tools (about 20-30 seconds)..."):
                try:
                    res = client.agent("assess", loan_id, user_id=rid)
                    rec = res.get("recommendation")
                    st.session_state["flash"] = (f"Agent proposes {nice(rec['recommended_action'])}" if rec else
                                                 "Agent analysis failed — routed to specialist review")
                except ApiError as exc:
                    st.session_state["flash"] = f"Agent analysis failed — routed to specialist review ({exc.detail})"
            st.rerun()
        agent_assessment.render(current, detail["state"])
        review_controls.render(current, detail["state"])
        review_controls.render_actions(detail)
        st.divider()
        _ask(client, loan_id)
    with tabs[3]:
        recs = client.recommendations(loan_id)
        if recs:
            df = pd.DataFrame(recs)[["created_at", "agent_mode", "recommended_action", "confidence", "status"]]
            st.dataframe(df, hide_index=True, use_container_width=True)
        if detail.get("actions"):
            st.dataframe(pd.DataFrame(detail["actions"])[["action_id", "action_type", "followup_date", "status",
                                                          "approved_by", "adapter_mode"]],
                         hide_index=True, use_container_width=True)
        if not recs and not detail.get("actions"):
            st.info("No recommendations or actions yet.")
    with tabs[4]:
        records = client.loan_activity(loan_id)
        activity_trace.render_flow(records)
        activity_trace.render_table(records)
