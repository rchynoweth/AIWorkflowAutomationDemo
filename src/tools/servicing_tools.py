"""Deterministic servicing tools used by the Loan Servicing Agent (docs/AGENT_TOOLS.md).

Every tool is read-only with respect to the System of Record. Preparation tools return uncommitted drafts.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from src.rules.dates import calculate_followup_date as _calc_followup
from src.rules.facts import LoanFacts
from src.rules.validation import check_existing_event as _check_existing
from src.rules.validation import prepare_event, validate_proposed_event as _validate
from src.services.portfolio_engine import PortfolioEvaluation
from src.services.state import OperationalState
from src.transformations import gold
from src.verification.verifier import FAILURE_STATUSES, _as_date, compare_fields, find_candidate_events


class ToolError(Exception):
    """Raised for expected tool failures (e.g. LOAN_NOT_FOUND)."""


@dataclass
class ToolContext:
    evaluation: PortfolioEvaluation
    ops: OperationalState
    settings: Any

    @property
    def processing_date(self) -> date:
        return self.evaluation.processing_date

    def facts(self, loan_id: str) -> LoanFacts:
        facts = self.evaluation.facts.get((loan_id or "").strip().upper())
        if facts is None:
            raise ToolError("LOAN_NOT_FOUND")
        return facts

    def result(self, loan_id: str) -> dict:
        self.facts(loan_id)
        return self.evaluation.results[loan_id.strip().upper()]


def _s(value: Any) -> Any:
    """JSON-safe scalar."""
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:  # noqa: BLE001
            return str(value)
    if isinstance(value, float) and value != value:
        return None
    return value


def _event(ev: dict) -> dict:
    return {k: _s(ev.get(k)) for k in ("event_id", "event_type", "milestone_type", "event_date", "followup_date",
                                       "completed_date", "status", "source", "event_note")}


# ---- loan context and history -------------------------------------------------------------
def get_loan_context(ctx: ToolContext, loan_id: str) -> dict:
    f = ctx.facts(loan_id)
    loan = f.loan
    keys = ["loan_id", "borrower_display_name", "property_city", "property_state", "property_county",
            "portfolio_id", "original_balance", "current_balance", "loan_status", "payment_status", "days_delinquent",
            "foreclosure_status", "boarding_date", "assigned_specialist_id", "specialist_name",
            "assigned_attorney_vendor_id", "party_name", "party_type", "is_active", "synthetic_data"]
    return {k: _s(loan.get(k)) for k in keys}


def get_event_history(ctx: ToolContext, loan_id: str, limit: int = 50, include_payments: bool = False) -> dict:
    f = ctx.facts(loan_id)
    events = [e for e in f.events if include_payments or e.get("event_type") != "PAYMENT_RECEIVED"]
    return {"loan_id": f.loan_id, "event_count": len(events), "events": [_event(e) for e in events[-limit:]]}


def get_current_milestone(ctx: ToolContext, loan_id: str) -> dict:
    f = ctx.facts(loan_id)
    if not f.current_milestone:
        return {"loan_id": f.loan_id, "has_servicing_track": False, "rule_id": "RULE-MILESTONE-001"}
    cm = f.current_milestone
    return {"loan_id": f.loan_id, "has_servicing_track": True, **_event(cm),
            "milestone_sequence": cm.get("milestone_sequence"), "rule_found": f.rule_found,
            "rule_id": "RULE-MILESTONE-001"}


def check_milestone_completion(ctx: ToolContext, loan_id: str) -> dict:
    f = ctx.facts(loan_id)
    cm = f.current_milestone or {}
    return {"loan_id": f.loan_id, "milestone_type": cm.get("milestone_type"), "is_complete": f.milestone_complete,
            "completed_date": _s(_as_date(cm.get("completed_date"))), "status": cm.get("status"),
            "conflicts": f.milestone_conflicts, "rule_ids": ["RULE-MILESTONE-002", "RULE-DATA-002"]}


def check_followup_status(ctx: ToolContext, loan_id: str) -> dict:
    f = ctx.facts(loan_id)
    r = ctx.result(loan_id)
    followup_codes = [c["code"] for c in r["raw_conditions"]
                      if c["code"] in ("OVERDUE", "DUE", "UPCOMING", "MISSING_FOLLOWUP")]
    return {"loan_id": f.loan_id, "milestone_type": r["current_milestone"],
            "effective_followup_date": r["effective_followup_date"],
            "source_event_id": f.effective_followup_event_id, "days_to_followup": f.days_to_followup,
            "days_overdue": f.days_overdue, "lookahead_days": (f.rule or {}).get("lookahead_days"),
            "followup_condition": followup_codes[0] if followup_codes else "ON_TRACK_OR_NOT_APPLICABLE",
            "open_followup_events": len(f.open_followups),
            "rule_ids": ["RULE-FOLLOWUP-001", "RULE-FOLLOWUP-002", "RULE-FOLLOWUP-003", "RULE-FOLLOWUP-004",
                         "RULE-FOLLOWUP-005"]}


def calculate_days_to_followup(ctx: ToolContext, loan_id: str | None = None, followup_date: str | None = None) -> dict:
    if followup_date:
        fu = _as_date(followup_date)
    else:
        fu = ctx.facts(loan_id).effective_followup_date
    if fu is None:
        return {"followup_date": None, "days_to_followup": None, "days_overdue": None}
    days = (fu - ctx.processing_date).days
    return {"followup_date": fu.isoformat(), "processing_date": ctx.processing_date.isoformat(),
            "days_to_followup": days, "days_overdue": max(0, -days)}


def get_next_required_milestone(ctx: ToolContext, loan_id: str) -> dict:
    f = ctx.facts(loan_id)
    nxt = f.next_milestone_type
    rule = ctx.evaluation.ctx.rules_by_type.get(nxt or "", {})
    return {"loan_id": f.loan_id, "current_milestone": (f.current_milestone or {}).get("milestone_type"),
            "next_milestone_type": nxt, "exists_already": f.next_milestone_exists,
            "default_followup_days": rule.get("default_followup_days"), "rule_id": "RULE-MILESTONE-003"}


def get_milestone_rule(ctx: ToolContext, milestone_type: str) -> dict:
    mt = (milestone_type or "").strip().upper()
    rule = ctx.evaluation.ctx.rules_by_type.get(mt)
    if rule is None:
        inactive = ctx.evaluation.ctx.all_rules_by_type.get(mt)
        return {"milestone_type": mt, "found": False, "inactive_rule_exists": inactive is not None,
                "rule_id": "RULE-DATA-001"}
    return {"found": True, **{k: _s(v) for k, v in rule.items() if k != "dq_issues"}, "synthetic_assumption": True}


# ---- duplicate, pending, review checks ----------------------------------------------------
def check_existing_event(ctx: ToolContext, loan_id: str, event_type: str, milestone_type: str | None = None,
                         action_type: str | None = None) -> dict:
    f = ctx.facts(loan_id)
    mt = milestone_type or (f.current_milestone or {}).get("milestone_type")
    return {"loan_id": f.loan_id, "event_type": event_type, "milestone_type": mt,
            **_check_existing(f, event_type, mt, action_type, ctx.evaluation.ctx)}


def check_pending_recommendation(ctx: ToolContext, loan_id: str) -> dict:
    f = ctx.facts(loan_id)
    pending = [r for r in ctx.ops.recommendations_for(f.loan_id) if r.get("status") in ("PENDING_REVIEW", "DEFERRED")]
    return {"loan_id": f.loan_id, "pending_recommendations": [
        {k: r.get(k) for k in ("recommendation_id", "status", "recommended_action", "created_at", "agent_mode")}
        for r in pending], "has_pending": bool(pending)}


def check_pending_action(ctx: ToolContext, loan_id: str) -> dict:
    f = ctx.facts(loan_id)
    pending = []
    for a in f.actions:
        v = f.verifications[a["action_id"]]
        if v["verification_status"] == "PENDING":
            pending.append({"action_id": a["action_id"], "action_type": a.get("action_type"),
                            "status": a.get("status"), "verification_status": "PENDING",
                            "event_date": _s(a.get("event_date")), "followup_date": _s(a.get("followup_date"))})
    return {"loan_id": f.loan_id, "pending_actions": pending, "has_pending": bool(pending),
            "rule_id": "RULE-PENDING-001"}


def check_previous_rejection(ctx: ToolContext, loan_id: str) -> dict:
    f = ctx.facts(loan_id)
    rejections = [{"decision_id": d["decision_id"], "original_action": d.get("original_action"),
                   "reason": d.get("reason"), "decided_at": _s(d.get("decided_at"))}
                  for d in f.decisions if d.get("decision") == "REJECT"]
    return {"loan_id": f.loan_id, "rejections": rejections[-5:], "rejected_actions_in_lookback": f.prior_rejected_actions,
            "lookback_days": ctx.settings.thresholds.get("prior_rejection_lookback_days"),
            "rule_id": "RULE-REVIEW-001"}


def get_assigned_party(ctx: ToolContext, loan_id: str) -> dict:
    f = ctx.facts(loan_id)
    ectx = ctx.evaluation.ctx
    spec = ectx.specialists_by_id.get(f.loan.get("assigned_specialist_id") or "", {})
    party = ectx.parties_by_id.get(f.loan.get("assigned_attorney_vendor_id") or "", {})
    return {"loan_id": f.loan_id,
            "specialist": {"id": spec.get("specialist_id"), "name": spec.get("display_name"),
                           "team": spec.get("team"), "active": bool(spec.get("active"))},
            "party": {"id": party.get("party_id"), "name": party.get("display_name"),
                      "type": party.get("party_type"), "active": bool(party.get("active"))} if party else None,
            "required_party_type": f.required_party_type, "party_ok": f.party_ok, "specialist_ok": f.specialist_ok,
            "rule_ids": ["RULE-DATA-003", "RULE-DATA-004"]}


# ---- escalation, scoring, actions ----------------------------------------------------------
def calculate_escalation_state(ctx: ToolContext, loan_id: str) -> dict:
    r = ctx.result(loan_id)
    return {"loan_id": r["loan_id"], "escalation_state": r["escalation_state"],
            "escalation_reasons": r["escalation_reasons"], "required_role": r["required_role"],
            "allowed_actions": r["allowed_actions"], "health_segment": r["health_segment"],
            "escalation_version": ctx.settings.escalation_version}


def calculate_loan_attention_score(ctx: ToolContext, loan_id: str) -> dict:
    r = ctx.result(loan_id)
    return {"loan_id": r["loan_id"], "score": r["attention_score"], "priority": r["priority"],
            "score_drivers": r["score_drivers"], "primary_condition": r["primary_condition"],
            "secondary_conditions": r["secondary_conditions"], "calculated_at": r["calculated_at"],
            "scoring_version": r["scoring_version"]}


def get_attention_score_drivers(ctx: ToolContext, loan_id: str) -> dict:
    r = ctx.result(loan_id)
    drivers = sorted(r["score_drivers"], key=lambda d: d["points"], reverse=True)
    return {"loan_id": r["loan_id"], "score": r["attention_score"], "priority": r["priority"],
            "score_drivers": drivers, "summary": r["top_drivers_text"]}


def get_allowed_actions(ctx: ToolContext, loan_id: str) -> dict:
    r = ctx.result(loan_id)
    return {"loan_id": r["loan_id"], "primary_condition": r["primary_condition"],
            "allowed_actions": r["allowed_actions"], "default_action": r["default_action"],
            "removed_actions": r["removed_actions"], "rule_id": "RULE-ACTIONS-001"}


def calculate_followup_date(ctx: ToolContext, loan_id: str, action_type: str) -> dict:
    f = ctx.facts(loan_id)
    return {"loan_id": f.loan_id, "action_type": action_type, **_calc_followup(action_type, f, ctx.evaluation.ctx)}


def _original_failed_action(f: LoanFacts) -> dict | None:
    for a in reversed(f.actions):
        if f.verifications[a["action_id"]]["verification_status"] in FAILURE_STATUSES:
            return a
    return None


def prepare_followup_event(ctx: ToolContext, loan_id: str, action_type: str, followup_date: str | None = None,
                           note: str | None = None, outreach: str | None = None) -> dict:
    f = ctx.facts(loan_id)
    original = _original_failed_action(f) if action_type == "RETRY_FAILED_ACTION" else None
    return prepare_event(action_type, f, ctx.evaluation.ctx, followup_date, note, outreach, None, original)


def prepare_escalation(ctx: ToolContext, loan_id: str, reason: str | None = None, target_role: str | None = None) -> dict:
    f = ctx.facts(loan_id)
    r = ctx.result(loan_id)
    role = target_role or ("SERVICING_MANAGER" if r["escalation_state"] == "CRITICAL" else "SENIOR_SPECIALIST")
    draft = prepare_event("ESCALATE_TO_SPECIALIST", f, ctx.evaluation.ctx, None,
                          reason or f"Escalation: {r['primary_condition']} ({r['escalation_state']}).", None, role)
    return {**draft, "required_role": role, "escalation_reasons": r["escalation_reasons"]}


def validate_proposed_event(ctx: ToolContext, loan_id: str, action_type: str, event_type: str | None = None,
                            followup_date: str | None = None, note: str | None = None,
                            recommendation_fingerprint: str | None = None) -> dict:
    f = ctx.facts(loan_id)
    draft = prepare_followup_event(ctx, loan_id, action_type, followup_date, note)
    if event_type and draft.get("creates_event"):
        draft["event_type"] = event_type
    return _validate(draft, f, ctx.result(loan_id), ctx.evaluation.ctx, recommendation_fingerprint)


# ---- verification -------------------------------------------------------------------------
def _find_action(ctx: ToolContext, action_id: str) -> tuple[dict, LoanFacts]:
    for f in ctx.evaluation.facts.values():
        for a in f.actions:
            if a["action_id"] == action_id:
                return a, f
    raise ToolError("ACTION_NOT_FOUND")


def verify_servicing_event_created(ctx: ToolContext, action_id: str) -> dict:
    action, f = _find_action(ctx, action_id)
    return {**f.verifications[action_id], "action_type": action.get("action_type")}


def compare_approved_to_actual(ctx: ToolContext, action_id: str) -> dict:
    action, f = _find_action(ctx, action_id)
    candidates = find_candidate_events(action, f.events)
    approved = {k: _s(action.get(k)) for k in ("event_type", "event_date", "followup_date", "milestone_type")}
    return {"action_id": action_id, "approved": approved, "actual": [_event(c) for c in candidates],
            "differences": compare_fields(action, candidates[0]) if len(candidates) == 1 else [],
            "match_count": len(candidates), "rule_id": "RULE-VERIFICATION-002"}


# ---- portfolio tools -----------------------------------------------------------------------
def get_portfolio_health_summary(ctx: ToolContext) -> dict:
    ops_actions = list(ctx.ops.actions.values())
    return {"processing_date": ctx.processing_date.isoformat(),
            **gold.portfolio_kpis(ctx.evaluation, list(ctx.ops.recommendations.values()), ops_actions),
            "health_segments": gold.health_segments(ctx.evaluation)}


def get_priority_queue(ctx: ToolContext, limit: int = 20, priority: str | None = None,
                       condition: str | None = None) -> dict:
    rows = gold.priority_queue_rows(ctx.evaluation, list(ctx.ops.recommendations.values()))
    if priority:
        rows = [r for r in rows if r["priority"] == priority.upper()]
    if condition:
        rows = [r for r in rows if r["primary_condition"] == condition.upper()]
    keep = ("queue_rank", "priority", "loan_id", "primary_condition", "attention_score", "current_milestone",
            "days_overdue", "top_drivers_text", "recommended_action")
    return {"count": len(rows), "rows": [{k: r[k] for k in keep} for r in rows[:limit]]}


def get_portfolio_exceptions(ctx: ToolContext, limit: int = 50) -> dict:
    rows = []
    for r in ctx.evaluation.active_results():
        exc = [c for c in r["raw_conditions"] if c["code"] in ("DATA_EXCEPTION", "DUPLICATE_RISK")]
        if exc:
            rows.append({"loan_id": r["loan_id"], "priority": r["priority"], "conditions": exc})
    return {"count": len(rows), "rows": rows[:limit]}


def get_specialist_workload_summary(ctx: ToolContext) -> dict:
    summary: dict[str, dict] = {}
    for r in ctx.evaluation.active_results():
        key = r["specialist_name"] or "Unassigned"
        s = summary.setdefault(key, {"specialist": key, "assigned": 0, "need_attention": 0, "critical": 0, "high": 0})
        s["assigned"] += 1
        s["need_attention"] += int(r["needs_attention"])
        s["critical"] += int(r["priority"] == "CRITICAL")
        s["high"] += int(r["priority"] == "HIGH")
    return {"specialists": sorted(summary.values(), key=lambda s: -s["need_attention"])}


def get_recommendations_awaiting_approval(ctx: ToolContext, limit: int = 50) -> dict:
    recs = [r for r in ctx.ops.recommendations.values() if r.get("status") == "PENDING_REVIEW"]
    recs.sort(key=lambda r: -int(r.get("attention_score") or 0))
    return {"count": len(recs), "rows": [
        {k: r.get(k) for k in ("recommendation_id", "loan_id", "priority", "attention_score", "recommended_action",
                               "confidence", "created_at", "agent_mode")} for r in recs[:limit]]}


def get_failed_verifications(ctx: ToolContext, limit: int = 50) -> dict:
    rows = [{k: _s(v.get(k)) for k in ("action_id", "loan_id", "action_type", "verification_status", "detail")}
            for v in ctx.evaluation.all_verifications() if v["verification_status"] in FAILURE_STATUSES]
    return {"count": len(rows), "rows": rows[:limit]}
