"""Agent-tool interaction (scripted LLM), persistence round trips, decisions, outbound actions, adapter."""
import json

import pytest

from src.agent import ScriptedLlmClient
from src.models import DecisionRequest
from src.storage import LocalRepository
from src.service import LoanServicingService
from tests.conftest import GENERATED

pytestmark = pytest.mark.integration


def test_llm_agent_tool_loop_through_service(tmp_path, settings_no_baseline):
    loan = "LSI-SYN-000013"
    llm = ScriptedLlmClient([
        {"tool_calls": [{"id": "1", "name": "get_loan_context", "arguments": {"loan_id": loan}},
                        {"id": "2", "name": "check_previous_rejection", "arguments": {"loan_id": loan}}]},
        {"tool_calls": [{"id": "3", "name": "get_allowed_actions", "arguments": {}}]},  # loan_id injected
        {"tool_calls": [{"id": "4", "name": "submit_recommendation", "arguments": {
            "recommended_action": "CREATE_FOLLOWUP", "rationale": "Prior CONTACT_ATTORNEY rejected; follow up.",
            "confidence": "HIGH", "suggested_note": "Follow-up scheduled.", "evidence_refs": ["check_previous_rejection"],
            "missing_information": ["Reason for vendor delay"]}}]},
    ])
    repo = LocalRepository(settings_no_baseline, source_dir=GENERATED, state_dir=tmp_path / "s")
    svc = LoanServicingService(settings_no_baseline, repo, agent_mode="llm", llm=llm).load()
    out = svc.analyze_loan(loan)
    rec = out["recommendation"]
    assert out["agent_mode"] == "llm" and rec["recommended_action"] == "CREATE_FOLLOWUP"
    assert rec["rationale"].startswith("Prior CONTACT_ATTORNEY")
    assert "Reason for vendor delay" in rec["missing_information"]
    assert [c["origin"] for c in rec["tool_calls"][:3]] == ["agent", "agent", "agent"]
    # tool results were returned to the model
    tool_msgs = [m for m in llm.requests[-1]["messages"] if m["role"] == "tool"]
    assert any(json.loads(m["content"])["success"] for m in tool_msgs)
    assert any(a["tool_name"] == "get_allowed_actions" for a in svc.activity(loan))


def test_state_persists_across_reload(tmp_path, settings_no_baseline):
    repo = LocalRepository(settings_no_baseline, source_dir=GENERATED, state_dir=tmp_path / "s")
    svc = LoanServicingService(settings_no_baseline, repo, agent_mode="deterministic").load()
    svc.settings.application["data"]["outbound_dir"] = str(tmp_path / "out")
    rec = svc.analyze_loan("LSI-SYN-000005")["recommendation"]
    action = svc.decide(rec["recommendation_id"], DecisionRequest(decision="APPROVE"))["action"]
    svc.submit_action(action["action_id"])
    svc.refresh()
    assert (tmp_path / "out" / f"{action['action_id']}.json").exists()

    repo2 = LocalRepository(settings_no_baseline, source_dir=GENERATED, state_dir=tmp_path / "s")
    svc2 = LoanServicingService(settings_no_baseline, repo2, agent_mode="deterministic").load()
    assert svc2.ops.refresh_cycle == 1
    assert svc2.ops.actions[action["action_id"]]["status"] == "VERIFIED"
    assert svc2.ops.recommendations[rec["recommendation_id"]]["status"] == "APPROVED"
    assert svc2.evaluation.facts["LSI-SYN-000005"].latest_verification["verification_status"] == "VERIFIED"


def test_baseline_recommendations_and_reset(tmp_path):
    from src.config import load_settings
    settings = load_settings(overrides={"demo_scenarios.baseline_recommendations": {"enabled": True, "exclude_loans": ["LSI-SYN-000005", "LSI-SYN-000004"]}})
    repo = LocalRepository(settings, source_dir=GENERATED, state_dir=tmp_path / "s")
    svc = LoanServicingService(settings, repo, agent_mode="deterministic").load()
    n = len(svc.ops.recommendations)
    assert n > 100
    excluded = set(settings.demo_scenarios["baseline_recommendations"]["exclude_loans"])
    assert not excluded & {r["loan_id"] for r in svc.ops.recommendations.values()}
    out = svc.reset_demo()
    assert out["baseline_recommendations"] == n and svc.ops.refresh_cycle == 0


def test_triage_candidates_skip_spotlight_and_current_llm(tmp_path, settings_no_baseline):
    repo = LocalRepository(settings_no_baseline, source_dir=GENERATED, state_dir=tmp_path / "s")
    svc = LoanServicingService(settings_no_baseline, repo, agent_mode="deterministic").load()
    ids = svc.triage_candidates(limit=50)
    assert "LSI-SYN-000005" not in ids and "LSI-SYN-000004" not in ids
    assert len(ids) == len(set(ids)) == 50
    out = svc.triage(loan_ids=ids[:3], max_workers=3)
    assert out["analyzed"] == 3
    assert {r["loan_id"] for r in out["results"]} == set(ids[:3])
