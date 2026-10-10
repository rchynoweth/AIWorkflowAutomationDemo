"""Source refresh and verification of submitted actions."""
from __future__ import annotations

import uuid

from src.services.activity import utcnow
from src.verification.verifier import FAILURE_STATUSES

RECHECK_STATUSES = {"SUBMITTED", "VERIFICATION_FAILED"}


def verify_submitted_actions(evaluation, ops_actions: dict[str, dict], cycle: int) -> tuple[list[dict], list[dict]]:
    """Return (verification_result_rows, updated_actions) for app-submitted actions after a refresh."""
    results, updated = [], []
    for action in ops_actions.values():
        if action.get("status") not in RECHECK_STATUSES:
            continue
        facts = evaluation.facts.get(action["loan_id"])
        if facts is None or action["action_id"] not in facts.verifications:
            continue
        v = facts.verifications[action["action_id"]]
        results.append({
            "verification_id": f"VER-{uuid.uuid4().hex[:12]}",
            "action_id": action["action_id"],
            "loan_id": action["loan_id"],
            "cycle": cycle,
            "verification_status": v["verification_status"],
            "matched_event_ids": v["matched_event_ids"],
            "differences": v["differences"],
            "detail": v["detail"],
            "evaluated_at": utcnow(),
        })
        new_status = action["status"]
        if v["verification_status"] == "VERIFIED":
            new_status = "VERIFIED"
        elif v["verification_status"] in FAILURE_STATUSES:
            new_status = "VERIFICATION_FAILED"
        if new_status != action["status"]:
            changed = dict(action, status=new_status)
            if new_status == "VERIFIED":
                changed["verified_at"] = utcnow()
            updated.append(changed)
    return results, updated
