"""Approved-action creation (with revalidation) and submission through the System-of-Record adapter."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from src.rules.validation import prepare_event, validate_proposed_event
from src.services.activity import utcnow
from src.verification.verifier import FAILURE_STATUSES


class ValidationFailed(Exception):
    def __init__(self, errors: list[dict], validation: dict):
        super().__init__("VALIDATION_FAILED")
        self.errors = errors
        self.validation = validation


class InvalidState(Exception):
    pass


def new_action_id() -> str:
    return f"ACT-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"


def original_failed_action(facts) -> dict | None:
    for a in reversed(facts.actions):
        if facts.verifications[a["action_id"]]["verification_status"] in FAILURE_STATUSES:
            return a
    return None


def revalidate(evaluation, rec: dict, action_type: str, followup_date: str | None, note: str | None,
               outreach: str | None, escalation_target: str | None, event_type: str | None = None,
               allow_escalation: bool = False) -> tuple[dict, dict]:
    """Rebuild the outbound draft from current facts and validate it (RULE-VALIDATION-001)."""
    loan_id = rec["loan_id"]
    facts = evaluation.facts[loan_id]
    state = dict(evaluation.results[loan_id])
    if allow_escalation and "ESCALATE_TO_SPECIALIST" not in state["allowed_actions"]:
        state["allowed_actions"] = state["allowed_actions"] + ["ESCALATE_TO_SPECIALIST"]
    original = original_failed_action(facts) if action_type == "RETRY_FAILED_ACTION" else None
    draft = prepare_event(action_type, facts, evaluation.ctx, followup_date, note, outreach, escalation_target, original)
    if event_type and draft.get("creates_event") and action_type == "RETRY_FAILED_ACTION":
        draft["event_type"] = event_type
    validation = validate_proposed_event(draft, facts, state, evaluation.ctx, rec.get("state_fingerprint"),
                                         rec.get("rule_version"))
    return draft, validation


def build_action(rec: dict, decision: dict, draft: dict, reviewer_id: str, adapter_mode: str) -> dict:
    action_id = new_action_id()
    payload = {**draft, "status": "APPROVED_FOR_SUBMISSION", "action_id": action_id,
               "recommendation_id": rec["recommendation_id"], "decision_id": decision["decision_id"],
               "approved_by": reviewer_id}
    return {
        "action_id": action_id,
        "loan_id": rec["loan_id"],
        "recommendation_id": rec["recommendation_id"],
        "decision_id": decision["decision_id"],
        "action_type": draft["action_type"],
        "event_type": draft["event_type"],
        "milestone_type": draft.get("milestone_type") or "",
        "event_date": draft["event_date"],
        "followup_date": draft.get("followup_date"),
        "note": draft.get("event_note"),
        "outreach": draft.get("outreach_text"),
        "status": "APPROVED",
        "outbound_payload": payload,
        "adapter_mode": adapter_mode,
        "adapter_result": {},
        "approved_by": reviewer_id,
        "approved_at": utcnow(),
        "submitted_at": None,
        "verified_at": None,
        "failure_reason": None,
        "retry_of_action_id": draft.get("retry_of_action_id"),
        "synthetic_data": True,
    }


def write_outbound_file(directory, action: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{action['action_id']}.json").write_text(json.dumps(action["outbound_payload"], indent=2, default=str),
                                                          encoding="utf-8")


def submit(action: dict, adapter, evaluation, cycle: int) -> tuple[dict, list[dict]]:
    """Submit an APPROVED action through the adapter. Returns (updated_action, sor_rows)."""
    if action.get("status") != "APPROVED":
        raise InvalidState(f"Action {action['action_id']} is {action.get('status')}, not APPROVED")
    facts = evaluation.facts[action["loan_id"]]
    result = adapter.submit(action["outbound_payload"], action, cycle, facts.events, evaluation.processing_date)
    updated = dict(action)
    updated["submitted_at"] = utcnow()
    updated["adapter_mode"] = result["mode"]
    updated["adapter_result"] = {k: v for k, v in result.items() if k != "sor_events"}
    if result["accepted"]:
        updated["status"] = "SUBMITTED"
    else:
        updated["status"] = "FAILED"
        updated["failure_reason"] = result["message"]
    return updated, result["sor_events"]
