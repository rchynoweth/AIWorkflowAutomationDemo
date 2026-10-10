"""Deterministic Loan Servicing Agent: fixed investigation plan, templated narrative.

Used in tests, when the LLM is unavailable, and for baseline recommendations in the pipeline.
"""
from __future__ import annotations

from src.agents.base import LoanServicingAgent, RunContext
from src.agents.briefing import deterministic_briefing
from src.agents.recommendation_builder import build_recommendation, template_narrative

INVESTIGATION_PLAN = [
    "get_loan_context", "get_event_history", "get_current_milestone", "check_milestone_completion",
    "check_followup_status", "check_pending_action", "check_previous_rejection", "get_assigned_party",
    "calculate_escalation_state", "calculate_loan_attention_score", "get_allowed_actions",
]
DECLINE_TERMS = ("legal advice", "lawsuit", "eligib", "should i foreclose", "foreclosure authority", "loss mitigation",
                 "financial advice", "compliance decision", "is it legal")


class DeterministicLoanServicingAgent(LoanServicingAgent):
    mode = "deterministic"

    def __init__(self, settings):
        self.settings = settings
        self.agent_version = f"{settings.agent_version}-deterministic"

    def assess_loan(self, loan_id: str, run: RunContext, fallback_reason: str | None = None) -> dict:
        loan_id = loan_id.strip().upper()
        executor = run.executor(loan_id)
        run.step("candidate_detected", loan_id, "Assessment requested")
        first = executor.call(INVESTIGATION_PLAN[0], {"loan_id": loan_id})
        if not first["success"]:
            return {"recommendation": None, "answer": f"Assessment failed: {first['error']}",
                    "tool_calls": executor.records, "agent_mode": self.mode, "error": first["error"]}
        for name in INVESTIGATION_PLAN[1:]:
            executor.call(name, {"loan_id": loan_id})
        state = run.tool_ctx.result(loan_id)
        rec = build_recommendation(executor, loan_id, state, self.settings, self.mode, run.run_id,
                                   choice=None, fallback_reason=fallback_reason)
        run.step("recommendation_generated", loan_id, f"{rec['recommended_action']} ({rec['confidence']})")
        run.step("awaiting_approval", loan_id, rec["status"])
        return {"recommendation": rec, "answer": rec["rationale"], "tool_calls": executor.records,
                "agent_mode": self.mode}

    # ---- governed questions ---------------------------------------------------------------
    def answer_question(self, question: str, loan_id: str | None, run: RunContext) -> dict:
        q = (question or "").lower()
        executor = run.executor(loan_id)
        if any(term in q for term in DECLINE_TERMS):
            return {"answer": "I can't provide legal, financial, eligibility, or other regulated determinations. "
                              "Please refer this question to the appropriate servicing manager or counsel. I can "
                              "summarize the loan's servicing facts if helpful.",
                    "tool_calls": [], "agent_mode": self.mode}
        if not loan_id:
            summary = executor.call("get_portfolio_health_summary", {})["data"]
            queue = executor.call("get_priority_queue", {"limit": 5})["data"]
            top = ", ".join(f"{r['loan_id']} ({r['priority']}, {r['primary_condition']})" for r in queue["rows"])
            answer = (f"{summary['need_attention']} of {summary['active_loans']} active loans need attention; "
                      f"{summary['critical']} are CRITICAL. Top of the queue: {top}. "
                      "(get_portfolio_health_summary, get_priority_queue)")
            return {"answer": answer, "tool_calls": executor.records, "agent_mode": self.mode}

        loan_id = loan_id.strip().upper()
        ctx_res = executor.call("get_loan_context", {"loan_id": loan_id})
        if not ctx_res["success"]:
            return {"answer": f"Loan {loan_id} was not found.", "tool_calls": executor.records, "agent_mode": self.mode}
        state = run.tool_ctx.result(loan_id)
        score = executor.call("calculate_loan_attention_score", {"loan_id": loan_id})["data"]
        cond_text = "; ".join(f"{c['code']} ({c['rule_id']}): {c['detail']}" for c in state["raw_conditions"])

        if any(w in q for w in ("why", "prioriti", "flag", "priority", "score")):
            drivers = executor.call("get_attention_score_drivers", {"loan_id": loan_id})["data"]
            answer = (f"{loan_id} is {state['priority']} with score {score['score']}. Conditions: {cond_text}. "
                      f"Score drivers: {drivers['summary']}. Escalation is {state['escalation_state']} "
                      f"(required role {state['required_role']}). The score is calculated deterministically from "
                      "config/attention_scoring.yml. (calculate_loan_attention_score, get_attention_score_drivers)")
        elif "reject" in q:
            answer = ("Rejecting records your decision and reason, creates no outbound event, and removes the "
                      "rejected action from this loan's allowed actions for 14 days (RULE-REVIEW-001) unless "
                      f"escalation reaches ESCALATE or CRITICAL. The loan stays in the queue while {state['primary_condition']} "
                      "persists. (check_previous_rejection)")
            executor.call("check_previous_rejection", {"loan_id": loan_id})
        elif "next" in q:
            nxt = executor.call("get_next_required_milestone", {"loan_id": loan_id})["data"]
            allowed = executor.call("get_allowed_actions", {"loan_id": loan_id})["data"]
            answer = (f"Current milestone: {state['current_milestone'] or 'none'}; configured next milestone: "
                      f"{nxt['next_milestone_type'] or 'none'} (exists already: {nxt['exists_already']}). "
                      f"Allowed actions now: {', '.join(allowed['allowed_actions'])}; deterministic default "
                      f"{allowed['default_action']}. (get_next_required_milestone, get_allowed_actions)")
        elif "missing" in q:
            from src.agents.recommendation_builder import deterministic_missing_information
            missing = deterministic_missing_information(state, executor)
            answer = ("Missing information: " + ("; ".join(missing) if missing else "none detected by the rules")
                      + f". Conditions: {cond_text}.")
        elif "pending" in q:
            pa = executor.call("check_pending_action", {"loan_id": loan_id})["data"]
            pr = executor.call("check_pending_recommendation", {"loan_id": loan_id})["data"]
            answer = (f"Pending actions: {', '.join(a['action_id'] + ' ' + a['action_type'] for a in pa['pending_actions']) or 'none'}. "
                      f"Recommendations awaiting review: {len(pr['pending_recommendations'])}. "
                      "(check_pending_action, check_pending_recommendation)")
        elif "follow" in q or "existing" in q or "duplicate" in q:
            fu = executor.call("check_followup_status", {"loan_id": loan_id})["data"]
            ex = executor.call("check_existing_event", {"loan_id": loan_id, "event_type": "FOLLOWUP"})["data"]
            answer = (f"Effective follow-up: {fu['effective_followup_date'] or 'none'} (days to follow-up "
                      f"{fu['days_to_followup']}, days overdue {fu['days_overdue']}); open follow-up events for the "
                      f"current milestone: {fu['open_followup_events']}; open not-overdue FOLLOWUP equivalents: "
                      f"{len(ex['open_equivalent_events'])}. (check_followup_status, check_existing_event)")
        elif "rule" in q:
            rule = executor.call("get_milestone_rule", {"milestone_type": state["current_milestone"] or ""})["data"]
            answer = (f"Applicable rules: {', '.join(state['condition_rule_ids'])}. Milestone rule for "
                      f"{state['current_milestone']}: " + (
                          f"follow-up {rule.get('default_followup_days')} days, look-ahead {rule.get('lookahead_days')} "
                          f"days, overdue action {rule.get('overdue_action')}, severity {rule.get('severity')} (synthetic)."
                          if rule.get("found") else "no active rule (RULE-DATA-001)."))
        elif "evidence" in q:
            for name in ("get_current_milestone", "check_followup_status", "calculate_escalation_state"):
                executor.call(name, {"loan_id": loan_id})
            answer = (f"Evidence: {cond_text}. Milestone {state['current_milestone']}, effective follow-up "
                      f"{state['effective_followup_date']}, escalation {state['escalation_state']}, score "
                      f"{score['score']} ({score['priority']}).")
        else:
            narrative = template_narrative(state, state["default_action"], {})
            answer = narrative["rationale"]
        return {"answer": answer, "tool_calls": executor.records, "agent_mode": self.mode}

    def portfolio_briefing(self, facts: list[dict], run: RunContext) -> dict:
        return {"text": deterministic_briefing(facts), "source": "deterministic", "rejected_reason": None}
