"""Synthetic adapter modes, review decisions, revalidation, schemas."""
from datetime import date

import pytest

from src.service import InvalidState, SyntheticServicingSystemAdapter, ValidationFailed
from src.models import DecisionEdits, DecisionRequest, Recommendation

OUTBOUND = {"loan_id": "LSI-SYN-000005", "event_type": "CONTACT", "milestone_type": "TITLE_REVIEW",
            "event_date": "2026-10-12", "followup_date": "2026-10-19", "event_note": "n"}
ACTION = {"action_id": "ACT-X"}
OPEN = [{"event_id": "E1", "loan_id": "LSI-SYN-000005", "event_type": "FOLLOWUP", "milestone_type": "TITLE_REVIEW",
         "status": "OPEN", "is_followup_type": True, "event_date": "2026-10-01", "followup_date": "2026-10-05"}]


def adapter(mode):
    return SyntheticServicingSystemAdapter({"adapter": {"default_mode": mode}}, ["FOLLOWUP", "CONTACT"])


def test_adapter_success_supersedes_open_followups():
    res = adapter("SUCCESS").submit(OUTBOUND, ACTION, 0, OPEN, date(2026, 10, 12))
    assert res["accepted"] and len(res["sor_events"]) == 2
    new, closed = res["sor_events"]
    assert "[ref ACT-X]" in new["event_note"] and new["available_cycle"] == 1
    assert closed["event_id"] == "E1" and closed["status"] == "COMPLETED"


def test_adapter_failure_mismatch_duplicate_delayed():
    assert not adapter("FAIL").submit(OUTBOUND, ACTION, 0, OPEN, date(2026, 10, 12))["accepted"]
    mm = adapter("MISMATCH").submit(OUTBOUND, ACTION, 0, [], date(2026, 10, 12))
    assert mm["sor_events"][0]["followup_date"] == "2026-10-26"
    dup = adapter("DUPLICATE").submit(OUTBOUND, ACTION, 0, OPEN, date(2026, 10, 12))
    assert len(dup["sor_events"]) == 2 and all(e["event_id"].startswith("EVT-SOR") for e in dup["sor_events"])
    delayed = adapter("DELAYED").submit(OUTBOUND, ACTION, 3, [], date(2026, 10, 12))
    assert delayed["sor_events"][0]["available_cycle"] == 6


def test_reject_requires_no_action_and_records_decision(service):
    rec = service.analyze_loan("LSI-SYN-000004")["recommendation"]  # 1 day overdue
    out = service.decide(rec["recommendation_id"], DecisionRequest(decision="REJECT", reason="not now"))
    assert out["action"] is None and out["recommendation"]["status"] == "REJECTED"
    assert out["decision"]["original_action"] == "CONTACT_ATTORNEY"
    # RULE-REVIEW-001: the rejected action is removed while escalation stays below ESCALATE
    assert "CONTACT_ATTORNEY" not in service.evaluation.get("LSI-SYN-000004")["allowed_actions"]


def test_rejection_on_long_overdue_loan_escalates(service):
    rec = service.analyze_loan("LSI-SYN-000005")["recommendation"]  # 18 days overdue
    service.decide(rec["recommendation_id"], DecisionRequest(decision="REJECT", reason="not now"))
    state = service.evaluation.get("LSI-SYN-000005")
    assert state["escalation_state"] == "ESCALATE"  # RULE-ESCALATION-008
    assert "ESCALATE_TO_SPECIALIST" in state["allowed_actions"]


def test_cannot_decide_twice(service):
    rec = service.analyze_loan("LSI-SYN-000005")["recommendation"]
    service.decide(rec["recommendation_id"], DecisionRequest(decision="DEFER"))
    with pytest.raises(InvalidState):
        service.decide(rec["recommendation_id"], DecisionRequest(decision="APPROVE"))


def test_edit_is_revalidated(service):
    rec = service.analyze_loan("LSI-SYN-000005")["recommendation"]
    with pytest.raises(ValidationFailed) as exc:
        service.decide(rec["recommendation_id"], DecisionRequest(
            decision="EDIT", edits=DecisionEdits(action_type="CREATE_NEXT_MILESTONE")))
    assert exc.value.errors[0]["code"] == "ACTION_NOT_ALLOWED"
    out = service.decide(rec["recommendation_id"], DecisionRequest(
        decision="EDIT", edits=DecisionEdits(followup_date="2026-10-16", note="edited note")))
    assert out["action"]["followup_date"] == "2026-10-16" and out["action"]["note"] == "edited note"
    assert out["decision"]["edits"]["followup_date"] == "2026-10-16"


def test_escalate_creates_escalation_action(service):
    rec = service.analyze_loan("LSI-SYN-000005")["recommendation"]
    out = service.decide(rec["recommendation_id"], DecisionRequest(
        decision="ESCALATE", edits=DecisionEdits(escalation_target="SENIOR_SPECIALIST")))
    assert out["action"]["action_type"] == "ESCALATE_TO_SPECIALIST"
    assert out["action"]["outbound_payload"]["escalation_target_role"] == "SENIOR_SPECIALIST"


def test_stale_recommendation_blocked(service):
    rec = service.analyze_loan("LSI-SYN-000005")["recommendation"]
    service.ops.recommendations[rec["recommendation_id"]]["state_fingerprint"] = "stale"
    with pytest.raises(ValidationFailed) as exc:
        service.decide(rec["recommendation_id"], DecisionRequest(decision="APPROVE"))
    assert exc.value.errors[0]["code"] == "STALE_RECOMMENDATION"


def test_recommendation_schema_validates(service):
    rec = service.analyze_loan("LSI-SYN-000006")["recommendation"]
    model = Recommendation(**rec)
    assert model.recommended_action == "ESCALATE_TO_SPECIALIST"
