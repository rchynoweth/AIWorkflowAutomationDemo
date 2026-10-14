"""Loan: the rule facts, then the agent drafts the next step - live or overnight - and a person decides."""
from datetime import date

import pandas as pd
import streamlit as st

from app import data, ui

NEWS_EXAMPLE = ("Attorney update: the court is backlogged and the hearing will be rescheduled; expect a new date "
                "in about two weeks.")


def rule_facts(state: dict, ai: dict) -> None:
    insight = ai["insights"].get(state["loan_id"])
    if insight:
        ui.ai_box(insight["ai_summary"], f"Summary written overnight by AI Functions (ai_query, "
                  f"{insight['model_endpoint']}) in notebook 07", key="insight")
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
                f"allowed actions **{', '.join(ui.nice(a) for a in state['allowed_actions'])}**")


def current_draft(loan_id: str, ai: dict) -> dict | None:
    """The agent's latest draft: the live one from this session, otherwise the one from the overnight workflow."""
    live = st.session_state.get(f"draft_{loan_id}")
    if live:
        return live
    overnight = ai["reviews"].get(loan_id)
    if overnight and overnight["recommended_action"]:
        return {"answer": overnight["review"], "steps": [], "key": "overnight", "source":
                f"Drafted overnight by the agent (notebook 08, {overnight['tool_call_count']} Unity Catalog tool calls)",
                "draft": {"action": overnight["recommended_action"], "followup_date": overnight["proposed_followup_date"],
                          "note": overnight["proposed_note"], "outreach": overnight["proposed_outreach"]}}
    return None


def ask_for_draft(loan_id: str, has_draft: bool) -> None:
    """The on-demand side: the agent investigates live, optionally with new information or custom instructions."""
    news = st.text_area("What's new on this loan? (optional)", key=f"news_{loan_id}", height=70,
                        placeholder=f"Paste an update and the agent re-plans around it. For example: {NEWS_EXAMPLE}")
    with st.expander("Custom instructions for the agent"):
        instructions = ui.instructions_box(f"loan_{loan_id}")
    label = "Re-plan with the agent" if has_draft else "Have the agent propose the next step"
    if st.button(label, type="primary", icon=":material/auto_awesome:"):
        with st.spinner("The agent is investigating with its Unity Catalog tools and drafting the next step..."):
            try:
                result = data.propose_next_step(loan_id, news.strip(), instructions)
            except Exception as exc:  # noqa: BLE001
                st.error(f"The agent did not respond (it may be waking up from scale-to-zero): {exc}")
                return
        result["source"] = "Drafted just now by the agent" + (" with your update" if news.strip() else "")
        result["key"] = str(result["seconds"])
        st.session_state[f"draft_{loan_id}"] = result


def review_draft(state: dict, draft: dict) -> dict:
    """The person reviews the agent's draft, edits it, and confirms. Returns the proposal for the timeline."""
    allowed = [a for a in state["allowed_actions"] if a != "NO_ACTION"]
    proposed = draft["draft"].get("action")
    if proposed not in allowed:  # the rules have the last word
        st.warning(f"The agent proposed **{ui.nice(proposed) or 'nothing usable'}**, which the rules do not allow for "
                   "this loan, so the draft starts from the rules' default.", icon=":material/gpp_maybe:")
        proposed = state["recommended_action"] if state["recommended_action"] in allowed else allowed[0]
    action = st.selectbox("Action", allowed, index=allowed.index(proposed), format_func=ui.nice,
                          key=f"action_{state['loan_id']}_{draft['key']}",
                          help="Only actions the rules allow for this loan.")
    event = data.proposal(state, action)
    if action == draft["draft"].get("action"):  # keep the agent's date, note, and outreach for its own action
        try:
            event["followup_date"] = date.fromisoformat(draft["draft"].get("followup_date") or "")
        except ValueError:
            pass
        event["note"] = draft["draft"].get("note") or event["note"]
        event["outreach"] = draft["draft"].get("outreach") or event["outreach"]
    st.caption(f"{draft['source']}. Creates a **{ui.nice(event['event_type'])}** event for "
               f"**{ui.nice(event['milestone_type'])}**. Nothing is sent until you confirm.")
    with st.form(f"confirm_{state['loan_id']}_{action}_{draft['key']}", border=False):
        c1, c2 = st.columns([1, 3])
        followup = c1.date_input("Follow-up date", value=event["followup_date"])
        note = c2.text_area("Servicing note", value=event["note"], height=70)
        outreach = ""
        if event["outreach"] or action.startswith("CONTACT_"):
            outreach = st.text_area("Outreach message", value=event["outreach"], height=110)
        if st.form_submit_button("Confirm and schedule", type="primary", icon=":material/event_available:"):
            try:
                action_id = data.schedule(state, action, followup, note, outreach)
                st.session_state.pop(f"draft_{state['loan_id']}", None)
                st.toast(f"{ui.nice(action)} sent to the servicing system as a bulk-upload file ({action_id})")
                st.rerun()
            except ValueError as exc:
                st.error(f"Not scheduled: {exc}")
    return {**event, "event_date": None, "event_note": event["note"], "state": "PROPOSED"}


def next_step(state: dict, ai: dict) -> dict | None:
    st.markdown("#### Next step - the agent drafts it, you decide")
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
            st.info(f"**{label}** was sent to the servicing system (follow-up {last['followup_date']}). The next "
                    "lsi-pipeline run verifies that it landed.", icon=":material/schedule:")
            return None
    if not [a for a in state["allowed_actions"] if a != "NO_ACTION"]:
        st.success("The rules allow no action on this loan right now - nothing to draft.", icon=":material/check_circle:")
        return None
    draft = current_draft(loan_id, ai)
    ask_for_draft(loan_id, has_draft=draft is not None)
    draft = current_draft(loan_id, ai)
    if not draft:
        st.info("No draft yet. Ask the agent to propose the next step - it investigates live with its tools.")
        return None
    with st.container(border=True):
        ui.agent_answer(draft)
        return review_draft(state, draft)


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


def ask_about_loan(loan_id: str) -> None:
    with st.expander("Ask the agent anything about this loan"):
        history = st.session_state.setdefault(f"chat_{loan_id}", [])
        question = st.text_input("Question", key=f"question_{loan_id}", label_visibility="collapsed",
                                 placeholder="For example: what has the attorney done on this loan so far?")
        if st.button("Ask", key=f"ask_{loan_id}") and question:
            with st.spinner("The agent is choosing tools and querying Unity Catalog..."):
                try:
                    history.insert(0, {"question": question, **data.ask_agent(
                        [{"role": "user", "content": f"About loan {loan_id}: {question}"}])})
                except Exception as exc:  # noqa: BLE001
                    st.error(f"The agent did not respond: {exc}")
        for item in history:
            st.markdown(f"**{ui.esc(item['question'])}**")
            ui.agent_answer(item)


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
            f"{ui.nice(state['payment_status'])} - {ui.nice(state['foreclosure_status'])} - "
            f"balance ${state['current_balance']:,.0f}</div>", unsafe_allow_html=True)
st.write("")
rule_facts(state, ai)
st.divider()
left, right = st.columns([3, 2], gap="large")
with left:
    proposal = next_step(state, ai)
with right:
    timeline(state, proposal)
st.divider()
ask_about_loan(loan_id)
