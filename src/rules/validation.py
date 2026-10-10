"""Outbound event preparation and validation (RULE-DUPLICATE-002, RULE-VALIDATION-001).

Prepared events are uncommitted drafts. Nothing here writes to the System of Record.
"""
from __future__ import annotations

import hashlib
from datetime import date, timedelta

from src.rules.facts import EngineContext, LoanFacts
from src.verification.verifier import _as_date


def event_type_for(action_type: str, ctx: EngineContext, original_action: dict | None = None) -> str | None:
    spec = ctx.settings.allowed_actions["actions"].get(action_type, {})
    if not spec.get("creates_event"):
        return None
    event_type = spec.get("event_type")
    if event_type == "from_original_action":
        return (original_action or {}).get("event_type") or "FOLLOWUP"
    return event_type


def milestone_for(action_type: str, facts: LoanFacts, original_action: dict | None = None) -> str | None:
    if action_type == "CREATE_NEXT_MILESTONE":
        return facts.next_milestone_type
    if action_type == "RETRY_FAILED_ACTION" and original_action and original_action.get("milestone_type"):
        return original_action["milestone_type"]
    return (facts.current_milestone or {}).get("milestone_type")


def idempotency_key(loan_id: str, action_type: str, milestone: str | None, event_date: date) -> str:
    raw = f"{loan_id}|{action_type}|{milestone or ''}|{event_date.isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def prepare_event(action_type: str, facts: LoanFacts, ctx: EngineContext, followup_date: str | None = None,
                  note: str | None = None, outreach: str | None = None, escalation_target: str | None = None,
                  original_action: dict | None = None) -> dict:
    """Build an uncommitted, loan-servicing-system-compatible outbound event draft."""
    from src.rules.dates import calculate_followup_date

    P = ctx.processing_date
    event_type = event_type_for(action_type, ctx, original_action)
    milestone = milestone_for(action_type, facts, original_action)
    if event_type is None:
        return {"loan_id": facts.loan_id, "action_type": action_type, "event_type": None, "creates_event": False,
                "status": "NO_EVENT", "synthetic_data": True}
    calc = calculate_followup_date(action_type, facts, ctx)
    fu = followup_date or calc["followup_date"]
    party_id = facts.loan.get("assigned_attorney_vendor_id") or None
    party = ctx.parties_by_id.get(party_id or "", {})
    return {
        "loan_id": facts.loan_id,
        "action_type": action_type,
        "event_type": event_type,
        "milestone_type": milestone,
        "event_date": P.isoformat(),
        "followup_date": fu,
        "followup_basis": calc["basis"] if not followup_date else "reviewer edit",
        "event_note": (note or "").strip(),
        "outreach_text": (outreach or "").strip(),
        "assigned_party_id": party_id,
        "assigned_party_type": party.get("party_type"),
        "escalation_target_role": escalation_target if action_type == "ESCALATE_TO_SPECIALIST" else None,
        "retry_of_action_id": (original_action or {}).get("action_id") if action_type == "RETRY_FAILED_ACTION" else None,
        "source_system": "LOAN_SERVICING_INTELLIGENCE",
        "idempotency_key": idempotency_key(facts.loan_id, action_type, milestone, P),
        "creates_event": True,
        "status": "DRAFT_UNCOMMITTED",
        "synthetic_data": True,
    }


def check_existing_event(facts: LoanFacts, event_type: str | None, milestone_type: str | None,
                         action_type: str | None, ctx: EngineContext) -> dict:
    """RULE-DUPLICATE-001/002."""
    P = ctx.processing_date
    equivalent = []
    if event_type == "MILESTONE":
        equivalent = [e for e in facts.events if (e.get("milestone_type") or "") == (milestone_type or "")
                      and e.get("event_type") == "MILESTONE" and e.get("status") != "CANCELLED"]
    elif event_type:
        for e in facts.events:
            if e.get("event_type") != event_type or e.get("status") != "OPEN":
                continue
            if milestone_type and (e.get("milestone_type") or "") != milestone_type:
                continue
            fu = _as_date(e.get("followup_date"))
            if fu is None or fu >= P:
                equivalent.append(e)
    same_pending = bool(facts.pending_action and action_type and facts.pending_action.get("action_type") == action_type)
    open_same_type = {}
    for e in facts.open_followups:
        open_same_type[e["event_type"]] = open_same_type.get(e["event_type"], 0) + 1
    return {
        "open_equivalent_events": [
            {"event_id": e["event_id"], "event_type": e["event_type"], "milestone_type": e.get("milestone_type"),
             "followup_date": str(_as_date(e.get("followup_date")) or ""), "status": e.get("status")}
            for e in equivalent],
        "pending_action_same_type": same_pending,
        "duplicate_risk": bool(equivalent) or same_pending,
        "existing_duplicate_open_events": {k: v for k, v in open_same_type.items() if v >= 2},
        "rule_ids": ["RULE-DUPLICATE-001", "RULE-DUPLICATE-002"],
    }


def validate_proposed_event(draft: dict, facts: LoanFacts, evaluation: dict, ctx: EngineContext,
                            recommendation_fingerprint: str | None = None,
                            recommendation_rule_version: str | None = None) -> dict:
    th = ctx.thresholds
    P = ctx.processing_date
    errors: list[dict] = []
    warnings: list[dict] = []
    action = draft.get("action_type")

    def err(code: str, message: str) -> None:
        errors.append({"code": code, "message": message})

    if action not in evaluation["allowed_actions"]:
        err("ACTION_NOT_ALLOWED", f"{action} is not in allowed actions {evaluation['allowed_actions']}.")
    if not facts.loan.get("is_active", True):
        err("LOAN_INACTIVE", "Loan is not active.")
    if recommendation_fingerprint and recommendation_fingerprint != evaluation["state_fingerprint"]:
        err("STALE_RECOMMENDATION", "Loan state changed since the recommendation was generated; re-run analysis.")
    if recommendation_rule_version and recommendation_rule_version != ctx.settings.rule_version:
        err("STALE_RECOMMENDATION", "Rule version changed since the recommendation was generated.")

    if not draft.get("creates_event"):
        warnings.append({"code": "NO_EVENT_FOR_ACTION", "message": "NO_ACTION produces no outbound event."})
        return {"valid": not errors, "errors": errors, "warnings": warnings, "rule_id": "RULE-VALIDATION-001"}

    expected_type = event_type_for(action, ctx, {"event_type": draft.get("event_type")}) if action else None
    if action != "RETRY_FAILED_ACTION" and draft.get("event_type") != expected_type:
        err("EVENT_TYPE_MISMATCH", f"{action} must create {expected_type}, not {draft.get('event_type')}.")
    fu = _as_date(draft.get("followup_date"))
    horizon = P + timedelta(days=int(th.get("max_followup_horizon_days", 120)))
    if fu is None or fu < P or fu > horizon:
        err("FOLLOWUP_OUT_OF_RANGE", f"Follow-up date must be between {P} and {horizon}.")
    required = ctx.settings.allowed_actions["actions"].get(action, {}).get("requires_party_type")
    if required:
        party = ctx.parties_by_id.get(draft.get("assigned_party_id") or "")
        if not (party and party.get("active") and party.get("party_type") == required):
            err("PARTY_REQUIRED", f"{action} requires an active assigned {required.lower()}.")
    if len(draft.get("event_note") or "") > int(th.get("max_note_length", 1000)):
        err("NOTE_TOO_LONG", "Note exceeds the maximum length.")
    if action != "REVIEW_DATA_EXCEPTION":
        dup = check_existing_event(facts, draft.get("event_type"), draft.get("milestone_type"), action, ctx)
        if dup["duplicate_risk"]:
            err("DUPLICATE_EVENT", "An equivalent open event or pending action already exists.")
    if facts.pending_action and action != "RETRY_FAILED_ACTION":
        err("PENDING_ACTION_EXISTS", f"Action {facts.pending_action['action_id']} is still awaiting verification.")
    return {"valid": not errors, "errors": errors, "warnings": warnings, "rule_id": "RULE-VALIDATION-001"}
