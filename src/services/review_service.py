"""Human review decisions: APPROVE, EDIT, REJECT, DEFER, ESCALATE."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from src.services.action_service import InvalidState, ValidationFailed, revalidate
from src.services.activity import utcnow


def new_decision_id() -> str:
    return f"DEC-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"


def resolve_decision(rec: dict, request, evaluation) -> tuple[dict, dict | None, dict | None]:
    """Return (decision_record, draft_or_None, validation_or_None). Raises ValidationFailed / InvalidState."""
    if rec.get("status") != "PENDING_REVIEW":
        raise InvalidState(f"Recommendation {rec['recommendation_id']} is {rec.get('status')}")
    decision = request.decision
    edits = request.edits.model_dump(exclude_none=True) if request.edits else {}
    action_type = rec["recommended_action"]
    followup = rec.get("recommended_followup_date")
    note = rec.get("suggested_note")
    outreach = rec.get("suggested_outreach")
    target = None
    if decision == "EDIT":
        action_type = (edits.get("action_type") or action_type).upper()
        if edits.get("action_type") and edits["action_type"].upper() != rec["recommended_action"]:
            followup = None  # recalculate for the new action unless the reviewer set one
        followup = edits.get("followup_date") or followup
        note = edits.get("note", note)
        outreach = edits.get("outreach", outreach)
        target = edits.get("escalation_target")
    elif decision == "ESCALATE":
        action_type = "ESCALATE_TO_SPECIALIST"
        followup = edits.get("followup_date")
        target = edits.get("escalation_target") or (
            "SERVICING_MANAGER" if rec.get("escalation_state") == "CRITICAL" else "SENIOR_SPECIALIST")
        note = edits.get("note") or f"Escalated by reviewer: {request.reason or rec['primary_condition']}"

    record = {
        "decision_id": new_decision_id(),
        "recommendation_id": rec["recommendation_id"],
        "loan_id": rec["loan_id"],
        "reviewer_id": request.reviewer_id,
        "reviewer_role": request.reviewer_role,
        "decision": decision,
        "original_action": rec["recommended_action"],
        "final_action": action_type if decision in ("APPROVE", "EDIT", "ESCALATE") else None,
        "original_followup_date": rec.get("recommended_followup_date"),
        "final_followup_date": followup if decision in ("APPROVE", "EDIT", "ESCALATE") else None,
        "original_note": rec.get("suggested_note"),
        "final_note": note if decision in ("APPROVE", "EDIT", "ESCALATE") else None,
        "edits": edits,
        "comment": request.comment,
        "reason": request.reason,
        "decided_at": utcnow(),
        "synthetic_data": True,
    }
    if decision in ("REJECT", "DEFER") or action_type == "NO_ACTION":
        return record, None, None
    draft, validation = revalidate(evaluation, rec, action_type, followup, note, outreach, target,
                                   event_type=edits.get("event_type"), allow_escalation=(decision == "ESCALATE"))
    if not validation["valid"]:
        raise ValidationFailed(validation["errors"], validation)
    record["final_followup_date"] = draft.get("followup_date")
    return record, draft, validation


STATUS_FOR_DECISION = {"APPROVE": "APPROVED", "EDIT": "APPROVED", "REJECT": "REJECTED", "DEFER": "DEFERRED",
                       "ESCALATE": "ESCALATED"}
