"""Loan: rule facts, AI created by the Databricks backend, and on-demand analysis by the deployed agent."""
from __future__ import annotations

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
        ui.ai_box(insight["ai_summary"], f"AI Functions: ai_query ({insight.get('model_endpoint')}) in notebook 07, "
                                         f"{insight.get('generated_at')} UTC")
        st.write("")
    if review:
        action = ui.nice(review.get("recommended_action")) or "See review"
        ui.ai_box(f"Recommended action: {action}\n\n{review['review']}",
                  f"Loan Servicing Agent ({review.get('agent_endpoint')}) in notebook 08 - "
                  f"{review.get('tool_call_count')} tool calls: {review.get('tools_called')}")


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
    left, right = st.columns(2, gap="large")
    with left:
        _rule_facts(detail)
    with right:
        _backend_ai(loan_id, client.backend_ai())
    st.divider()
    _on_demand(client, loan_id)
    with st.expander("Servicing event timeline"):
        ui.timeline(client.events(loan_id))
