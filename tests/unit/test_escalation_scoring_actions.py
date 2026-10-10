"""Escalation, attention scoring, allowed actions, prior rejection, pending state."""
from src.scoring.attention import priority_for
from tests.conftest import loan


def test_escalation_states(evaluation):
    assert evaluation.get(loan(6))["escalation_state"] == "CRITICAL"
    assert evaluation.get(loan(6))["required_role"] == "SERVICING_MANAGER"
    assert evaluation.get(loan(12))["escalation_state"] == "ESCALATE"  # missing party
    assert evaluation.get(loan(16))["escalation_state"] == "ESCALATE"  # verification failure
    assert evaluation.get(loan(5))["escalation_state"] == "FOLLOW_UP"
    assert evaluation.get(loan(2))["escalation_state"] == "WATCH"
    assert evaluation.get(loan(1))["escalation_state"] == "NONE"
    reasons = {r["rule_id"] for r in evaluation.get(loan(6))["escalation_reasons"]}
    assert "RULE-ESCALATION-001" in reasons


def test_pending_action_does_not_escalate_overdue(evaluation):
    s19 = evaluation.get(loan(19))
    assert s19["escalation_state"] == "WATCH"
    assert s19["needs_attention"] is False


def test_score_is_explainable_sum(evaluation):
    s05 = evaluation.get(loan(5))
    assert s05["attention_score"] == 54
    assert sum(d["points"] for d in s05["score_drivers"]) == 54
    factors = {d["factor"]: d["points"] for d in s05["score_drivers"]}
    assert factors == {"primary_condition": 30, "days_overdue": 18, "milestone_severity": 6}


def test_score_caps_and_dampener(evaluation):
    s06 = evaluation.get(loan(6))
    assert {d["factor"]: d["points"] for d in s06["score_drivers"]}["days_overdue"] == 30  # capped
    s19 = evaluation.get(loan(19))
    assert any(d["factor"] == "covered_by_pending_action" and d["points"] == -30 for d in s19["score_drivers"])
    assert s19["priority"] == "LOW"


def test_priority_thresholds(settings):
    th = settings.attention_scoring["priority_thresholds"]
    assert priority_for(70, th) == "CRITICAL"
    assert priority_for(69, th) == "HIGH"
    assert priority_for(45, th) == "HIGH"
    assert priority_for(20, th) == "MEDIUM"
    assert priority_for(0, th) == "LOW"


def test_allowed_actions_by_condition(evaluation):
    assert evaluation.get(loan(5))["allowed_actions"] == ["CONTACT_ATTORNEY", "CREATE_FOLLOWUP", "REQUEST_INFORMATION"]
    assert evaluation.get(loan(7))["default_action"] == "CREATE_NEXT_MILESTONE"
    assert evaluation.get(loan(1))["allowed_actions"] == ["NO_ACTION"]


def test_critical_prepends_escalation(evaluation):
    assert evaluation.get(loan(6))["allowed_actions"][0] == "ESCALATE_TO_SPECIALIST"


def test_prior_rejection_removes_action(evaluation):
    s13 = evaluation.get(loan(13))
    assert "CONTACT_ATTORNEY" not in s13["allowed_actions"]
    assert s13["default_action"] == "CREATE_FOLLOWUP"
    assert any(r["rule_id"] == "RULE-REVIEW-001" for r in s13["removed_actions"])


def test_verification_override_for_mismatch(evaluation):
    s17 = evaluation.get(loan(17))
    assert s17["latest_verification_status"] == "MISMATCH"
    assert s17["default_action"] == "REVIEW_DATA_EXCEPTION"


def test_pending_state(evaluation):
    assert evaluation.get(loan(14))["pending_action_id"] is not None
    assert evaluation.get(loan(14))["latest_verification_status"] == "PENDING"
