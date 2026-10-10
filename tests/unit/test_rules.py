"""Conditions, precedence, follow-up/look-ahead/overdue logic, sequencing, completion, dates."""
from datetime import date

import pytest

from src.rules.conditions import select_primary
from src.rules.dates import calculate_followup_date, roll_to_business_day
from tests.conftest import loan


def codes(evaluation, n):
    return {c["code"] for c in evaluation.get(loan(n))["raw_conditions"]}


@pytest.mark.parametrize("n,expected", [
    (1, "NO_ACTION"), (2, "UPCOMING"), (3, "DUE"), (4, "OVERDUE"), (5, "OVERDUE"), (6, "OVERDUE"),
    (7, "COMPLETED_NEEDS_NEXT"), (8, "MISSING_FOLLOWUP"), (9, "DUPLICATE_RISK"), (10, "DATA_EXCEPTION"),
    (11, "DATA_EXCEPTION"), (12, "DATA_EXCEPTION"), (14, "PENDING_ACTION"), (16, "VERIFICATION_FAILURE"),
    (19, "ALREADY_ACTIONED"), (20, "PENDING_REVIEW"),
])
def test_primary_condition(evaluation, n, expected):
    assert evaluation.get(loan(n))["primary_condition"] == expected


def test_overdue_days_and_lookahead(evaluation):
    assert evaluation.get(loan(4))["days_overdue"] == 1
    assert evaluation.get(loan(5))["days_overdue"] == 18
    assert evaluation.get(loan(6))["days_overdue"] == 75
    assert evaluation.get(loan(2))["days_to_followup"] == 5
    assert evaluation.get(loan(3))["days_to_followup"] == 0


def test_current_milestone_is_highest_sequence(evaluation):
    facts = evaluation.facts[loan(6)]
    seqs = [e["milestone_sequence"] for e in facts.milestone_events]
    assert facts.current_milestone["milestone_sequence"] == max(seqs)
    assert facts.current_milestone["milestone_type"] == "JUDGMENT_HEARING"


def test_completion_and_conflicts(evaluation):
    assert evaluation.facts[loan(7)].milestone_complete
    assert "COMPLETED_BEFORE_EVENT" in evaluation.facts[loan(10)].milestone_conflicts
    rule_ids = evaluation.get(loan(10))["condition_rule_ids"]
    assert "RULE-DATA-002" in rule_ids


def test_missing_rule_and_missing_party(evaluation):
    assert "RULE-DATA-001" in evaluation.get(loan(11))["condition_rule_ids"]
    s12 = evaluation.get(loan(12))
    assert "RULE-DATA-003" in s12["condition_rule_ids"]
    assert {"DATA_EXCEPTION", "OVERDUE"} <= codes(evaluation, 12)


def test_multiple_unresolved_conditions(evaluation):
    s18 = evaluation.get(loan(18))
    assert {"DATA_EXCEPTION", "DUPLICATE_RISK", "OVERDUE"} <= codes(evaluation, 18)
    assert s18["primary_condition"] == "DATA_EXCEPTION"
    assert set(s18["secondary_conditions"]) == {"DUPLICATE_RISK", "OVERDUE"}


def test_effective_followup_uses_latest_open_followup(evaluation):
    facts = evaluation.facts[loan(9)]
    assert facts.effective_followup_date.isoformat() == "2026-11-02"  # P+21
    assert len(facts.open_followups) == 2


def test_select_primary_respects_precedence():
    raw = [{"code": "UPCOMING"}, {"code": "OVERDUE"}, {"code": "DATA_EXCEPTION"}]
    primary, secondary = select_primary(raw, ["DATA_EXCEPTION", "OVERDUE", "UPCOMING", "NO_ACTION"])
    assert primary == "DATA_EXCEPTION" and secondary == ["OVERDUE", "UPCOMING"]
    assert select_primary([], ["NO_ACTION"]) == ("NO_ACTION", [])


def test_business_day_roll():
    assert roll_to_business_day(date(2026, 10, 17)) == date(2026, 10, 19)  # Saturday -> Monday
    assert roll_to_business_day(date(2026, 10, 19)) == date(2026, 10, 19)


def test_followup_date_calculation(evaluation):
    facts = evaluation.facts[loan(5)]
    out = calculate_followup_date("CONTACT_ATTORNEY", facts, evaluation.ctx)
    assert out["followup_date"] == "2026-10-19" and out["days"] == 7
    out = calculate_followup_date("CREATE_FOLLOWUP", facts, evaluation.ctx)  # TITLE_REVIEW default 21 days
    assert out["followup_date"] == "2026-11-02"
    assert calculate_followup_date("NO_ACTION", facts, evaluation.ctx)["followup_date"] is None


def test_inactive_loans_excluded_from_active_results(evaluation):
    inactive = [r for r in evaluation.results.values() if not r["is_active"]]
    assert inactive and all(r not in evaluation.active_results() for r in inactive)
