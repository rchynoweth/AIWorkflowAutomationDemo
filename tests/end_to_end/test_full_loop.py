"""synthetic files -> ingestion -> rule detection -> score -> agent recommendation -> human approval simulation
-> outbound event -> synthetic system update -> refreshed ingestion -> verification (plus failure paths)."""
import json
from datetime import date

import pytest

from src.config.settings import load_settings
from src.data_generation.generator import generate_dataset, write_dataset
from src.models.schemas import DecisionEdits, DecisionRequest
from src.repositories.local import LocalRepository
from src.services.servicing_service import LoanServicingService

pytestmark = pytest.mark.end_to_end


@pytest.fixture()
def fresh_service(tmp_path):
    settings = load_settings(overrides={"demo_scenarios.baseline_recommendations": {"enabled": False}})
    settings.application["data"]["outbound_dir"] = str(tmp_path / "outbound")
    src = tmp_path / "landing"
    write_dataset(generate_dataset(seed=settings.seed, processing_date=date(2026, 10, 12), loan_count=300), src)
    repo = LocalRepository(settings, source_dir=src, state_dir=tmp_path / "state")
    return LoanServicingService(settings, repo, agent_mode="deterministic").load(), tmp_path


def test_full_loop_success(fresh_service):
    svc, tmp = fresh_service
    loan = "LSI-SYN-000005"
    state = svc.evaluation.get(loan)
    assert (state["primary_condition"], state["attention_score"], state["priority"]) == ("OVERDUE", 54, "HIGH")
    rec = svc.analyze_loan(loan)["recommendation"]
    assert rec["recommended_action"] == "CONTACT_ATTORNEY" and rec["requires_human_approval"]
    # Nothing is written to the System of Record before approval.
    assert svc.ops.sor_events == [] and svc.ops.actions == {}
    decision = svc.decide(rec["recommendation_id"], DecisionRequest(decision="APPROVE", reviewer_id="SPEC-01"))
    action = decision["action"]
    outbound = json.loads((tmp / "outbound" / f"{action['action_id']}.json").read_text())
    assert outbound["event_type"] == "CONTACT" and outbound["synthetic_data"] is True
    assert svc.evaluation.get(loan)["primary_condition"] == "ALREADY_ACTIONED"
    submitted = svc.submit_action(action["action_id"])
    assert submitted["status"] == "SUBMITTED" and svc.ops.sor_events
    assert svc.evaluation.facts[loan].latest_verification["verification_status"] == "PENDING"  # not yet refreshed
    refresh = svc.refresh()
    assert refresh["verification"] == {"VERIFIED": 1}
    assert svc.ops.actions[action["action_id"]]["status"] == "VERIFIED"
    after = svc.evaluation.get(loan)
    assert after["days_overdue"] == 0 and after["needs_attention"] is False
    events = svc.loan_events(loan)
    assert any(e["display_state"] == "VERIFIED" for e in events)


def test_configured_failure_returns_to_queue(fresh_service):
    svc, _ = fresh_service
    loan = "LSI-SYN-000004"  # adapter FAIL
    before = svc.evaluation.get(loan)["attention_score"]
    rec = svc.analyze_loan(loan)["recommendation"]
    action = svc.decide(rec["recommendation_id"], DecisionRequest(decision="APPROVE"))["action"]
    out = svc.submit_action(action["action_id"])
    assert out["status"] == "FAILED" and "configured failure" in out["failure_reason"]
    state = svc.evaluation.get(loan)
    assert state["primary_condition"] == "VERIFICATION_FAILURE" and state["needs_attention"]
    assert state["attention_score"] > before
    assert state["default_action"] == "RETRY_FAILED_ACTION"
    assert loan in [r["loan_id"] for r in svc.priority_queue()]


def test_mismatch_and_duplicate_and_delayed(fresh_service):
    svc, _ = fresh_service
    results = {}
    for loan in ("LSI-SYN-000013", "LSI-SYN-000008", "LSI-SYN-000003"):  # MISMATCH, DUPLICATE, DELAYED
        rec = svc.analyze_loan(loan)["recommendation"]
        action = svc.decide(rec["recommendation_id"], DecisionRequest(decision="APPROVE"))["action"]
        svc.submit_action(action["action_id"])
        results[loan] = action["action_id"]
    svc.refresh()
    status = {loan: svc.evaluation.facts[loan].verifications[aid]["verification_status"] for loan, aid in results.items()}
    assert status == {"LSI-SYN-000013": "MISMATCH", "LSI-SYN-000008": "DUPLICATE", "LSI-SYN-000003": "PENDING"}
    assert svc.evaluation.get("LSI-SYN-000013")["primary_condition"] == "VERIFICATION_FAILURE"
    svc.refresh()
    svc.refresh()
    assert svc.evaluation.facts["LSI-SYN-000003"].verifications[results["LSI-SYN-000003"]]["verification_status"] == "VERIFIED"


def test_retry_after_failure(fresh_service):
    svc, _ = fresh_service
    loan = "LSI-SYN-000016"  # pre-existing NOT_FOUND
    rec = svc.analyze_loan(loan)["recommendation"]
    assert rec["recommended_action"] == "RETRY_FAILED_ACTION"
    action = svc.decide(rec["recommendation_id"], DecisionRequest(
        decision="EDIT", edits=DecisionEdits(note="Resubmitting outreach")))["action"]
    assert action["event_type"] == "CONTACT" and action["retry_of_action_id"]
    svc.submit_action(action["action_id"])
    svc.refresh()
    assert svc.evaluation.facts[loan].verifications[action["action_id"]]["verification_status"] == "VERIFIED"
    assert svc.evaluation.get(loan)["primary_condition"] != "VERIFICATION_FAILURE"
