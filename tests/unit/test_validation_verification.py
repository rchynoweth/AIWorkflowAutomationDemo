"""Proposed-event validation and action verification."""
from datetime import date

from src.rules.validation import prepare_event, validate_proposed_event
from src.verification.verifier import verify_action
from tests.conftest import loan

P = date(2026, 10, 12)


def _validate(evaluation, n, action, **kw):
    facts = evaluation.facts[loan(n)]
    draft = prepare_event(action, facts, evaluation.ctx, kw.get("followup"), kw.get("note"))
    return validate_proposed_event(draft, facts, evaluation.get(loan(n)), evaluation.ctx, kw.get("fingerprint"))


def codes(result):
    return {e["code"] for e in result["errors"]}


def test_valid_default_action(evaluation):
    assert _validate(evaluation, 5, "CONTACT_ATTORNEY")["valid"]


def test_not_allowed_and_out_of_range(evaluation):
    assert "ACTION_NOT_ALLOWED" in codes(_validate(evaluation, 5, "CREATE_NEXT_MILESTONE"))
    assert "FOLLOWUP_OUT_OF_RANGE" in codes(_validate(evaluation, 5, "CONTACT_ATTORNEY", followup="2026-10-01"))
    assert "FOLLOWUP_OUT_OF_RANGE" in codes(_validate(evaluation, 5, "CONTACT_ATTORNEY", followup="2027-06-01"))


def test_note_too_long_and_stale(evaluation):
    assert "NOTE_TOO_LONG" in codes(_validate(evaluation, 5, "CONTACT_ATTORNEY", note="x" * 1001))
    assert "STALE_RECOMMENDATION" in codes(_validate(evaluation, 5, "CONTACT_ATTORNEY", fingerprint="deadbeef"))


def test_pending_action_blocks_new_event(evaluation):
    facts = evaluation.facts[loan(19)]
    draft = prepare_event("CONTACT_ATTORNEY", facts, evaluation.ctx)
    state = dict(evaluation.get(loan(19)), allowed_actions=["CONTACT_ATTORNEY"])
    result = validate_proposed_event(draft, facts, state, evaluation.ctx)
    assert {"PENDING_ACTION_EXISTS", "DUPLICATE_EVENT"} & codes(result)


def test_duplicate_open_followup(evaluation):
    facts = evaluation.facts[loan(9)]  # two open future FOLLOWUP events
    draft = prepare_event("CREATE_FOLLOWUP", facts, evaluation.ctx)
    state = dict(evaluation.get(loan(9)), allowed_actions=["CREATE_FOLLOWUP"])
    assert "DUPLICATE_EVENT" in codes(validate_proposed_event(draft, facts, state, evaluation.ctx))


def test_no_action_creates_no_event(evaluation):
    result = _validate(evaluation, 1, "NO_ACTION")
    assert result["valid"] and result["warnings"][0]["code"] == "NO_EVENT_FOR_ACTION"


ACTION = {"action_id": "ACT-T1", "loan_id": "L1", "event_type": "FOLLOWUP", "event_date": "2026-10-12",
          "followup_date": "2026-10-20", "status": "SUBMITTED", "submitted_at": "2026-10-12T09:00:00",
          "milestone_type": ""}


def _ev(event_id, followup="2026-10-20", note="[ref ACT-T1]"):
    return {"event_id": event_id, "event_type": "FOLLOWUP", "source": "SERVICING_SYSTEM_ADAPTER", "status": "OPEN",
            "event_date": "2026-10-12", "followup_date": followup, "event_note": note,
            "created_at": "2026-10-12T09:05:00"}


def test_verification_statuses():
    assert verify_action(ACTION, [_ev("E1")], P)["verification_status"] == "VERIFIED"
    mismatch = verify_action(ACTION, [_ev("E1", "2026-10-27")], P)
    assert mismatch["verification_status"] == "MISMATCH"
    assert mismatch["differences"][0]["field"] == "followup_date"
    assert verify_action(ACTION, [_ev("E1"), _ev("E2")], P)["verification_status"] == "DUPLICATE"
    assert verify_action(ACTION, [], P)["verification_status"] == "PENDING"
    assert verify_action(ACTION, [], date(2026, 10, 15))["verification_status"] == "NOT_FOUND"
    assert verify_action({**ACTION, "status": "FAILED"}, [], P)["verification_status"] == "FAILED"


def test_reference_token_must_match():
    other = _ev("E9", note="[ref ACT-OTHER]")
    assert verify_action(ACTION, [other], P)["verification_status"] == "PENDING"
