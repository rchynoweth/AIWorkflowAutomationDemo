"""Loan: AI from the Databricks backend, the rule facts, on-demand analysis by the agent, and the next step."""
from datetime import date

import pandas as pd
import streamlit as st

from app import data, ui

ANALYSIS_PROMPT = ("Review loan {loan_id}. Using your tools, explain in 3 to 5 short bullets why it needs attention "
                   "and what has already happened. End with exactly one line: 'Recommended action: <ACTION>' "
                   "choosing an action returned by lsi_get_allowed_actions.")


def backend_ai(loan_id: str, ai: dict) -> None:
    st.markdown("#### AI from the Databricks backend")
    insight, review = ai["insights"].get(loan_id), ai["reviews"].get(loan_id)
    if not insight and not review:
        st.info("The backend workflow summarizes the Critical and High loans. Use the on-demand analysis below.")
    if insight:
        ui.ai_box(insight["ai_summary"], f"AI Functions (ai_query, {insight['model_endpoint']}) in notebook 07",
                  key="insight")
    if review:
        ui.ai_box(f"**Recommended action: {ui.nice(review['recommended_action'])}**\n\n"
                  + ui.without_recommended_line(review["review"]),
                  f"Loan Servicing Agent in notebook 08 - {review['tool_call_count']} Unity Catalog tool calls",
                  key="review")


def rule_facts(state: dict) -> None:
    st.markdown("#### Rule facts (notebook 04, plain SQL)")
    conditions = "".join(f"<li>{ui.esc(c['detail'])} <code>{c['rule_id']}</code></li>" for c in state["conditions"])
    st.markdown(f'<div class="lsi-rule"><b>Why it needs attention</b><ul style="margin-bottom:0">{conditions}</ul></div>',
                unsafe_allow_html=True)
    drivers = pd.DataFrame(state["score_drivers"])
    if not drivers.empty:
        st.markdown(f"**Attention score {state['attention_score']}** - how it adds up")
        st.bar_chart(drivers.set_index("detail")["points"], horizontal=True, height=170)
    st.markdown(f"Milestone **{ui.nice(state['current_milestone']) or 'none'}** - next milestone "
                f"**{ui.nice(state['next_milestone']) or 'none'}** - follow-up **{state['followup_date'] or '-'}** - "
                f"balance **${state['current_balance']:,.0f}**")


def on_demand(loan_id: str) -> None:
    st.markdown("#### On-demand AI analysis")
    st.caption("Calls the deployed Loan Servicing Agent on Model Serving right now. It chooses its own Unity Catalog "
               "tools; nothing is changed or sent.")
    history = st.session_state.setdefault(f"analysis_{loan_id}", [])
    instructions = ui.instructions_box(f"loan_{loan_id}")
    left, right = st.columns([1, 3])
    run = left.button("Run AI analysis now", type="primary", icon=":material/auto_awesome:")
    question = right.chat_input("Ask the agent about this loan")
    if run or question:
        prompt = ANALYSIS_PROMPT.format(loan_id=loan_id) if run else f"About loan {loan_id}: {question}"
        with st.spinner("The agent is choosing tools and querying Unity Catalog..."):
            try:
                result = data.ask_agent([{"role": "user", "content": prompt}], instructions)
                history.insert(0, {"question": "Full analysis" if run else question, "instructions": instructions,
                                   **result})
            except Exception as exc:  # noqa: BLE001
                st.error(f"The agent did not respond (it may be waking up from scale-to-zero): {exc}")
    for item in history:
        with st.container(border=True):
            st.markdown(f"**{ui.esc(item['question'])}**")
            if item["instructions"]:
                st.caption(f"Custom instructions: {item['instructions']}")
            ui.agent_answer(item)


def next_step(state: dict, ai: dict) -> dict | None:
    """A person picks an allowed action, edits it, and confirms. Returns the proposal shown on the timeline."""
    st.markdown("#### Next step - you decide")
    loan_id = state["loan_id"]
    last = data.latest_app_action(loan_id)
    if last:
        status, label = last["verification_status"], ui.nice(last["action_type"])
        if status == "VERIFIED":
            st.success(f"**{label}** was verified in the servicing system.", icon=":material/verified:")
        elif status in ("NOT_FOUND", "MISMATCH", "DUPLICATE"):
            st.error(f"**{label}** did not land as approved ({ui.nice(status)}). It is back in the queue.",
                     icon=":material/error:")
        else:
            st.info(f"**{label}** is scheduled (follow-up {last['followup_date']}). The next lsi-pipeline run "
                    "verifies it landed in the servicing system.", icon=":material/schedule:")
            return None
    allowed = [a for a in state["allowed_actions"] if a != "NO_ACTION"]
    if not allowed:
        st.success("No action is needed for this loan right now.", icon=":material/check_circle:")
        return None

    # Preselect the agent's latest suggestion: on-demand analysis first, then the batch review, then the rules.
    suggestions = [ui.recommended_action(item["answer"]) for item in st.session_state.get(f"analysis_{loan_id}", [])]
    suggestions += [(ai["reviews"].get(loan_id) or {}).get("recommended_action"), state["recommended_action"]]
    preferred = next((s for s in suggestions if s in allowed), allowed[0])
    action = st.selectbox("Action", allowed, index=allowed.index(preferred), format_func=ui.nice,
                          help="Only actions the rules allow for this loan. Preselected: the agent's recommendation.")
    proposal = data.proposal(state, action)
    st.caption(f"Creates a **{ui.nice(proposal['event_type'])}** event for **{ui.nice(proposal['milestone_type'])}**. "
               "Nothing is sent until you confirm.")
    with st.form(f"schedule_{action}", border=False):
        c1, c2 = st.columns([1, 3])
        followup = c1.date_input("Follow-up date", value=proposal["followup_date"])
        note = c2.text_area("Servicing note", value=proposal["note"], height=70)
        outreach = st.text_area("Outreach message", value=proposal["outreach"], height=90) if proposal["outreach"] else ""
        if st.form_submit_button("Confirm and schedule", type="primary", icon=":material/event_available:"):
            try:
                action_id = data.schedule(state, action, followup, note, outreach)
                st.toast(f"{ui.nice(action)} scheduled ({action_id})")
                st.rerun()
            except ValueError as exc:
                st.error(f"Not scheduled: {exc}")
    return {**proposal, "event_date": None, "event_note": proposal["note"], "state": "PROPOSED"}


def timeline(state: dict, proposal: dict | None) -> None:
    st.markdown("#### Servicing timeline")
    today = date.today().isoformat()
    events = []
    for ev in reversed(data.events(state["loan_id"])):
        if ev["from_app"]:
            ev["state"] = "SCHEDULED"
        elif ev["event_id"] == state["milestone_event_id"]:
            ev["state"] = "CURRENT"
        elif ev["status"] == "COMPLETED":
            ev["state"] = "COMPLETED"
        elif ev["status"] == "OPEN" and ev["followup_date"] and ev["followup_date"] < today:
            ev["state"] = "OVERDUE"
        else:
            ev["state"] = "OPEN"
        events.append(ev)
    ui.timeline(([proposal] if proposal else []) + events[:8])


# ---- page ---------------------------------------------------------------------------------------------------------
st.markdown("## Loan")
ui.notes("loan")
ids = [r["loan_id"] for r in data.loans()]
default = st.session_state.get("loan_id")
loan_id = st.selectbox("Loan", ids, index=ids.index(default) if default in ids else None, label_visibility="collapsed",
                       placeholder="Select a synthetic loan, for example LSI-SYN-000007")
if not loan_id:
    st.info("Pick a loan, or open one from the Portfolio.")
    st.stop()
st.session_state["loan_id"] = loan_id
state = data.loan(loan_id)
ai = data.backend_ai()

st.markdown(f"<div style='font-size:1.3rem; font-weight:700'>{loan_id} - {ui.esc(state['borrower_display_name'])} "
            f"&nbsp; {ui.badge(ui.nice(state['priority']), ui.PRIORITY_COLORS[state['priority']])}</div>"
            f"<div class='lsi-muted'>{ui.nice(state['primary_condition'])} - {state['days_overdue']} days overdue - "
            f"{ui.nice(state['payment_status'])} - {ui.nice(state['foreclosure_status'])}</div>",
            unsafe_allow_html=True)
st.write("")
backend_ai(loan_id, ai)
st.divider()
rule_facts(state)
st.divider()
on_demand(loan_id)
st.divider()
left, right = st.columns([3, 2], gap="large")
with left:
    proposal = next_step(state, ai)
with right:
    timeline(state, proposal)
